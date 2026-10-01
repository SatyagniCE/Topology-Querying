"""Cross-record integrity checks for a canonical circuit."""
from collections import Counter
from .models import CircuitRecord


def validate_circuit(circuit: CircuitRecord) -> list[str]:
    errors = []
    ids = [device.id for device in circuit.devices]
    if len(ids) != len(set(ids)):
        errors.append("duplicate device ID")
    net_ids = [net.id for net in circuit.nets]
    if len(net_ids) != len(set(net_ids)):
        errors.append("duplicate net ID")
    net_id_set = set(net_ids)
    degrees: Counter[str] = Counter()
    for device in circuit.devices:
        for ordinal, connection in enumerate(device.connections):
            if connection.net_id not in net_id_set:
                errors.append(f"missing net {connection.net_id}")
            if connection.terminal_ordinal != ordinal:
                errors.append(f"invalid terminal ordinal in {device.id}")
            degrees[connection.net_id] += 1
    for net in circuit.nets:
        if net.degree_by_terminal != degrees[net.id]:
            errors.append(f"incorrect degree for {net.id}")
    for port in circuit.ports:
        if port.net_id not in net_id_set:
            errors.append(f"missing port net {port.net_id}")
    if circuit.statistics.device_count != len(circuit.devices):
        errors.append("incorrect device count")
    if circuit.statistics.net_count != len(circuit.nets):
        errors.append("incorrect net count")
    if circuit.statistics.connection_count != sum(degrees.values()):
        errors.append("incorrect connection count")
    return errors
