from pathlib import Path

from circuit_ingest import AnalogGenieParser, ParseMode, SourceBundle, discover
from circuit_ingest.cli import run
from circuit_ingest.models import CircuitRecord
from circuit_ingest.registry import DEVICE_SPECS
from circuit_ingest.parser import parse_device_line
from circuit_ingest.parser import MAX_FILE_BYTES
from circuit_ingest.validation import validate_circuit
from gnn_pruning.conversion.graph import TopologyAnnotations, build_device_graph
from gnn_pruning.conversion.netlist import NetlistParseError, parse_netlist
import pytest


def bundle(tmp_path: Path, netlist: str, ports: str = "a b") -> SourceBundle:
    root = tmp_path / "Dataset"
    directory = root / "7"
    directory.mkdir(parents=True)
    (directory / "7.cir").write_text(netlist, encoding="utf-8")
    (directory / "Port7.txt").write_text(ports, encoding="utf-8")
    return discover(root)[0]


def test_preserves_duplicate_names_bjt_substrate_and_isolated_port(tmp_path):
    source = bundle(tmp_path, "Q1 (a b x 0) npn\nQ1 (x a b 0) pnp\n", "a b spare")
    result = AnalogGenieParser().parse(source)
    assert result.status == "valid_with_warnings"
    circuit = result.circuit
    assert circuit is not None
    assert [device.id for device in circuit.devices] == [
        "analoggenie:7:device:000001", "analoggenie:7:device:000002"
    ]
    assert circuit.devices[0].connections[3].terminal == "substrate"
    assert circuit.devices[0].connections[3].net_id == "analoggenie:7:net:0"
    assert circuit.ports[2].referenced_by_device is False
    assert circuit.nets[-1].degree_by_terminal == 0
    assert {issue.code for issue in result.issues} == {
        "DUPLICATE_SOURCE_INSTANCE", "PORT_NOT_REFERENCED"
    }


def test_unknown_type_is_opaque_only_in_lenient_mode(tmp_path):
    source = bundle(tmp_path, "Q7 (a b) SPECIAL_BLOCK\n")
    strict = AnalogGenieParser().parse(source)
    assert strict.status == "quarantined"
    assert strict.circuit is not None
    assert strict.circuit.devices[0].canonical_type == "opaque"
    lenient = AnalogGenieParser().parse(source, mode=ParseMode.LENIENT)
    assert lenient.status == "valid_with_warnings"
    assert [c.terminal for c in lenient.circuit.devices[0].connections] == ["pin_0", "pin_1"]


def test_malformed_line_and_wrong_arity_quarantine(tmp_path):
    source = bundle(tmp_path, "R1 (a b) resistor\nM1 (a b c) nmos4\nBAD (a (b)) resistor\n")
    result = AnalogGenieParser().parse(source)
    assert result.status == "quarantined"
    assert {issue.code for issue in result.issues} >= {"WRONG_DEVICE_ARITY", "MALFORMED_DEVICE_LINE"}


def test_existing_parser_routes_primary_analoggenie_file(tmp_path):
    source = bundle(tmp_path, "I1 (a b c d e) TRANSMISSION_GATE\n", "a b")
    parsed = parse_netlist(source.primary_netlist_path.read_text(), {}, path=str(source.primary_netlist_path))
    assert parsed.instances[0].kind == "TRANSMISSION_GATE"
    assert parsed.instances[0].terminal_roles == ("a", "b", "control", "vdd", "vss")


def test_cli_emits_deterministic_circuit_and_report(tmp_path):
    source = bundle(tmp_path, "R1 (a b) resistor\n")
    output = tmp_path / "out"
    args = ["parse-analoggenie", "--dataset-root", str(source.root_directory), "--output-dir", str(output)]
    assert run(args) == 0
    first = (output / "circuits/7.json").read_bytes()
    first_report = (output / "audit-report.json").read_bytes()
    assert run(args) == 0
    assert (output / "circuits/7.json").read_bytes() == first
    assert (output / "audit-report.json").read_bytes() == first_report
    assert (output / "canonical-circuit.schema.json").exists()
    assert (output / "manifest.jsonl").exists()
    assert (output / "audit-report.json").exists()
    assert CircuitRecord.model_validate_json(first).statistics.device_count == 1


@pytest.mark.parametrize("raw_type,terminals", [
    ("nmos4", ("drain", "gate", "source", "bulk")),
    ("pmos4", ("drain", "gate", "source", "bulk")),
    ("npn", ("collector", "base", "emitter", "substrate")),
    ("pnp", ("collector", "base", "emitter", "substrate")),
    ("resistor", ("p", "n")),
    ("capacitor", ("p", "n")),
    ("inductor", ("p", "n")),
    ("diode", ("p", "n")),
    ("XOR", ("a", "b", "vdd", "vss", "y")),
    ("PFD", ("a", "b", "qa", "qb", "vdd", "vss")),
    ("INVERTER", ("a", "q", "vdd", "vss")),
    ("TRANSMISSION_GATE", ("a", "b", "control", "vdd", "vss")),
])
def test_registry_terminal_order(tmp_path, raw_type, terminals):
    names = [f"n{index}" for index in range(len(terminals))]
    source = bundle(tmp_path, f"Q7 ({' '.join(names)}) {raw_type}\n", "n0")
    result = AnalogGenieParser().parse(source)
    assert result.status == "valid"
    assert tuple(connection.terminal for connection in result.circuit.devices[0].connections) == terminals
    assert len(DEVICE_SPECS) == 12


def test_existing_graph_flow_accepts_official_primary(tmp_path):
    source = bundle(tmp_path, "M1 (a b c d) nmos4\nR1 (a b) resistor\n")
    parsed = parse_netlist(source.primary_netlist_path.read_text(), {}, path=str(source.primary_netlist_path))
    graph = build_device_graph(parsed, TopologyAnnotations())
    assert len(graph.nodes) == 2


def test_pinned_corpus_semantics_and_counts():
    root = Path(__file__).resolve().parents[2] / "AnalogGenie/Dataset"
    if not root.is_dir():
        pytest.skip("AnalogGenie submodule is unavailable")
    bundles = discover(root)
    assert len(bundles) == 3350
    parser = AnalogGenieParser()
    counts = {"devices": 0, "duplicates": 0, "unused_ports": 0}
    raw_types = set()
    for source in bundles:
        result = parser.parse(source)
        assert result.status in ("valid", "valid_with_warnings"), source.circuit_id
        circuit = result.circuit
        counts["devices"] += circuit.statistics.device_count
        counts["duplicates"] += bool(circuit.statistics.duplicate_source_instance_count)
        counts["unused_ports"] += circuit.statistics.unreferenced_port_count
        raw_types.update(device.raw_type for device in circuit.devices)
        assert circuit.statistics.connection_count == sum(len(d.connections) for d in circuit.devices)
        assert all(len(device.connections) == 4 for device in circuit.devices if device.raw_type in ("npn", "pnp"))
    assert counts == {"devices": 69639, "duplicates": 2305, "unused_ports": 5}
    assert raw_types == set(DEVICE_SPECS)


def test_line_grammar_and_rejections():
    assert parse_device_line("\tQ7  ( a\tb c d )\tnmos4\r") == ("Q7", ("a", "b", "c", "d"), "nmos4")
    assert parse_device_line("  * comment") is None
    for line in ("M1 a b) nmos4", "M1 (a (b)) nmos4", "M1 () nmos4", "M1 (a b) resistor extra"):
        with pytest.raises(ValueError):
            parse_device_line(line)


def test_quarantined_circuit_has_no_json_output(tmp_path):
    source = bundle(tmp_path, "M1 (a b) nmos4\n")
    output = tmp_path / "out"
    assert run(["parse-analoggenie", "--dataset-root", str(source.root_directory), "--output-dir", str(output)]) == 1
    assert not (output / "circuits/7.json").exists()
    assert 'WRONG_DEVICE_ARITY' in (output / "issues.jsonl").read_text()


def test_quarantine_removes_stale_output_from_prior_parse(tmp_path):
    source = bundle(tmp_path, "R1 (a b) resistor\n")
    output = tmp_path / "out"
    args = ["parse-analoggenie", "--dataset-root", str(source.root_directory), "--output-dir", str(output)]
    assert run(args) == 0
    assert (output / "circuits/7.json").exists()
    source.primary_netlist_path.write_text("R1 (a b c) resistor\n")
    assert run(args) == 1
    assert not (output / "circuits/7.json").exists()


def test_removed_source_does_not_leave_circuit_json(tmp_path):
    source = bundle(tmp_path, "R1 (a b) resistor\n")
    output = tmp_path / "out"
    args = ["parse-analoggenie", "--dataset-root", str(source.root_directory), "--output-dir", str(output)]
    assert run(args) == 0
    source.primary_netlist_path.unlink()
    source.port_path.unlink()
    source.primary_netlist_path.parent.rmdir()
    assert run(args) == 0
    assert not (output / "circuits/7.json").exists()


def test_oversized_source_fails_before_parsing(tmp_path):
    source = bundle(tmp_path, "R1 (a b) resistor\n")
    with source.primary_netlist_path.open("r+b") as stream:
        stream.truncate(MAX_FILE_BYTES + 1)
    result = AnalogGenieParser().parse(source)
    assert result.status == "failed"
    assert result.issues[0].code == "SOURCE_TOO_LARGE"


def test_existing_parser_reports_missing_port_in_official_layout(tmp_path):
    directory = tmp_path / "AnalogGenie/Dataset/7"
    directory.mkdir(parents=True)
    path = directory / "7.cir"
    path.write_text("R1 (a b) resistor\n")
    with pytest.raises(NetlistParseError, match="MISSING_PORT_FILE"):
        parse_netlist(path.read_text(), {}, path=str(path))


def test_cross_record_validation_detects_missing_net(tmp_path):
    source = bundle(tmp_path, "R1 (a b) resistor\n")
    circuit = AnalogGenieParser().parse(source).circuit
    circuit.devices[0].connections[0].net_id = "missing"
    assert "missing net" in validate_circuit(circuit)[0]
