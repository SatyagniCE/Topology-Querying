"""Deterministic conversion from parsed netlists to device-only multigraphs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import TypeAlias

from gnn_pruning.contracts import (
    DEVICE_KINDS,
    INTERFACE_FLAGS,
    NET_ROLES,
    TERMINAL_ROLES,
    DeviceEdge,
    DeviceGraph,
    DeviceNode,
)
from gnn_pruning.conversion.device_types import DEVICE_TYPES
from gnn_pruning.conversion.netlist import (
    ParsedExpression,
    ParsedInstance,
    ParsedNetlist,
)
from gnn_pruning.io import atomic_write_json, canonical_sha256, load_json


# VSS is a rail only when an annotation explicitly maps it to gnd.
_DEFAULT_RAIL_ALIASES = (("0", "gnd"), ("GND", "gnd"), ("VDD", "vdd"))

_EntryInput: TypeAlias = Mapping[str, str] | Iterable[tuple[str, str]]


@dataclass(frozen=True)
class TopologyAnnotations:
    """Exact, reviewable topology semantics for a parsed circuit.

    ``rail_aliases`` names only power/ground nets.  ``net_roles`` names only
    non-rail semantic nets.  Both collections are normalized into sorted tuples,
    so annotation ordering cannot affect the generated graph or its JSON bytes.
    """

    rail_aliases: _EntryInput = field(default_factory=lambda: _DEFAULT_RAIL_ALIASES)
    net_roles: _EntryInput = field(default_factory=tuple)
    review_status: str = "pending"

    def __post_init__(self) -> None:
        rails = _normalize_entries(self.rail_aliases, label="rail alias")
        roles = _normalize_entries(self.net_roles, label="net role")
        for alias, flag in rails:
            if flag not in {"gnd", "vdd"}:
                raise ValueError(f"rail alias {alias} must map to gnd or vdd")
        for net, role in roles:
            if role not in NET_ROLES:
                raise ValueError(f"unknown net role {role}")
            if net in dict(rails):
                raise ValueError(f"net {net} cannot be both rail and semantic")
        if self.review_status not in {"pending", "approved"}:
            raise ValueError("annotation review_status must be pending or approved")
        object.__setattr__(self, "rail_aliases", rails)
        object.__setattr__(self, "net_roles", roles)

    @property
    def rail_flags(self) -> dict[str, str]:
        """Return exact rail alias to interface-flag mappings."""
        return dict(self.rail_aliases)

    @property
    def roles_by_net(self) -> dict[str, str]:
        """Return exact semantic net roles, without any name heuristics."""
        return dict(self.net_roles)


def build_device_graph(
    parsed: ParsedNetlist, annotations: TopologyAnnotations
) -> DeviceGraph:
    """Build a terminal-aware directed multigraph with one node per instance."""
    if not isinstance(parsed, ParsedNetlist):
        raise TypeError("parsed must be a ParsedNetlist")
    if not isinstance(annotations, TopologyAnnotations):
        raise TypeError("annotations must be TopologyAnnotations")

    _validate_parsed_netlist(parsed)
    contacts_by_net: dict[str, list[tuple[str, str]]] = defaultdict(list)
    instances_by_id: dict[str, ParsedInstance] = {}
    for instance in parsed.instances:
        instances_by_id[instance.instance_id] = instance
    for instance in parsed.instances:
        for net, terminal in zip(instance.nets, instance.terminal_roles, strict=True):
            contacts_by_net[net].append((instance.instance_id, terminal))

    available_nets = set(contacts_by_net)
    for net in annotations.roles_by_net:
        if net not in available_nets:
            raise ValueError(f"unknown annotated net {net}")

    rail_flags = annotations.rail_flags
    roles_by_net = annotations.roles_by_net
    node_flags: dict[str, set[str]] = defaultdict(set)
    equivalences: dict[str, set[tuple[str, str]]] = defaultdict(set)
    raw_edges: list[DeviceEdge] = []

    for net in sorted(contacts_by_net):
        contacts = contacts_by_net[net]
        _record_terminal_equivalence(contacts, equivalences)
        if net in rail_flags:
            # Current model consumes device-level rail flags, not rail edges.
            # The graph loses which terminal touched which rail; retain the
            # parsed netlist if that exact connectivity is needed downstream.
            for device_id, _ in contacts:
                node_flags[device_id].add(rail_flags[net])
            continue

        net_role = roles_by_net.get(net, "signal")
        if net_role in INTERFACE_FLAGS:
            for device_id, _ in contacts:
                node_flags[device_id].add(net_role)
        first_terminal_by_device: dict[str, str] = {}
        for device_id, terminal in contacts:
            first_terminal_by_device.setdefault(device_id, terminal)
        representative_contacts = sorted(first_terminal_by_device.items())
        for source_id, source_terminal in representative_contacts:
            for destination_id, destination_terminal in representative_contacts:
                if source_id == destination_id:
                    continue
                raw_edges.append(
                    DeviceEdge(
                        src=source_id,
                        dst=destination_id,
                        src_terminal=source_terminal,
                        dst_terminal=destination_terminal,
                        net=net,
                        net_role=net_role,
                        parallel_index=0,
                    )
                )

    edges = _with_parallel_indices(raw_edges)
    nodes = tuple(
        _build_node(instance, node_flags[instance_id], equivalences[instance_id])
        for instance_id, instance in sorted(instances_by_id.items())
    )
    graph = DeviceGraph(
        nodes=nodes,
        edges=edges,
        rail_nets=tuple(sorted(rail_flags)),
    )
    graph.validate()
    return graph


def write_device_graph(path: Path, graph: DeviceGraph) -> str:
    """Write canonical graph JSON and return the SHA-256 of its logical content."""
    document = device_graph_to_dict(graph)
    atomic_write_json(path, document)
    return canonical_sha256(document)


def read_device_graph(path: Path) -> DeviceGraph:
    """Read a graph written by :func:`write_device_graph` and validate it."""
    document = load_json(path)
    try:
        _require_exact_keys(
            document,
            {
                "converter_version",
                "edges",
                "graph_schema_version",
                "nodes",
                "rail_nets",
            },
            "device graph",
        )
        converter_version = _json_string(document, "converter_version")
        graph_schema_version = document["graph_schema_version"]
        if isinstance(graph_schema_version, bool) or not isinstance(
            graph_schema_version, int
        ):
            raise ValueError("graph_schema_version must be an integer")
        nodes = tuple(_node_from_dict(item) for item in _json_list(document, "nodes"))
        edges = tuple(_edge_from_dict(item) for item in _json_list(document, "edges"))
        rail_nets = tuple(_json_strings(document, "rail_nets"))
        graph = DeviceGraph(
            nodes=nodes,
            converter_version=converter_version,
            graph_schema_version=graph_schema_version,
            edges=edges,
            rail_nets=rail_nets,
        )
        graph.validate()
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid device graph {path}: {error}") from error
    return graph


def device_graph_to_dict(graph: DeviceGraph) -> dict[str, object]:
    """Return the canonical JSON-compatible representation of ``graph``."""
    graph.validate()
    return {
        "converter_version": graph.converter_version,
        "edges": [
            {
                "dst": edge.dst,
                "dst_terminal": edge.dst_terminal,
                "net": edge.net,
                "net_role": edge.net_role,
                "parallel_index": edge.parallel_index,
                "src": edge.src,
                "src_terminal": edge.src_terminal,
            }
            for edge in sorted(
                graph.edges,
                key=lambda edge: (
                    edge.src,
                    edge.dst,
                    edge.net,
                    edge.src_terminal,
                    edge.dst_terminal,
                    edge.parallel_index,
                ),
            )
        ],
        "graph_schema_version": graph.graph_schema_version,
        "nodes": [
            {
                "fixed_attributes": [
                    list(item) for item in sorted(node.fixed_attributes)
                ],
                "id": node.id,
                "interface_flags": sorted(node.interface_flags),
                "kind": node.kind,
                "terminal_equivalence": [
                    list(item) for item in sorted(node.terminal_equivalence)
                ],
                "terminal_roles": list(node.terminal_roles),
                "tunable_kinds": sorted(node.tunable_kinds),
            }
            for node in sorted(graph.nodes, key=lambda node: node.id)
        ],
        "rail_nets": sorted(graph.rail_nets),
    }


def _normalize_entries(
    entries: _EntryInput, *, label: str
) -> tuple[tuple[str, str], ...]:
    raw_items = entries.items() if isinstance(entries, Mapping) else entries
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, Sequence) or isinstance(item, str) or len(item) != 2:
            raise ValueError(f"{label} entries must contain exactly two strings")
        name, value = item
        if not isinstance(name, str) or not name:
            raise ValueError(f"{label} name must be a non-empty string")
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} value must be a non-empty string")
        if name in seen:
            raise ValueError(f"duplicate {label} {name}")
        seen.add(name)
        normalized.append((name, value))
    return tuple(sorted(normalized))


def _validate_parsed_netlist(parsed: ParsedNetlist) -> None:
    if not isinstance(parsed.source_sha256, str) or not parsed.source_sha256:
        raise ValueError("parsed netlist source SHA-256 must be a non-empty string")
    seen_ids: set[str] = set()
    for instance in parsed.instances:
        if not isinstance(instance, ParsedInstance):
            raise ValueError("parsed netlist contains an invalid instance")
        if not instance.instance_id:
            raise ValueError("parsed instance ID must not be empty")
        if instance.instance_id in seen_ids:
            raise ValueError(f"duplicate parsed instance ID {instance.instance_id}")
        seen_ids.add(instance.instance_id)
        device_type = DEVICE_TYPES.get(instance.kind)
        graph_kind = device_type.graph_kind if device_type else instance.kind
        if graph_kind not in DEVICE_KINDS:
            raise ValueError(f"unknown parsed device kind {instance.kind}")
        if len(instance.nets) != len(instance.terminal_roles):
            raise ValueError(
                f"parsed instance {instance.instance_id} has {len(instance.nets)} nets "
                f"for {len(instance.terminal_roles)} terminal roles"
            )
        if len(set(instance.terminal_roles)) != len(instance.terminal_roles):
            raise ValueError(
                f"duplicate parsed terminal role on {instance.instance_id}"
            )
        for net in instance.nets:
            if not isinstance(net, str) or not net:
                raise ValueError(
                    f"invalid net on parsed instance {instance.instance_id}"
                )
        for terminal in instance.terminal_roles:
            if terminal not in TERMINAL_ROLES:
                raise ValueError(f"unknown terminal role {terminal}")
        if set(instance.attributes) != set(instance.expressions):
            raise ValueError(f"attribute/expression mismatch on {instance.instance_id}")
        for name, expression in instance.expressions.items():
            _validate_expression(instance.instance_id, name, expression)
            if instance.attributes[name] != expression.raw:
                raise ValueError(
                    f"attribute raw value mismatch on {instance.instance_id}"
                )


def _validate_expression(instance_id: str, name: str, expression: object) -> None:
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(expression, ParsedExpression)
    ):
        raise ValueError(f"invalid parsed expression on {instance_id}")
    if expression.value is not None and not math.isfinite(expression.value):
        raise ValueError(f"non-finite parsed expression {name} on {instance_id}")


def _record_terminal_equivalence(
    contacts: list[tuple[str, str]],
    equivalences: dict[str, set[tuple[str, str]]],
) -> None:
    terminals_by_device: dict[str, list[str]] = defaultdict(list)
    for device_id, terminal in contacts:
        terminals_by_device[device_id].append(terminal)
    for device_id, terminals in terminals_by_device.items():
        for index, first in enumerate(sorted(terminals)):
            for second in sorted(terminals)[index + 1 :]:
                equivalences[device_id].add((first, second))


def _with_parallel_indices(edges: list[DeviceEdge]) -> tuple[DeviceEdge, ...]:
    ordered = sorted(
        edges,
        key=lambda edge: (
            edge.src,
            edge.dst,
            edge.net,
            edge.src_terminal,
            edge.dst_terminal,
        ),
    )
    counters: dict[tuple[str, str], int] = defaultdict(int)
    indexed: list[DeviceEdge] = []
    for edge in ordered:
        key = (edge.src, edge.dst)
        indexed.append(
            DeviceEdge(
                src=edge.src,
                dst=edge.dst,
                src_terminal=edge.src_terminal,
                dst_terminal=edge.dst_terminal,
                net=edge.net,
                net_role=edge.net_role,
                parallel_index=counters[key],
            )
        )
        counters[key] += 1
    return tuple(indexed)


def _build_node(
    instance: ParsedInstance,
    flags: set[str],
    terminal_equivalence: set[tuple[str, str]],
) -> DeviceNode:
    device_type = DEVICE_TYPES.get(instance.kind)
    tunable_attributes = device_type.tunable_attributes if device_type else {}
    fixed_attributes = tuple(
        sorted(
            (name, expression.value)
            for name, expression in instance.expressions.items()
            if expression.value is not None
        )
    )
    tunable_kinds = tuple(
        sorted(
            {
                tunable_kind
                for name, expression in instance.expressions.items()
                if expression.value is None
                and (tunable_kind := tunable_attributes.get(name))
                is not None
            }
        )
    )
    return DeviceNode(
        id=instance.instance_id,
        kind=device_type.graph_kind if device_type else instance.kind,
        terminal_roles=instance.terminal_roles,
        terminal_equivalence=tuple(sorted(terminal_equivalence)),
        interface_flags=tuple(sorted(flags)),
        fixed_attributes=fixed_attributes,
        tunable_kinds=tunable_kinds,
    )


def _json_list(document: Mapping[str, object], name: str) -> list[object]:
    value = document[name]
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _json_strings(document: Mapping[str, object], name: str) -> list[str]:
    values = _json_list(document, name)
    if not all(isinstance(item, str) for item in values):
        raise ValueError(f"{name} must contain strings")
    return [item for item in values if isinstance(item, str)]


def _node_from_dict(value: object) -> DeviceNode:
    if not isinstance(value, Mapping):
        raise ValueError("node must be a JSON object")
    _require_exact_keys(
        value,
        {
            "fixed_attributes",
            "id",
            "interface_flags",
            "kind",
            "terminal_equivalence",
            "terminal_roles",
            "tunable_kinds",
        },
        "node",
    )
    fixed = _json_numeric_pairs(value, "fixed_attributes")
    equivalence = _json_string_pairs(value, "terminal_equivalence")
    return DeviceNode(
        id=_json_string(value, "id"),
        kind=_json_string(value, "kind"),
        terminal_roles=tuple(_json_strings(value, "terminal_roles")),
        terminal_equivalence=tuple(equivalence),
        interface_flags=tuple(_json_strings(value, "interface_flags")),
        fixed_attributes=tuple(fixed),
        tunable_kinds=tuple(_json_strings(value, "tunable_kinds")),
    )


def _edge_from_dict(value: object) -> DeviceEdge:
    if not isinstance(value, Mapping):
        raise ValueError("edge must be a JSON object")
    _require_exact_keys(
        value,
        {
            "dst",
            "dst_terminal",
            "net",
            "net_role",
            "parallel_index",
            "src",
            "src_terminal",
        },
        "edge",
    )
    parallel_index = value["parallel_index"]
    if isinstance(parallel_index, bool) or not isinstance(parallel_index, int):
        raise ValueError("parallel_index must be an integer")
    return DeviceEdge(
        src=_json_string(value, "src"),
        dst=_json_string(value, "dst"),
        src_terminal=_json_string(value, "src_terminal"),
        dst_terminal=_json_string(value, "dst_terminal"),
        net=_json_string(value, "net"),
        net_role=_json_string(value, "net_role"),
        parallel_index=parallel_index,
    )


def _json_numeric_pairs(
    document: Mapping[str, object], name: str
) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for item in _json_list(document, name):
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise ValueError(f"{name} must contain string-keyed pairs")
        if isinstance(item[1], bool) or not isinstance(item[1], (int, float)):
            raise ValueError(f"{name} values must be numeric")
        pairs.append((item[0], float(item[1])))
    return pairs


def _json_string_pairs(
    document: Mapping[str, object], name: str
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for item in _json_list(document, name):
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise ValueError(f"{name} must contain string-keyed pairs")
        if not isinstance(item[1], str):
            raise ValueError(f"{name} values must be strings")
        pairs.append((item[0], item[1]))
    return pairs


def _json_string(document: Mapping[str, object], name: str) -> str:
    value = document[name]
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _require_exact_keys(
    document: Mapping[str, object], expected: set[str], label: str
) -> None:
    missing = expected - set(document)
    unknown = set(document) - expected
    if missing:
        raise ValueError(f"{label} missing keys: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{label} has unknown keys: {', '.join(sorted(unknown))}")
