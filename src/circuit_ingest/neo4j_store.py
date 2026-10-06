"""Transactional Neo4j storage for canonical circuit projections."""
from __future__ import annotations

from neo4j import Driver, ManagedTransaction

from .canonical_graph import CircuitProjection, project_circuit
from .models import CircuitRecord


_CONSTRAINTS = (
    "CREATE CONSTRAINT circuit_id_unique IF NOT EXISTS FOR (c:Circuit) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT device_id_unique IF NOT EXISTS FOR (d:Device) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT net_id_unique IF NOT EXISTS FOR (n:Net) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT port_id_unique IF NOT EXISTS FOR (p:Port) REQUIRE p.id IS UNIQUE",
)
_OWNERSHIP = {"Device": "HAS_DEVICE", "Net": "HAS_NET", "Port": "HAS_PORT"}


def create_constraints(driver: Driver, database: str) -> None:
    """Create the four stable-ID uniqueness constraints before import."""
    for statement in _CONSTRAINTS:
        driver.execute_query(statement, database_=database)


def replace_circuit(driver: Driver, database: str, record: CircuitRecord) -> None:
    """Atomically replace one circuit and its owned topology."""
    projection = project_circuit(record)
    with driver.session(database=database) as session:
        session.execute_write(_replace_circuit_tx, projection)


def create_circuit_if_missing(driver: Driver, database: str, record: CircuitRecord) -> bool:
    """Bootstrap absent circuits without replacing existing topology or annotations."""
    projection = project_circuit(record)
    with driver.session(database=database) as session:
        return session.execute_write(_create_missing_tx, projection)


def _create_missing_tx(tx: ManagedTransaction, projection: CircuitProjection) -> bool:
    exists = tx.run("MATCH (c:Circuit {id:$id}) RETURN count(c) AS n",
                    id=projection.circuit_id).single()
    if exists["n"]:
        return False
    tx.run("""
        CREATE (c:Circuit {id:$id, dataset:$dataset,
                           schema_version:$schema_version, record_json:$record_json})
    """, id=projection.circuit_id, dataset=projection.dataset,
           schema_version=projection.schema_version,
           record_json=projection.record_json).consume()
    _create_projected_subgraph(tx, projection)
    return True


def _replace_circuit_tx(tx: ManagedTransaction, projection: CircuitProjection) -> None:
    circuit_id = projection.circuit_id
    tx.run("""
        MATCH (c:Circuit {id:$id})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n)
        DETACH DELETE n
    """, id=circuit_id).consume()
    tx.run("MATCH (c:Circuit {id:$id}) DETACH DELETE c", id=circuit_id).consume()
    tx.run("""
        CREATE (c:Circuit {id:$id, dataset:$dataset,
                           schema_version:$schema_version, record_json:$record_json})
    """, id=circuit_id, dataset=projection.dataset,
           schema_version=projection.schema_version,
           record_json=projection.record_json).consume()
    _create_projected_subgraph(tx, projection)


def _create_projected_subgraph(tx: ManagedTransaction,
                               projection: CircuitProjection) -> None:
    circuit_id = projection.circuit_id
    for kind, ownership in _OWNERSHIP.items():
        rows = [{"id": node.id, **node.properties}
                for node in projection.nodes if node.kind == kind]
        if not rows:
            continue
        result = tx.run(f"""
            UNWIND $rows AS props
            MATCH (c:Circuit {{id:$circuit_id}})
            CREATE (n:{kind}) SET n = props
            CREATE (c)-[:{ownership}]->(n)
            RETURN count(n) AS created
        """, rows=rows, circuit_id=circuit_id).single()
        if result is None or result["created"] != len(rows):
            raise RuntimeError(f"failed to create all {kind} nodes for {circuit_id}")
    for kind, source_label in (("CONNECTED_TO", "Device"), ("MAPS_TO", "Port")):
        rows = [{"source": edge.source, "target": edge.target,
                 "properties": edge.properties}
                for edge in projection.edges if edge.kind == kind]
        if not rows:
            continue
        result = tx.run(f"""
            UNWIND $rows AS row
            MATCH (source:{source_label} {{id:row.source}})
            MATCH (target:Net {{id:row.target}})
            CREATE (source)-[r:{kind}]->(target)
            SET r = row.properties
            RETURN count(r) AS created
        """, rows=rows).single()
        if result is None or result["created"] != len(rows):
            raise RuntimeError(f"failed to create all {kind} edges for {circuit_id}")
