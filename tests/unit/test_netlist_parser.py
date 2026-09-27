"""Behavioral tests for the checked-in analog netlist grammar."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from gnn_pruning.conversion.netlist import NetlistParseError, parse_netlist


def test_parser_preserves_mos_terminal_order_and_internal_short():
    """A MOS drain-gate short must remain visible to graph construction."""
    parsed = parse_netlist("N1 (net4 net4 0 GND) nmos w=W l=45n", {})

    node = parsed.instances[0]
    assert node.instance_id == "N1"
    assert node.kind == "nmos"
    assert node.nets == ("net4", "net4", "0", "GND")
    assert node.terminal_roles == ("drain", "gate", "source", "body")
    assert node.attributes == {"w": "W", "l": "45n"}
    assert node.expressions["l"].value == pytest.approx(45e-9)
    assert node.expressions["w"].value is None
    assert (
        parsed.source_sha256
        == hashlib.sha256(b"N1 (net4 net4 0 GND) nmos w=W l=45n").hexdigest()
    )


def test_parser_preserves_all_supported_terminal_vocabularies():
    """Changing a device's terminal ordering would make graph edges incorrect."""
    parsed = parse_netlist(
        "\n".join(
            (
                "P0 (d g s b) pmos w=1u",
                "R0 (left right) resistor r=2.5K",
                "C0 (left 0) capacitor c=100f",
                "L0 (left 0) inductor l=1n",
                "V0 (left 0) vsource dc=VDD",
                "I0 (left 0) isource dc=1m",
                "PORT0 (left 0) port r=50",
                "B0 (se plus minus) balun rin=50 rout=25 loss=0",
            )
        ),
        {"VDD": 1.2},
    )

    assert [(item.kind, item.terminal_roles) for item in parsed.instances] == [
        ("pmos", ("drain", "gate", "source", "body")),
        ("resistor", ("positive", "negative")),
        ("capacitor", ("positive", "negative")),
        ("inductor", ("positive", "negative")),
        ("vsource", ("positive", "negative")),
        ("isource", ("positive", "negative")),
        ("port", ("port", "reference")),
        ("balun", ("single_ended", "differential_positive", "differential_negative")),
    ]
    assert parsed.instances[1].expressions["r"].value == pytest.approx(2500.0)
    assert parsed.instances[4].expressions["dc"].value == pytest.approx(1.2)


def test_primitive_type_wins_when_a_subcircuit_has_the_same_name():
    parsed = parse_netlist(
        "subckt resistor a b\n"
        "C0 (a b) capacitor\n"
        "ends resistor\n"
        "R0 (left right) resistor",
        {},
    )

    assert [(item.instance_id, item.kind, item.nets) for item in parsed.instances] == [
        ("R0", "resistor", ("left", "right"))
    ]


def test_repeated_ids_keep_raw_name_and_source_line():
    parsed = parse_netlist(
        "R0 (left middle) resistor\nR0 (middle right) resistor", {}
    )

    assert [item.instance_id for item in parsed.instances] == ["R0@L1", "R0@L2"]
    assert [item.raw_instance_id for item in parsed.instances] == ["R0", "R0"]
    assert [item.line_number for item in parsed.instances] == [1, 2]


def test_repeated_subcircuit_call_ids_scope_their_children():
    parsed = parse_netlist(
        "subckt PAIR a b\n"
        "R0 (a b) resistor\n"
        "ends PAIR\n"
        "I0 (left middle) PAIR\n"
        "I0 (middle right) PAIR",
        {},
    )

    assert [item.instance_id for item in parsed.instances] == [
        "I0@L4/R0", "I0@L5/R0"
    ]
    assert [item.raw_instance_id for item in parsed.instances] == ["R0", "R0"]
    assert [item.line_number for item in parsed.instances] == [2, 2]


def test_subcircuit_call_uses_sibling_full_file_and_its_nested_definition(tmp_path):
    folder = tmp_path / "Dataset/1"
    folder.mkdir(parents=True)
    source = folder / "1.cir"
    source.write_text("I0 (left right) WRAP\n", encoding="utf-8")
    (folder / "1_full.cir").write_text(
        "subckt INNER a b\n"
        "R0 (a b) resistor\n"
        "ends INNER\n"
        "subckt WRAP a b\n"
        "I1 (a b) INNER\n"
        "ends WRAP\n",
        encoding="utf-8",
    )

    parsed = parse_netlist(source.read_text(), {}, path=str(source))

    assert [(item.instance_id, item.nets) for item in parsed.instances] == [
        ("I0/I1/R0", ("left", "right"))
    ]


def test_subcircuit_own_definition_precedes_sibling(tmp_path):
    folder = tmp_path / "Dataset/1"
    folder.mkdir(parents=True)
    source = folder / "1.cir"
    source.write_text(
        "subckt CELL a b\nR0 (a b) resistor\nends CELL\nI0 (left right) CELL\n",
        encoding="utf-8",
    )
    (folder / "1_full.cir").write_text(
        "subckt CELL a b\nC0 (a b) capacitor\nends CELL\n",
        encoding="utf-8",
    )

    parsed = parse_netlist(source.read_text(), {}, path=str(source))

    assert [(item.instance_id, item.kind) for item in parsed.instances] == [
        ("I0/R0", "resistor")
    ]


def test_identical_global_subcircuit_fallback(tmp_path):
    root = tmp_path / "Dataset"
    for folder_name in ("1", "2", "3"):
        (root / folder_name).mkdir(parents=True)
    source = root / "1/1.cir"
    source.write_text("I0 (left right) CELL\n", encoding="utf-8")
    definition = "subckt CELL a b\nR0 (a b) resistor\nends CELL\n"
    first = root / "2/2_full.cir"
    second = root / "3/3_full.cir"
    first.write_text(definition, encoding="utf-8")
    second.write_text(definition, encoding="utf-8")

    parsed = parse_netlist(source.read_text(), {}, path=str(source))
    assert [item.instance_id for item in parsed.instances] == ["I0/R0"]


def test_ambiguous_global_subcircuit_reports_definition_locations(tmp_path):
    root = tmp_path / "Dataset"
    for folder_name in ("1", "2", "3"):
        (root / folder_name).mkdir(parents=True)
    source = root / "1/1.cir"
    source.write_text("I0 (left right) CELL\n", encoding="utf-8")
    first = root / "2/2_full.cir"
    second = root / "3/3_full.cir"
    first.write_text(
        "subckt CELL a b\nR0 (a b) resistor\nends CELL\n",
        encoding="utf-8",
    )
    second.write_text(
        "subckt CELL a b\nC0 (a b) capacitor\nends CELL\n",
        encoding="utf-8",
    )
    with pytest.raises(NetlistParseError, match="ambiguous subckt CELL") as caught:
        parse_netlist(source.read_text(), {}, path=str(source))
    assert f"{first}:1" in str(caught.value)
    assert f"{second}:1" in str(caught.value)


def test_parser_joins_continuations_and_unescapes_differential_nets():
    """A continuation must not split an instance or retain net-name escapes."""
    parsed = parse_netlist(
        "L0 (Vin\\+ net1) inductor \\\n             l=L1p-sqrt(L1p*L1s)*k q=30",
        {},
    )

    item = parsed.instances[0]
    assert item.nets == ("Vin+", "net1")
    assert item.attributes == {"l": "L1p-sqrt(L1p*L1s)*k", "q": "30"}
    assert item.expressions["l"].value is None
    assert item.expressions["l"].symbols == ("L1p", "sqrt", "L1s", "k")
    assert item.expressions["q"].value == pytest.approx(30.0)
    assert item.line_number == 1


def test_parser_accepts_the_brief_leading_plus_continuation_form():
    """The documented continuation prefix must not become an attribute token."""
    parsed = parse_netlist(
        "L0 (Vin\\+ net1) inductor \\\n+             l=L1p-sqrt(L1p*L1s)*k q=30",
        {},
    )

    assert parsed.instances[0].nets == ("Vin+", "net1")
    assert parsed.instances[0].attributes["l"] == "L1p-sqrt(L1p*L1s)*k"


def test_parser_keeps_parenthesized_and_spaced_attribute_expressions_raw():
    """Task 6 needs the source expression, including its original spacing."""
    parsed = parse_netlist(
        "N0 (d g s b) nmos as=W * 2.5 * (45.0n) ps=(2 * W) + (5 * (45.0n))",
        {},
    )

    item = parsed.instances[0]
    assert item.attributes["as"] == "W * 2.5 * (45.0n)"
    assert item.attributes["ps"] == "(2 * W) + (5 * (45.0n))"
    assert item.expressions["as"].value is None
    assert item.expressions["ps"].value is None


@pytest.mark.parametrize(
    ("text", "reason", "line"),
    [
        ("X0 (a b) mystery x=1", "unknown device kind mystery", 1),
        ("R0 (a b resistor r=1", "malformed terminal list", 1),
        ("R0 (a b) resistor r=(1", "unbalanced parentheses", 1),
        ("R0 (a b) resistor r=1 \\", "unterminated continuation", 1),
        ("R0 (a) resistor r=1", "expected 2 terminals", 1),
    ],
)
def test_parser_rejects_unsupported_or_malformed_noncomment_statements(
    text: str, reason: str, line: int
):
    """Every non-comment statement must either parse or report its exact source."""
    with pytest.raises(NetlistParseError) as caught:
        parse_netlist(text, {}, path="circuits/example/source.netlist")

    error = caught.value
    assert error.path == "circuits/example/source.netlist"
    assert error.line_number == line
    assert reason in error.reason
    assert f"circuits/example/source.netlist:{line}: {reason}" in str(error)


def test_parser_ignores_comments_and_preserves_source_context():
    """Comment lines must not become devices or shift a device's physical line."""
    parsed = parse_netlist(
        "// Library name: proof\n\n  // another comment\nR0 (a b) resistor r=1k\n",
        {},
        path="memory.netlist",
    )

    item = parsed.instances[0]
    assert item.line_number == 4
    assert item.source_text == "R0 (a b) resistor r=1k"
    assert item.expressions["r"].value == pytest.approx(1000.0)


def test_parser_rejects_non_numeric_fixed_values_and_never_evaluates_expressions():
    """Fixed values are explicit numbers; derived expressions remain unevaluated."""
    with pytest.raises(NetlistParseError, match="fixed value for VDD must be numeric"):
        parse_netlist("V0 (vdd 0) vsource dc=VDD", {"VDD": "1.2"})

    parsed = parse_netlist(
        "L0 (a b) inductor l=sqrt(L1*L2)*k", {"L1": 1.0, "L2": 4.0, "k": 0.5}
    )
    assert parsed.instances[0].expressions["l"].value is None


def test_parser_rejects_nonfinite_engineering_literals():
    """An overflowing literal is malformed numeric input, not a raw expression."""
    with pytest.raises(NetlistParseError, match="numeric literal must be finite"):
        parse_netlist("R0 (a b) resistor r=1e309", {})
