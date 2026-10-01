"""Lossless parser for AnalogGenie primary topology files."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import quote

from .models import (
    CircuitRecord, Connection, DetectionResult, DeviceRecord, NetRecord, ParseIssue,
    ParseMode, ParseResult, ParserRecord, PortRecord, SourceBundle, SourceRecord, Statistics,
)
from .registry import DEVICE_SPECS
from .validation import validate_circuit

_LINE = re.compile(r"\s*([^\s()]+)\s+\(\s*([^()]*)\s*\)\s+([^\s()]+)\s*")
MAX_FILE_BYTES = 4_000_000
MAX_LINE_LENGTH = 20_000


def parse_device_line(line: str) -> tuple[str, tuple[str, ...], str] | None:
    """Return instance, ordered nets and trailing type; None for comments/blanks."""
    if not line.strip() or line.lstrip().startswith(("//", "*")):
        return None
    if len(line) > MAX_LINE_LENGTH:
        raise ValueError("line exceeds size limit")
    match = _LINE.fullmatch(line)
    if match is None:
        raise ValueError("malformed device line")
    nets = tuple(match.group(2).split())
    if not nets:
        raise ValueError("empty terminal list")
    return match.group(1), nets, match.group(3)


def _net_id(circuit_id: str, name: str) -> str:
    return f"analoggenie:{circuit_id}:net:{quote(name, safe='')}"


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root.parent).as_posix()


class AnalogGenieParser:
    dialect = "analoggenie"

    def can_parse(self, source: SourceBundle) -> DetectionResult:
        expected = source.root_directory / source.circuit_id
        supported = (source.circuit_id.isdecimal() and
                     source.primary_netlist_path == expected / f"{source.circuit_id}.cir" and
                     source.port_path == expected / f"Port{source.circuit_id}.txt")
        return DetectionResult(supported=supported, reason="official primary bundle" if supported else "bundle does not match AnalogGenie layout")

    def parse(self, source: SourceBundle, *, mode: ParseMode = ParseMode.STRICT) -> ParseResult:
        mode = ParseMode(mode)
        issues: list[ParseIssue] = []
        primary_name = _relative(source.root_directory, source.primary_netlist_path)
        port_name = _relative(source.root_directory, source.port_path)

        def issue(severity: str, code: str, message: str, path: str = primary_name,
                  line: int | None = None, **context: str | int) -> None:
            issues.append(ParseIssue(severity=severity, code=code, message=message,
                                     source_file=path, source_line=line, context=context))

        if not self.can_parse(source).supported:
            issue("fatal", "INVALID_SOURCE_BUNDLE", "Source bundle does not match official layout.")
            return ParseResult(status="failed", circuit=None, issues=issues)
        for path in (source.primary_netlist_path, source.port_path, *source.auxiliary_paths):
            if path.is_symlink() or not path.resolve().is_relative_to(source.root_directory.resolve()):
                issue("fatal", "UNSAFE_PATH", f"Unsafe path: {path.name}")
                return ParseResult(status="failed", circuit=None, issues=issues)
        if not source.primary_netlist_path.is_file():
            issue("fatal", "MISSING_PRIMARY_NETLIST", "Primary netlist is missing.")
            return ParseResult(status="failed", circuit=None, issues=issues)
        if not source.port_path.is_file():
            issue("error", "MISSING_PORT_FILE", "Port file is missing.", port_name)
            return ParseResult(status="quarantined", circuit=None, issues=issues)
        try:
            if (source.primary_netlist_path.stat().st_size > MAX_FILE_BYTES or
                    source.port_path.stat().st_size > MAX_FILE_BYTES):
                issue("fatal", "SOURCE_TOO_LARGE", "Source file exceeds size limit.")
                return ParseResult(status="failed", circuit=None, issues=issues)
            primary_bytes = source.primary_netlist_path.read_bytes()
            port_bytes = source.port_path.read_bytes()
            if len(primary_bytes) > MAX_FILE_BYTES or len(port_bytes) > MAX_FILE_BYTES:
                issue("fatal", "SOURCE_TOO_LARGE", "Source file exceeds size limit.")
                return ParseResult(status="failed", circuit=None, issues=issues)
            text = primary_bytes.decode("utf-8")
            port_text = port_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            issue("fatal", "INVALID_ENCODING", str(exc))
            return ParseResult(status="failed", circuit=None, issues=issues)
        except OSError as exc:
            issue("fatal", "SOURCE_READ_ERROR", str(exc))
            return ParseResult(status="failed", circuit=None, issues=issues)

        for path in source.auxiliary_paths:
            if not (path.name.startswith(("Opamp", "Book", "Cadence", "Pagenumber")) or path.name == f"{source.circuit_id}_full.cir"):
                issue("info", "UNEXPECTED_FILE", f"Unexpected auxiliary file {path.name}.", _relative(source.root_directory, path))
        raw_ports = port_text.split()
        port_first: dict[str, int] = {}
        for ordinal, name in enumerate(raw_ports):
            if name in port_first:
                issue("error", "DUPLICATE_PORT", f"Duplicate port {name}.", port_name, 1, port=name)
            else:
                port_first[name] = ordinal
        if not raw_ports:
            issue("warning", "NO_PORTS", "No ports declared.", port_name)

        circuit_id = source.circuit_id
        nets: dict[str, NetRecord] = {}
        devices: list[DeviceRecord] = []
        seen_instances: set[str] = set()
        duplicate_count = 0
        unknown_count = 0
        for line_number, raw_line in enumerate(text.splitlines(), 1):
            try:
                parsed = parse_device_line(raw_line)
            except ValueError as exc:
                issue("error", "MALFORMED_DEVICE_LINE", str(exc), primary_name, line_number)
                continue
            if parsed is None:
                continue
            instance, raw_nets, raw_type = parsed
            spec = DEVICE_SPECS.get(raw_type)
            if spec is not None and len(raw_nets) != len(spec.terminals):
                issue("error", "WRONG_DEVICE_ARITY", f"{raw_type} expects {len(spec.terminals)} terminals, got {len(raw_nets)}.", primary_name, line_number, device_type=raw_type)
                continue
            if spec is None:
                unknown_count += 1
                issue("error" if mode is ParseMode.STRICT else "warning", "UNKNOWN_DEVICE_TYPE", f"Unknown type {raw_type}; kept as opaque.", primary_name, line_number, device_type=raw_type, arity=len(raw_nets))
                roles = tuple(f"pin_{n}" for n in range(len(raw_nets)))
            else:
                roles = spec.terminals
            if instance in seen_instances:
                duplicate_count += 1
                issue("info", "DUPLICATE_SOURCE_INSTANCE", f"Repeated source instance {instance}.", primary_name, line_number, instance=instance)
            seen_instances.add(instance)
            connections = []
            for ordinal, (role, name) in enumerate(zip(roles, raw_nets, strict=True)):
                if name not in nets:
                    nets[name] = NetRecord(id=_net_id(circuit_id, name), name=name,
                                           is_external=False, port_ordinal=None, degree_by_terminal=0)
                nets[name].degree_by_terminal += 1
                connections.append(Connection(terminal=role, terminal_ordinal=ordinal, net_id=nets[name].id))
            device_ordinal = len(devices) + 1
            devices.append(DeviceRecord(id=f"analoggenie:{circuit_id}:device:{device_ordinal:06d}",
                                        ordinal=device_ordinal, source_instance=instance, source_line=line_number,
                                        raw_type=raw_type, canonical_type=spec.canonical_type if spec else "opaque",
                                        category=spec.category if spec else "opaque", connections=connections,
                                        raw_line=raw_line))
        if not devices:
            issue("error", "EMPTY_NETLIST", "No device records found.")
        ports = []
        unreferenced = 0
        for ordinal, name in enumerate(raw_ports):
            if name not in nets:
                nets[name] = NetRecord(id=_net_id(circuit_id, name), name=name,
                                       is_external=True, port_ordinal=ordinal, degree_by_terminal=0)
            net = nets[name]
            net.is_external = True
            if net.port_ordinal is None:
                net.port_ordinal = ordinal
            referenced = net.degree_by_terminal > 0
            if not referenced:
                unreferenced += 1
                issue("warning", "PORT_NOT_REFERENCED", f"Declared port {name} is not referenced by a device.", port_name, 1, port=name)
            ports.append(PortRecord(name=name, ordinal=ordinal, net_id=net.id,
                                    referenced_by_device=referenced))
        issues.sort(key=lambda item: (item.source_line or 0, item.code))
        type_counts = dict(sorted(Counter(device.canonical_type for device in devices).items()))
        circuit = CircuitRecord(parser=ParserRecord(mode=mode), circuit_id=f"analoggenie:{circuit_id}",
                                source_circuit_id=circuit_id, dataset=source.dataset_name,
                                source=SourceRecord(primary_netlist=primary_name, port_file=port_name,
                                                    primary_sha256=sha256(primary_bytes).hexdigest(),
                                                    port_sha256=sha256(port_bytes).hexdigest(),
                                                    auxiliary_files=[_relative(source.root_directory, path) for path in source.auxiliary_paths]),
                                ports=ports, nets=list(nets.values()), devices=devices,
                                statistics=Statistics(device_count=len(devices), net_count=len(nets),
                                                      external_port_count=len(ports),
                                                      connection_count=sum(len(d.connections) for d in devices),
                                                      device_type_counts=type_counts,
                                                      duplicate_source_instance_count=duplicate_count,
                                                      unreferenced_port_count=unreferenced,
                                                      unknown_device_type_count=unknown_count), issues=issues)
        for error in validate_circuit(circuit):
            issue("error", "INVALID_CIRCUIT_RECORD", error)
        if len(circuit.issues) != len(issues):
            issues.sort(key=lambda item: (item.source_line or 0, item.code))
            circuit.issues = issues
        severity = {item.severity for item in issues}
        status = "quarantined" if "error" in severity or "fatal" in severity else "valid_with_warnings" if "warning" in severity else "valid"
        return ParseResult(status=status, circuit=circuit, issues=issues)
