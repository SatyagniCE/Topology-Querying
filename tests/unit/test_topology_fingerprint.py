"""Hand-wired structural fixtures, not asserted functional classifications."""
import numpy as np
import pytest

from circuit_workbench import retrieval
from circuit_workbench.uploads import parse_upload


def circuit(text, ports=""):
    return parse_upload(text, "Structural retrieval fixture", ports)


PAIR = "M1 (a in1 tail 0) nmos4\nM2 (b in2 tail 0) nmos4\nM3 (tail bias 0 0) nmos4"
SEPARATE = "M1 (a in1 t1 0) nmos4\nM2 (b in2 t2 0) nmos4\nM3 (t1 bias t2 0) nmos4"


def test_profile_identifies_shared_source_not_shared_ground():
    profile = retrieval.topology_profile(circuit(PAIR))
    assert profile["motifs"]["nmos:shared_source_pair"] == 1
    grounded = circuit("M1 (a in1 0 0) nmos4\nM2 (b in2 0 0) nmos4")
    assert retrieval.topology_profile(grounded)["motifs"]["nmos:shared_source_pair"] == 0


def test_profile_mirror_candidate_requires_gate_drain_tie():
    tied = circuit("M1 (bias bias 0 0) nmos4\nM2 (out bias 0 0) nmos4")
    untied = circuit("M1 (a bias 0 0) nmos4\nM2 (out bias 0 0) nmos4")
    assert retrieval.topology_profile(tied)["motifs"]["nmos:mirror_candidate_pair"] == 1
    assert retrieval.topology_profile(untied)["motifs"]["nmos:mirror_candidate_pair"] == 0


def test_stack_uses_source_drain_not_gate_connection():
    stack = circuit("M1 (out b1 mid 0) nmos4\nM2 (mid b2 0 0) nmos4")
    gate_link = circuit("M1 (out mid b1 0) nmos4\nM2 (mid b2 0 0) nmos4")
    assert retrieval.topology_profile(stack)["motifs"]["nmos:drain_source_stack"] == 1
    assert retrieval.topology_profile(gate_link)["motifs"]["nmos:drain_source_stack"] == 0


def test_series_rc_distinguishes_shunt_components():
    series = circuit("R1 (a mid) resistor\nC1 (mid b) capacitor")
    parallel = circuit("R1 (a b) resistor\nC1 (a b) capacitor")
    assert retrieval.topology_profile(series)["motifs"]["series_rc"] == 1
    assert retrieval.topology_profile(parallel)["motifs"]["series_rc"] == 0


def test_complete_neighbourhood_sequence_includes_four_hops():
    profile = retrieval.topology_profile(circuit(PAIR))
    assert len(profile["neighborhoods"]) == 5
    assert all(sum(level.values()) == 9 for level in profile["neighborhoods"])


def test_shared_source_rewire_has_material_fingerprint_difference():
    # Same device inventory and size must not dominate the changed wiring.
    a, b = circuit(PAIR), circuit(SEPARATE)
    assert retrieval.cosine(retrieval.topology_vector(a), retrieval.topology_vector(b)) < 0.8


def test_fingerprint_and_exact_comparison_ignore_ids_order_and_internal_names():
    a = circuit(PAIR)
    b = circuit("M9 (x sig1 common 0) nmos4\nM8 (y sig2 common 0) nmos4\nM7 (common ctrl 0 0) nmos4")
    b.devices.reverse()
    b.nets.reverse()
    assert retrieval.cosine(retrieval.topology_vector(a), retrieval.topology_vector(b)) == pytest.approx(1)
    assert retrieval.structural_similarity(retrieval.topology_profile(a), retrieval.topology_profile(b)) == pytest.approx(1)


def test_component_values_do_not_change_topology():
    a = circuit("R1 (a b) resistor r=1k\nC1 (b 0) capacitor c=1p")
    b = circuit("R1 (a b) resistor r=100k\nC1 (b 0) capacitor c=20p")
    assert retrieval.cosine(retrieval.topology_vector(a), retrieval.topology_vector(b)) == pytest.approx(1)


def test_passive_pin_order_is_irrelevant_but_mos_terminals_are_not():
    a = circuit("R1 (in mid) resistor\nC1 (mid 0) capacitor", "in 0")
    b = circuit("R1 (mid in) resistor\nC1 (0 mid) capacitor", "in 0")
    assert retrieval.cosine(retrieval.topology_vector(a), retrieval.topology_vector(b)) == pytest.approx(1)
    mos = circuit("M1 (out in 0 0) nmos4", "out in 0")
    swapped = circuit("M1 (in out 0 0) nmos4", "out in 0")
    assert retrieval.cosine(retrieval.topology_vector(mos), retrieval.topology_vector(swapped)) < 0.99


def test_exact_structural_comparison_prefers_same_connections():
    a = retrieval.topology_profile(circuit(PAIR))
    same = retrieval.topology_profile(circuit(PAIR.replace("M1", "MX")))
    changed = retrieval.topology_profile(circuit(SEPARATE))
    assert retrieval.structural_similarity(a, same) == pytest.approx(1)
    assert 0 <= retrieval.structural_similarity(a, changed) < 0.8


def test_passive_only_and_ported_circuits_remain_finite():
    for record in (circuit("R1 (a b) resistor"), circuit(PAIR, "in1 in2 a b")):
        vector = retrieval.topology_vector(record)
        assert vector.shape == (768,) and vector.dtype == np.float32
        assert np.isfinite(vector).all() and np.linalg.norm(vector) == pytest.approx(1)


def test_unreferenced_port_is_counted_without_breaking_the_profile():
    from circuit_ingest.models import NetRecord, PortRecord
    record = circuit("R1 (a b) resistor")
    record.nets.append(NetRecord(id="unused", name="unused", is_external=True,
                                 port_ordinal=0, degree_by_terminal=0))
    record.ports.append(PortRecord(name="unused", ordinal=0, net_id="unused", referenced_by_device=False))
    record.statistics.net_count += 1
    record.statistics.external_port_count += 1
    record.statistics.unreferenced_port_count += 1
    profile = retrieval.topology_profile(record)
    assert profile["motifs"]["unused_port"] == 1
    assert np.isfinite(retrieval.topology_vector(record)).all()


def test_grouped_motif_counts_handle_repeated_gates_drains_and_sources():
    record = circuit("M1 (g g tail 0) nmos4\nM2 (a g tail 0) nmos4\nM3 (a g tail 0) nmos4\nM4 (b h tail 0) nmos4")
    profile = retrieval.topology_profile(record)
    assert profile["motifs"]["nmos:shared_source_pair"] == 3
    assert profile["motifs"]["nmos:shared_gate_pair"] == 2
    assert profile["motifs"]["nmos:mirror_candidate_pair"] == 2


def test_search_rescores_compact_vector_collision_with_full_patterns(tmp_path):
    from circuit_workbench.catalog import Catalog
    db = Catalog(tmp_path / "state", tmp_path / "empty", tmp_path / "upstream")
    records = [circuit(PAIR), circuit(SEPARATE), circuit(PAIR.replace("M1", "MX"))]
    records[0].circuit_id = "uploaded:ref"
    records[1].circuit_id = "uploaded:a-wrong"
    records[2].circuit_id = "uploaded:z-right"
    ids = [db.add_upload(record, record.source.primary_sha256, {"description": "fixture"}) for record in records]
    # Simulate an extreme compact-vector collision, without mocking retrieval.
    same_vector = retrieval.topology_vector(records[0]).tobytes()
    with db.connect() as conn:
        for identifier in ids:
            conn.execute("INSERT INTO vectors(id,topology,descriptor_version,revision) VALUES(?,?,?,0)",
                         (identifier, same_vector, retrieval.VERSION))
    result = retrieval.Retrieval(db).search(reference_id=ids[0], limit=2)
    assert result["items"][0]["id"] == ids[2]
    assert result["items"][0]["structural_score"] == pytest.approx(1)
    assert result["items"][1]["structural_score"] < 0.8
    assert result["reranked"] == 2
