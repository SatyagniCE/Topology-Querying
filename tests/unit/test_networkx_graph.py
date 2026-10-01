from circuit_ingest.canonical_graph import project_circuit
from circuit_ingest.models import CircuitRecord
from circuit_ingest.networkx_graph import build_networkx_graph, graph_signature
from tests.fixtures.canonical_record import sample_record


def test_graph_matches_projection():
    record = sample_record()
    projection = project_circuit(record)
    graph = build_networkx_graph(record)
    assert graph.graph == {
        "circuit_id": projection.circuit_id, "dataset": projection.dataset,
        "schema_version": projection.schema_version, "record_json": projection.record_json,
    }
    assert CircuitRecord.model_validate_json(graph.graph["record_json"]) == record
    assert {node: attributes for node, attributes in graph.nodes(data=True)} == {
        node.id: {"id": node.id, "kind": node.kind, **node.properties}
        for node in projection.nodes
    }
    actual = sorted((source, target, key, tuple(sorted(properties.items())))
                    for source, target, key, properties in graph.edges(keys=True, data=True))
    expected = sorted((edge.source, edge.target,
                       f"CONNECTED_TO:{edge.properties['terminal_ordinal']}"
                       if edge.kind == "CONNECTED_TO" else "MAPS_TO",
                       tuple(sorted({"kind": edge.kind, **edge.properties}.items())))
                      for edge in projection.edges)
    assert actual == expected


def test_parallel_contacts_keep_distinct_keys():
    graph = build_networkx_graph(sample_record())
    device = "test:networkx:device:000001"
    net = "test:networkx:net:shared"
    edges = graph.get_edge_data(device, net)
    assert edges["CONNECTED_TO:0"] == {
        "kind": "CONNECTED_TO", "terminal": "collector", "terminal_ordinal": 0}
    assert edges["CONNECTED_TO:1"] == {
        "kind": "CONNECTED_TO", "terminal": "base", "terminal_ordinal": 1}
    assert len(edges) == 3
    assert not graph.has_edge(net, device)


def test_zero_degree_port_maps_to_net():
    graph = build_networkx_graph(sample_record())
    port = "test:networkx:port:000000"
    net = "test:networkx:net:unused"
    assert graph.nodes[net]["degree_by_terminal"] == 0
    assert graph.nodes[port]["referenced_by_device"] is False
    assert graph.get_edge_data(port, net) == {"MAPS_TO": {"kind": "MAPS_TO"}}
    assert not any(data["kind"] == "CONNECTED_TO" for _, _, data in graph.in_edges(net, data=True))


def test_duplicate_source_names_keep_global_ids():
    graph = build_networkx_graph(sample_record())
    devices = {node for node, data in graph.nodes(data=True)
               if data["kind"] == "Device" and data["source_instance"] == "Q30"}
    assert devices == {"test:networkx:device:000001", "test:networkx:device:000002"}


def test_graph_signature_detects_changes():
    graph = build_networkx_graph(sample_record())
    original = graph_signature(graph)
    changed_edge = graph.copy()
    changed_edge.edges["test:networkx:device:000001", "test:networkx:net:shared",
                       "CONNECTED_TO:0"]["terminal_ordinal"] = 8
    assert graph_signature(changed_edge) != original
    changed_metadata = graph.copy()
    changed_metadata.graph["dataset"] = "changed"
    assert graph_signature(changed_metadata) != original
