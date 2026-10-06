"""Persistent catalog; authoritative topology and revisioned researcher edits."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from pydantic import BaseModel, ConfigDict, Field
from circuit_ingest.models import CircuitRecord


class RevisionConflict(ValueError):
    pass


class UserMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=6000)
    family: str = Field(default="", max_length=100)
    topology: str = Field(default="", max_length=150)
    stage_count: int | None = Field(default=None, ge=1, le=20)
    input_mode: str = Field(default="", max_length=40)
    output_mode: str = Field(default="", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=10000)


def now():
    return datetime.now(timezone.utc).isoformat()


class Catalog:
    def __init__(self, state: Path, corpus: Path, upstream: Path):
        self.state, self.corpus, self.upstream = Path(state), Path(corpus), Path(upstream)
        self.state.mkdir(parents=True, exist_ok=True)
        self.path = self.state / "catalog.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS circuits (
                    id TEXT PRIMARY KEY, record TEXT NOT NULL, netlist TEXT NOT NULL,
                    reference_text TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 0, modified TEXT NOT NULL,
                    sync_state TEXT NOT NULL DEFAULT 'pending', sync_error TEXT NOT NULL DEFAULT '',
                    image TEXT NOT NULL DEFAULT '', source_hash TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS source_hash_idx ON circuits(source_hash);
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY, text_hash TEXT, semantic BLOB, topology BLOB,
                    model TEXT, error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY, kind TEXT, query TEXT, parameters TEXT,
                    created TEXT, row_count INTEGER);
                CREATE TABLE IF NOT EXISTS metadata_history (
                    id INTEGER PRIMARY KEY, circuit_id TEXT, revision INTEGER,
                    metadata TEXT, created TEXT);
            """)
            if "descriptor_version" not in {r[1] for r in db.execute("PRAGMA table_info(vectors)")}:
                db.execute("ALTER TABLE vectors ADD COLUMN descriptor_version TEXT NOT NULL DEFAULT ''")
            if "revision" not in {r[1] for r in db.execute("PRAGMA table_info(vectors)")}:
                db.execute("ALTER TABLE vectors ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        self.bootstrap()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def bootstrap(self):
        with self.connect() as db:
            existing = {row[0] for row in db.execute("SELECT id FROM circuits")}
            for path in sorted((self.corpus / "circuits").glob("*.json")):
                data = json.loads(path.read_text())
                if data["circuit_id"] in existing:
                    continue
                record = CircuitRecord.model_validate(data)
                source = self.upstream / record.source.primary_netlist
                netlist = source.read_text() if source.is_file() else "\n".join(d.raw_line for d in record.devices)
                refs = []
                for name in record.source.auxiliary_files:
                    p = self.upstream / name
                    if p.name.startswith("Pagenumber") and p.suffix == ".txt" and p.is_file():
                        refs.append(p.read_text(errors="replace"))
                db.execute("INSERT INTO circuits(id,record,netlist,reference_text,modified,source_hash) VALUES(?,?,?,?,?,?)",
                           (record.circuit_id, record.model_dump_json(), netlist, "\n".join(refs), now(), record.source.primary_sha256))

    def row(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM circuits WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return dict(row)

    def record(self, identifier):
        return CircuitRecord.model_validate_json(self.row(identifier)["record"])

    def summary(self, row):
        record = json.loads(row["record"])
        metadata = UserMetadata.model_validate_json(row["metadata"]).model_dump()
        return {"id": row["id"], "source_id": record["source_circuit_id"], "dataset": record["dataset"],
                "title": metadata["title"] or f"Circuit {record['source_circuit_id']}",
                "description": metadata["description"], "family": metadata["family"],
                "topology": metadata["topology"], "tags": metadata["tags"],
                "statistics": record["statistics"], "revision": row["revision"],
                "has_schematic": bool(self.asset(row["id"], "book")),
                "sync_state": row["sync_state"]}

    def list(self, search="", dataset="", device="", family="", offset=0, limit=40):
        clauses, args = [], []
        if search:
            # Escape wildcard characters so a pasted circuit name behaves literally.
            term = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(id LIKE ? ESCAPE '\\' OR metadata LIKE ? ESCAPE '\\' OR reference_text LIKE ? ESCAPE '\\')")
            args.extend(["%" + term + "%"] * 3)
        if dataset:
            clauses.append("json_extract(record,'$.dataset')=?")
            args.append(dataset)
        if device:
            clauses.append("json_extract(record,?) > 0")
            args.append("$.statistics.device_type_counts." + device)
        if family:
            clauses.append("json_extract(metadata,'$.family')=?")
            args.append(family)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM circuits" + where, args).fetchone()[0]
            rows = db.execute("SELECT * FROM circuits" + where + " ORDER BY CASE WHEN id LIKE 'uploaded:%' THEN 0 ELSE 1 END, CAST(json_extract(record,'$.source_circuit_id') AS INTEGER), id LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        return {"total": total, "items": [self.summary(dict(row)) for row in rows], "offset": offset, "limit": limit}

    def detail(self, identifier):
        row = self.row(identifier)
        record = json.loads(row["record"])
        return {**self.summary(row), "metadata": UserMetadata.model_validate_json(row["metadata"]).model_dump(),
                "netlist": row["netlist"], "reference_text": row["reference_text"],
                "source": record["source"], "parser": record["parser"], "ports": record["ports"],
                "issues": record["issues"], "modified": row["modified"], "sync_error": row["sync_error"],
                "assets": [kind for kind in ("book", "cadence") if self.asset(identifier, kind)],
                "evidence_note": "User annotations are supplied by the researcher and are not electrically verified."}

    def edit(self, identifier, metadata, revision):
        validated = UserMetadata.model_validate(metadata).model_dump()
        for tag in validated["tags"]:
            if len(tag) > 80:
                raise ValueError("Tags must be at most 80 characters.")
        with self.connect() as db:
            result = db.execute("UPDATE circuits SET metadata=?, revision=revision+1, modified=?, sync_state='pending', sync_error='' WHERE id=? AND revision=?",
                                (json.dumps(validated), now(), identifier, revision))
            if result.rowcount != 1:
                if not db.execute("SELECT 1 FROM circuits WHERE id=?", (identifier,)).fetchone():
                    raise KeyError(identifier)
                raise RevisionConflict("This circuit changed since you opened it. Reload before saving.")
            db.execute("INSERT INTO metadata_history(circuit_id,revision,metadata,created) VALUES(?,?,?,?)", (identifier, revision + 1, json.dumps(validated), now()))
            db.execute("DELETE FROM vectors WHERE id=?", (identifier,))
        return self.detail(identifier)

    def add_upload(self, record, text, metadata, image=""):
        validated = UserMetadata.model_validate(metadata).model_dump()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM circuits WHERE source_hash=?", (record.source.primary_sha256,)).fetchone():
                raise ValueError("This netlist is already in the library.")
            db.execute("INSERT INTO circuits(id,record,netlist,metadata,modified,image,source_hash) VALUES(?,?,?,?,?,?,?)",
                       (record.circuit_id, record.model_dump_json(), text, json.dumps(validated), now(), image, record.source.primary_sha256))
        return record.circuit_id

    def asset(self, identifier, kind):
        # Only server-owned asset kinds are exposed; no arbitrary filesystem paths.
        if kind not in {"book", "cadence"}:
            return None
        row = self.row(identifier)
        if row["image"] and kind == "book":
            p = (self.state / "uploads" / row["image"]).resolve()
            return p if p.is_relative_to((self.state / "uploads").resolve()) and p.is_file() else None
        rec = json.loads(row["record"])
        prefix = "Book" if kind == "book" else "Cadence"
        for name in rec["source"]["auxiliary_files"]:
            p = (self.upstream / name).resolve()
            if p.name.startswith(prefix) and p.suffix.lower() in {".png", ".jpg", ".jpeg"} and p.is_relative_to(self.upstream.resolve()) and p.is_file():
                return p
        return None

    def search_text(self, identifier):
        return self.search_text_row(self.row(identifier))

    @staticmethod
    def search_text_row(row):
        record = json.loads(row["record"])
        meta = UserMetadata.model_validate_json(row["metadata"]).model_dump()
        stats = record["statistics"]
        fields = [meta[k] for k in ("title", "description", "family", "topology", "input_mode", "output_mode", "notes") if meta[k]]
        if meta["stage_count"]:
            fields.append(f"{meta['stage_count']} stages (user annotation)")
        fields.extend(meta["tags"])
        fields.append(row["reference_text"])
        fields.append("Devices: " + ", ".join(f"{n} {kind}" for kind, n in stats["device_type_counts"].items()))
        fields.append("Ports: " + ", ".join(p["name"] for p in record["ports"]))
        return ". ".join(fields)

    def history(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM history ORDER BY id DESC LIMIT 20")]

    def save_history(self, kind, query, parameters, count):
        with self.connect() as db:
            db.execute("INSERT INTO history(kind,query,parameters,created,row_count) VALUES(?,?,?,?,?)", (kind, query, json.dumps(parameters), now(), count))
