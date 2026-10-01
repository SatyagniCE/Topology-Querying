from circuit_ingest.models import (
    CircuitRecord, Connection, DeviceRecord, NetRecord, ParseMode,
    ParserRecord, PortRecord, SourceRecord, Statistics,
)
from circuit_ingest.canonical_graph import project_circuit


def test_parallel_terminals_survive_projection():
    circuit_id = "test:projection"
    net_id = f"{circuit_id}:net:shared"
    record = CircuitRecord(
        parser=ParserRecord(mode=ParseMode.STRICT),
        circuit_id=circuit_id,
        source_circuit_id="projection",
        dataset="test",
        source=SourceRecord(primary_netlist="test.cir", port_file="Port.txt",
                            primary_sha256="0" * 64, port_sha256="0" * 64,
                            auxiliary_files=[]),
        ports=[PortRecord(name="shared", ordinal=0, net_id=net_id,
                          referenced_by_device=True)],
        nets=[NetRecord(id=net_id, name="shared", is_external=True,
                        port_ordinal=0, degree_by_terminal=2)],
        devices=[DeviceRecord(
            id=f"{circuit_id}:device:000001", ordinal=1,
            source_instance="Q1", source_line=1, raw_type="npn",
            canonical_type="npn", category="transistor",
            connections=[Connection(terminal="collector", terminal_ordinal=0, net_id=net_id),
                         Connection(terminal="base", terminal_ordinal=1, net_id=net_id)],
            raw_line="Q1 (shared shared) npn",
        )],
        statistics=Statistics(device_count=1, net_count=1, external_port_count=1,
                              connection_count=2, device_type_counts={"npn": 1},
                              duplicate_source_instance_count=0,
                              unreferenced_port_count=0, unknown_device_type_count=0),
        issues=[],
    )

    projection = project_circuit(record)

    assert [(edge.kind, edge.source, edge.target, edge.properties)
            for edge in projection.edges] == [
        ("CONNECTED_TO", f"{circuit_id}:device:000001", net_id,
         {"terminal": "collector", "terminal_ordinal": 0}),
        ("CONNECTED_TO", f"{circuit_id}:device:000001", net_id,
         {"terminal": "base", "terminal_ordinal": 1}),
        ("MAPS_TO", f"{circuit_id}:port:000000", net_id, {}),
    ]
    assert [(node.kind, node.id) for node in projection.nodes] == [
        ("Device", f"{circuit_id}:device:000001"),
        ("Net", net_id),
        ("Port", f"{circuit_id}:port:000000"),
    ]
    assert "port_ordinal" not in projection.nodes[1].properties
