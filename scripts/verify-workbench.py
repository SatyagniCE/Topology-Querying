"""Read-only smoke checks for the running local workbench and live Neo4j."""
import json
import sys

import httpx


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"
    with httpx.Client(base_url=base, timeout=30) as client:
        def get(path, **params):
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

        def post(path, body):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        health = get("/api/status")
        assert health["circuits"] >= 3350
        assert health["retrieval"]["state"] == "ready", health
        assert health["neo4j"]["connected"] and not health["neo4j"]["pending"], health
        identifier = "analoggenie:1004"
        path = "/api/circuits/" + identifier
        detail = get(path)
        assert detail["statistics"]["device_count"] == 17
        graphs = {kind: get(path + "/graph", backend=kind) for kind in ("networkx", "neo4j")}
        signature = lambda g: sorted((n["canonical_id"], n["kind"]) for n in g["nodes"])
        assert signature(graphs["networkx"]) == signature(graphs["neo4j"])
        assert all(len(g["nodes"]) == 40 and len(g["edges"]) == 68 for g in graphs.values())
        for kind in detail["assets"]:
            image = client.get(path + "/asset/" + kind)
            assert image.status_code == 200 and image.headers["content-type"].startswith("image/")
        exported = get(path + "/networkx")
        assert exported["multigraph"] and exported["directed"] and len(exported["edges"]) == 68
        query = "MATCH (c:Circuit {id:$id})-[:HAS_DEVICE]->(d) MATCH (d)-[r:CONNECTED_TO]->(n) RETURN d,r,n"
        result = post("/api/query", {"query": query, "parameters": {"id": identifier}})
        assert len(result["rows"]) == 60 and len(result["graph"]["nodes"]) == 32
        before = post("/api/query", {"query": "MATCH (c:Circuit) RETURN count(c) AS n"})["rows"][0]["n"]
        assert client.post("/api/query", json={"query": "MATCH (n) DETACH DELETE n"}).status_code == 422
        after = post("/api/query", {"query": "MATCH (c:Circuit) RETURN count(c) AS n"})["rows"][0]["n"]
        assert before == after == health["circuits"]
        assert client.post("/api/query", json={"query": "MATCH ("}).status_code == 422
        query = "MATCH (ref:Circuit {id:$id}) MATCH (c:Circuit) SEARCH c IN (VECTOR INDEX circuit_topology_idx FOR ref.topology_embedding LIMIT 21) SCORE AS score WITH c,ref,score WHERE c<>ref RETURN c.id AS id,score,c.topology_descriptor_version AS version ORDER BY score DESC"
        neighbors = post("/api/query", {"query": query, "parameters": {"id": identifier}})
        from circuit_workbench.retrieval import VERSION
        assert "analoggenie:1009" in {r["id"] for r in neighbors["rows"]}
        assert all(r["id"] != identifier and r["version"] == VERSION for r in neighbors["rows"])
        topology = post("/api/search", {"reference_id": identifier, "limit": 10})
        # Reviewed two-output/RC shape candidates remain near the top, but a
        # structural reranker need not keep the old cosine winner in first place.
        assert {"analoggenie:1009", "analoggenie:366"} <= {r["id"] for r in topology["items"][:5]}
        assert topology["descriptor_version"] == VERSION and topology["reranked"] == 100
        assert all(r["structural_score"] is not None for r in topology["items"])
        assert all(r["id"] != identifier for r in topology["items"])
        hybrid = post("/api/search", {"text": "Differential amplifier with two output branches", "reference_id": identifier, "limit": 10})
        assert hybrid["mode"] == "hybrid" and len(hybrid["items"]) == 10
        assert all(r["semantic_score"] is not None and r["topology_score"] is not None for r in hybrid["items"])
        semantic = post("/api/search", {"text": "Resistively loaded common-source amplifier", "limit": 10})
        assert semantic["mode"] == "semantic" and len(semantic["items"]) == 10
        assert client.post("/api/uploads/preview", json={"netlist": "junk", "description": "Invalid test"}).status_code == 422
        print(json.dumps({"passed": True, "circuits": health["circuits"], "indexed": health["indexed"],
                          "graph_parity": {k: [len(v["nodes"]), len(v["edges"])] for k, v in graphs.items()},
                          "descriptor_version": VERSION,
                          "topology_neighbors": [{"id": r["id"], "cosine": round(r["topology_score"], 3), "full_pattern": round(r["structural_score"], 3)} for r in topology["items"][:5]],
                          "hybrid_candidates": [r["id"] for r in hybrid["items"][:5]],
                          "query_guard_preserved_count": after}, indent=2))


if __name__ == "__main__":
    main()
