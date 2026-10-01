# NetworkX Canonical Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, cache, and verify one NetworkX graph per valid canonical AnalogGenie circuit without requiring Neo4j for graph construction or use.

**Architecture:** The merged Neo4j implementation already provides `circuit_ingest.canonical_graph.project_circuit`; NetworkX reuses it unchanged as the sole canonical-record-to-topology transformation. Each validated `CircuitRecord` becomes one `nx.MultiDiGraph`, keyed by `circuit_id`, with Circuit metadata on the graph and the projected Device/Net/Port topology inside it. A corpus command writes atomic local pickle caches and a keyed manifest; parity and audit tests compare both backends against the shared projection and the generated parser report.

**Tech Stack:** Python 3.11+, Pydantic 2, NetworkX 3, Neo4j Python driver 6 for optional live parity tests, pytest, pickle.

**Spec:** `docs/superpowers/specs/2026-10-02-networkx-canonical-corpus-design.md`

## Global Constraints

- Consume only validated `CircuitRecord` JSON from `circuits/*.json`; do not parse AnalogGenie source or add a second topology transformation.
- Reuse merged `project_circuit(record: CircuitRecord) -> CircuitProjection` from `src/circuit_ingest/canonical_graph.py`; Neo4j already calls it. Modify it only if a parity test demonstrates a defect, with a regression test for both consumers.
- Make one `nx.MultiDiGraph` per `circuit_id`; never merge circuits or share nets between graphs.
- Use exact projected Device and Net IDs and `<circuit_id>:port:<six-digit ordinal>` Port IDs. Nodes carry `id`, `kind`, and exactly the projected Neo4j properties; edges carry `kind` and exactly the projected relationship properties.
- Direct `CONNECTED_TO` from Device to Net and `MAPS_TO` from Port to Net. Use `CONNECTED_TO:<terminal_ordinal>` and `MAPS_TO` as edge keys; keep parallel terminal contacts separate.
- Keep graph attributes `circuit_id`, `dataset`, `schema_version`, and the deterministic complete `record_json`. The canonical JSON retains `Net.port_ordinal`; materialized Net nodes omit it in both backends.
- Use pickle only for trusted, locally generated caches. Do not add GraphML or another export; canonical JSON is the portable source.
- Derive all corpus-wide expected counts and type counts at verification time from the generated `output/analoggenie/audit-report.json` (or a supplied report path). Never embed corpus totals in code, scripts, or tests.
- Keep generated pickles, manifests, and corpus JSON outside Git; the current `.gitignore` already excludes `output/`.

## File map

- `src/circuit_ingest/canonical_graph.py`: existing shared projection; reuse without a second mapper.
- `src/circuit_ingest/networkx_graph.py`: one-record builder and normalized graph signature.
- `src/circuit_ingest/networkx_corpus.py`: validated corpus build, atomic pickle and manifest writes, keyed loading, audit, and CLI.
- `pyproject.toml`: add `circuit-networkx` entry point; use existing NetworkX 3 dependency.
- `tests/__init__.py`, `tests/fixtures/__init__.py`, and `tests/fixtures/canonical_record.py`: reusable valid record fixture for both NetworkX and live parity tests.
- `tests/unit/test_networkx_graph.py`: exact projection mapping, directed/multiedge behavior, IDs, and signature tests.
- `tests/unit/test_networkx_corpus.py`: pickle round trip, keyed manifest/loading, invalid-input behavior, and dynamic report expectations.
- `tests/integration/test_backend_parity.py`: NetworkX and live Neo4j node/edge signatures against one `CircuitProjection`.
- `tests/integration/test_networkx_corpus.py`: full-corpus audit, native circuit-755 traversal, and two-build signature equality.
- `README.md`: build, load by ID, audit, trusted-cache rule, and Neo4j-independent usage.

## Review Focus

- Two terminals on the same Device→Net pair must be two directed edges with different ordinal keys; `test_parallel_contacts_keep_distinct_keys` in Task 1.
- An unreferenced Port and zero-degree Net must remain present and linked by `MAPS_TO`; `test_zero_degree_port_maps_to_net` in Task 1.
- Duplicate source-instance names must retain distinct canonical IDs; `test_duplicate_source_names_keep_global_ids` in Task 1.
- Invalid JSON must identify its file and leave neither a partial pickle nor a manifest entry; `test_invalid_input_leaves_no_cache` in Task 2.
- Changing only the supplied report must change audit expectations; `test_report_change_changes_expected_counts` in Task 3.

---

### Task 1: Build one circuit graph from the merged shared projection

**Files:** Create `src/circuit_ingest/networkx_graph.py`, `tests/__init__.py`, `tests/fixtures/__init__.py`, `tests/fixtures/canonical_record.py`, and `tests/unit/test_networkx_graph.py`. Read `src/circuit_ingest/canonical_graph.py`; do not duplicate it.

**Interfaces:** Consume `project_circuit(record: CircuitRecord) -> CircuitProjection`. Produce `build_networkx_graph(record: CircuitRecord) -> nx.MultiDiGraph` and `graph_signature(graph: nx.MultiDiGraph) -> tuple`.

- [ ] **Step 1: Write fixture and failing tests.** Make a valid record with two distinct Device IDs sharing `source_instance`, two terminal ordinals from one Device to one Net, and an unreferenced Port mapped to a zero-degree Net. In `test_graph_matches_projection`, assert graph attributes equal the projection metadata, `record_json` validates back to the original record, every projected node equals `{id, kind, **properties}`, and the directed keyed edge multiset equals every projected edge plus its `kind`. In `test_parallel_contacts_keep_distinct_keys`, assert exactly two Device→shared-Net edges with keys `CONNECTED_TO:0` and `CONNECTED_TO:1`, different `terminal` values, and no reverse edges. In `test_zero_degree_port_maps_to_net`, assert the Port→Net `MAPS_TO` edge exists and the Net has no incoming `CONNECTED_TO`. In `test_duplicate_source_names_keep_global_ids`, assert two nodes with the same source name retain separate projected IDs. In `test_graph_signature_detects_changes`, mutate one edge ordinal and one graph attribute in copies and assert both signatures differ. Run `.venv/bin/python -m pytest tests/unit/test_networkx_graph.py -q`. **Expected:** collection fails because `networkx_graph` does not exist; no test passes spuriously.
- [ ] **Step 2: Implement the builder and signature.** Add nodes by `NodeSpec.id` with `id`, `kind`, and `NodeSpec.properties`; add directed edges by `EdgeSpec.source`/`target` with the specified keys, `kind`, and `EdgeSpec.properties`. Put exactly the four projection metadata fields on `graph.graph`. Normalize sorted graph attributes, node IDs/attributes, and directed `(source, target, key, attributes)` rows into a comparable tuple; reject a graph missing the required metadata or edge kind. **Expected:** no record-to-topology decisions occur outside `project_circuit`.
- [ ] **Step 3: Run `.venv/bin/python -m pytest tests/unit/test_networkx_graph.py tests/unit/test_canonical_graph.py -q` and `.venv/bin/python -m pytest -q`.** **Expected:** all Task 1 assertions and the full existing suite pass; the targeted graph tests use no Neo4j connection, and the graph signature changes for either metadata or edge changes.
- [ ] **Step 4: Commit only Task 1 files** with `feat: build NetworkX graphs from canonical projection`. **Expected:** commit contains builder, fixture, and tests, with no corpus caches.

### Task 2: Atomic pickle corpus and keyed loading

**Files:** Create `src/circuit_ingest/networkx_corpus.py` and `tests/unit/test_networkx_corpus.py`; modify `pyproject.toml` and `README.md`.

**Interfaces:** Produce `build_corpus(input_dir: Path, output_dir: Path) -> dict[str, str]` (circuit ID to relative pickle path), `load_graph(output_dir: Path, circuit_id: str) -> nx.MultiDiGraph`, `iter_graphs(output_dir: Path) -> Iterator[tuple[str, nx.MultiDiGraph]]`, and `circuit-networkx build --input-dir PATH --output-dir PATH`.

- [ ] **Step 1: Write failing cache tests.** `test_two_circuits_have_separate_keyed_pickles` asserts two records create two manifest keys, each entry contains the SHA-256 of its graph's `record_json`, and the distinct files contain no merged graph. `test_pickle_round_trip_preserves_signature` asserts loaded type is `MultiDiGraph` and `graph_signature`, edge keys, node attributes, and `record_json` equal the source graph. `test_load_by_id_and_sorted_iteration` asserts exact requested ID, sorted iteration, and rejection of unknown IDs. `test_invalid_input_leaves_no_cache` supplies malformed JSON after one valid file and asserts a file-named error, no pickle, and no manifest entry or partial cache in a fresh output directory. `test_manifest_rejects_unsafe_path` replaces a manifest path with `../outside.pkl` and then with a symlink to an outside file; both must fail before unpickling. Run `.venv/bin/python -m pytest tests/unit/test_networkx_corpus.py -q`. **Expected:** collection fails because `networkx_corpus` does not exist.
- [ ] **Step 2: Implement build and loading.** Prevalidate all sorted `circuits/*.json` with `CircuitRecord.model_validate_json` and `project_circuit` before creating output; reject a nonempty output directory and duplicate `circuit_id`. Write each graph pickle with highest protocol to a same-directory temporary file, `fsync`, and atomic replace. Use `graphs/<sha256(circuit_id)>.pkl`; write `manifest.json` atomically, keyed by circuit ID with relative path and SHA-256 of deterministic `record_json`. On load, require that exact derived path under the output directory, reject symlinks, require a matching graph `circuit_id` and `nx.MultiDiGraph`, and iterate sorted manifest IDs. **Expected:** invalid input cannot publish a manifest or pickle, and a caller can load one graph without loading the corpus.
- [ ] **Step 3: Add the `circuit-networkx` script and `build` CLI, then document one-circuit loading and trusted local pickle use.** Run `.venv/bin/python -m pytest tests/unit/test_networkx_corpus.py -q`, `.venv/bin/circuit-networkx --help`, and `.venv/bin/python -m pytest -q`. **Expected:** cache tests and the full suite pass; CLI lists `build`; usage requires no Neo4j variables or live database.
- [ ] **Step 4: Commit only cache module, tests, entry point, and README changes** with `feat: cache canonical NetworkX corpus`. **Expected:** generated pickle files and manifest are absent from the commit.

### Task 3: Cross-backend parity and report-driven audit

**Files:** Extend `src/circuit_ingest/networkx_corpus.py`; create `tests/integration/test_backend_parity.py` and `tests/integration/test_networkx_corpus.py`; extend `tests/unit/test_networkx_corpus.py` and `README.md`.

**Interfaces:** Produce `audit_corpus(output_dir: Path, report_path: Path) -> list[str]` and `circuit-networkx audit --output-dir PATH --report PATH`. Reuse Task 1's `graph_signature` and Task 2's keyed loader.

- [ ] **Step 1: Write and run cross-backend parity tests.** Build the same fixture record and projection; compare NetworkX's complete normalized Device/Net/Port nodes and `CONNECTED_TO`/`MAPS_TO` directed edge multiset with `NodeSpec`/`EdgeSpec`, including IDs, labels/kinds, all properties, terminal ordinals, and parallel multiplicity. In a live Neo4j integration test, use a unique test circuit ID, `replace_circuit`, query only its owned nodes and projected relationships, compare normalized Cypher rows to that same projection, and delete only that test circuit afterward. Run `NEO4J_TEST_REQUIRED=1 .venv/bin/python -m pytest tests/integration/test_backend_parity.py -q`. **Expected:** all parity assertions pass against the local database; any mismatch identifies a concrete backend defect to repair before Step 2.
- [ ] **Step 2: Write failing audit tests.** For a tiny generated corpus with a synthetic `analoggenie:755` Q30 substrate→Net-0 connection, assert `audit_corpus` returns `[]` against its matching temporary report; alter only report Device totals and then a canonical type count and assert exact mismatch messages. Assert graph count, Device/Net/Port node totals, `CONNECTED_TO`/`MAPS_TO` edge totals, and per-type Device counts are all compared. Add `test_755_q30_substrate_graph_traversal` that loads the actual generated graph `analoggenie:755` from `output/networkx-a` when `NETWORKX_CORPUS_TEST=1`, traverses Q30's outgoing edges, and requires exactly one `CONNECTED_TO` edge with `terminal='substrate'`, `terminal_ordinal=3`, and target Net `name='0'`. Add `test_full_corpus_matches_generated_report` and `test_two_builds_have_equal_signatures` under the same gate, using `output/networkx-a`, `output/networkx-b`, and `output/analoggenie/audit-report.json`. Run `.venv/bin/python -m pytest tests/unit/test_networkx_corpus.py tests/integration/test_networkx_corpus.py -q`. **Expected:** audit-related unit tests fail because `audit_corpus` is missing; full-corpus tests skip until the Task 4 builds exist.
- [ ] **Step 3: Implement `audit_corpus` and the CLI `audit` subcommand.** Stream one graph at a time; compare observed graph count with `status_counts.valid + status_counts.valid_with_warnings`, Device/Net/Port with `totals`, `CONNECTED_TO` with `totals.connections`, `MAPS_TO` with `totals.ports`, and canonical Device types with `canonical_device_type_counts`. Read the supplied report on every audit call. Traverse circuit 755 exactly as in Step 2, report every mismatch, and return nonzero from CLI if any mismatch exists. **Expected:** no corpus-wide number is embedded in source or test expectations.
- [ ] **Step 4: Run `NEO4J_TEST_REQUIRED=1 .venv/bin/python -m pytest tests/integration/test_backend_parity.py tests/unit/test_networkx_corpus.py tests/integration/test_networkx_corpus.py -q`, `.venv/bin/circuit-networkx --help`, and `.venv/bin/python -m pytest -q`.** **Expected:** all parity, fixture audit, spot-check, and full-suite tests pass; CLI lists both `build` and `audit` and exits nonzero for a deliberately changed report.
- [ ] **Step 5: Commit only audit, parity tests, and documentation changes** with `feat: audit NetworkX corpus and backend parity`. **Expected:** no generated corpus cache or Neo4j data is committed.

### Task 4: Full-corpus rebuild and deterministic signatures

**Files:** Modify `README.md` only if commands need correction. Generated output stays under ignored `output/`.

**Interfaces:** Consume `circuit-networkx build`, `circuit-networkx audit`, `iter_graphs`, and `graph_signature`.

- [ ] **Step 1: Run `git submodule update --init --recursive`; `.venv/bin/circuit-ingest parse-analoggenie --dataset-root AnalogGenie/Dataset --output-dir output/analoggenie --mode strict --source-commit "$(git -C AnalogGenie rev-parse HEAD)"`; then `.venv/bin/circuit-networkx build --input-dir output/analoggenie --output-dir output/networkx-a` and the same command with `output/networkx-b`.** **Expected:** each manifest has exactly the dynamically reported count of valid plus valid-with-warnings circuits, every key is a `circuit_id`, and neither build reads Neo4j connection settings.
- [ ] **Step 2: Run `circuit-networkx audit --output-dir output/networkx-a --report output/analoggenie/audit-report.json` and repeat for `output/networkx-b`.** **Expected:** both exit zero with zero graph/node/edge/type mismatches and the circuit-755 traversal passes; expected totals come only from that generated report.
- [ ] **Step 3: Run `NETWORKX_CORPUS_TEST=1 .venv/bin/python -m pytest tests/integration/test_networkx_corpus.py::test_two_builds_have_equal_signatures -q`.** The test iterates both corpora in sorted `circuit_id` order and compares `graph_signature` for every pair. **Expected:** identical ID sets and exactly zero differing signatures across graph metadata, node attributes, directed endpoints, edge keys, and edge attributes; do not compare pickle bytes.
- [ ] **Step 4: Run `NEO4J_TEST_REQUIRED=1 NEO4J_CORPUS_TEST=1 NETWORKX_CORPUS_TEST=1 .venv/bin/python -m pytest -q` with the local Neo4j fixture available, then `git diff --check`.** **Expected:** full suite passes with no skips of required NetworkX corpus, Neo4j corpus, or live parity checks and no whitespace errors. Record test count, corpus counts, audit outcomes, and signature comparison.
- [ ] **Step 5: Commit only any corrected documentation** if needed; leave the NetworkX branch unmerged for review. **Expected:** `git status --short` has no generated cache files, and `main` remains at its pre-NetworkX commit.
