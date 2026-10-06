"""Live graph access, search-vector synchronization and a read-only query console."""
import json
import re
import threading
import time

import numpy as np
from neo4j import GraphDatabase, Query, READ_ACCESS
from neo4j.graph import Node, Relationship, Path

from circuit_ingest.neo4j_store import replace_circuit
from .retrieval import MODEL, VERSION


def validate_cypher(query):
    if not query.strip() or len(query) > 20000:
        raise ValueError("Supply a Cypher query under 20,000 characters.")
    # Strip comments and literal strings before checking commands; EXPLAIN is the
    # authoritative second gate and rejects writes hidden by alternate syntax.
    code = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`[^`]*`", " ", query)
    if ";" in code.rstrip().rstrip(";"):
        raise ValueError("Run one read query at a time.")
    if re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|ALTER|GRANT|DENY|REVOKE|LOAD|FOREACH|TERMINATE|START|STOP|USE|INSERT)\b", code, re.I):
        raise ValueError("The query workbench accepts read-only Cypher. Use the circuit editor for changes.")
    if re.search(r"\bCALL\s+(?!\{)", code, re.I):
        raise ValueError("Procedure calls are unavailable in the V1 console; MATCH, RETURN and SEARCH are supported.")
    if re.match(r"\s*(EXPLAIN|PROFILE|SHOW|CYPHER)\b", code, re.I):
        raise ValueError("Enter the read query directly, starting with MATCH, WITH, RETURN or CALL { ... }.")
    return query.strip().rstrip(";")


def clean_properties(properties):
    return {k: v for k, v in dict(properties).items() if k not in {"record_json", "semantic_embedding", "topology_embedding"}}


class Serializer:
    def __init__(self):
        self.nodes, self.edges, self.circuits = {}, {}, set()
        self.truncated = False

    def convert(self, value, depth=0):
        if depth > 12:
            return "[nested value]"
        if isinstance(value, Node):
            props = clean_properties(value)
            identifier = props.get("id", value.element_id)
            kind = next(iter(value.labels), "Node")
            label = props.get("source_instance") or props.get("name") or ("Circuit " + str(identifier).split(":")[-1] if kind == "Circuit" else str(identifier).split(":")[-1])
            if len(self.nodes) < 1200:
                self.nodes[value.element_id] = {"id": value.element_id, "canonical_id": identifier, "kind": kind,
                                                "label": label, "properties": props}
            elif value.element_id not in self.nodes:
                self.truncated = True
            if kind == "Circuit":
                self.circuits.add(str(identifier))
            elif ":device:" in str(identifier) or ":net:" in str(identifier) or ":port:" in str(identifier):
                self.circuits.add(re.split(r":(?:device|net|port):", str(identifier))[0])
            return {"type": kind, **props}
        if isinstance(value, Relationship):
            self.convert(value.start_node)
            self.convert(value.end_node)
            props = dict(value)
            if len(self.edges) < 3000 and value.start_node.element_id in self.nodes and value.end_node.element_id in self.nodes:
                self.edges[value.element_id] = {"id": value.element_id, "from": value.start_node.element_id,
                                                "to": value.end_node.element_id, "label": props.get("terminal", value.type),
                                                "kind": value.type, "properties": props}
            elif value.element_id not in self.edges:
                self.truncated = True
            return {"type": value.type, **props}
        if isinstance(value, Path):
            return {"nodes": [self.convert(n) for n in value.nodes], "relationships": [self.convert(r) for r in value.relationships]}
        if isinstance(value, dict):
            return {str(k): self.convert(v, depth + 1) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            converted = [self.convert(v, depth + 1) for v in value[:1000]]
            return {"items": converted, "truncated": True, "total": len(value)} if len(value) > 1000 else converted
        if isinstance(value, str):
            if re.fullmatch(r"(?:analoggenie:\d+|uploaded:[\w-]+)", value):
                self.circuits.add(value)
            return value
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)

    def graph(self):
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values()), "truncated": self.truncated}


class Neo4jService:
    def __init__(self, settings, catalog):
        self.catalog, self.settings = catalog, settings
        self.lock = threading.Lock()
        self.state = {"connected": False, "error": "", "pending": 0}
        self.driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password),
                                          connection_timeout=3, connection_acquisition_timeout=4, max_connection_pool_size=6)

    def health(self):
        try:
            self.driver.verify_connectivity()
            self.state.update(connected=True, error="")
        except Exception as exc:
            self.state.update(connected=False, error=str(exc))
        with self.catalog.connect() as db:
            self.state["pending"] = db.execute("SELECT count(*) FROM circuits WHERE sync_state != 'synced'").fetchone()[0]
        return dict(self.state)

    def query(self, text, parameters=None, limit=200):
        query = validate_cypher(text)
        serializer = Serializer()
        start = time.monotonic()
        with self.driver.session(database=self.settings.neo4j_database, default_access_mode=READ_ACCESS) as session:
            with session.begin_transaction(timeout=10) as tx:
                summary = tx.run("EXPLAIN " + query, parameters or {}).consume()
                if summary.query_type != "r":
                    raise ValueError("Neo4j identified this as a write or schema query; it was not executed.")
                result = tx.run(query, parameters or {})
                columns = list(result.keys())
                rows = []
                truncated = False
                for row in result:
                    if len(rows) >= limit:
                        truncated = True
                        break
                    rows.append({k: serializer.convert(v) for k, v in dict(row).items()})
                # Rollback ends expensive streaming queries once the display cap is met.
                tx.rollback()
        self.state.update(connected=True, error="")
        return {"columns": columns, "rows": rows, "graph": serializer.graph(), "circuit_ids": sorted(serializer.circuits)[:50],
                "elapsed_ms": round((time.monotonic() - start) * 1000), "truncated": truncated, "limit": limit}

    def graph(self, identifier):
        result = self.query("MATCH (c:Circuit {id:$id})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n) OPTIONAL MATCH (n)-[r:CONNECTED_TO|MAPS_TO]->(m) RETURN n,r,m", {"id": identifier}, limit=3000)
        if not result["graph"]["nodes"]:
            raise ValueError("This circuit has not been synchronized to Neo4j yet.")
        result["graph"]["truncated"] |= result["truncated"]
        return result["graph"]

    def sync(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if not self.health()["connected"]:
                return
            with self.catalog.connect() as db:
                rows = db.execute("SELECT c.id,c.record,c.metadata,c.reference_text,c.revision,v.semantic,v.topology,v.text_hash FROM circuits c JOIN vectors v ON c.id=v.id AND c.revision=v.revision WHERE c.sync_state!='synced' AND v.semantic IS NOT NULL AND v.topology IS NOT NULL AND v.descriptor_version=? AND v.model=?", (VERSION, MODEL)).fetchall()
            with self.driver.session(database=self.settings.neo4j_database) as session:
                for index in range(0, len(rows), 64):
                    batch = []
                    for row in rows[index:index + 64]:
                        if row["id"].startswith("uploaded:"):
                            exists = session.run("MATCH (c:Circuit {id:$id}) RETURN count(c) AS n", id=row["id"]).single()["n"]
                            if not exists:
                                replace_circuit(self.driver, self.settings.neo4j_database, self.catalog.record(row["id"]))
                        metadata = json.loads(row["metadata"])
                        batch.append({"id": row["id"], "revision": row["revision"], "text_hash": row["text_hash"], "properties": {
                            "title": metadata.get("title", ""), "description": metadata.get("description", ""),
                            "family": metadata.get("family", ""), "topology": metadata.get("topology", ""),
                            "stage_count": metadata.get("stage_count"), "input_mode": metadata.get("input_mode", ""),
                            "output_mode": metadata.get("output_mode", ""), "tags": metadata.get("tags", []),
                            "notes": metadata.get("notes", ""), "metadata_revision": row["revision"],
                            "search_text": self.catalog.search_text_row(row), "embedding_model": MODEL,
                            "topology_descriptor_version": VERSION, "embedding_text_hash": row["text_hash"],
                            "semantic_embedding": np.frombuffer(row["semantic"], dtype=np.float32).tolist(),
                            "topology_embedding": np.frombuffer(row["topology"], dtype=np.float32).tolist()}})
                    synced = session.run("UNWIND $rows AS row MATCH (c:Circuit {id:row.id}) SET c += row.properties RETURN c.id AS id", rows=batch)
                    ids = [r["id"] for r in synced]
                    with self.catalog.connect() as db:
                        for entry in batch:
                            if entry["id"] in ids:
                                db.execute("""UPDATE circuits SET sync_state='synced',sync_error='' WHERE id=? AND revision=?
                                    AND EXISTS(SELECT 1 FROM vectors v WHERE v.id=circuits.id AND v.revision=circuits.revision
                                        AND v.descriptor_version=? AND v.model=? AND v.text_hash=? AND v.semantic IS NOT NULL)""",
                                    (entry["id"], entry["revision"], VERSION, MODEL, entry["text_hash"]))
                            else:
                                db.execute("UPDATE circuits SET sync_error='Circuit missing in Neo4j; import the canonical corpus first' WHERE id=?", (entry["id"],))
                for name, property_name, dimension in (("circuit_semantic_idx", "semantic_embedding", 384), ("circuit_topology_idx", "topology_embedding", 768)):
                    session.run(f"CREATE VECTOR INDEX {name} IF NOT EXISTS FOR (c:Circuit) ON c.{property_name} OPTIONS {{indexConfig: {{`vector.dimensions`: {dimension}, `vector.similarity_function`: 'cosine', `vector.quantization.type`: 'none'}}}}").consume()
            self.health()
        except Exception as exc:
            self.state.update(error=str(exc))
            with self.catalog.connect() as db:
                db.execute("UPDATE circuits SET sync_error=? WHERE sync_state!='synced'", (str(exc),))
        finally:
            self.lock.release()
