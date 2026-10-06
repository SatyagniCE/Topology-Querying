"""Exercise persistent researcher workflows against real local records."""
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[2]


def catalog(tmp_path):
    from circuit_workbench.catalog import Catalog
    source = tmp_path / "corpus" / "circuits"
    source.mkdir(parents=True)
    for identifier in ("1004", "1009", "2030"):
        shutil.copyfile(ROOT / "data/analoggenie/circuits" / f"{identifier}.json", source / f"{identifier}.json")
    return Catalog(tmp_path / "state", source.parent, ROOT / "AnalogGenie")


def test_catalog_preserves_edits_across_bootstrap_and_rejects_stale_revision(tmp_path):
    from circuit_workbench.catalog import RevisionConflict
    db = catalog(tmp_path)
    detail = db.detail("analoggenie:1004")
    assert detail["statistics"]["device_count"] == 17
    assert "389" in detail["reference_text"]
    saved = db.edit("analoggenie:1004", {"description": "Test differential amplifier", "tags": ["reviewed"], "family": "opamp"}, revision=0)
    assert saved["metadata"]["description"] == "Test differential amplifier"
    db.bootstrap()
    assert db.detail("analoggenie:1004")["metadata"]["family"] == "opamp"
    assert db.list(search="reviewed")["total"] == 1
    with pytest.raises(RevisionConflict):
        db.edit("analoggenie:1004", {"description": "old"}, revision=0)


def test_topology_fingerprint_ignores_instance_and_internal_net_names(tmp_path):
    from circuit_workbench.retrieval import topology_vector, cosine
    db = catalog(tmp_path)
    record = db.record("analoggenie:1004")
    renamed = record.model_copy(deep=True)
    for n in renamed.nets:
        if not n.is_external:
            n.name = "arbitrary_" + n.name
    for d in renamed.devices:
        d.source_instance = "renamed" + str(d.ordinal)
    assert cosine(topology_vector(record), topology_vector(renamed)) == pytest.approx(1.0)
    assert cosine(topology_vector(record), topology_vector(db.record("analoggenie:2030"))) < 0.999


def test_upload_requires_supported_netlist_and_description(tmp_path):
    from circuit_workbench.uploads import parse_upload
    record = parse_upload("M1 (out in 0 0) nmos4\nR1 (VDD out) resistor r=10k", "A resistively loaded NMOS amplifier", "VDD in out 0")
    assert record.statistics.device_count == 2
    assert record.devices[1].parameters["r"] == "10k"
    spice = parse_upload("* Amplifier\n.model NMOD NMOS\nM1 out in 0 0 NMOD W=10u L=1u\nR1 VDD out 10k\n.end", "Amplifier", "VDD in out 0")
    assert spice.devices[0].canonical_type == "nmos"
    assert spice.devices[1].parameters["r"] == "10k"
    for text, description in [("garbage", "something"), ("M1 out in 0 0 mystery", "something"), ("R1 (a b) resistor", ""), ("X1 a b undefined", "amp")]:
        with pytest.raises(ValueError):
            parse_upload(text, description, "")


def test_topology_preserves_io_shape_and_passive_branches(tmp_path):
    from circuit_workbench.retrieval import topology_vector, cosine
    db = catalog(tmp_path)
    reference = topology_vector(db.record("analoggenie:1004"))
    # 1009 retains two outputs and two series RC branches; 2030 has one
    # output and one capacitor. This checks wiring/shape, not circuit family.
    assert cosine(reference, topology_vector(db.record("analoggenie:1009"))) > cosine(reference, topology_vector(db.record("analoggenie:2030")))


def test_upload_duplicate_and_metadata_revision_rebuild(tmp_path):
    from circuit_workbench.uploads import parse_upload
    db = catalog(tmp_path)
    record = parse_upload("R1 (a b) resistor r=1k", "Resistor network", "a b")
    circuit = db.add_upload(record, "R1 (a b) resistor r=1k", {"description": "Resistor network"})
    assert db.detail(circuit)["dataset"] == "Uploaded"
    with pytest.raises(ValueError, match="already"):
        db.add_upload(record, "R1 (a b) resistor r=1k", {"description": "Duplicate"})
    assert db.detail(circuit)["sync_state"] == "pending"


def test_upload_rejects_repeated_source_instance_names():
    from circuit_workbench.uploads import parse_upload
    for netlist in ("R1 a b 1k\nR1 b c 2k", "M1 (a b c c) nmos4\nm1 (b a c c) nmos4", "R1(a b) resistor\nR1(b c) resistor"):
        with pytest.raises(ValueError, match="Duplicate"):
            parse_upload(netlist, "Repeated names must not be repaired silently")


def test_spice_nets_are_case_insensitive_and_waveforms_rejected():
    from circuit_workbench.uploads import parse_upload
    record = parse_upload("R1 OUT 0 1k\nC1 out 0 1p", "Same electrical node", "out 0")
    assert record.statistics.net_count == 2
    assert record.ports[0].name == "OUT"
    assert record.devices[0].connections[0].net_id == record.devices[1].connections[0].net_id
    for netlist in ("V1 in 0 PULSE(0,1,0,1n,1n,5n,10n)", "V1 in 0 SIN(0,1,1k)", "R1 a b 1k\nC1 (b c) capacitor"):
        with pytest.raises(ValueError):
            parse_upload(netlist, "Unsupported syntax")


def test_read_only_cypher_rejects_procedures_and_multiple_statements():
    from circuit_workbench.neo4j import validate_cypher
    validate_cypher("MATCH (c:Circuit) RETURN c.id LIMIT 10;")
    validate_cypher("MATCH (c:Circuit) WHERE c.id = $id RETURN c")
    for query in ["MATCH (n) DETACH DELETE n", "CALL dbms.shutdown()", "RETURN 1; CREATE (:Bad)", "LOAD CSV FROM 'file:///x' AS x RETURN x", "CREATE INDEX x FOR (c:Circuit) ON (c.id)"]:
        with pytest.raises(ValueError):
            validate_cypher(query)


def test_result_serializer_preserves_vectors_and_marks_large_lists():
    from circuit_workbench.neo4j import Serializer
    serializer = Serializer()
    assert serializer.convert(list(range(768))) == list(range(768))
    capped = serializer.convert(list(range(1001)))
    assert capped["truncated"] and capped["total"] == 1001 and len(capped["items"]) == 1000


def test_api_edit_upload_and_asset_boundary(tmp_path):
    from fastapi.testclient import TestClient
    from circuit_workbench.app import create_app
    from circuit_workbench.settings import Settings
    db = catalog(tmp_path)
    settings = Settings(ROOT, db.state, db.corpus, db.upstream)
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        response = client.get("/api/circuits", params={"search": "1004"})
        assert response.json()["total"] == 1
        graph = client.get("/api/circuits/analoggenie:1004/graph", params={"backend": "networkx"}).json()
        assert len(graph["nodes"]) == 40
        assert len(graph["edges"]) == 68
        import networkx as nx
        exported = client.get("/api/circuits/analoggenie:1004/networkx").json()
        restored = nx.node_link_graph(exported, edges="edges")
        assert restored.is_multigraph() and restored.is_directed()
        assert restored.number_of_nodes() == 40 and restored.number_of_edges() == 68
        save = client.patch("/api/circuits/analoggenie:1004", json={"revision": 0, "metadata": {"description": "API test", "title": "Reviewed amplifier"}})
        assert save.status_code == 200
        assert save.json()["metadata"]["title"] == "Reviewed amplifier"
        stale = client.patch("/api/circuits/analoggenie:1004", json={"revision": 0, "metadata": {"description": "stale"}})
        assert stale.status_code == 409
        assert client.get("/api/circuits/analoggenie:1004/asset/../../README.md").status_code != 200
        assert client.post("/api/uploads/preview", json={"netlist": "junk", "description": "invalid"}).status_code == 422
        import base64
        from io import BytesIO
        from PIL import Image
        image = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image, format="PNG")
        upload = client.post("/api/uploads", json={"netlist": "R1 (a b) resistor r=2k", "description": "Test resistor", "ports": "a b", "metadata": {"title": "New test circuit"}})
        assert upload.status_code == 201
        assert client.get("/api/circuits/" + upload.json()["id"]).json()["statistics"]["device_count"] == 1
        illustrated = client.post("/api/uploads", json={"netlist": "R1 (a b) resistor r=3k", "description": "Image fixture", "image_base64": base64.b64encode(image.getvalue()).decode()})
        assert illustrated.status_code == 201
        served = client.get("/api/circuits/" + illustrated.json()["id"] + "/asset/book")
        assert served.headers["content-type"] == "image/png" and served.content == image.getvalue()
        assert client.post("/api/uploads", json={"netlist": "R1 (a b) resistor r=4k", "description": "Invalid image", "image_base64": "bad image"}).status_code == 422


def test_metadata_invalidation_drops_old_vectors(tmp_path):
    db = catalog(tmp_path)
    with db.connect() as conn:
        conn.execute("INSERT INTO vectors(id,text_hash,semantic,topology) VALUES(?,?,?,?)", ("analoggenie:1004", "old", b"old vector", b"old topology"))
    db.edit("analoggenie:1004", {"description": "new description"}, revision=0)
    with db.connect() as conn:
        assert conn.execute("SELECT 1 FROM vectors WHERE id='analoggenie:1004'").fetchone() is None


def test_graph_descriptor_upgrade_reuses_text_vectors(tmp_path):
    import hashlib
    import numpy as np
    from circuit_workbench.retrieval import Retrieval, MODEL, VERSION, TEXT_VERSION
    db = catalog(tmp_path)
    with db.connect() as conn:
        conn.execute("UPDATE circuits SET sync_state='synced'")
    semantic = np.ones(384, dtype=np.float32).tobytes()
    for identifier in ("analoggenie:1004", "analoggenie:1009", "analoggenie:2030"):
        fingerprint = hashlib.sha256((TEXT_VERSION + db.search_text(identifier)).encode()).hexdigest()
        with db.connect() as conn:
            conn.execute("INSERT INTO vectors(id,text_hash,semantic,topology,model) VALUES(?,?,?,?,?)", (identifier, fingerprint, semantic, b"old", MODEL))
    retrieval = Retrieval(db)
    retrieval.build()
    assert retrieval.model is None  # No model download or text recomputation.
    assert retrieval.status["indexed"] == 3
    with db.connect() as conn:
        rows = conn.execute("SELECT semantic,descriptor_version,length(topology) AS n FROM vectors").fetchall()
    assert all(r["semantic"] == semantic and r["descriptor_version"] == VERSION and r["n"] == 768 * 4 for r in rows)
    with db.connect() as conn:
        assert {r[0] for r in conn.execute("SELECT sync_state FROM circuits")} == {"pending"}


def test_edit_during_vector_build_cannot_resurrect_stale_vectors(tmp_path, monkeypatch):
    import numpy as np
    import circuit_workbench.retrieval as module
    db = catalog(tmp_path)
    retrieval = module.Retrieval(db)
    class Model:
        def passage_embed(self, texts, **kwargs):
            return iter([np.ones(384, dtype=np.float32) for _ in texts])
    retrieval.model = Model()
    original = module.topology_vector
    def edit_during_build(record):
        db.edit(record.circuit_id, {"description": "Newer description"}, revision=0)
        return original(record)
    monkeypatch.setattr(module, "topology_vector", edit_during_build)
    retrieval.update("analoggenie:1004")
    with db.connect() as conn:
        assert conn.execute("SELECT 1 FROM vectors WHERE id='analoggenie:1004'").fetchone() is None
    monkeypatch.setattr(module, "topology_vector", original)
    with db.connect() as conn:
        conn.execute("UPDATE circuits SET sync_state='synced' WHERE id='analoggenie:1004'")
    retrieval.update("analoggenie:1004")
    with db.connect() as conn:
        assert conn.execute("SELECT revision FROM vectors WHERE id='analoggenie:1004'").fetchone()[0] == 1
    assert db.row("analoggenie:1004")["sync_state"] == "pending"
