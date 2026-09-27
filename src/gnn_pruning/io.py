"""Deterministic JSON serialization helpers for checked-in artifacts."""

from __future__ import annotations

import hashlib
from importlib.resources.abc import Traversable
import json
import os
import tempfile
from pathlib import Path


def load_json(path: Path | Traversable) -> dict[str, object]:
    """Load a UTF-8 JSON object, rejecting arrays and scalar documents."""
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def canonical_sha256(value: object) -> str:
    """Return the SHA-256 of canonical, compact UTF-8 JSON."""
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_write_json(path: Path, value: object, *, sort_keys: bool = True) -> None:
    """Atomically replace *path* with deterministic JSON in its own directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=sort_keys,
        )
        + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
