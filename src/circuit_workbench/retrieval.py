"""Local pretrained semantic vectors and deterministic circuit descriptors."""
import hashlib
import json
import threading

import numpy as np
from circuit_ingest.models import CircuitRecord
from .topology import VERSION, port_role, topology_vector, topology_profile, structural_similarity

MODEL = "BAAI/bge-small-en-v1.5"
TEXT_VERSION = "terminal-wl-v1"  # Existing text index format; graph updates do not re-embed text.


def unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def cosine(a, b):
    return float(np.clip(unit(a) @ unit(b), -1, 1))


class Retrieval:
    def __init__(self, catalog):
        self.catalog = catalog
        self.model = None
        self.lock = threading.RLock()
        self.status = {"state": "starting", "model": MODEL, "indexed": 0, "total": 0, "error": ""}

    def _model(self):
        if self.model is None:
            from fastembed import TextEmbedding
            self.model = TextEmbedding(MODEL, cache_dir=str(self.catalog.state / "model"), threads=2)
        return self.model

    def _write_topology(self, identifier, revision, fingerprint, topology, semantic=None):
        with self.catalog.connect() as db:
            result = db.execute("""INSERT INTO vectors(id,text_hash,topology,model,descriptor_version,semantic,revision)
                SELECT ?,?,?,?,?,?,? FROM circuits WHERE id=? AND revision=?
                ON CONFLICT(id) DO UPDATE SET text_hash=excluded.text_hash,topology=excluded.topology,
                    model=excluded.model,descriptor_version=excluded.descriptor_version,
                    semantic=excluded.semantic,revision=excluded.revision,error=''""",
                (identifier, fingerprint, topology.tobytes(), MODEL, VERSION, semantic, revision, identifier, revision))
            if result.rowcount:
                db.execute("UPDATE circuits SET sync_state='pending' WHERE id=? AND revision=?", (identifier, revision))
            return bool(result.rowcount)

    def _write_semantic(self, db, identifier, revision, vector):
        return db.execute("""UPDATE vectors SET semantic=?,error='' WHERE id=? AND revision=?
            AND EXISTS(SELECT 1 FROM circuits c WHERE c.id=vectors.id AND c.revision=vectors.revision)""",
            (unit(vector).tobytes(), identifier, revision)).rowcount

    def build(self):
        with self.lock:
            with self.catalog.connect() as db:
                rows = db.execute("SELECT * FROM circuits ORDER BY id").fetchall()
                saved = {r["id"]: r for r in db.execute("SELECT id,text_hash,semantic,model,descriptor_version,revision FROM vectors")}
            self.status.update(state="topology", total=len(rows), error="")
            pending = []
            for row in rows:
                identifier = row["id"]
                text = self.catalog.search_text_row(row)
                hash_value = hashlib.sha256((TEXT_VERSION + text).encode()).hexdigest()
                stored = saved.get(identifier)
                text_current = stored and stored["revision"] == row["revision"] and stored["text_hash"] == hash_value and stored["semantic"] and stored["model"] == MODEL
                if text_current and stored["descriptor_version"] == VERSION:
                    continue
                topo = topology_vector(CircuitRecord.model_validate_json(row["record"]))
                if not self._write_topology(identifier, row["revision"], hash_value, topo, stored["semantic"] if text_current else None):
                    continue  # A newer edit owns this entry; its queued update will index it.
                if text_current:
                    continue
                pending.append((identifier, text, row["revision"]))
            self.status.update(state="embedding", indexed=len(rows)-len(pending))
            if pending:
                model = self._model()
                for start in range(0, len(pending), 64):
                    batch = pending[start:start + 64]
                    vectors = list(model.passage_embed([text for _, text, _ in batch], batch_size=32))
                    with self.catalog.connect() as db:
                        for (identifier, _, revision), vector in zip(batch, vectors, strict=True):
                            self._write_semantic(db, identifier, revision, vector)
                    self.status["indexed"] += len(batch)
                    print(f"Search index: {self.status['indexed']}/{len(rows)}", flush=True)
            with self.catalog.connect() as db:
                indexed = db.execute("SELECT count(*) FROM vectors v JOIN circuits c ON c.id=v.id AND c.revision=v.revision WHERE v.semantic IS NOT NULL").fetchone()[0]
            self.status.update(state="ready", indexed=indexed)

    def build_safe(self):
        try:
            self.build()
        except Exception as exc:
            self.status.update(state="error", error=str(exc))
            print(f"Semantic index unavailable: {exc}", flush=True)

    def update(self, identifier):
        with self.lock:
            row = self.catalog.row(identifier)
            revision = row["revision"]
            text = self.catalog.search_text_row(row)
            fingerprint = hashlib.sha256((TEXT_VERSION + text).encode()).hexdigest()
            topo = topology_vector(CircuitRecord.model_validate_json(row["record"]))
            if not self._write_topology(identifier, revision, fingerprint, topo):
                return
            try:
                vector = unit(next(self._model().passage_embed([text])))
                with self.catalog.connect() as db:
                    self._write_semantic(db, identifier, revision, vector)
            except Exception as exc:
                with self.catalog.connect() as db:
                    db.execute("UPDATE vectors SET error=? WHERE id=? AND revision=?", (str(exc), identifier, revision))
                raise ValueError("Saved locally; text embedding could not be rebuilt. Retry indexing.") from exc

    def search(self, text="", reference_id="", limit=20, dataset="", device="", family=""):
        if not text.strip() and not reference_id:
            raise ValueError("Enter a search description or choose a reference circuit.")
        semantic_query = None
        if text.strip():
            if self.status["state"] != "ready":
                raise ValueError("Text search is warming up. Use reference-only topology search or wait for indexing.")
            with self.lock:
                semantic_query = unit(next(self._model().query_embed([text])))
        reference = self.catalog.record(reference_id) if reference_id else None
        reference_profile = topology_profile(reference) if reference else None
        topology_query = topology_vector(reference, profile=reference_profile) if reference else None
        with self.catalog.connect() as db:
            rows = db.execute("SELECT c.*,v.semantic,v.topology,v.error FROM circuits c JOIN vectors v ON c.id=v.id AND c.revision=v.revision WHERE v.descriptor_version=?", (VERSION,)).fetchall()
        candidates = []
        for row in rows:
            if row["id"] == reference_id:
                continue
            rec, meta = json.loads(row["record"]), json.loads(row["metadata"])
            if dataset and rec["dataset"] != dataset:
                continue
            if device and not rec["statistics"]["device_type_counts"].get(device):
                continue
            if family and meta.get("family") != family:
                continue
            if semantic_query is not None and not row["semantic"]:
                continue
            candidates.append({"row": dict(row), "semantic_score": cosine(semantic_query, np.frombuffer(row["semantic"], dtype=np.float32)) if semantic_query is not None else None,
                               "topology_score": cosine(topology_query, np.frombuffer(row["topology"], dtype=np.float32)) if topology_query is not None and row["topology"] else None,
                               "structural_score": None, "score": 0.0})
        topology_ranked = sorted((c for c in candidates if c["topology_score"] is not None),
                                 key=lambda c: (-c["topology_score"], c["row"]["id"]))
        shortlist = topology_ranked[:100]
        if reference:
            for candidate in shortlist:
                candidate["structural_score"] = structural_similarity(reference_profile,
                    topology_profile(CircuitRecord.model_validate_json(candidate["row"]["record"])))
            # Rescore full pattern labels; do not let vector hash collisions decide ties.
            shortlist.sort(key=lambda c: (-c["structural_score"], -c["topology_score"], c["row"]["id"]))
            topology_ranked = shortlist + topology_ranked[100:]
        for key in ("semantic_score", "topology_score"):
            ranked = topology_ranked if key == "topology_score" else sorted(
                (c for c in candidates if c[key] is not None), key=lambda c: (-c[key], c["row"]["id"]))
            for rank, candidate in enumerate(ranked, 1):
                candidate["score"] += 1 / (60 + rank)
        candidates.sort(key=lambda c: (-c["score"], c["row"]["id"]))
        results = []
        for candidate in candidates[:limit]:
            summary = self.catalog.summary(candidate.pop("row"))
            evidence = []
            if reference:
                for kind in ("nmos", "pmos", "capacitor", "resistor"):
                    before = reference.statistics.device_type_counts.get(kind, 0)
                    after = summary["statistics"]["device_type_counts"].get(kind, 0)
                    if before or after:
                        evidence.append(f"{kind}: {after} vs reference {before}")
                evidence.append(f"ports: {summary['statistics']['external_port_count']} vs reference {reference.statistics.external_port_count}")
            else:
                evidence.append("Ranked using existing source references, user description and structural facts.")
            results.append({**summary, **candidate, "evidence": evidence})
        mode = "hybrid" if text and reference_id else "semantic" if text else "topology"
        return {"mode": mode, "items": results, "total": len(candidates), "model": MODEL,
                "descriptor_version": VERSION, "reranked": len(shortlist),
                "warning": "Similarity ranks candidates. Stage count, circuit family and performance are not certified.",
                "request": {"text": text, "reference_id": reference_id, "limit": limit, "dataset": dataset, "device": device, "family": family}}
