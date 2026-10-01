"""Both adapters must materialize the same shared circuit projection."""
import json
import os
from pathlib import Path
from uuid import uuid4

from neo4j import GraphDatabase
import pytest

from circuit_ingest.canonical_graph import project_circuit
from circuit_ingest.neo4j_store import create_constraints, replace_circuit
from circuit_ingest.networkx_graph import build_networkx_graph
from tests.fixtures.canonical_record import sample_record


def _settings():
    values = dict(os.environ)
    path = Path.home() / ".config/query-retrieve/neo4j.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, value = line.split("=", 1)
            values.setdefault(name, value)
    names = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")
    if any(name not in values for name in names):
        if os.environ.get("NEO4J_TEST_REQUIRED") == "1":
            pytest.fail("Neo4j parity settings are missing")
        pytest.skip("Neo4j parity settings are missing")
    return values


def _packed(properties):
    return json.dumps(properties, sort_keys=True, separators=(",", ":"))


def test_networkx_and_neo4j_match_shared_projection():
    settings = _settings()
    circuit_id = f"test:parity:{uuid4().hex}"
    record = sample_record(circuit_id)
    projection = project_circuit(record)
    graph = build_networkx_graph(record)
    expected_nodes = sorted((node.kind, node.id,
                             _packed({"id": node.id, **node.properties}))
                            for node in projection.nodes)
    expected_edges = sorted((edge.kind, edge.source, edge.target,
                             _packed(edge.properties)) for edge in projection.edges)
    graph_nodes = sorted((data["kind"], node_id,
                          _packed({key: value for key, value in data.items() if key != "kind"}))
                         for node_id, data in graph.nodes(data=True))
    graph_edges = sorted((data["kind"], source, target,
                          _packed({key: value for key, value in data.items() if key != "kind"}))
                         for source, target, data in graph.edges(data=True))
    assert graph_nodes == expected_nodes
    assert graph_edges == expected_edges

    with GraphDatabase.driver(settings["NEO4J_URI"], auth=(settings["NEO4J_USER"],
                                                    settings["NEO4J_PASSWORD"])) as driver:
        try:
            driver.verify_connectivity()
        except Exception:
            if os.environ.get("NEO4J_TEST_REQUIRED") == "1":
                raise
            pytest.skip("Neo4j parity database is unavailable")
        db = settings["NEO4J_DATABASE"]
        create_constraints(driver, db)
        try:
            replace_circuit(driver, db, record)
            nodes, _, _ = driver.execute_query("""
                MATCH (c:Circuit {id:$id})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n)
                RETURN labels(n) AS labels, properties(n) AS props
            """, id=circuit_id, database_=db)
            edges, _, _ = driver.execute_query("""
                MATCH (c:Circuit {id:$id})-[:HAS_DEVICE|HAS_PORT]->(s)
                      -[r:CONNECTED_TO|MAPS_TO]->(t:Net)
                MATCH (c)-[:HAS_NET]->(t)
                RETURN type(r) AS kind, s.id AS source, t.id AS target,
                       properties(r) AS props
            """, id=circuit_id, database_=db)
            db_nodes = sorted((row["labels"][0], row["props"]["id"],
                               _packed(row["props"])) for row in nodes)
            db_edges = sorted((row["kind"], row["source"], row["target"],
                               _packed(row["props"])) for row in edges)
            assert db_nodes == expected_nodes
            assert db_edges == expected_edges
        finally:
            with driver.session(database=db) as session:
                session.run("""
                    MATCH (c:Circuit {id:$id})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n)
                    DETACH DELETE n
                """, id=circuit_id).consume()
                session.run("MATCH (c:Circuit {id:$id}) DETACH DELETE c",
                            id=circuit_id).consume()
