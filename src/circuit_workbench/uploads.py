"""Validate flat analog netlists and convert them to the canonical contract."""
from collections import Counter
import hashlib
import re
import uuid

from circuit_ingest.models import (CircuitRecord, Connection, DeviceRecord, NetRecord,
                                  ParserRecord, ParseMode, PortRecord, SourceRecord, Statistics)
from circuit_ingest.validation import validate_circuit
from gnn_pruning.conversion.netlist import parse_netlist
from gnn_pruning.conversion.device_types import DEVICE_TYPES


def dialect(text):
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith(("*", "//", "."))]
    parenthesized = [bool(re.match(r"\S+\s*\(", line)) for line in lines]
    if any(parenthesized) and not all(parenthesized):
        raise ValueError("Do not mix flat SPICE and parenthesized typed devices in one upload.")
    return "typed" if parenthesized and all(parenthesized) else "spice"


def normalize_spice(text):
    models = {}
    spelling = {}
    def nets(names):
        # SPICE names are case-insensitive; retain the first source spelling.
        return " ".join(spelling.setdefault(name.casefold(), name) for name in names)
    for line in text.splitlines():
        match = re.match(r"\s*\.model\s+(\S+)\s+(NMOS|PMOS|NPN|PNP|D)\b", line, re.I)
        if match:
            models[match[1].lower()] = {"nmos": "nmos4", "pmos": "pmos4", "npn": "npn", "pnp": "pnp", "d": "diode"}[match[2].lower()]
    result = []
    for index, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("*", "//")):
            result.append("")
            continue
        if re.match(r"\.(model|end|title)\b", line, re.I):
            result.append("")
            continue
        if line.startswith("."):
            raise ValueError(f"Line {index}: directive {line.split()[0]} is not supported; supply a flat topology netlist.")
        if "(" in line and ")" in line and re.match(r"\S+\s*\(", line):
            result.append(line)
            continue
        fields = line.split()
        prefix = fields[0][0].upper()
        if prefix in "RCL" and len(fields) == 4:
            kind = {"R": "resistor", "C": "capacitor", "L": "inductor"}[prefix]
            line = f"{fields[0]} ({nets(fields[1:3])}) {kind} {prefix.lower()}={fields[3]}"
        elif prefix == "M" and len(fields) >= 6:
            kind = models.get(fields[5].lower()) or {"nmos": "nmos4", "nmos4": "nmos4", "pmos": "pmos4", "pmos4": "pmos4"}.get(fields[5].lower())
            if not kind or kind not in {"nmos4", "pmos4"}:
                raise ValueError(f"Line {index}: model {fields[5]} needs an explicit .model NMOS or PMOS declaration.")
            line = f"{fields[0]} ({nets(fields[1:5])}) {kind} {' '.join(fields[6:])}"
        elif prefix == "Q" and len(fields) in {5, 6}:
            model_index = len(fields) - 1
            kind = models.get(fields[model_index].lower()) or {"npn": "npn", "pnp": "pnp"}.get(fields[model_index].lower())
            if kind not in {"npn", "pnp"}:
                raise ValueError(f"Line {index}: BJT model requires explicit NPN/PNP typing.")
            bjt_nets = fields[1:model_index] + (["0"] if len(fields) == 5 else [])
            line = f"{fields[0]} ({nets(bjt_nets)}) {kind}"
        elif prefix == "D" and len(fields) == 4:
            if models.get(fields[3].lower(), fields[3].lower()) not in {"diode", "d"}:
                raise ValueError(f"Line {index}: diode model needs an explicit .model D declaration.")
            line = f"{fields[0]} ({nets(fields[1:3])}) diode"
        elif prefix in "VI" and len(fields) in {4, 5}:
            value = fields[3] if len(fields) == 4 else fields[4] if fields[3].upper() == "DC" else None
            if value is None or not re.fullmatch(r"(?:[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[A-Za-z]*|[A-Za-z_]\w*)", value) or value.upper() in {"PULSE", "PWL", "SIN", "EXP", "SFFM", "AM", "AC"}:
                raise ValueError(f"Line {index}: only DC independent sources with a scalar value or parameter name are supported.")
            line = f"{fields[0]} ({nets(fields[1:3])}) {'vsource' if prefix == 'V' else 'isource'} dc={value}"
        else:
            raise ValueError(f"Line {index}: unsupported statement. Use flat R/C/L/M/Q/D/V/I SPICE or parenthesized typed devices.")
        result.append(line)
    return "\n".join(result)


def parse_upload(text: str, description: str, ports: str = "") -> CircuitRecord:
    if not description.strip():
        raise ValueError("A basic description is required.")
    if not text.strip() or len(text.encode()) > 1_000_000:
        raise ValueError("Supply a nonempty netlist under 1 MB.")
    source_dialect = dialect(text)
    normalized = normalize_spice(text)
    # The general parser preserves historic duplicate names by adding suffixes.
    # Uploads are stricter: reject duplicates before that repair takes place.
    instances = [re.match(r"([^\s(]+)", line.strip()).group(1).lower() for line in normalized.splitlines() if line.strip()]
    if len(set(instances)) != len(instances):
        raise ValueError("Duplicate device instance names are not allowed in uploads.")
    parsed = parse_netlist(normalized, {}, path="uploaded.cir")
    if not parsed.instances:
        raise ValueError("The netlist contains no supported devices.")
    if len(parsed.instances) > 2000:
        raise ValueError("V1 supports at most 2,000 devices per circuit.")
    instances = [d.instance_id.lower() for d in parsed.instances]
    if len(set(instances)) != len(instances):
        raise ValueError("Duplicate device instance names are not allowed in uploads.")
    port_names = ports.replace(",", " ").split()
    all_nets = set(net for d in parsed.instances for net in d.nets)
    if source_dialect == "spice":
        spelling = {n.casefold(): n for n in all_nets}
        port_names = [spelling.get(p.casefold(), p) for p in port_names]
    if len(set(port_names)) != len(port_names):
        raise ValueError("Port names must be unique.")
    if any(port not in all_nets for port in port_names):
        raise ValueError("Every supplied port must appear in the netlist.")
    identifier = "uploaded:" + str(uuid.uuid4())
    net_ids = {net: identifier + ":net:" + net for net in all_nets}
    devices, degree = [], Counter()
    for i, d in enumerate(parsed.instances, 1):
        kind = DEVICE_TYPES[d.kind].graph_kind
        conns = []
        for j, (terminal, net) in enumerate(zip(d.terminal_roles, d.nets, strict=True)):
            terminal = {"body": "bulk", "positive": "p", "negative": "n"}.get(terminal, terminal)
            conns.append(Connection(terminal=terminal, terminal_ordinal=j, net_id=net_ids[net]))
            degree[net] += 1
        devices.append(DeviceRecord(id=f"{identifier}:device:{i:06d}", ordinal=i, source_instance=d.instance_id,
                                    source_line=d.line_number, raw_type=d.kind, canonical_type=kind,
                                    category="transistor" if kind in {"nmos", "pmos", "npn", "pnp"} else "passive",
                                    connections=conns, parameters=dict(d.attributes), raw_line=d.source_text))
    records = [NetRecord(id=net_ids[n], name=n, is_external=n in port_names,
                         port_ordinal=port_names.index(n) if n in port_names else None,
                         degree_by_terminal=degree[n]) for n in sorted(all_nets)]
    port_records = [PortRecord(name=n, ordinal=i, net_id=net_ids[n], referenced_by_device=True) for i, n in enumerate(port_names)]
    hash_value = hashlib.sha256(text.encode()).hexdigest()
    record = CircuitRecord(parser=ParserRecord(name="workbench-flat", mode=ParseMode.STRICT), circuit_id=identifier,
                           source_circuit_id=identifier.split(":", 1)[1][:8], dataset="Uploaded",
                           source=SourceRecord(primary_netlist="upload.cir", port_file="", primary_sha256=hash_value,
                                               port_sha256=hashlib.sha256(ports.encode()).hexdigest(), auxiliary_files=[]),
                           devices=devices, nets=records, ports=port_records,
                           statistics=Statistics(device_count=len(devices), net_count=len(records), external_port_count=len(port_records),
                                                 connection_count=sum(degree.values()), device_type_counts=dict(Counter(d.canonical_type for d in devices)),
                                                 duplicate_source_instance_count=0, unreferenced_port_count=0, unknown_device_type_count=0), issues=[])
    problems = validate_circuit(record)
    if problems:
        raise ValueError("; ".join(problems))
    return record
