# Research Workbench Implementation Plan

> **For agentic workers:** Execute inline in this chat. Use the authorized user
> scope, test critical data contracts first, and keep progress in this file.

**Goal:** A polished local circuit browser, upload flow and query workbench with
hybrid retrieval over the current corpus.

**Architecture:** FastAPI/static UI, SQLite local catalog, local pretrained text
vectors plus deterministic topology vectors; Neo4j provides live graphs and
read-only Cypher. Canonical records remain portable and unchanged.

**Tech Stack:** Python, FastAPI, SQLite, NumPy, FastEmbed, NetworkX, Neo4j, vis-network.

**Spec:** ../specs/2026-10-06-research-workbench-design.md

## Global constraints

- Local single user; listen on 127.0.0.1.
- Defer LLM metadata annotation and automatic text-to-Cypher.
- Preserve user edits; show synchronization/embedding errors explicitly.
- No numeric electrical claims without supplied evidence.
- Local artifacts under output/workbench; no secrets committed.

## Review focus

- Stale metadata edits must return a conflict rather than lose data.
- Unsupported uploaded model names and unresolved subcircuits must fail clearly.
- Backend outages must preserve local library/retrieval functionality.
- Queries returning nested nodes/paths must still produce usable table/graph links.
- Rapid UI navigation must not render stale detail responses over newer selections.

## Tasks and progress

- [x] Catalog and upload: `src/circuit_workbench/catalog.py`, `uploads.py`,
  `settings.py`; tests in `tests/unit/test_workbench.py`. SQLite revisioned metadata,
  raw source references, safe asset lookup, deterministic upload validation.
- [x] Retrieval: `retrieval.py`; tests for label invariance, port differences,
  self-match exclusion and edit invalidation. Persistent local vectors, exact
  cosine and reciprocal rank fusion. One local FastEmbed model cache.
- [x] Neo4j and API: `neo4j.py`, `app.py`, `cli.py`; API tests for actual persistence,
  image serving, query validation and upload errors. Durable sync state; vector
  indexes; typed result serialization. Start command and optional dependencies.
- [x] UI: `static/index.html`, `static/app.css`, `static/app.js`; library,
  inspector, live graph, schematic zoom, netlist copy/download, metadata editor,
  Cypher results/history/schema, similarity results and upload preview.
- [x] Verify: corpus bootstrap/model indexing, live Neo4j tests, full pytest,
  browser researcher workflow, desktop/mobile screenshots and iterative fixes.
- [x] Handoff: README/start script, leave application running with verified URL,
  report limitations and metadata enrichment recommendation.

Ruling: use the existing clean checkout on a new codex branch so the running local
app and assets remain in the directory the user knows; no external deployment.
Ruling: user authorized continued build after choosing local single user and
deferring enrichment. Proceed without repeated design permission gates.

## Verified outcome

- 137 tests passed; 14 existing environment-gated integration tests skipped.
- Live smoke checks passed on 3,351 indexed records (3,350 original + one demo).
- NetworkX/Neo4j parity for 1004: 40 nodes, 68 edges. Pending sync: zero.
- Browser exercised valid/invalid uploads, user edit/save/refresh, unsaved cancel,
  all Cypher examples, graph results, hybrid search and desktop/narrow layouts.
- Read-only review findings fixed: duplicate source IDs (including no-space typed
  syntax), SPICE casing, DC waveform rejection, revision-safe vector/sync writes,
  asynchronous form isolation, stale graph data and concurrent hash deduplication.
- Screenshots saved under output/workbench/screenshots; guide at docs/workbench.md.
- Local application running on 127.0.0.1:8766. No remote push/deployment.
