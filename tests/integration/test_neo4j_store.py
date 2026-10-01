from __future__ import annotations

import os
import json
from pathlib import Path

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ConstraintError

from circuit_ingest.models import (
    CircuitRecord, Connection, DeviceRecord, NetRecord, ParseMode,
    ParserRecord, PortRecord, SourceRecord, Statistics,
)
from circuit_ingest.neo4j_store import create_constraints, replace_circuit
from circuit_ingest.neo4j_cli import run
from circuit_ingest.neo4j_audit import audit_database
from circuit_ingest.loader import discover
from circuit_ingest.parser import AnalogGenieParser


def _record(circuit_id: str) -> CircuitRecord:
    shared = f"{circuit_id}:net:shared"
    ground = f"{circuit_id}:net:0"
    unused = f"{circuit_id}:net:unused"
    device_ids = [f"{circuit_id}:device:{ordinal:06d}" for ordinal in (1, 2)]
    devices = [
        DeviceRecord(
            id=device_ids[0], ordinal=1, source_instance="Q30", source_line=1,
            raw_type="npn", canonical_type="npn", category="transistor",
            connections=[
                Connection(terminal="collector", terminal_ordinal=0, net_id=shared),
                Connection(terminal="base", terminal_ordinal=1, net_id=shared),
                Connection(terminal="emitter", terminal_ordinal=2, net_id=shared),
                Connection(terminal="substrate", terminal_ordinal=3, net_id=ground),
            ], raw_line="Q30 (shared shared shared 0) npn",
        ),
        DeviceRecord(
            id=device_ids[1], ordinal=2, source_instance="Q30", source_line=2,
            raw_type="npn", canonical_type="npn", category="transistor",
            connections=[
                Connection(terminal="collector", terminal_ordinal=0, net_id=shared),
                Connection(terminal="base", terminal_ordinal=1, net_id=shared),
                Connection(terminal="emitter", terminal_ordinal=2, net_id=shared),
                Connection(terminal="substrate", terminal_ordinal=3, net_id=ground),
            ], raw_line="Q30 (shared shared shared 0) npn",
        ),
    ]
    return CircuitRecord(
        parser=ParserRecord(mode=ParseMode.STRICT), circuit_id=circuit_id,
        source_circuit_id=circuit_id, dataset="test",
        source=SourceRecord(primary_netlist="test.cir", port_file="Port.txt",
                            primary_sha256="0" * 64, port_sha256="0" * 64,
                            auxiliary_files=[]),
        ports=[PortRecord(name="unused", ordinal=0, net_id=unused,
                          referenced_by_device=False)],
        nets=[
            NetRecord(id=shared, name="shared", is_external=False,
                      port_ordinal=None, degree_by_terminal=6),
            NetRecord(id=ground, name="0", is_external=False,
                      port_ordinal=None, degree_by_terminal=2),
            NetRecord(id=unused, name="unused", is_external=True,
                      port_ordinal=0, degree_by_terminal=0),
        ], devices=devices,
        statistics=Statistics(device_count=2, net_count=3, external_port_count=1,
                              connection_count=8, device_type_counts={"npn": 2},
                              duplicate_source_instance_count=1,
                              unreferenced_port_count=1,
                              unknown_device_type_count=0), issues=[],
    )


def _settings() -> dict[str, str]:
    values = dict(os.environ)
    path = Path.home() / ".config/query-retrieve/neo4j.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, value = line.split("=", 1)
            values.setdefault(name, value)
    return values


@pytest.fixture
def database(request):
    settings = _settings()
    driver = GraphDatabase.driver(settings["NEO4J_URI"],
                                  auth=(settings["NEO4J_USER"], settings["NEO4J_PASSWORD"]))
    driver.verify_connectivity()
    database_name = settings["NEO4J_DATABASE"]
    circuit_id = f"test:neo4j:{request.node.name}"
    create_constraints(driver, database_name)
    try:
        yield driver, database_name, circuit_id
    finally:
        with driver.session(database=database_name) as session:
            session.run("MATCH (c:Circuit {id:$id})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n) DETACH DELETE n",
                        id=circuit_id).consume()
            session.run("MATCH (c:Circuit {id:$id}) DETACH DELETE c", id=circuit_id).consume()
        driver.close()


def _one(driver, database_name, query, **params):
    with driver.session(database=database_name) as session:
        return session.run(query, **params).single()


def test_terminal_direction_and_ordinal(database):
    driver, db, circuit_id = database
    replace_circuit(driver, db, _record(circuit_id))
    row = _one(driver, db, """
        MATCH (:Circuit {id:$id})-[:HAS_DEVICE]->(d:Device)-[r:CONNECTED_TO]->(n:Net {name:'0'})
        WHERE d.ordinal = 1
        RETURN r.terminal AS terminal, r.terminal_ordinal AS ordinal, n.id AS net_id
    """, id=circuit_id)
    assert dict(row) == {"terminal": "substrate", "ordinal": 3,
                         "net_id": f"{circuit_id}:net:0"}
    assert _one(driver, db, "MATCH (:Net)-[r:CONNECTED_TO]->(:Device) RETURN count(r) AS n")["n"] == 0


def test_zero_degree_port_maps_to_net(database):
    driver, db, circuit_id = database
    replace_circuit(driver, db, _record(circuit_id))
    row = _one(driver, db, """
        MATCH (:Circuit {id:$id})-[:HAS_PORT]->(p:Port)-[:MAPS_TO]->(n:Net)
        RETURN p.id AS port_id, p.referenced_by_device AS referenced,
               n.name AS net_name, n.degree_by_terminal AS degree
    """, id=circuit_id)
    assert dict(row) == {"port_id": f"{circuit_id}:port:000000",
                         "referenced": False, "net_name": "unused", "degree": 0}


def test_duplicate_source_names_keep_distinct_ids(database):
    driver, db, circuit_id = database
    replace_circuit(driver, db, _record(circuit_id))
    row = _one(driver, db, """
        MATCH (:Circuit {id:$id})-[:HAS_DEVICE]->(d:Device {source_instance:'Q30'})
        RETURN count(d) AS n, collect(d.id) AS ids
    """, id=circuit_id)
    assert row["n"] == 2
    assert set(row["ids"]) == {f"{circuit_id}:device:000001",
                               f"{circuit_id}:device:000002"}


def test_unknown_net_is_rejected_without_write(database):
    driver, db, circuit_id = database
    record = _record(circuit_id)
    record.devices[0].connections[0].net_id = "missing"
    with pytest.raises(ValueError, match="missing net"):
        replace_circuit(driver, db, record)
    assert _one(driver, db, "MATCH (c:Circuit {id:$id}) RETURN count(c) AS n", id=circuit_id)["n"] == 0


def test_failed_transaction_preserves_previous_circuit(database):
    driver, db, circuit_id = database
    other_id = f"{circuit_id}:other"
    create_constraints(driver, db)
    replace_circuit(driver, db, _record(circuit_id))
    replace_circuit(driver, db, _record(other_id))
    try:
        conflicting = _record(circuit_id)
        conflicting.devices[0].id = f"{other_id}:device:000001"
        with pytest.raises(ConstraintError):
            replace_circuit(driver, db, conflicting)
        row = _one(driver, db, """
            MATCH (:Circuit {id:$id})-[:HAS_DEVICE]->(d:Device)
            RETURN count(d) AS n, collect(d.id) AS ids
        """, id=circuit_id)
        assert row["n"] == 2
        assert f"{circuit_id}:device:000001" in row["ids"]
    finally:
        with driver.session(database=db) as session:
            session.run("MATCH (c:Circuit {id:$id})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n) DETACH DELETE n",
                        id=other_id).consume()
            session.run("MATCH (c:Circuit {id:$id}) DETACH DELETE c", id=other_id).consume()


def test_device_net_pattern_returns_circuit(database):
    driver, db, circuit_id = database
    replace_circuit(driver, db, _record(circuit_id))
    row = _one(driver, db, """
        MATCH (c:Circuit {id:$id})-[:HAS_DEVICE]->(d:Device {canonical_type:'npn'})
              -[:CONNECTED_TO]->(n:Net {name:'shared'})
        RETURN c.id AS circuit_id, count(DISTINCT d) AS devices
    """, id=circuit_id)
    assert dict(row) == {"circuit_id": circuit_id, "devices": 2}


def test_import_cli_reports_valid_and_invalid_records(database, tmp_path, monkeypatch, capsys):
    driver, db, circuit_id = database
    settings = _settings()
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.setenv(name, settings[name])
    input_dir = tmp_path / "input"
    circuits = input_dir / "circuits"
    circuits.mkdir(parents=True)
    (circuits / "valid.json").write_text(_record(circuit_id).model_dump_json(), encoding="utf-8")
    (circuits / "invalid.json").write_text("{not-json", encoding="utf-8")

    result = run(["import", "--input-dir", str(input_dir)])

    output = capsys.readouterr()
    assert result != 0
    assert "invalid.json" in output.err
    assert "imported=1" in output.out
    assert "failed=1" in output.out
    assert _one(driver, db, "MATCH (c:Circuit {id:$id}) RETURN count(c) AS n", id=circuit_id)["n"] == 1


def test_import_cli_rejects_invalid_record_without_partial_graph(database, tmp_path, monkeypatch):
    driver, db, circuit_id = database
    settings = _settings()
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.setenv(name, settings[name])
    input_dir = tmp_path / "input"
    circuits = input_dir / "circuits"
    circuits.mkdir(parents=True)
    record = _record(circuit_id)
    record.devices[0].connections[0].net_id = "missing"
    (circuits / "invalid.json").write_text(record.model_dump_json(), encoding="utf-8")

    assert run(["import", "--input-dir", str(input_dir)]) != 0
    assert _one(driver, db, "MATCH (c:Circuit {id:$id}) RETURN count(c) AS n", id=circuit_id)["n"] == 0


def test_import_cli_reports_unreachable_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "not-used")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    circuits = tmp_path / "circuits"
    circuits.mkdir()
    (circuits / "valid.json").write_text(_record("test:unreachable").model_dump_json(), encoding="utf-8")

    assert run(["import", "--input-dir", str(tmp_path)]) != 0
    assert "connect" in capsys.readouterr().err.lower()


def test_audit_spot_checks_circuit_755_q30_substrate(database, tmp_path, monkeypatch):
    driver, db, _ = database
    root = Path(__file__).parents[2]
    existing = _one(driver, db, "MATCH (c:Circuit {id:'analoggenie:755'}) RETURN count(c) AS n")["n"]
    if existing:
        report = root / "analoggenie-audit-report.json"
        report_data = json.loads(report.read_text(encoding="utf-8"))
    else:
        dataset = root / "AnalogGenie" / "Dataset"
        source = next(bundle for bundle in discover(dataset) if bundle.circuit_id == "755")
        result = AnalogGenieParser().parse(source)
        assert result.circuit is not None
        record = result.circuit
        replace_circuit(driver, db, record)
        report = tmp_path / "audit-report.json"
        report_data = {
            "status_counts": {"valid": 1, "valid_with_warnings": 0},
            "totals": {"devices": record.statistics.device_count,
                       "nets": record.statistics.net_count,
                       "ports": record.statistics.external_port_count,
                       "connections": record.statistics.connection_count},
            "canonical_device_type_counts": record.statistics.device_type_counts,
        }
        report.write_text(json.dumps(report_data), encoding="utf-8")
    try:
        assert audit_database(driver, db, report) == []
        settings = _settings()
        for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
            monkeypatch.setenv(name, settings[name])
        assert run(["audit", "--report", str(report)]) == 0
        report_data["totals"]["devices"] += 1
        wrong_report = tmp_path / "wrong-audit-report.json"
        wrong_report.write_text(json.dumps(report_data), encoding="utf-8")
        assert run(["audit", "--report", str(wrong_report)]) == 1
        row = _one(driver, db, """
            MATCH (c:Circuit {id:'analoggenie:755'})-[:HAS_DEVICE]->
                  (d:Device {source_instance:'Q30'})-
                  [r:CONNECTED_TO {terminal:'substrate'}]->(n:Net {name:'0'})
            RETURN count(r) AS n, collect(r.terminal_ordinal) AS ordinals
        """)
        assert dict(row) == {"n": 1, "ordinals": [3]}
    finally:
        if not existing:
            with driver.session(database=db) as session:
                session.run("MATCH (c:Circuit {id:'analoggenie:755'})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n) DETACH DELETE n").consume()
                session.run("MATCH (c:Circuit {id:'analoggenie:755'}) DETACH DELETE c").consume()
