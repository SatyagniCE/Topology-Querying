"""Training-free circuit features. Motifs are wiring evidence, not device roles."""
from collections import Counter, defaultdict
import hashlib
import math

import numpy as np

VERSION = "terminal-wl-v3"
TYPES = ["nmos", "pmos", "npn", "pnp", "resistor", "capacitor", "inductor", "diode", "voltage_source", "current_source", "xor", "pfd", "inverter", "transmission_gate"]
ROUND_WEIGHTS = (0.25, 0.65, 0.9, 0.9, 0.65)
BLOCK_WEIGHTS = (0.65, 1.0, 0.9)
MOS_PATTERNS = ("gate_drain_tie", "gate_source_tie", "source_bulk_tie", "shared_source_pair",
                "shared_gate_pair", "mirror_candidate_pair", "drain_source_stack", "gate_driven_by_drain")
MOTIFS = tuple(f"{kind}:{pattern}" for kind in ("nmos", "pmos") for pattern in MOS_PATTERNS) + (
    "complementary_shared_drain", "complementary_shared_gate", "series_rc", "capacitor_to_rail",
    "capacitor_between_nonrails", "capacitor_gate_drain_bridge", "gate_only_net", "nonrail_components",
    "unused_port", "unknown_port_role", "input_gate_connection", "output_drain_connection")


def port_role(name):
    name = name.upper()
    if name in {"VDD", "VCC", "VDD!", "VCC!"}:
        return "supply"
    if name in {"0", "GND", "VSS", "VEE", "GND!", "VSS!"}:
        return "ground"
    if "OUT" in name:
        return "output"
    if "IN" in name:
        return "input"
    if name.startswith(("VB", "IB", "BIAS", "VREF", "IREF")):
        return "bias"
    if name.startswith(("CLK", "PHI", "CK", "CLOCK")):
        return "clock"
    return "external"


def unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def topology_profile(record):
    """Uncompressed WL features plus conservative, terminal-specific motif counts.

    No arbitrary identifiers or component values enter the features. R/C/L pins
    are unordered; transistor and diode terminals remain distinct. Rail labels
    are held constant to prevent supplies spreading global circuit identity.
    """
    labels, adjacency, roles = {}, {}, {}
    for net in record.nets:
        role = port_role(net.name)
        if not net.is_external and role not in {"supply", "ground"}:
            role = "internal"
        roles[net.id] = role
        labels[net.id] = "net:" + role
        adjacency[net.id] = []
    rails = {key for key, role in roles.items() if role in {"supply", "ground"}}
    devices = {d.id: d for d in record.devices}
    terminals = {}
    for device in record.devices:
        labels[device.id] = "device:" + device.canonical_type
        adjacency[device.id] = []
        terminals[device.id] = {c.terminal: c.net_id for c in device.connections}
        for connection in device.connections:
            terminal = "pin" if device.canonical_type in {"resistor", "capacitor", "inductor"} else connection.terminal
            adjacency[device.id].append((terminal, connection.net_id))
            adjacency[connection.net_id].append((terminal, device.id))
    neighborhoods = []
    for level in range(len(ROUND_WEIGHTS)):
        neighborhoods.append(Counter(label for node, label in labels.items() if node not in rails))
        if level == len(ROUND_WEIGHTS) - 1:
            break
        labels = {node: label if node in rails else hashlib.blake2b(
            (label + "|" + "|".join(sorted(t + ":" + labels[n] for t, n in adjacency[node]))).encode(),
            digest_size=16).hexdigest() for node, label in labels.items()}

    motifs = Counter()
    # Grouping by gate/source avoids a quadratic scan across unrelated devices.
    mos = {key: device for key, device in devices.items()
           if device.canonical_type in {"nmos", "pmos"}
           and {"gate", "drain", "source"} <= terminals[key].keys()
           and terminals[key]["drain"] != terminals[key]["source"]}
    gates, sources, drains = defaultdict(list), defaultdict(list), defaultdict(list)
    for key, device in mos.items():
        t, kind = terminals[key], device.canonical_type
        gates[t["gate"]].append(key)
        sources[t["source"]].append(key)
        drains[t["drain"]].append(key)
        for pattern, tied in (("gate_drain_tie", t["gate"] == t["drain"]),
                              ("gate_source_tie", t["gate"] == t["source"]),
                              ("source_bulk_tie", t["source"] == t.get("bulk"))):
            motifs[f"{kind}:{pattern}"] += int(tied)
        motifs["input_gate_connection"] += int(roles[t["gate"]] == "input")
        motifs["output_drain_connection"] += int(roles[t["drain"]] == "output")
    # Count cross-products and use inclusion/exclusion, rather than enumerating
    # O(n²) transistor pairs on high-fanout gates/sources.
    pairs = lambda n: n * (n - 1) // 2
    for net, members in sources.items():
        if net in rails:
            continue  # Sharing ground is not a differential-pair-like feature.
        drain_counts = Counter(mos[key].canonical_type for key in drains.get(net, ()))
        for kind in ("nmos", "pmos"):
            group = [terminals[key] for key in members if mos[key].canonical_type == kind]
            gate_counts = Counter(t["gate"] for t in group)
            end_counts = Counter(t["drain"] for t in group)
            joint_counts = Counter((t["gate"], t["drain"]) for t in group)
            motifs[f"{kind}:shared_source_pair"] += (pairs(len(group))
                - sum(pairs(n) for n in gate_counts.values())
                - sum(pairs(n) for n in end_counts.values())
                + sum(pairs(n) for n in joint_counts.values()))
            motifs[f"{kind}:drain_source_stack"] += len(group) * drain_counts[kind]
    for net, members in gates.items():
        if net in rails:
            continue
        kind_counts = Counter(mos[key].canonical_type for key in members)
        motifs["complementary_shared_gate"] += kind_counts["nmos"] * kind_counts["pmos"]
        active_drains = Counter(mos[key].canonical_type for key in drains.get(net, ())
                                if terminals[key]["gate"] != terminals[key]["drain"])
        for kind in ("nmos", "pmos"):
            group = [terminals[key] for key in members if mos[key].canonical_type == kind]
            end_counts = Counter(t["drain"] for t in group)
            motifs[f"{kind}:shared_gate_pair"] += pairs(len(group)) - sum(pairs(n) for n in end_counts.values())
            tied = Counter(t["source"] for t in group if t["drain"] == net)
            untied = Counter(t["source"] for t in group if t["drain"] != net)
            motifs[f"{kind}:mirror_candidate_pair"] += sum(n * untied[source] for source, n in tied.items())
            motifs[f"{kind}:gate_driven_by_drain"] += len(group) * active_drains[kind]
    for net, members in drains.items():
        if net not in rails:
            motifs["complementary_shared_drain"] += sum(mos[key].canonical_type == "nmos" for key in members) * sum(mos[key].canonical_type == "pmos" for key in members)
    for net, neighbors in adjacency.items():
        if net not in roles or net in rails:
            continue
        if neighbors and all(terminal == "gate" for terminal, _ in neighbors):
            motifs["gate_only_net"] += 1
        if len(neighbors) == 2:
            a, b = (devices[key] for _, key in neighbors)
            if {a.canonical_type, b.canonical_type} == {"resistor", "capacitor"}:
                # Parallel RC shares two endpoints and is not a series branch.
                if {c.net_id for c in a.connections} & {c.net_id for c in b.connections} == {net}:
                    motifs["series_rc"] += 1
    gate_drain_ends = Counter(frozenset((terminals[key]["gate"], terminals[key]["drain"])) for key in mos)
    for key, device in devices.items():
        ends = {c.net_id for c in device.connections}
        if device.canonical_type == "capacitor" and len(ends) == 2:
            motifs["capacitor_to_rail" if ends & rails else "capacitor_between_nonrails"] += 1
            motifs["capacitor_gate_drain_bridge"] += gate_drain_ends[frozenset(ends)]
    pending = set(adjacency) - rails
    while pending:
        motifs["nonrail_components"] += 1
        stack = [pending.pop()]
        while stack:
            for _, other in adjacency[stack.pop()]:
                if other in pending:
                    pending.remove(other)
                    stack.append(other)
    motifs["unused_port"] = sum(not port.referenced_by_device for port in record.ports)
    motifs["unknown_port_role"] = sum(port_role(port.name) == "external" for port in record.ports)

    counts = np.zeros(32, dtype=np.float32)
    for i, kind in enumerate(TYPES):
        counts[i] = math.sqrt(record.statistics.device_type_counts.get(kind, 0))
    counts[20] = math.log1p(record.statistics.device_count)
    counts[21] = math.log1p(record.statistics.net_count)
    for offset, kind in ((14, "resistor"), (17, "capacitor")):
        counts[offset + min(2, record.statistics.device_type_counts.get(kind, 0))] = 2
    ports = np.zeros(32, dtype=np.float32)
    role_counts = Counter(port_role(port.name) for port in record.ports)
    for i, role in enumerate(("supply", "ground", "input", "output", "bias", "clock", "external")):
        ports[i] = math.sqrt(role_counts[role])
    for offset, role in ((8, "input"), (14, "output")):
        ports[offset + min(5, role_counts[role])] = 2
    motif_vector = np.zeros(64, dtype=np.float32)
    for i, motif in enumerate(MOTIFS):
        motif_vector[i] = math.sqrt(motifs[motif])
        motif_vector[32+i] = min(3, motifs[motif])
    return {"neighborhoods": tuple(neighborhoods), "motifs": motifs,
            "blocks": (unit(counts), unit(ports), unit(motif_vector))}


def topology_vector(record, *, profile=None):
    profile = topology_profile(record) if profile is None else profile
    # Share a larger bucket space rather than 128 buckets per depth. Depth is
    # part of the feature key, so equal labels at different depths stay distinct.
    # Normalize the WL block once: deeper levels must not outweigh all explicit
    # I/O and motif evidence merely because there are more refinement rounds.
    vector = np.zeros(640, dtype=np.float32)
    for level, (weight, features) in enumerate(zip(ROUND_WEIGHTS, profile["neighborhoods"], strict=True)):
        total = sum(features.values())
        for label, count in features.items():
            digest = hashlib.blake2b(f"{level}:{label}".encode(), digest_size=8).digest()
            vector[int.from_bytes(digest[:4]) % len(vector)] += (1 if digest[4] % 2 else -1) * weight * math.sqrt(count / total)
    return unit(np.concatenate([weight * block for weight, block in zip(BLOCK_WEIGHTS, profile["blocks"], strict=True)] + [unit(vector)]))


def structural_similarity(a, b):
    """Compare full pattern labels, avoiding collisions in the compact vector.

    Still a local-pattern comparison, not an isomorphism or electrical proof.
    """
    dot = norm_a = norm_b = 0.0
    for weight, av, bv in zip(BLOCK_WEIGHTS, a["blocks"], b["blocks"], strict=True):
        dot += weight**2 * float(av @ bv)
        norm_a += weight**2 * float(av @ av)
        norm_b += weight**2 * float(bv @ bv)
    wl_dot = wl_a = wl_b = 0.0
    for weight, ac, bc in zip(ROUND_WEIGHTS, a["neighborhoods"], b["neighborhoods"], strict=True):
        an, bn = sum(ac.values()), sum(bc.values())
        if an and bn:
            wl_dot += weight**2 * sum(math.sqrt(count * bc.get(label, 0)) for label, count in ac.items()) / math.sqrt(an * bn)
        wl_a += weight**2 * bool(an)
        wl_b += weight**2 * bool(bn)
    if wl_a and wl_b:
        dot += wl_dot / math.sqrt(wl_a * wl_b)
    norm_a += bool(wl_a)
    norm_b += bool(wl_b)
    return float(np.clip(dot / math.sqrt(norm_a * norm_b), 0, 1)) if norm_a and norm_b else 0.0
