import json
from hashlib import sha256
from pathlib import Path

import networkx as nx
import pytest

from circuit_ingest.networkx_corpus import build_corpus, iter_graphs, load_graph, run
from circuit_ingest.networkx_graph import build_networkx_graph, graph_signature
from tests.fixtures.canonical_record import sample_record


def _write(input_dir: Path, *circuit_ids: str) -> None:
    circuits = input_dir / "circuits"
    circuits.mkdir(parents=True)
    for circuit_id in circuit_ids:
        (circuits / f"{circuit_id.rsplit(':', 1)[-1]}.json").write_text(
            sample_record(circuit_id).model_dump_json(), encoding="utf-8")


def test_two_circuits_have_separate_keyed_pickles(tmp_path):
    source = tmp_path / "source"
    _write(source, "test:one", "test:two")
    cache = tmp_path / "cache"
    paths = build_corpus(source, cache)
    manifest = json.loads((cache / "manifest.json").read_text())
    assert set(paths) == set(manifest) == {"test:one", "test:two"}
    assert len(set(paths.values())) == 2
    for circuit_id, relative_path in paths.items():
        assert (cache / relative_path).is_file()
        assert manifest[circuit_id]["path"] == relative_path
        graph = load_graph(cache, circuit_id)
        assert graph.graph["circuit_id"] == circuit_id
        assert manifest[circuit_id]["record_sha256"] == sha256(
            graph.graph["record_json"].encode()).hexdigest()
        assert all(node.startswith(circuit_id + ":") for node in graph.nodes)


def test_pickle_round_trip_preserves_signature(tmp_path):
    source = tmp_path / "source"
    _write(source, "test:one")
    cache = tmp_path / "cache"
    build_corpus(source, cache)
    original = build_networkx_graph(sample_record("test:one"))
    loaded = load_graph(cache, "test:one")
    assert isinstance(loaded, nx.MultiDiGraph)
    assert graph_signature(loaded) == graph_signature(original)
    assert loaded.graph["record_json"] == original.graph["record_json"]
    assert set(loaded.edges(keys=True)) == set(original.edges(keys=True))


def test_load_by_id_and_sorted_iteration(tmp_path):
    source = tmp_path / "source"
    _write(source, "test:two", "test:one")
    cache = tmp_path / "cache"
    build_corpus(source, cache)
    assert load_graph(cache, "test:two").graph["circuit_id"] == "test:two"
    assert [circuit_id for circuit_id, _ in iter_graphs(cache)] == ["test:one", "test:two"]
    with pytest.raises(KeyError, match="test:missing"):
        load_graph(cache, "test:missing")


def test_invalid_input_leaves_no_cache(tmp_path):
    source = tmp_path / "source"
    _write(source, "test:one")
    (source / "circuits" / "zbad.json").write_text("{bad", encoding="utf-8")
    cache = tmp_path / "cache"
    with pytest.raises(ValueError, match="zbad.json"):
        build_corpus(source, cache)
    assert not cache.exists() or list(cache.rglob("*")) == []


def test_manifest_rejects_unsafe_path(tmp_path):
    source = tmp_path / "source"
    _write(source, "test:one")
    cache = tmp_path / "cache"
    paths = build_corpus(source, cache)
    manifest_path = cache / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["test:one"]["path"] = "../outside.pkl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="path"):
        load_graph(cache, "test:one")
    manifest["test:one"]["path"] = paths["test:one"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = cache / paths["test:one"]
    outside = tmp_path / "outside.pkl"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        load_graph(cache, "test:one")


def test_build_cli_needs_no_neo4j(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _write(source, "test:one")
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.delenv(name, raising=False)
    assert run(["build", "--input-dir", str(source), "--output-dir", str(tmp_path / "cache")]) == 0
    assert load_graph(tmp_path / "cache", "test:one").number_of_nodes() == 6


def _report(path: Path, record) -> Path:
    path.write_text(json.dumps({
        "status_counts": {"valid": 1},
        "totals": {"devices": record.statistics.device_count,
                   "nets": record.statistics.net_count,
                   "ports": record.statistics.external_port_count,
                   "connections": record.statistics.connection_count},
        "canonical_device_type_counts": record.statistics.device_type_counts,
    }), encoding="utf-8")
    return path


def test_audit_matches_tiny_corpus_and_spot_check(tmp_path):
    from circuit_ingest.networkx_corpus import audit_corpus
    source = tmp_path / "source"
    record = sample_record("analoggenie:755", duplicate=False)
    _write(source, "analoggenie:755")
    (source / "circuits/755.json").write_text(record.model_dump_json(), encoding="utf-8")
    cache = tmp_path / "cache"
    build_corpus(source, cache)
    assert audit_corpus(cache, _report(tmp_path / "report.json", record)) == []


@pytest.mark.parametrize("field,expected", [
    ("status", "Circuit"), ("devices", "Device"), ("nets", "Net"),
    ("ports", "Port"), ("connections", "CONNECTED_TO"),
    ("type", "device type npn"),
])
def test_report_change_changes_expected_counts(tmp_path, field, expected):
    from circuit_ingest.networkx_corpus import audit_corpus
    record = sample_record("analoggenie:755", duplicate=False)
    source = tmp_path / "source"
    _write(source, "analoggenie:755")
    (source / "circuits/755.json").write_text(record.model_dump_json(), encoding="utf-8")
    cache = tmp_path / "cache"
    build_corpus(source, cache)
    report = _report(tmp_path / "report.json", record)
    data = json.loads(report.read_text())
    if field == "status":
        data["status_counts"]["valid"] += 1
    elif field == "type":
        data["canonical_device_type_counts"]["npn"] += 1
    else:
        data["totals"][field] += 1
    report.write_text(json.dumps(data), encoding="utf-8")
    assert any(expected in message for message in audit_corpus(cache, report))


def test_audit_cli_exits_nonzero_for_changed_report(tmp_path):
    record = sample_record("analoggenie:755", duplicate=False)
    source = tmp_path / "source"
    _write(source, "analoggenie:755")
    (source / "circuits/755.json").write_text(record.model_dump_json(), encoding="utf-8")
    cache = tmp_path / "cache"
    build_corpus(source, cache)
    report = _report(tmp_path / "report.json", record)
    data = json.loads(report.read_text())
    data["totals"]["devices"] += 1
    report.write_text(json.dumps(data), encoding="utf-8")
    assert run(["audit", "--output-dir", str(cache), "--report", str(report)]) == 1
