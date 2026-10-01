"""Small valid canonical records shared by backend tests."""
from circuit_ingest.models import (
    CircuitRecord, Connection, DeviceRecord, NetRecord, ParseMode,
    ParserRecord, PortRecord, SourceRecord, Statistics,
)


def sample_record(circuit_id: str = "test:networkx", *, duplicate: bool = True) -> CircuitRecord:
    shared = f"{circuit_id}:net:shared"
    ground = f"{circuit_id}:net:0"
    unused = f"{circuit_id}:net:unused"
    count = 2 if duplicate else 1
    devices = [DeviceRecord(
        id=f"{circuit_id}:device:{ordinal:06d}", ordinal=ordinal,
        source_instance="Q30", source_line=ordinal, raw_type="npn",
        canonical_type="npn", category="transistor",
        connections=[
            Connection(terminal="collector", terminal_ordinal=0, net_id=shared),
            Connection(terminal="base", terminal_ordinal=1, net_id=shared),
            Connection(terminal="emitter", terminal_ordinal=2, net_id=shared),
            Connection(terminal="substrate", terminal_ordinal=3, net_id=ground),
        ], raw_line="Q30 (shared shared shared 0) npn",
    ) for ordinal in range(1, count + 1)]
    return CircuitRecord(
        parser=ParserRecord(mode=ParseMode.STRICT), circuit_id=circuit_id,
        source_circuit_id=circuit_id, dataset="test",
        source=SourceRecord(primary_netlist="test.cir", port_file="Port.txt",
                            primary_sha256="0" * 64, port_sha256="0" * 64,
                            auxiliary_files=[]),
        ports=[PortRecord(name="unused", ordinal=0, net_id=unused,
                          referenced_by_device=False)],
        nets=[
            NetRecord(id=shared, name="shared", is_external=False,
                      port_ordinal=None, degree_by_terminal=3 * count),
            NetRecord(id=ground, name="0", is_external=False,
                      port_ordinal=None, degree_by_terminal=count),
            NetRecord(id=unused, name="unused", is_external=True,
                      port_ordinal=0, degree_by_terminal=0),
        ], devices=devices,
        statistics=Statistics(device_count=count, net_count=3, external_port_count=1,
                              connection_count=4 * count, device_type_counts={"npn": count},
                              duplicate_source_instance_count=count - 1,
                              unreferenced_port_count=1,
                              unknown_device_type_count=0), issues=[],
    )
