"""Trusted local pickle cache for one canonical graph per circuit."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import pickle
import sys
import tempfile
from typing import Iterator

import networkx as nx

from .canonical_graph import project_circuit
from .models import CircuitRecord
from .networkx_graph import build_networkx_graph


def _graph_path(circuit_id: str) -> str:
    return f"graphs/{sha256(circuit_id.encode('utf-8')).hexdigest()}.pkl"


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def build_corpus(input_dir: Path, output_dir: Path) -> dict[str, str]:
    """Validate canonical JSON before writing a fresh keyed graph cache."""
    circuit_dir = Path(input_dir) / "circuits"
    paths = sorted(circuit_dir.glob("*.json")) if circuit_dir.is_dir() else []
    if not paths:
        raise ValueError(f"no circuit JSON files found in {circuit_dir}")
    output_dir = Path(output_dir)
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError(f"output directory is not empty: {output_dir}")
    records: dict[str, CircuitRecord] = {}
    for path in paths:
        try:
            record = CircuitRecord.model_validate_json(path.read_text(encoding="utf-8"))
            project_circuit(record)
        except Exception as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if record.circuit_id in records:
            raise ValueError(f"duplicate circuit_id {record.circuit_id} in {path.name}")
        records[record.circuit_id] = record
    manifest: dict[str, dict[str, str]] = {}
    for circuit_id in sorted(records):
        graph = build_networkx_graph(records[circuit_id])
        relative = _graph_path(circuit_id)
        _atomic_bytes(output_dir / relative, pickle.dumps(graph, protocol=pickle.HIGHEST_PROTOCOL))
        manifest[circuit_id] = {
            "path": relative,
            "record_sha256": sha256(graph.graph["record_json"].encode("utf-8")).hexdigest(),
        }
    _atomic_bytes(output_dir / "manifest.json", (json.dumps(manifest, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
    return {circuit_id: entry["path"] for circuit_id, entry in manifest.items()}


def _manifest(output_dir: Path) -> dict[str, dict[str, str]]:
    path = output_dir / "manifest.json"
    if path.is_symlink():
        raise ValueError("manifest symlink is not allowed")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid manifest")
    return data


def _load_entry(output_dir: Path, circuit_id: str,
                entry: dict[str, str]) -> nx.MultiDiGraph:
    relative = entry.get("path")
    if relative != _graph_path(circuit_id):
        raise ValueError(f"invalid manifest path for {circuit_id}")
    path = output_dir / relative
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"pickle symlink is not allowed for {circuit_id}")
    with path.open("rb") as stream:
        graph = pickle.load(stream)
    if not isinstance(graph, nx.MultiDiGraph) or graph.graph.get("circuit_id") != circuit_id:
        raise ValueError(f"invalid graph for {circuit_id}")
    if sha256(graph.graph["record_json"].encode("utf-8")).hexdigest() != entry.get("record_sha256"):
        raise ValueError(f"record hash mismatch for {circuit_id}")
    return graph


def load_graph(output_dir: Path, circuit_id: str) -> nx.MultiDiGraph:
    """Load one graph from a trusted locally generated cache by canonical ID."""
    output_dir = Path(output_dir)
    manifest = _manifest(output_dir)
    if circuit_id not in manifest:
        raise KeyError(circuit_id)
    return _load_entry(output_dir, circuit_id, manifest[circuit_id])


def iter_graphs(output_dir: Path) -> Iterator[tuple[str, nx.MultiDiGraph]]:
    """Stream graphs in circuit-ID order without keeping the corpus in memory."""
    output_dir = Path(output_dir)
    manifest = _manifest(output_dir)
    for circuit_id in sorted(manifest):
        yield circuit_id, _load_entry(output_dir, circuit_id, manifest[circuit_id])


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="circuit-networkx")
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="cache canonical circuits as graphs")
    builder.add_argument("--input-dir", required=True, type=Path)
    builder.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        paths = build_corpus(args.input_dir, args.output_dir)
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"NetworkX build: graphs={len(paths)}")
    return 0


def main() -> None:
    raise SystemExit(run())
