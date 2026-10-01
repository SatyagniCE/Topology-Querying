"""Compare a live Neo4j circuit graph with a parser audit report."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from neo4j import Driver


@dataclass(frozen=True)
class AuditSnapshot:
    counts: dict[str, int]
    device_types: dict[str, int]
    invalid_port_mappings: int
    cross_circuit_connections: int
    orphan_nodes: int
    q30_terminal_ordinals: tuple[int, ...]


def compare_snapshot(snapshot: AuditSnapshot, report_path: Path) -> list[str]:
    """Return all differences from expectations in the current report file."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    totals = report["totals"]
    statuses = report["status_counts"]
    expected_counts = {
        "Circuit": statuses.get("valid", 0) + statuses.get("valid_with_warnings", 0),
        "Device": totals["devices"],
        "Net": totals["nets"],
        "Port": totals["ports"],
        "CONNECTED_TO": totals["connections"],
        "MAPS_TO": totals["ports"],
    }
    problems = []
    for name, expected in expected_counts.items():
        actual = snapshot.counts.get(name, 0)
        if actual != expected:
            problems.append(f"{name}: expected {expected}, found {actual}")
    expected_types = report["canonical_device_type_counts"]
    for name in sorted(set(expected_types) | set(snapshot.device_types)):
        expected = expected_types.get(name, 0)
        actual = snapshot.device_types.get(name, 0)
        if actual != expected:
            problems.append(f"device type {name}: expected {expected}, found {actual}")
    if snapshot.invalid_port_mappings:
        problems.append(f"port mappings: {snapshot.invalid_port_mappings} invalid")
    if snapshot.cross_circuit_connections:
        problems.append(f"cross-circuit connections: {snapshot.cross_circuit_connections} invalid")
    if snapshot.orphan_nodes:
        problems.append(f"orphan nodes: {snapshot.orphan_nodes} found")
    if snapshot.q30_terminal_ordinals != (3,):
        problems.append("Q30 substrate to net 0: expected one terminal ordinal 3, "
                        f"found {snapshot.q30_terminal_ordinals}")
    return problems


def _count(driver: Driver, database: str, query: str) -> int:
    records, _, _ = driver.execute_query(query, database_=database)
    return records[0]["n"]


def audit_database(driver: Driver, database: str, report_path: Path) -> list[str]:
    """Query topology counts and integrity, then compare to the report."""
    counts = {}
    for label in ("Circuit", "Device", "Net", "Port"):
        counts[label] = _count(driver, database,
                               f"MATCH (n:{label}) RETURN count(n) AS n")
    for kind in ("CONNECTED_TO", "MAPS_TO"):
        counts[kind] = _count(driver, database,
                              f"MATCH ()-[r:{kind}]->() RETURN count(r) AS n")
    records, _, _ = driver.execute_query(
        "MATCH (d:Device) RETURN d.canonical_type AS kind, count(d) AS n",
        database_=database)
    device_types = {row["kind"]: row["n"] for row in records}
    invalid_port_mappings = _count(driver, database, """
        MATCH (p:Port)
        OPTIONAL MATCH (p)-[r:MAPS_TO]->(n:Net)
        WITH p, count(r) AS links, collect(n) AS mapped_nets
        WHERE links <> 1 OR NOT EXISTS {
            MATCH (c:Circuit)-[:HAS_PORT]->(p)
            MATCH (c)-[:HAS_NET]->(owned_net:Net)
            WHERE owned_net IN mapped_nets
        }
        RETURN count(p) AS n
    """)
    cross_circuit_connections = _count(driver, database, """
        MATCH (d:Device)-[r:CONNECTED_TO]->(n:Net)
        WHERE NOT EXISTS {
            MATCH (c:Circuit)-[:HAS_DEVICE]->(d)
            MATCH (c)-[:HAS_NET]->(n)
        }
        RETURN count(r) AS n
    """)
    orphan_nodes = 0
    for label, relation in (("Device", "HAS_DEVICE"), ("Net", "HAS_NET"),
                            ("Port", "HAS_PORT")):
        orphan_nodes += _count(driver, database, f"""
            MATCH (n:{label})
            WHERE NOT EXISTS {{ MATCH (:Circuit)-[:{relation}]->(n) }}
            RETURN count(n) AS n
        """)
    records, _, _ = driver.execute_query("""
        MATCH (c:Circuit {id:'analoggenie:755'})-[:HAS_DEVICE]->
              (d:Device {source_instance:'Q30'})-
              [r:CONNECTED_TO {terminal:'substrate'}]->(n:Net {name:'0'})
        RETURN collect(r.terminal_ordinal) AS ordinals
    """, database_=database)
    ordinals = tuple(records[0]["ordinals"])
    return compare_snapshot(AuditSnapshot(
        counts=counts, device_types=device_types,
        invalid_port_mappings=invalid_port_mappings,
        cross_circuit_connections=cross_circuit_connections,
        orphan_nodes=orphan_nodes,
        q30_terminal_ordinals=ordinals,
    ), report_path)
