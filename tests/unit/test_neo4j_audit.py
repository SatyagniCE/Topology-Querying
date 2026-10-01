import json

from circuit_ingest.neo4j_audit import AuditSnapshot, compare_snapshot


def _report(tmp_path, *, devices=3):
    path = tmp_path / "audit-report.json"
    path.write_text(json.dumps({
        "status_counts": {"valid": 1, "valid_with_warnings": 1},
        "totals": {"devices": devices, "nets": 4, "ports": 1, "connections": 5},
        "canonical_device_type_counts": {"npn": devices},
    }), encoding="utf-8")
    return path


def _matching_snapshot():
    return AuditSnapshot(
        counts={"Circuit": 2, "Device": 3, "Net": 4, "Port": 1,
                "CONNECTED_TO": 5, "MAPS_TO": 1},
        device_types={"npn": 3}, invalid_port_mappings=0,
        cross_circuit_connections=0, orphan_nodes=0,
        q30_terminal_ordinals=(3,),
    )


def test_expected_counts_follow_report_changes(tmp_path):
    report = _report(tmp_path)
    assert compare_snapshot(_matching_snapshot(), report) == []
    report = _report(tmp_path, devices=4)
    messages = compare_snapshot(_matching_snapshot(), report)
    assert any("Device" in message and "expected 4" in message for message in messages)
    assert any("npn" in message and "expected 4" in message for message in messages)


def test_every_count_and_integrity_mismatch_is_reported(tmp_path):
    report = _report(tmp_path)
    actual = AuditSnapshot(
        counts={"Circuit": 0, "Device": 0, "Net": 0, "Port": 0,
                "CONNECTED_TO": 0, "MAPS_TO": 0},
        device_types={"resistor": 1}, invalid_port_mappings=1,
        cross_circuit_connections=1, orphan_nodes=1,
        q30_terminal_ordinals=(),
    )
    messages = compare_snapshot(actual, report)
    for subject in ("Circuit", "Device", "Net", "Port", "CONNECTED_TO",
                    "MAPS_TO", "npn", "resistor", "port mappings",
                    "cross-circuit", "orphan", "Q30"):
        assert any(subject in message for message in messages), subject
