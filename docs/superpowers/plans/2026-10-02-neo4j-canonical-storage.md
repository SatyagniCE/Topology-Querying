# Neo4j Canonical Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run local Neo4j and import the valid canonical AnalogGenie circuit records for device and net pattern queries, with corpus-level verification.

**Architecture:** A user-space Temurin 21 and Neo4j Community installation supplies a localhost database. A pure canonical-record projection produces Device/Net/Port nodes and terminal/port edges; a Python adapter consumes it and replaces each circuit-owned subgraph atomically. An audit command compares Cypher results to the current audit-report JSON and checks circuit 755/Q30 plus repeat-import counts.

**Tech Stack:** Python 3.11+, Pydantic 2, Neo4j Python driver 6, Cypher, Bash, Temurin 21, Neo4j Community 2026.09.0.

**Spec:** `docs/superpowers/specs/2026-10-02-neo4j-canonical-storage-design.md`

## Global Constraints

- Import only valid `CircuitRecord` files under `circuits/*.json`; preserve the complete record JSON on `Circuit`.
- Use `Circuit.id`, `Device.id`, `Net.id`, and derived `Port.id` as unique keys; create all four constraints before writes.
- Materialize `Circuit` ownership, directed `Device` → `Net` terminal connections, and separate `Port` → `Net` mappings, including zero-degree ports.
- Use one pure projection for Device/Net/Port properties and `CONNECTED_TO`/`MAPS_TO` edges so another graph backend can consume the same topology.
- Keep `port_ordinal` off the materialized `Net`; the full canonical JSON still retains it.
- Install JRE and Neo4j only in user-owned paths, bind localhost, and keep credentials out of Git.
- Read corpus-wide expected values dynamically from `analoggenie-audit-report.json`; never embed its counts in code or scripts.
- Preserve existing uncommitted parser and graph work; partial-stage shared files such as `README.md` and `pyproject.toml` and inspect the staged diff before each commit.

## File map

- `scripts/neo4j-local.sh`: install/start/stop/status for pinned local runtime; checksum verification and process-scoped `JAVA_HOME`.
- `src/circuit_ingest/canonical_graph.py`: validated, database-independent projection into typed node and edge records.
- `src/circuit_ingest/neo4j_store.py`: schema, validated transactional circuit replacement, and connection configuration.
- `src/circuit_ingest/neo4j_cli.py`: `circuit-neo4j import` and `audit` command entry point.
- `src/circuit_ingest/neo4j_audit.py`: database count/type/relationship/spot-check comparison against a supplied report.
- `pyproject.toml`: optional Neo4j driver dependency and `circuit-neo4j` script.
- `tests/integration/test_neo4j_store.py`: live fixture tests for graph mapping, rollback, and query results.
- `tests/unit/test_canonical_graph.py`: projection tests, including parallel terminal contacts.
- `tests/unit/test_neo4j_audit.py`: report parsing and dynamic expectation tests.
- `README.md`: local setup, corpus load, pattern queries, audit, and repeat-import instructions.

## Review Focus

- A JSON record with an unknown `net_id` must fail before changing the database; test in Task 2.
- A Port with no device connections must still map to its Net; test in Task 2.
- Duplicate source instance names must retain separate Device nodes by stable IDs; test in Task 2.
- A write failure after deletion must restore the previous circuit subgraph; test in Task 2.
- A changed audit-report count must change the expected result without editing code; test in Task 4.

---

### Task 1: User-space Neo4j runtime

**Files:** Create `scripts/neo4j-local.sh`; modify `README.md`.

**Interfaces:** Produce `scripts/neo4j-local.sh install|start|stop|status`, a localhost Bolt URI, and a `0600` user-owned environment file containing `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE`.

- [ ] **Step 1: Write runtime smoke checks** in the script's documented verification commands: `bash -n scripts/neo4j-local.sh`; after install, `... status`, `~/.local/opt/temurin-21/bin/java -version`, and `curl -I http://localhost:7474`. Expected: syntax success, Java 21, running server, HTTP response.
- [ ] **Step 2: Implement `install|start|stop|status`** in `scripts/neo4j-local.sh`. Download pinned Temurin 21 Linux x64 JRE plus vendor SHA-256 manifest and pinned Neo4j Community 2026.09.0 tarball; verify archive hashes before extraction; install below `~/.local/opt`; set `JAVA_HOME`/`PATH` only when invoking Neo4j; bind HTTP/Bolt to `127.0.0.1`; place data/logs in user-owned locations; set initial password before first start; reject an existing nonempty install rather than overwrite it.
- [ ] **Step 3: Run the smoke checks** after installation. Expected: all checks pass and `java -version` outside the script still reports the machine default Java 8.
- [ ] **Step 4: Document start, stop, URI, credentials, and local-data paths** in `README.md`; run `bash -n scripts/neo4j-local.sh` again. Expected: success.
- [ ] **Step 5: Commit only the runtime script and README change** with `feat: add user-space Neo4j runtime setup`.

### Task 2: Transactional canonical-record mapping

**Files:** Create `src/circuit_ingest/canonical_graph.py`, `src/circuit_ingest/neo4j_store.py`, `tests/unit/test_canonical_graph.py`, `tests/integration/test_neo4j_store.py`; modify `pyproject.toml`.

**Interfaces:** Produce `project_circuit(record: CircuitRecord) -> CircuitProjection` with ordered `NodeSpec(kind, id, properties)` and `EdgeSpec(kind, source, target, properties)` tuples for Device/Net/Port and `CONNECTED_TO`/`MAPS_TO`. Also produce `create_constraints(driver: Driver, database: str) -> None` and `replace_circuit(driver: Driver, database: str, record: CircuitRecord) -> None`. Use a private `_replace_circuit_tx(tx: ManagedTransaction, projection: CircuitProjection) -> None` so deletion and creation share one managed write transaction.

- [ ] **Step 1: Write failing projection and live fixture tests** named `test_parallel_terminals_survive_projection`, `test_terminal_direction_and_ordinal`, `test_zero_degree_port_maps_to_net`, `test_duplicate_source_names_keep_distinct_ids`, `test_unknown_net_is_rejected_without_write`, `test_failed_transaction_preserves_previous_circuit`, and `test_device_net_pattern_returns_circuit`. Assert exact labels, relationship directions, `terminal` and `terminal_ordinal`, unique IDs, and unchanged prior graph after an injected failure following deletion. Run `pytest tests/unit/test_canonical_graph.py tests/integration/test_neo4j_store.py -q`; expected: failure because modules are missing.
- [ ] **Step 2: Implement projection, schema, and replacement**. `project_circuit` validates via `validate_circuit(record)`, derives Port IDs with six-digit ordinals, keeps every terminal edge (including parallel edges to one Net), and omits `port_ordinal` from Net properties. In `neo4j_store.py`, create the four named uniqueness constraints, delete only nodes owned by the target Circuit, and recreate Circuit plus projected nodes, ownership, and projected edges in one managed write transaction. Store the complete record as deterministic JSON on Circuit.
- [ ] **Step 3: Run projection and six live fixture tests**. Expected: pass against the local database. Check that the rollback test truly raises after the old subgraph is deleted within the transaction.
- [ ] **Step 4: Add `neo4j>=6,<7` under a `neo4j` optional dependency** in `pyproject.toml`; run `python -m pytest tests/integration/test_neo4j_store.py -q`. Expected: pass.
- [ ] **Step 5: Commit only projection, adapter, their tests, and dependency change** with `feat: store canonical circuits in Neo4j`.

### Task 3: Import command and pattern-query examples

**Files:** Create `src/circuit_ingest/neo4j_cli.py`; modify `pyproject.toml`, `README.md`; extend `tests/integration/test_neo4j_store.py`.

**Interfaces:** Produce `circuit-neo4j import --input-dir PATH` and `run(argv: list[str] | None = None) -> int`. Read connection fields from environment; call Task 2's `create_constraints` and `replace_circuit`.

- [ ] **Step 1: Write failing CLI integration tests** for one valid JSON file, one malformed/invalid file, and an inaccessible database. Assert nonzero exit on any failed record, a per-circuit error, and summary counts; assert no partial graph for the rejected file. Run the targeted tests; expected: failure because CLI is missing.
- [ ] **Step 2: Implement `run` and `main`** in `neo4j_cli.py`, add the `circuit-neo4j` script entry, verify connectivity before import, sort `circuits/*.json` deterministically, parse via `CircuitRecord.model_validate_json`, and return nonzero if any file fails.
- [ ] **Step 3: Run targeted CLI tests**. Expected: pass. Add two runnable README Cypher examples: device type on a named Net returning circuit IDs, and a zero-degree Port mapped to its Net.
- [ ] **Step 4: Commit only CLI, tests, project metadata, and README changes** with `feat: import canonical circuits from JSON`.

### Task 4: Corpus audit and spot-check

**Files:** Create `src/circuit_ingest/neo4j_audit.py`, `tests/unit/test_neo4j_audit.py`; extend `src/circuit_ingest/neo4j_cli.py` and `tests/integration/test_neo4j_store.py`; modify `README.md`.

**Interfaces:** Produce `audit_database(driver: Driver, database: str, report_path: Path) -> list[str]` returning mismatch messages, and `circuit-neo4j audit --report PATH` exiting nonzero when the list is nonempty.

- [ ] **Step 1: Write failing audit tests**. Build a temporary report with deliberately changed totals and assert expected counts follow that file; assert mismatch messages for each label, `CONNECTED_TO`, `MAPS_TO`, per-type Device counts, orphan/cross-circuit relationships, and incorrect Port mapping. For the live spot-check test, parse and import the checked-in circuit 755 source into the test database, then assert the Q30/substrate-to-Net-0 query yields exactly one row with terminal ordinal `3`. Run targeted tests; expected: failure because audit functions are missing.
- [ ] **Step 2: Implement `audit_database`**. Read Circuit expectation from `status_counts.valid + status_counts.valid_with_warnings`; Device, Net, Port, and connection expectations from `totals`; Device type expectations from `canonical_device_type_counts`. Compare live Cypher results, ensure every Port maps to exactly one Net and every connection stays within one Circuit, then execute the exact Q30 spot-check from the spec. Do not embed corpus-wide count literals.
- [ ] **Step 3: Add `audit --report` to CLI** and run `pytest tests/unit/test_neo4j_audit.py tests/integration/test_neo4j_store.py -q`. Expected: pass, including the live spot-check after its test fixture imports circuit 755.
- [ ] **Step 4: Document the audit command and interpretation of nonzero exit** in `README.md`; commit only audit module, tests, CLI, and README changes with `feat: audit Neo4j against canonical corpus report`.

### Task 5: Full corpus load and idempotency evidence

**Files:** Modify `README.md` only if operating commands need correction; write generated corpus JSON, database data, and audit output outside Git.

**Interfaces:** Consume `circuit-ingest parse-analoggenie`, `circuit-neo4j import`, and `circuit-neo4j audit`.

- [ ] **Step 1: Generate the canonical JSON corpus** using the pinned local `AnalogGenie/Dataset` source and strict mode into a user-owned output directory. Expected: valid files plus an audit report; no quarantined or failed records unless the source has changed.
- [ ] **Step 2: Run the first full import and audit** using `analoggenie-audit-report.json` as the expected-value source; confirm it matches the freshly generated report, then save node-label and relationship-type count output. Expected: zero audit mismatches, including per-type counts and circuit 755/Q30 substrate → Net `0`.
- [ ] **Step 3: Run the same import a second time**. Query and compare every node-label and relationship-type count with Step 2. Expected: exact equality, then `circuit-neo4j audit` still exits zero.
- [ ] **Step 4: Run `python -m pytest` and `git diff --check`**. Expected: all tests pass and no whitespace errors. Report the install path, local URI, corpus-audit result, and second-import count equality to the user.
- [ ] **Step 5: Commit any corrected documentation only**; do not commit generated corpus, database files, logs, or credentials.
