"""Import validated canonical circuit JSON into Neo4j."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from neo4j import GraphDatabase

from .models import CircuitRecord
from .neo4j_audit import audit_database
from .neo4j_store import create_constraints, replace_circuit


def _connection_settings() -> tuple[str, str, str, str]:
    names = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise ValueError("missing Neo4j environment variables: " + ", ".join(missing))
    return tuple(os.environ[name] for name in names)  # type: ignore[return-value]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="circuit-neo4j")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="import canonical circuits/*.json")
    importer.add_argument("--input-dir", type=Path, required=True)
    auditor = commands.add_parser("audit", help="compare Neo4j with parser audit report")
    auditor.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "import":
        circuit_dir = args.input_dir / "circuits"
        paths = sorted(circuit_dir.glob("*.json")) if circuit_dir.is_dir() else []
        if not paths:
            print(f"no circuit JSON files found in {circuit_dir}", file=sys.stderr)
            return 2
    try:
        uri, user, password, database = _connection_settings()
        driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=3)
        try:
            driver.verify_connectivity()
            if args.command == "audit":
                problems = audit_database(driver, database, args.report)
                for problem in problems:
                    print(problem, file=sys.stderr)
                print(f"Neo4j audit: mismatches={len(problems)}")
                return 1 if problems else 0
            else:
                create_constraints(driver, database)
                imported = 0
                failed = 0
                for path in paths:
                    try:
                        record = CircuitRecord.model_validate_json(path.read_text(encoding="utf-8"))
                        replace_circuit(driver, database, record)
                        imported += 1
                    except Exception as exc:
                        failed += 1
                        print(f"{path.name}: {exc}", file=sys.stderr)
        finally:
            driver.close()
    except Exception as exc:
        print(f"Neo4j connection or setup failed: {exc}", file=sys.stderr)
        return 2
    print(f"Neo4j import: imported={imported} failed={failed}")
    return 1 if failed else 0


def main() -> None:
    raise SystemExit(run())
