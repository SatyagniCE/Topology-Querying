"""Immutable contracts for device graphs."""

from __future__ import annotations

import math
from dataclasses import dataclass


DEVICE_KINDS = frozenset(
    {
        "nmos",
        "pmos",
        "npn",
        "pnp",
        "diode",
        "resistor",
        "capacitor",
        "inductor",
        "current_source",
        "voltage_source",
        "balun",
        "load",
        "port",
    }
)
TERMINAL_ROLES = frozenset(
    {
        "drain",
        "gate",
        "source",
        "body",
        "collector",
        "base",
        "emitter",
        "substrate",
        "anode",
        "cathode",
        "positive",
        "negative",
        "port",
        "reference",
        "single_ended",
        "differential_positive",
        "differential_negative",
    }
)
INTERFACE_FLAGS = frozenset(
    {
        "vdd",
        "gnd",
        "bias",
        "input",
        "output",
        "differential-positive",
        "differential-negative",
    }
)
NET_ROLES = frozenset(
    {
        "signal",
        "bias",
        "input",
        "output",
        "differential-positive",
        "differential-negative",
    }
)
PARAMETER_TRANSFORMS = {
    "capacitance": "bounded_log10",
    "inductance": "bounded_log10",
    "resistance": "bounded_log10",
    "mos_width": "bounded_log10",
    "current": "bounded_log10",
    "voltage": "bounded_linear",
}
SUPPORTED_GRAPH_CONVERTER_VERSION = "gnn-pruning-device-graph/1.0.0"
SUPPORTED_GRAPH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DeviceNode:
    """One physical netlist instance; identifiers stay metadata, never inputs."""

    id: str
    kind: str
    terminal_roles: tuple[str, ...] = ()
    terminal_equivalence: tuple[tuple[str, str], ...] = ()
    interface_flags: tuple[str, ...] = ()
    fixed_attributes: tuple[tuple[str, float], ...] = ()
    tunable_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeviceEdge:
    """A terminal-aware directed relation on one retained non-rail net."""

    src: str
    dst: str
    src_terminal: str
    dst_terminal: str
    net: str
    net_role: str
    parallel_index: int


@dataclass(frozen=True)
class DeviceGraph:
    """A device-only directed multigraph with rail contact represented on nodes."""

    nodes: tuple[DeviceNode, ...]
    converter_version: str = SUPPORTED_GRAPH_CONVERTER_VERSION
    graph_schema_version: int = SUPPORTED_GRAPH_SCHEMA_VERSION
    edges: tuple[DeviceEdge, ...] = ()
    rail_nets: tuple[str, ...] = ("0", "GND", "VDD")

    def validate(self) -> None:
        if (
            not isinstance(self.converter_version, str)
            or self.converter_version != SUPPORTED_GRAPH_CONVERTER_VERSION
        ):
            raise ValueError(
                f"unsupported graph converter version {self.converter_version!r}"
            )
        if (
            isinstance(self.graph_schema_version, bool)
            or not isinstance(self.graph_schema_version, int)
            or self.graph_schema_version != SUPPORTED_GRAPH_SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported graph schema version {self.graph_schema_version!r}"
            )
        nodes_by_id: dict[str, DeviceNode] = {}
        for node in self.nodes:
            if not node.id:
                raise ValueError("node ID must not be empty")
            if node.id in nodes_by_id:
                raise ValueError(f"duplicate node ID {node.id}")
            nodes_by_id[node.id] = node
            self._validate_node(node)

        rail_nets = set(self.rail_nets)
        if len(rail_nets) != len(self.rail_nets):
            raise ValueError("duplicate rail net declaration")
        for edge in self.edges:
            if edge.src == edge.dst:
                raise ValueError(f"self-edge {edge.src}")
            for endpoint in (edge.src, edge.dst):
                if endpoint not in nodes_by_id:
                    raise ValueError(f"unknown node {endpoint}")
            if edge.src_terminal not in TERMINAL_ROLES:
                raise ValueError(f"unknown terminal role {edge.src_terminal}")
            if edge.dst_terminal not in TERMINAL_ROLES:
                raise ValueError(f"unknown terminal role {edge.dst_terminal}")
            if edge.src_terminal not in nodes_by_id[edge.src].terminal_roles:
                raise ValueError(
                    f"source terminal {edge.src_terminal} is not declared on node {edge.src}"
                )
            if edge.dst_terminal not in nodes_by_id[edge.dst].terminal_roles:
                raise ValueError(
                    "destination terminal "
                    f"{edge.dst_terminal} is not declared on node {edge.dst}"
                )
            if edge.net_role not in NET_ROLES:
                raise ValueError(f"unknown net role {edge.net_role}")
            if edge.parallel_index < 0:
                raise ValueError(f"negative parallel index {edge.parallel_index}")
            if edge.net in rail_nets:
                raise ValueError(f"rail net {edge.net} must not create an edge")

    @staticmethod
    def _validate_node(node: DeviceNode) -> None:
        if node.kind not in DEVICE_KINDS:
            raise ValueError(f"unknown device kind {node.kind}")
        if len(set(node.terminal_roles)) != len(node.terminal_roles):
            raise ValueError(f"duplicate terminal role on node {node.id}")
        for role in node.terminal_roles:
            if role not in TERMINAL_ROLES:
                raise ValueError(f"unknown terminal role {role}")
        for first, second in node.terminal_equivalence:
            if first == second:
                raise ValueError(f"terminal equivalence repeats {first}")
            if first not in node.terminal_roles or second not in node.terminal_roles:
                raise ValueError(
                    f"terminal equivalence references undeclared terminal on node {node.id}"
                )
        for flag in node.interface_flags:
            if flag not in INTERFACE_FLAGS:
                raise ValueError(f"unknown interface flag {flag}")
        attributes = [name for name, _ in node.fixed_attributes]
        if len(set(attributes)) != len(attributes):
            raise ValueError(f"duplicate fixed attribute on node {node.id}")
        if any(not math.isfinite(value) for _, value in node.fixed_attributes):
            raise ValueError(f"non-finite fixed attribute on node {node.id}")
        for kind in node.tunable_kinds:
            if kind not in PARAMETER_TRANSFORMS:
                raise ValueError(f"unknown tunable kind {kind}")
