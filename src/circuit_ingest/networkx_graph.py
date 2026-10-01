"""NetworkX materialization of the shared canonical circuit projection."""
from __future__ import annotations

import networkx as nx

from .canonical_graph import project_circuit
from .models import CircuitRecord


def build_networkx_graph(record: CircuitRecord) -> nx.MultiDiGraph:
    """Return one directed multigraph with canonical IDs and topology."""
    projection = project_circuit(record)
    graph = nx.MultiDiGraph(
        circuit_id=projection.circuit_id, dataset=projection.dataset,
        schema_version=projection.schema_version, record_json=projection.record_json,
    )
    for node in projection.nodes:
        graph.add_node(node.id, id=node.id, kind=node.kind, **node.properties)
    for edge in projection.edges:
        key = (f"CONNECTED_TO:{edge.properties['terminal_ordinal']}"
               if edge.kind == "CONNECTED_TO" else "MAPS_TO")
        graph.add_edge(edge.source, edge.target, key=key,
                       kind=edge.kind, **edge.properties)
    return graph


def graph_signature(graph: nx.MultiDiGraph) -> tuple:
    """Normalize all graph content for deterministic equality checks."""
    if not isinstance(graph, nx.MultiDiGraph):
        raise TypeError("expected MultiDiGraph")
    expected = {"circuit_id", "dataset", "schema_version", "record_json"}
    if set(graph.graph) != expected:
        raise ValueError("graph metadata is incomplete or unexpected")
    nodes = tuple(sorted((node_id, tuple(sorted(attributes.items())))
                         for node_id, attributes in graph.nodes(data=True)))
    edges = []
    for source, target, key, attributes in graph.edges(keys=True, data=True):
        if attributes.get("kind") not in {"CONNECTED_TO", "MAPS_TO"}:
            raise ValueError("edge kind is missing or invalid")
        edges.append((source, target, key, tuple(sorted(attributes.items()))))
    return (tuple(sorted(graph.graph.items())), nodes, tuple(sorted(edges)))
