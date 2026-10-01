"""Batch ingestion and reproducible corpus audit commands."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

from gnn_pruning.io import atomic_write_json
from .loader import discover
from .models import CircuitRecord, PARSER_VERSION, ParseMode, SCHEMA_VERSION
from .parser import AnalogGenieParser


def _json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _atomic_text(path: Path, value: str) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def run(argv: list[str] | None = None) -> int:
    command = argparse.ArgumentParser(prog="circuit-ingest")
    subcommands = command.add_subparsers(dest="command", required=True)
    for name in ("parse-analoggenie", "audit-analoggenie"):
        sub = subcommands.add_parser(name)
        sub.add_argument("--dataset-root", type=Path, required=True)
        sub.add_argument("--mode", choices=[mode.value for mode in ParseMode], default="strict")
        sub.add_argument("--source-commit")
        if name == "parse-analoggenie":
            sub.add_argument("--output-dir", type=Path, required=True)
        else:
            sub.add_argument("--report-path", type=Path)
    try:
        args = command.parse_args(argv)
        bundles = discover(args.dataset_root)
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    statuses: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    canonical_types: Counter[str] = Counter()
    raw_types: Counter[str] = Counter()
    unknown_arities: dict[str, set[int]] = {}
    totals: Counter[str] = Counter()
    unreferenced_ports: list[str] = []
    manifest = []
    issue_lines = []
    parser = AnalogGenieParser()
    output_dir = getattr(args, "output_dir", None)
    previous_ids: set[str] = set()
    if output_dir is not None and (output_dir / "manifest.jsonl").is_file():
        for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            circuit_id = entry.get("source_circuit_id")
            if isinstance(circuit_id, str) and circuit_id.isdecimal():
                previous_ids.add(circuit_id)
    for source in bundles:
        result = parser.parse(source, mode=ParseMode(args.mode))
        statuses[result.status] += 1
        for entry in result.issues:
            issues[entry.code] += 1
            issue_lines.append(_json_line({"source_circuit_id": source.circuit_id, **entry.model_dump(mode="json")}))
            if entry.code == "PORT_NOT_REFERENCED":
                unreferenced_ports.append(f"{source.circuit_id}:{entry.context['port']}")
            if entry.code == "UNKNOWN_DEVICE_TYPE":
                unknown_arities.setdefault(str(entry.context["device_type"]), set()).add(int(entry.context["arity"]))
        circuit = result.circuit
        path = None
        if circuit:
            stats = circuit.statistics
            totals.update({"devices": stats.device_count, "nets": stats.net_count,
                           "ports": stats.external_port_count, "connections": stats.connection_count,
                           "duplicate_source_instances": stats.duplicate_source_instance_count})
            if stats.duplicate_source_instance_count:
                totals["circuits_with_duplicate_source_instances"] += 1
            canonical_types.update(stats.device_type_counts)
            raw_types.update(device.raw_type for device in circuit.devices)
            if output_dir is not None and result.status in ("valid", "valid_with_warnings"):
                path = f"circuits/{source.circuit_id}.json"
                atomic_write_json(output_dir / path, circuit.model_dump(mode="json"))
        if output_dir is not None and path is None:
            (output_dir / "circuits" / f"{source.circuit_id}.json").unlink(missing_ok=True)
        manifest.append({"source_circuit_id": source.circuit_id, "status": result.status,
                         "output_path": path, "primary_sha256": circuit.source.primary_sha256 if circuit else None,
                         "device_count": circuit.statistics.device_count if circuit else 0,
                         "net_count": circuit.statistics.net_count if circuit else 0,
                         "warning_count": sum(issue.severity == "warning" for issue in result.issues),
                         "error_count": sum(issue.severity in ("error", "fatal") for issue in result.issues)})
    manifest_text = "".join(_json_line(item) for item in manifest)
    if output_dir is not None:
        for circuit_id in previous_ids - {source.circuit_id for source in bundles}:
            (output_dir / "circuits" / f"{circuit_id}.json").unlink(missing_ok=True)
    report = {"parser_version": PARSER_VERSION, "schema_version": SCHEMA_VERSION,
              "source_repository_commit": args.source_commit,
              "discovered_circuits": len(bundles),
              "status_counts": dict(sorted(statuses.items())), "totals": dict(sorted(totals.items())),
              "canonical_device_type_counts": dict(sorted(canonical_types.items())),
              "raw_device_type_counts": dict(sorted(raw_types.items())),
              "issue_counts": dict(sorted(issues.items())),
              "unknown_types_and_arities": {key: sorted(value) for key, value in sorted(unknown_arities.items())},
              "unreferenced_ports": unreferenced_ports,
              "manifest_sha256": sha256(manifest_text.encode("utf-8")).hexdigest()}
    if output_dir is not None:
        _atomic_text(output_dir / "manifest.jsonl", manifest_text)
        _atomic_text(output_dir / "issues.jsonl", "".join(issue_lines))
        atomic_write_json(output_dir / "audit-report.json", report)
        atomic_write_json(output_dir / "canonical-circuit.schema.json", CircuitRecord.model_json_schema())
    elif args.report_path:
        atomic_write_json(args.report_path, report)
    print(f"AnalogGenie: {len(bundles)} discovered; " + ", ".join(f"{key}={value}" for key, value in sorted(statuses.items())) +
          f"; devices={totals['devices']}; connections={totals['connections']}")
    return 1 if statuses["quarantined"] or statuses["failed"] else 0


def main() -> None:
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"internal error: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
