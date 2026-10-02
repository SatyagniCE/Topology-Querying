"""Behavioral checks for the device graph HTML viewer."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

from gnn_pruning.conversion.graph import (
    TopologyAnnotations,
    build_device_graph,
    write_device_graph,
)
from gnn_pruning.conversion.netlist import parse_netlist
from gnn_pruning.visualization.render import render_graph_file, to_networkx


def _sample_graph_path(path: Path) -> Path:
    graph = build_device_graph(
        parse_netlist(
            "M1 (left right VDD VDD) nmos\n"
            "M2 (left right 0 0) pmos",
            {},
        ),
        TopologyAnnotations(),
    )
    write_device_graph(path, graph)
    return path


def _dataset(html: str, name: str) -> list[dict]:
    match = re.search(rf"{name}\s*=\s*new vis\.DataSet\((\[.*?\])\);", html, re.S)
    assert match, f"missing {name} dataset"
    return json.loads(match.group(1))


def test_networkx_keeps_all_directed_parallel_connections(tmp_path: Path):
    from gnn_pruning.conversion.graph import read_device_graph

    graph = to_networkx(read_device_graph(_sample_graph_path(tmp_path / "graph.json")))

    assert graph.is_directed() and graph.is_multigraph()
    assert graph.number_of_edges() == 4
    assert {(src, dst, key, data["net"]) for src, dst, key, data in graph.edges(keys=True, data=True)} == {
        ("M1", "M2", 0, "left"),
        ("M1", "M2", 1, "right"),
        ("M2", "M1", 0, "left"),
        ("M2", "M1", 1, "right"),
    }


def test_viewer_edge_ids_are_unique_when_device_names_contain_separator():
    graph = build_device_graph(
        parse_netlist(
            "a|b (x 0) resistor\n"
            "c (x 0) resistor\n"
            "a (y 0) resistor\n"
            "b|c (y 0) resistor",
            {},
        ),
        TopologyAnnotations(),
    )
    visual = to_networkx(graph)
    edge_ids = [data["id"] for _, _, data in visual.edges(data=True)]

    assert len(edge_ids) == 4
    assert len(set(edge_ids)) == 4


def test_html_has_distinct_edges_rail_badges_and_inline_assets(tmp_path: Path):
    output = tmp_path / "circuit.html"
    render_graph_file(_sample_graph_path(tmp_path / "graph.json"), output)
    html = output.read_text(encoding="utf-8")
    nodes = {node["id"]: node for node in _dataset(html, "nodes")}
    edges = _dataset(html, "edges")

    assert set(nodes) == {"M1", "M2"}
    assert nodes["M1"]["label"].startswith("M1")
    assert "nmos" in nodes["M1"]["title"]
    assert "drain → left" in nodes["M1"]["title"]
    assert "gate → right" in nodes["M1"]["title"]
    assert "source →" in nodes["M1"]["title"]
    assert "body →" in nodes["M1"]["title"]
    assert "source → VDD" in nodes["M1"]["title"]
    assert "body → VDD" in nodes["M1"]["title"]
    assert "source → 0" in nodes["M2"]["title"]
    assert "body → 0" in nodes["M2"]["title"]
    assert "net unavailable" not in nodes["M1"]["title"]
    assert "<br>" not in nodes["M1"]["title"]
    assert "\nsource → VDD" in nodes["M1"]["title"]
    assert "VDD" in nodes["M1"]["label"]
    assert "GND" in nodes["M2"]["label"]
    assert {edge.get("label", "") for edge in edges} == {""}
    assert any("left: M1.drain ↔ M2.drain" in edge["title"] for edge in edges)
    assert any("right: M1.gate ↔ M2.gate" in edge["title"] for edge in edges)
    assert all("<br>" not in edge["title"] for edge in edges)
    assert len(edges) == 4
    assert len({edge["id"] for edge in edges}) == 4
    assert all(edge["smooth"]["enabled"] for edge in edges)
    assert "legend" in html.lower()
    assert "vis-network" in html
    assert not re.search(r'<(?:script|link)\b[^>]*(?:src|href)="https?://', html, re.I)


def test_cli_single_and_batch_render_graph_json(tmp_path: Path):
    source = tmp_path / "graph.json"
    _sample_graph_path(source)
    nested = tmp_path / "nested" / "other.graph.json"
    nested.parent.mkdir()
    _sample_graph_path(nested)
    one = tmp_path / "single.html"
    batch = tmp_path / "batch"

    for args in ((str(source), "--out", str(one)), (str(tmp_path), "--out", str(batch))):
        result = subprocess.run(
            [sys.executable, "-m", "gnn_pruning.visualization.render", *args],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    assert one.exists()
    assert (batch / "graph.html").exists()
    assert (batch / "nested" / "other.html").exists()


def test_folder_render_keeps_graph_and_graph_graph_outputs_distinct(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _sample_graph_path(source / "graph.json")
    _sample_graph_path(source / "graph.graph.json")
    output = tmp_path / "html"

    from gnn_pruning.visualization.render import render_folder

    rendered = render_folder(source, output)

    assert {path.name for path in rendered} == {"graph.html", "graph.graph.html"}
    assert all(path.is_file() for path in rendered)
