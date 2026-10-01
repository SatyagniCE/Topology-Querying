"""Full canonical corpus checks, enabled after the two planned builds."""
import os
from pathlib import Path

import pytest

from circuit_ingest.networkx_corpus import audit_corpus, iter_graphs, load_graph
from circuit_ingest.networkx_graph import graph_signature


ROOT = Path(__file__).parents[2]


def _ready():
    if os.environ.get("NETWORKX_CORPUS_TEST") != "1":
        pytest.skip("set NETWORKX_CORPUS_TEST=1 after both full builds")
    assert (ROOT / "output/networkx-a/manifest.json").is_file()
    assert (ROOT / "output/networkx-b/manifest.json").is_file()
    assert (ROOT / "output/analoggenie/audit-report.json").is_file()


def test_full_corpus_matches_generated_report():
    _ready()
    report = ROOT / "output/analoggenie/audit-report.json"
    assert audit_corpus(ROOT / "output/networkx-a", report) == []
    assert audit_corpus(ROOT / "output/networkx-b", report) == []


def test_755_q30_substrate_graph_traversal():
    _ready()
    graph = load_graph(ROOT / "output/networkx-a", "analoggenie:755")
    contacts = [
        (target, edge["terminal_ordinal"])
        for device, attributes in graph.nodes(data=True)
        if attributes["kind"] == "Device" and attributes["source_instance"] == "Q30"
        for _, target, _, edge in graph.out_edges(device, keys=True, data=True)
        if edge["kind"] == "CONNECTED_TO" and edge["terminal"] == "substrate"
        and graph.nodes[target]["name"] == "0"
    ]
    assert contacts == [("analoggenie:755:net:0", 3)]


def test_two_builds_have_equal_signatures():
    _ready()
    first = iter_graphs(ROOT / "output/networkx-a")
    second = iter_graphs(ROOT / "output/networkx-b")
    count = 0
    for (left_id, left), (right_id, right) in zip(first, second, strict=True):
        assert left_id == right_id
        assert graph_signature(left) == graph_signature(right)
        count += 1
    assert count > 0
