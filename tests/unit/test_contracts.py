"""Tests for immutable device graph contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from gnn_pruning.contracts import (
    DeviceEdge,
    DeviceGraph,
    DeviceNode,
)


def valid_graph() -> DeviceGraph:
    return DeviceGraph(
        nodes=(
            DeviceNode(id="M1", kind="nmos", terminal_roles=("drain", "gate")),
            DeviceNode(id="C1", kind="capacitor", terminal_roles=("positive",)),
        ),
        edges=(
            DeviceEdge(
                src="M1",
                dst="C1",
                src_terminal="drain",
                dst_terminal="positive",
                net="out",
                net_role="output",
                parallel_index=0,
            ),
        ),
    )


def test_contract_dataclasses_are_immutable():
    node = DeviceNode(id="M1", kind="nmos")

    with pytest.raises(FrozenInstanceError):
        node.id = "M2"  # type: ignore[misc]


def test_graph_accepts_terminal_aware_parallel_edges_and_rail_flags():
    graph = DeviceGraph(
        nodes=(
            DeviceNode(
                id="M1",
                kind="nmos",
                terminal_roles=("drain", "gate", "source"),
                terminal_equivalence=(("drain", "gate"),),
                interface_flags=("gnd",),
            ),
            DeviceNode(id="C1", kind="capacitor", terminal_roles=("positive",)),
        ),
        edges=(
            DeviceEdge("M1", "C1", "drain", "positive", "out", "output", 0),
            DeviceEdge("M1", "C1", "gate", "positive", "feedback", "signal", 1),
        ),
    )

    graph.validate()


def test_graph_accepts_edge_terminals_declared_on_their_endpoints():
    valid_graph().validate()


@pytest.mark.parametrize(
    "graph",
    (
        DeviceGraph(nodes=(DeviceNode("M1", "nmos"),), converter_version=1),  # type: ignore[arg-type]
        DeviceGraph(nodes=(DeviceNode("M1", "nmos"),), graph_schema_version=1.0),  # type: ignore[arg-type]
    ),
)
def test_graph_contract_rejects_wrong_version_types(graph: DeviceGraph):
    with pytest.raises(ValueError, match="unsupported graph .* version"):
        graph.validate()


@pytest.mark.parametrize(
    ("edge", "message"),
    [
        (
            DeviceEdge("M1", "C1", "source", "positive", "out", "output", 0),
            "source terminal source is not declared on node M1",
        ),
        (
            DeviceEdge("M1", "C1", "drain", "negative", "out", "output", 0),
            "destination terminal negative is not declared on node C1",
        ),
    ],
)
def test_graph_rejects_edge_terminal_absent_from_its_endpoint(
    edge: DeviceEdge, message: str
):
    graph = DeviceGraph(nodes=valid_graph().nodes, edges=(edge,))

    with pytest.raises(ValueError, match=message):
        graph.validate()


@pytest.mark.parametrize(
    ("graph", "message"),
    [
        (
            DeviceGraph(
                nodes=(DeviceNode("M1", "nmos"), DeviceNode("M1", "pmos")),
            ),
            "duplicate node ID M1",
        ),
        (
            DeviceGraph(
                nodes=(DeviceNode("M1", "nmos"),),
                edges=(DeviceEdge("M1", "M1", "drain", "gate", "out", "output", 0),),
            ),
            "self-edge M1",
        ),
        (
            DeviceGraph(
                nodes=(DeviceNode(id="M1", kind="nmos"),),
                edges=(
                    DeviceEdge(
                        src="M1",
                        dst="M2",
                        src_terminal="drain",
                        dst_terminal="positive",
                        net="out",
                        net_role="output",
                        parallel_index=0,
                    ),
                ),
            ),
            "unknown node M2",
        ),
        (DeviceGraph(nodes=(DeviceNode("M1", "mystery"),)), "unknown device kind"),
        (
            DeviceGraph(
                nodes=(
                    DeviceNode("M1", "nmos", terminal_roles=("drain",)),
                    DeviceNode("C1", "capacitor", terminal_roles=("positive",)),
                ),
                edges=(
                    DeviceEdge("M1", "C1", "drain", "positive", "out", "mystery", 0),
                ),
            ),
            "unknown net role",
        ),
        (
            DeviceGraph(
                nodes=(
                    DeviceNode("M1", "nmos", terminal_roles=("drain",)),
                    DeviceNode("C1", "capacitor", terminal_roles=("positive",)),
                ),
                edges=(
                    DeviceEdge("M1", "C1", "drain", "positive", "out", "output", -1),
                ),
            ),
            "negative parallel index",
        ),
        (
            DeviceGraph(
                nodes=(
                    DeviceNode("M1", "nmos", terminal_roles=("drain",)),
                    DeviceNode("C1", "capacitor", terminal_roles=("positive",)),
                ),
                edges=(
                    DeviceEdge("M1", "C1", "drain", "positive", "VDD", "signal", 0),
                ),
            ),
            "rail net VDD",
        ),
    ],
)
def test_graph_rejects_invalid_topology(graph: DeviceGraph, message: str):
    with pytest.raises(ValueError, match=message):
        graph.validate()
