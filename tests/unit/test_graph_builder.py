"""Behavioral tests for deterministic device-only graph conversion."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from gnn_pruning.contracts import (
    SUPPORTED_GRAPH_CONVERTER_VERSION,
    SUPPORTED_GRAPH_SCHEMA_VERSION,
)
from gnn_pruning.conversion.graph import (
    TopologyAnnotations,
    build_device_graph,
    device_graph_to_dict,
    read_device_graph,
    write_device_graph,
)
from gnn_pruning.conversion.netlist import (
    ParsedExpression,
    ParsedInstance,
    ParsedNetlist,
    parse_engineering_literal,
    parse_netlist,
)
from gnn_pruning.io import canonical_sha256


THREE_DEVICE_NET = """\
R1 (shared a) resistor r=1k
C1 (shared b) capacitor c=1p
L1 (shared c) inductor l=1n
"""

PARALLEL_RAIL_NETLIST = """\
M1 (feedback feedback 0 GND) nmos w=W l=45n
Cfb (feedback sense) capacitor c=Cfb
L1 (VDD sense) inductor l=1n
"""


def test_analoggenie_device_names_and_resistor_map_to_graph_nodes():
    parsed = parse_netlist(
        "M0 (out gate VSS VSS) nmos4 w=Wn\n"
        "M1 (out gate VDD VDD) pmos4 w=Wp\n"
        "R0 (VDD out) resistor r=Rload",
        {},
    )
    graph = build_device_graph(
        parsed,
        TopologyAnnotations(rail_aliases={"VSS": "gnd", "VDD": "vdd"}),
    )

    nodes = {node.id: node for node in graph.nodes}
    assert [(node.kind, node.terminal_roles) for node in graph.nodes] == [
        ("nmos", ("drain", "gate", "source", "body")),
        ("pmos", ("drain", "gate", "source", "body")),
        ("resistor", ("positive", "negative")),
    ]
    assert nodes["M0"].tunable_kinds == ("mos_width",)
    assert nodes["M1"].tunable_kinds == ("mos_width",)
    assert nodes["R0"].tunable_kinds == ("resistance",)
    assert {edge.net for edge in graph.edges} == {"out", "gate"}
    assert (
        "R0",
        "negative",
        "M0",
        "drain",
        "out",
    ) in {
        (edge.src, edge.src_terminal, edge.dst, edge.dst_terminal, edge.net)
        for edge in graph.edges
    }


def test_analoggenie_1044_full_netlist_flattens_to_six_mos_devices():
    source = Path(__file__).resolve().parents[1] / "fixtures/netlists/analoggenie_1044_full.cir"
    parsed = parse_netlist(source.read_text(encoding="utf-8"), {}, path=str(source))
    graph = build_device_graph(
        parsed, TopologyAnnotations(rail_aliases={"VDD": "vdd", "VSS": "gnd"})
    )

    assert {node.id: node.kind for node in graph.nodes} == {
        "I0/M0": "pmos",
        "I0/M1": "nmos",
        "M0": "nmos",
        "M1": "nmos",
        "M2": "nmos",
        "M3": "nmos",
    }
    assert {edge.net for edge in graph.edges} == {
        "VCONT1", "net7", "VCLK1", "VCLK2", "VCLK3", "VCLK4"
    }
    assert any(
        edge.src == "I0/M0" and edge.dst == "M3" and edge.net == "net7"
        for edge in graph.edges
    )


def test_analoggenie_diode_and_bjts_keep_ordered_contacts_in_graph():
    parsed = parse_netlist(
        "D5 (IB2 VOUT1) diode\n"
        "Q1 (net15 net21 net25 0) npn\n"
        "Q0 (VSS IIN1 IB1 0) pnp",
        {},
    )
    graph = build_device_graph(parsed, TopologyAnnotations())

    assert {node.id: (node.kind, node.terminal_roles) for node in graph.nodes} == {
        "D5": ("diode", ("anode", "cathode")),
        "Q1": ("npn", ("collector", "base", "emitter", "substrate")),
        "Q0": ("pnp", ("collector", "base", "emitter", "substrate")),
    }


def test_same_scope_duplicate_names_remain_distinct_graph_nodes():
    graph = build_device_graph(
        parse_netlist(
            "R0 (left shared) resistor\nR0 (shared right) resistor", {}
        ),
        TopologyAnnotations(),
    )

    assert {node.id for node in graph.nodes} == {"R0@L1", "R0@L2"}
    assert {(edge.src, edge.dst, edge.net) for edge in graph.edges} == {
        ("R0@L1", "R0@L2", "shared"),
        ("R0@L2", "R0@L1", "shared"),
    }


def test_three_devices_on_signal_net_create_six_directed_edges():
    """Dropping an ordered device pair would lose message-passing connectivity."""
    graph = build_device_graph(
        parse_netlist(THREE_DEVICE_NET, {}), TopologyAnnotations()
    )

    assert len(graph.edges) == 3 * 2
    assert {(edge.src, edge.dst) for edge in graph.edges} == {
        ("C1", "L1"),
        ("C1", "R1"),
        ("L1", "C1"),
        ("L1", "R1"),
        ("R1", "C1"),
        ("R1", "L1"),
    }
    assert all(edge.net_role == "signal" for edge in graph.edges)
    assert all(edge.src != edge.dst for edge in graph.edges)


def test_repeated_contacts_use_first_declared_terminal_per_distinct_device():
    """Repeated contacts belong in equivalence masks, not duplicate device edges."""
    graph = build_device_graph(
        parse_netlist("M1 (x x gnd bulk) nmos w=W\nC1 (x x) capacitor c=C", {}),
        TopologyAnnotations(),
    )

    assert {
        (edge.src, edge.src_terminal, edge.dst, edge.dst_terminal)
        for edge in graph.edges
    } == {
        ("M1", "drain", "C1", "positive"),
        ("C1", "positive", "M1", "drain"),
    }
    assert len(graph.edges) == 2 * (2 - 1)
    nodes = {node.id: node for node in graph.nodes}
    assert nodes["M1"].terminal_equivalence == (("drain", "gate"),)
    assert nodes["C1"].terminal_equivalence == (("negative", "positive"),)


def test_rails_are_flags_and_repeated_terminals_are_masks():
    """Turning rails into cliques or internal shorts into edges changes topology."""
    graph = build_device_graph(
        parse_netlist(PARALLEL_RAIL_NETLIST, {}), TopologyAnnotations()
    )
    m1 = next(node for node in graph.nodes if node.id == "M1")
    l1 = next(node for node in graph.nodes if node.id == "L1")

    assert {"gnd"} <= set(m1.interface_flags)
    assert {"vdd"} <= set(l1.interface_flags)
    assert ("drain", "gate") in m1.terminal_equivalence
    assert not any(edge.net in {"0", "GND", "VDD"} for edge in graph.edges)
    assert (
        len([edge for edge in graph.edges if {edge.src, edge.dst} == {"M1", "Cfb"}])
        == 2
    )


def test_multiple_nets_between_a_pair_are_retained_with_pair_local_indices():
    """Coalescing two nets between a pair must not turn a multigraph into a graph."""
    graph = build_device_graph(
        parse_netlist(
            "R1 (left right) resistor r=1\nC1 (left right) capacitor c=1p", {}
        ),
        TopologyAnnotations(),
    )

    assert [
        (edge.src, edge.dst, edge.net, edge.parallel_index) for edge in graph.edges
    ] == [
        ("C1", "R1", "left", 0),
        ("C1", "R1", "right", 1),
        ("R1", "C1", "left", 0),
        ("R1", "C1", "right", 1),
    ]


def test_exact_annotations_assign_roles_and_interface_flags_without_substring_guesses():
    """A similarly named net must remain signal unless it is explicitly annotated."""
    graph = build_device_graph(
        parse_netlist("R1 (Vin Vinb) resistor r=1\nC1 (Vin Vinb) capacitor c=1p", {}),
        TopologyAnnotations(net_roles=(("Vin", "input"),)),
    )

    vin_edges = [edge for edge in graph.edges if edge.net == "Vin"]
    vinb_edges = [edge for edge in graph.edges if edge.net == "Vinb"]
    assert {edge.net_role for edge in vin_edges} == {"input"}
    assert {edge.net_role for edge in vinb_edges} == {"signal"}
    assert all("input" in node.interface_flags for node in graph.nodes)


def test_unknown_annotation_and_invalid_annotation_values_are_rejected():
    """A misspelled annotation must fail rather than silently change graph meaning."""
    parsed = parse_netlist("R1 (left right) resistor r=1", {})

    with pytest.raises(ValueError, match="unknown annotated net missing"):
        build_device_graph(
            parsed, TopologyAnnotations(net_roles=(("missing", "output"),))
        )
    with pytest.raises(ValueError, match="unknown net role mystery"):
        TopologyAnnotations(net_roles=(("left", "mystery"),))
    with pytest.raises(ValueError, match="rail alias .* must map to gnd or vdd"):
        TopologyAnnotations(rail_aliases=(("power", "bias"),))


def test_graph_maps_source_kinds_and_keeps_numeric_attributes_separate_from_raw_tunables():
    """Using raw sizing expressions as fixed features would leak candidate values."""
    graph = build_device_graph(
        parse_netlist(
            "\n".join(
                (
                    "P1 (a b c d) pmos w=2u l=45n",
                    "R1 (a e) resistor r=1k",
                    "C1 (e f) capacitor c=Ctune",
                    "L1 (f g) inductor l=sqrt(Lp*Ls)*k",
                    "V1 (g 0) vsource dc=1.2",
                    "I1 (a 0) isource dc=Ibias",
                    "PORT1 (b 0) port r=50",
                    "B1 (c h i) balun rin=50 rout=25 loss=0",
                )
            ),
            {},
        ),
        TopologyAnnotations(),
    )
    by_id = {node.id: node for node in graph.nodes}

    assert by_id["V1"].kind == "voltage_source"
    assert by_id["I1"].kind == "current_source"
    assert by_id["L1"].kind == "inductor"
    assert by_id["B1"].kind == "balun"
    assert dict(by_id["P1"].fixed_attributes) == pytest.approx({"l": 45e-9, "w": 2e-6})
    assert by_id["P1"].tunable_kinds == ()
    assert by_id["C1"].fixed_attributes == ()
    assert by_id["C1"].tunable_kinds == ("capacitance",)
    assert by_id["L1"].fixed_attributes == ()
    assert by_id["L1"].tunable_kinds == ("inductance",)
    assert by_id["I1"].tunable_kinds == ("current",)
    assert by_id["V1"].fixed_attributes == (("dc", 1.2),)


def test_invalid_manually_constructed_parsed_data_is_rejected_before_graph_creation():
    """Bypassing the parser must not permit a malformed topology into a graph."""
    expression = ParsedExpression(raw="1", value=1.0, symbols=())
    invalid = ParsedNetlist(
        instances=(
            ParsedInstance(
                instance_id="R1",
                kind="resistor",
                nets=("left",),
                terminal_roles=("positive", "negative"),
                attributes={"r": "1"},
                expressions={"r": expression},
                line_number=1,
                source_text="R1 (left) resistor r=1",
            ),
        ),
        source_sha256="source",
    )

    with pytest.raises(ValueError, match="has 1 nets for 2 terminal roles"):
        build_device_graph(invalid, TopologyAnnotations())


def test_graph_builder_preserves_supported_manual_graph_kind():
    parsed = ParsedNetlist(
        instances=(
            ParsedInstance(
                instance_id="LOAD1",
                kind="load",
                nets=("out", "0"),
                terminal_roles=("positive", "negative"),
                attributes={},
                expressions={},
                line_number=1,
                source_text="manual load",
            ),
        ),
        source_sha256="source",
    )

    graph = build_device_graph(parsed, TopologyAnnotations())

    assert graph.nodes[0].kind == "load"
    assert graph.nodes[0].terminal_roles == ("positive", "negative")


def test_canonical_graph_bytes_hash_and_read_round_trip_ignore_instance_and_annotation_order(
    tmp_path: Path,
):
    """Input ordering must not produce different checked-in graph artifacts."""
    parsed = parse_netlist(PARALLEL_RAIL_NETLIST, {})
    reordered = replace(parsed, instances=tuple(reversed(parsed.instances)))
    first = build_device_graph(
        parsed,
        TopologyAnnotations(net_roles=(("sense", "output"), ("feedback", "bias"))),
    )
    second = build_device_graph(
        reordered,
        TopologyAnnotations(net_roles=(("feedback", "bias"), ("sense", "output"))),
    )
    first_path = tmp_path / "first.graph.json"
    second_path = tmp_path / "second.graph.json"

    first_hash = write_device_graph(first_path, first)
    second_hash = write_device_graph(second_path, second)

    assert first_path.read_bytes() == second_path.read_bytes()
    assert first_hash == second_hash
    assert first_hash == canonical_sha256(
        json.loads(first_path.read_text(encoding="utf-8"))
    )
    assert read_device_graph(first_path) == first


def test_canonical_graph_contains_immutable_converter_and_schema_versions():
    graph = build_device_graph(
        parse_netlist(THREE_DEVICE_NET, {}), TopologyAnnotations()
    )

    document = device_graph_to_dict(graph)

    assert graph.converter_version == SUPPORTED_GRAPH_CONVERTER_VERSION
    assert graph.graph_schema_version == SUPPORTED_GRAPH_SCHEMA_VERSION
    assert document["converter_version"] == "gnn-pruning-device-graph/1.0.0"
    assert document["graph_schema_version"] == 1


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_converter",
        "missing_schema",
        "unknown_top_level",
        "extra_version_form",
        "converter_wrong_type",
        "converter_unsupported",
        "schema_wrong_type",
        "schema_bool",
        "schema_unsupported",
    ),
)
def test_graph_reader_rejects_missing_unknown_or_unsupported_version_metadata(
    tmp_path: Path, mutation: str
):
    document = device_graph_to_dict(
        build_device_graph(parse_netlist(THREE_DEVICE_NET, {}), TopologyAnnotations())
    )
    document["converter_version"] = "gnn-pruning-device-graph/1.0.0"
    document["graph_schema_version"] = 1
    if mutation == "missing_converter":
        del document["converter_version"]
    elif mutation == "missing_schema":
        del document["graph_schema_version"]
    elif mutation == "unknown_top_level":
        document["unexpected"] = True
    elif mutation == "extra_version_form":
        document["schema_version"] = 1
    elif mutation == "converter_wrong_type":
        document["converter_version"] = 1
    elif mutation == "converter_unsupported":
        document["converter_version"] = "gnn-pruning-device-graph/2.0.0"
    elif mutation == "schema_wrong_type":
        document["graph_schema_version"] = "1"
    elif mutation == "schema_bool":
        document["graph_schema_version"] = True
    elif mutation == "schema_unsupported":
        document["graph_schema_version"] = 2
    else:  # pragma: no cover - parameter table is exhaustive
        raise AssertionError(mutation)
    path = tmp_path / f"{mutation}.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid device graph"):
        read_device_graph(path)


def test_parallel_and_rails_golden_graph_is_exact(tmp_path: Path):
    """A change to canonical graph JSON must be reviewed through the golden fixture."""
    fixture_root = Path(__file__).parents[1] / "fixtures" / "graphs"
    annotation_data = json.loads(
        (fixture_root / "parallel_and_rails.annotations.json").read_text(
            encoding="utf-8"
        )
    )
    annotations = TopologyAnnotations(
        rail_aliases=tuple(tuple(pair) for pair in annotation_data["rail_aliases"]),
        net_roles=tuple(tuple(pair) for pair in annotation_data["net_roles"]),
    )
    path = tmp_path / "parallel_and_rails.graph.json"

    write_device_graph(
        path, build_device_graph(parse_netlist(PARALLEL_RAIL_NETLIST, {}), annotations)
    )

    assert path.read_text(encoding="utf-8") == (
        fixture_root / "parallel_and_rails.graph.json"
    ).read_text(encoding="utf-8")
