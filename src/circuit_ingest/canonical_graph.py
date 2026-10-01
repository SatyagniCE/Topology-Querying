"""Database-independent topology projection of a canonical circuit."""
from __future__ import annotations

from dataclasses import dataclass
import json

from .models import CircuitRecord, SCHEMA_VERSION
from .validation import validate_circuit


@dataclass(frozen=True)
class NodeSpec:
    kind: str
    id: str
    properties: dict[str, str | int | bool]


@dataclass(frozen=True)
class EdgeSpec:
    kind: str
    source: str
    target: str
    properties: dict[str, str | int]


@dataclass(frozen=True)
class CircuitProjection:
    circuit_id: str
    dataset: str
    schema_version: str
    record_json: str
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeSpec, ...]


def project_circuit(record: CircuitRecord) -> CircuitProjection:
    """Validate and materialize Device, Net, Port, and terminal topology once."""
    if record.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported circuit schema version {record.schema_version}")
    errors = validate_circuit(record)
    if errors:
        raise ValueError("invalid circuit record: " + "; ".join(errors))

    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []
    for device in record.devices:
        nodes.append(NodeSpec("Device", device.id, {
            "source_instance": device.source_instance,
            "ordinal": device.ordinal,
            "canonical_type": device.canonical_type,
            "raw_type": device.raw_type,
            "category": device.category,
        }))
        for connection in device.connections:
            edges.append(EdgeSpec("CONNECTED_TO", device.id, connection.net_id, {
                "terminal": connection.terminal,
                "terminal_ordinal": connection.terminal_ordinal,
            }))
    for net in record.nets:
        nodes.append(NodeSpec("Net", net.id, {
            "name": net.name,
            "is_external": net.is_external,
            "degree_by_terminal": net.degree_by_terminal,
        }))
    for port in record.ports:
        port_id = f"{record.circuit_id}:port:{port.ordinal:06d}"
        nodes.append(NodeSpec("Port", port_id, {
            "name": port.name,
            "ordinal": port.ordinal,
            "referenced_by_device": port.referenced_by_device,
        }))
        edges.append(EdgeSpec("MAPS_TO", port_id, port.net_id, {}))

    record_json = json.dumps(record.model_dump(mode="json"), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
    return CircuitProjection(record.circuit_id, record.dataset, record.schema_version,
                             record_json, tuple(nodes), tuple(edges))
