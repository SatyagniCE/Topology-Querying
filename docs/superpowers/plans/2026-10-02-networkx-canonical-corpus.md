# NetworkX Canonical Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, serialize, and verify one NetworkX graph per valid canonical AnalogGenie circuit without requiring Neo4j.

**Architecture:** Neo4j Task 2 implements the pure `circuit_ingest.canonical_graph.project_circuit` projection first. The NetworkX builder consumes that exact projection, stores Circuit metadata on each graph, and writes one pickle plus a manifest entry per circuit. Backend parity tests compare both materializations to the projection; corpus verification reads its expectations from the audit report.

**Tech Stack:** Python 3.11+, Pydantic 2, NetworkX 3, pytest, pickle.

**Spec:** `docs/superpowers/specs/2026-10-02-networkx-canonical-corpus-design.md`

## Global Constraints

- Source is validated `circuits/*.json`; each graph has exactly one `circuit_id` and is independent of Neo4j.
- Reuse canonical Device/Net IDs and the shared six-digit Port ID rule; never renumber nodes.
- Use `nx.MultiDiGraph` with directed `CONNECTED_TO` and `MAPS_TO` edges, preserving parallel terminal contacts and exact attributes.
- Read corpus-wide expectations dynamically from `analoggenie-audit-report.json`; compare normalized graph content, not pickle bytes.
- Pickle files are trusted local caches, written atomically; do not load unknown pickle files.
- Do not implement a second record-to-topology mapping. If Neo4j Task 2 has not finished, wait for `project_circuit` rather than creating a duplicate.
- Preserve existing uncommitted parser and graph changes; partial-stage shared files such as `README.md` and `pyproject.toml` before commits.

## File map

- `src/circuit_ingest/canonical_graph.py`: shared `project_circuit` from Neo4j Task 2; reused unchanged unless parity tests expose a defect.
- `src/circuit_ingest/networkx_graph.py`: one-record `MultiDiGraph` builder and normalized signature.
- `src/circuit_ingest/networkx_corpus.py`: atomic pickle writer, manifest, keyed loader/iterator, CLI, and corpus audit.
- `pyproject.toml`: `circuit-networkx` script entry; existing NetworkX dependency is reused.
- `tests/unit/test_networkx_graph.py`: graph mapping and pickle round trip.
- `tests/integration/test_backend_parity.py`: NetworkX and live Neo4j subgraph signatures against one projection.
- `tests/integration/test_networkx_corpus.py`: full-corpus counts, 755/Q30 check, and two-build determinism.
- `README.md`: build, load-by-ID, audit, and local-cache trust instructions.

## Review Focus

- Two terminals of one Device on one Net must remain two keyed directed edges; test in Task 1.
- A zero-degree external Net must remain reachable from its Port; test in Task 1.
- Duplicate source-instance names must never collapse nodes because IDs differ; test in Task 1.
- An invalid record must not leave a partial pickle or manifest entry; test in Task 2.
- A changed audit report must alter expected totals without code edits; test in Task 3.

---

### Task 1: Build one circuit graph from the shared projection

**Files:** Create `src/circuit_ingest/networkx_graph.py`, `tests/unit/test_networkx_graph.py`; reuse `src/circuit_ingest/canonical_graph.py` from Neo4j Task 2.

**Interfaces:** Consume `project_circuit(record: CircuitRecord) -> CircuitProjection`; produce `build_networkx_graph(record: CircuitRecord) -> nx.MultiDiGraph` and `graph_signature(graph: nx.MultiDiGraph) -> tuple`.

- [ ] **Step 1: Write failing fixture tests** `test_graph_matches_projection`, `test_parallel_contacts_keep_distinct_keys`, `test_zero_degree_port_maps_to_net`, and `test_duplicate_source_names_keep_global_ids`. Compare every projected node kind/property and edge endpoint/kind/property to the built graph; assert `graph.graph['record_json']` round-trips to the input record. Run `pytest tests/unit/test_networkx_graph.py -q`; expected: failure because builder is missing.
- [ ] **Step 2: Implement `build_networkx_graph` and `graph_signature`**. Add projected nodes by global ID and projected edges with `CONNECTED_TO:<terminal_ordinal>` or `MAPS_TO` keys; put `circuit_id`, `schema_version`, `dataset`, and deterministic full `record_json` on the graph. Sort signature components, including graph attributes, directed endpoints, keys, and properties.
- [ ] **Step 3: Run Task 1 tests and the existing projection unit tests**. Expected: all pass; no Neo4j connection is used.
- [ ] **Step 4: Commit only builder and unit tests** with `feat: build NetworkX graphs from canonical projection`.

### Task 2: Atomic corpus cache and keyed loading

**Files:** Create `src/circuit_ingest/networkx_corpus.py`; extend `tests/unit/test_networkx_graph.py`; modify `pyproject.toml`, `README.md`.

**Interfaces:** Produce `build_corpus(input_dir: Path, output_dir: Path) -> dict[str, str]`, `load_graph(output_dir: Path, circuit_id: str) -> nx.MultiDiGraph`, `iter_graphs(output_dir: Path) -> Iterator[tuple[str, nx.MultiDiGraph]]`, and `circuit-networkx build --input-dir PATH --output-dir PATH`.

- [ ] **Step 1: Write failing tests** for two JSON records yielding two keyed pickle files and manifest entries, a pickle round trip preserving edge keys/properties, load by `circuit_id`, iteration without merging, and invalid JSON leaving no partial file or manifest entry. Run targeted tests; expected: failure because corpus module is missing.
- [ ] **Step 2: Implement corpus writer and loader**. Validate each `CircuitRecord`, write each pickle via temporary file plus atomic replace, and write a manifest keyed by `circuit_id` with relative path and canonical-record SHA-256. Sort IDs, derive safe output names, and reject untrusted/missing manifest paths. Use highest pickle protocol; load only user-generated local files.
- [ ] **Step 3: Add CLI entry and README usage**. Run targeted tests and `python -m pytest`; expected: pass. Document the cache's trusted-input rule and that Neo4j is unnecessary.
- [ ] **Step 4: Commit only corpus module, tests, entry point, and README change** with `feat: cache canonical NetworkX corpus`.

### Task 3: Cross-backend parity and corpus audit

**Files:** Create `tests/integration/test_backend_parity.py`, `tests/integration/test_networkx_corpus.py`; extend `src/circuit_ingest/networkx_corpus.py` and `README.md`.

**Interfaces:** Produce `audit_corpus(output_dir: Path, report_path: Path) -> list[str]` and `circuit-networkx audit --output-dir PATH --report PATH`.

- [ ] **Step 1: Write and run parity tests**. For the same fixture projection, compare normalized NetworkX node/edge rows to `project_circuit`; query Neo4j's Device/Net/Port nodes and `CONNECTED_TO`/`MAPS_TO` edges for that circuit and compare their normalized rows to that same projection. Assert exact IDs, properties, direction, and multiplicity. Expected: pass if both completed adapters are correct; a failure is a concrete adapter defect to reproduce and fix before continuing.
- [ ] **Step 2: Write failing corpus-audit tests**. Supply a temporary audit report with changed totals and assert expectations change; compare graph count, Device/Net/Port totals, `CONNECTED_TO`/`MAPS_TO` totals, and canonical Device type counts. Add a test that graph `analoggenie:755` contains exactly one Q30 outgoing `substrate`/ordinal `3` edge to Net `0`. Run targeted tests; expected: failure before audit implementation.
- [ ] **Step 3: Implement `audit_corpus` and CLI `audit`**. Read expected counts from `status_counts`, `totals`, and `canonical_device_type_counts` at run time; stream graphs by ID, accumulate actual counts, and report every mismatch. Perform the Q30 check and exit nonzero on any mismatch.
- [ ] **Step 4: Run parity and audit tests**. Expected: all pass, including live Neo4j parity where its test fixture is installed; NetworkX corpus tests pass without Neo4j.
- [ ] **Step 5: Commit only audit, parity tests, and documentation changes** with `feat: audit NetworkX corpus and backend parity`.

### Task 4: Full rebuild determinism

**Files:** Modify `README.md` only if commands need correction; generated pickles and manifests stay outside Git.

**Interfaces:** Consume `circuit-networkx build`, `circuit-networkx audit`, and `graph_signature`.

- [ ] **Step 1: Build the full corpus into two fresh output directories** from the same `circuits/*.json`; expected: one manifest entry and one graph per valid circuit in each.
- [ ] **Step 2: Run `circuit-networkx audit` against the current `analoggenie-audit-report.json` for both outputs**. Expected: no count/type/edge mismatch and Q30 substrate → Net `0` passes.
- [ ] **Step 3: Compare every `circuit_id` and `graph_signature` between the two outputs**. Expected: exact equality across graph attributes, nodes, directed endpoints, edge keys, and edge attributes.
- [ ] **Step 4: Run `python -m pytest` and `git diff --check`**. Expected: all tests pass and no whitespace errors; report corpus totals and determinism evidence.
- [ ] **Step 5: Commit any corrected documentation only**; never commit pickle caches.
