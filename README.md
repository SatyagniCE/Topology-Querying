# Topology Querying · Circuit Atlas

A local, single-user research workbench for **analog circuit topology**. Inspect
netlists and schematics, explore their terminal-level graphs, run read-only
Cypher, and find circuits structurally similar to a reference circuit.

The repository ships **3,350 canonical AnalogGenie circuits**, not 10,000.
It does not automatically classify their function or verify electrical specs.
No custom training, hosted LLM, API key or AnalogGenie model checkpoint is needed.

## Start here

| You want to… | Read |
| --- | --- |
| Install and launch on a new machine | [Setup guide](docs/setup.md) |
| Understand the screens, queries and retrieval | [Workbench guide](docs/workbench.md) |
| Contribute code, pull updates or push a branch | [Co-developer guide](CONTRIBUTING.md) |
| Use the parser, graph exports and legacy CLI tools | [Parser and graph tools](docs/parser-and-graph-tools.md) |

## Quick start

Install **Git**, **Python 3.11–3.13** (3.13 recommended), and **Docker**
first. Open Docker Desktop on Mac; on Linux, make sure `docker info` works
without running the project as root. Internet is needed for the initial setup.

```bash
git clone --recurse-submodules https://github.com/SatyagniCE/Topology-Querying.git
cd Topology-Querying
bash scripts/setup-workbench.sh
bash scripts/run-workbench.sh
```

The launcher opens [Circuit Atlas](http://127.0.0.1:8766/) automatically.
Keep its terminal open; **Ctrl+C** stops the web app.

**On Mac:** after downloading/cloning, double-click **Setup.command** once.
When setup finishes, double-click **Launch.command** for subsequent sessions.
The setup guide covers macOS permission prompts, ZIP downloads and prerequisites.

**Platforms:** the scripts target macOS and Linux; Windows users should use WSL2.
The current end-to-end setup verification was performed on macOS.
There is no native Windows double-click launcher.

### What setup does

1. Checks Python, Docker, corpus files and port availability.
2. Creates a project-only `.venv` and installs the workbench dependencies.
3. Fetches the pinned AnalogGenie source assets if missing.
4. Creates or reuses a local Neo4j Community container with persistent storage.
5. Imports **only missing circuits**, preserving existing graph records.
6. Builds/reuses local text and topology indexes and synchronizes Neo4j.

It does **not** install system software, retrain a model, generate semantic
metadata, clear a database or discard uploaded circuits/annotations.
Initial downloads, graph import and indexing take longer than later launches;
progress is printed in the terminal. Re-running setup resumes completed work.

## Capabilities

| Area | Available in V1 |
| --- | --- |
| Circuit library | Browse circuits, ID/text lookup, dataset/device filters |
| Circuit inspection | Available source schematic, netlist, canonical JSON, provenance and device counts |
| Graphs | NetworkX graph and live Neo4j graph, terminal connections, device inspector, zoom/Fit/expand and JSON exports |
| Structural queries | Read-only Cypher `MATCH`/`WHERE`, aggregation, paths and read subqueries |
| Vector queries | Explicit Neo4j vector `SEARCH` over synchronized text/topology vectors |
| Similarity | Reference-only structural retrieval; optional text-only and hybrid modes |
| Uploads | Validate and save supported flat netlists with a required description; optional ports, annotations and image |
| Annotations | Manual researcher edits, revision history and index/sync refresh |
| Query workflow | JSON parameters, successful-query history, table/graph views and result downloads |

**NetworkX and Neo4j are two views of the same canonical circuit model, not two
different inferred topologies.** Neo4j is needed for Cypher and its live graph;
the local library/NetworkX inspection can remain available if it goes offline.

## Search modes: what they actually mean

| Mode | Input and behavior | Important boundary |
| --- | --- | --- |
| Library lookup | Literal substring over circuit IDs, annotations and source-reference text | No embeddings |
| Reference similarity | Select a circuit; compare its wiring-derived descriptor with other circuits | No descriptions needed; similarity is not functional equivalence |
| Text similarity | Embed a description and compare with saved circuit text vectors | Weak when descriptions are missing; does not enforce device/spec constraints |
| Hybrid similarity | Combine independent text and structural rankings | Optional; sparse text can make results worse |
| Cypher | Run exactly the query you supply | No automatic English-to-Cypher conversion or hidden hybrid reranking |

For circuits with little semantic information, start with **reference-only
similarity or explicit structural Cypher**.

Typing “two outputs and at least one capacitor” in text similarity does **not**
enforce those conditions. Use a Cypher query that explicitly expresses the
conditions. An external LLM can help write that query if supplied with our
schema and examples; it must not invent properties or numeric embeddings.

The topology descriptor is a deterministic, terminal-aware **768-dimensional
fingerprint**, using device counts, heuristic port roles, wiring motifs and
WL-style local neighborhoods. The UI rescores the top 100 topology candidates
using uncompressed structural features. Text uses local BGE-small, 384 dimensions.
Hybrid uses rank fusion. Native vector Cypher uses the stored fingerprint but
does **not** automatically apply the UI's Python reranker.
See [retrieval details](docs/workbench.md#how-retrieval-actually-works).

## First five minutes

1. Open Library, search for `1004`, and open that circuit.
2. Inspect its netlist/schematic and toggle NetworkX ↔ Neo4j.
3. Choose **Find similar**, leave text empty, and inspect the returned candidates.
4. Open Query → Cypher and run the examples below.
5. Check the footer status: indexing complete, Neo4j connected, no pending sync.

Inventory:

```cypher
MATCH (c:Circuit)
RETURN count(c) AS circuits
```

Inspect circuit 1004's actual terminal connections:

```cypher
MATCH (c:Circuit {id:'analoggenie:1004'})-[:HAS_DEVICE]->(d:Device)
MATCH (d)-[r:CONNECTED_TO]->(n:Net)
RETURN d,r,n
LIMIT 100
```

More templates: [queries/](queries/) and [docs/queries/](docs/queries/).
The [three-stage diagnostic](docs/queries/three-stage-opamp-candidates.cypher)
is a narrowly defined **candidate pattern**, not a stage-count classifier.

## Limitations

- **No automatic semantic metadata.** Circuit family, named topology, stage count,
  functional roles and performance are not reliably labeled across the corpus.
  Manual annotations are user assertions, not independently verified facts.
- **No simulation or spec guarantees.** Gain, bandwidth, power, stability and supply
  range cannot be established from similarity scores or device counts.
- **No natural-language query compiler.** The text box does not generate Cypher.
- **No trained circuit graph encoder or schematic understanding.** Graph vectors
  are engineered fingerprints; schematic images are displayed, not interpreted.
- **No broad electrical retrieval benchmark.** Regression fixtures and sampled
  rankings exist; they do not establish general retrieval accuracy.
- **Upload parser is deliberately limited.** Supported flat SPICE/typed netlists
  only; no `.include`, hierarchical `.subckt`, PDK resolution or control blocks.
  A valid upload is structurally parseable, not guaranteed electrically valid.
- **Query limits.** Read-only console, 10-second transaction timeout, default
  200 displayed rows; graph views cap at 1,200 nodes / 3,000 edges.
- **Local V1 only.** No multi-user authentication/permissions or production
  hosting. Keep the app/database on loopback.
- **Scaling is not yet proven at 10k.** The committed corpus has 3,350 records.
  Source assets and Python/model/Neo4j dependencies consume additional storage.

## Architecture

```text
AnalogGenie source / supported uploads
                  │
                  ▼
      Canonical circuit JSON
         ┌────────┴─────────┐
         ▼                  ▼
   NetworkX graph       Neo4j graph
         │                  │
         └───── Circuit Atlas UI ─────┐
                                      │
                     Local SQLite catalog
                     annotations / uploads / history
                     text + topology vectors
                                      │
                             Neo4j vector sync
```

Parsing/graph construction records explicit device-terminal-to-net connections.
It does not infer a knowledge graph of electrical meaning.
SQLite holds local user state; Neo4j provides graph queries and synchronized
vector indexes. Browser UI assets are bundled; there is no Node build step.

## Repository layout

| Path | Purpose |
| --- | --- |
| `README.md`, `docs/setup.md`, `CONTRIBUTING.md` | Entry point, installation and collaboration |
| `Setup.command`, `Launch.command` | Mac double-click entry points |
| `scripts/setup-workbench.sh`, `scripts/run-workbench.sh` | Main setup/launch commands |
| `src/circuit_workbench/` | Web app, local catalog, upload validation, retrieval and runtime helpers |
| `src/circuit_ingest/` | Canonical parser, Neo4j storage and NetworkX/HTML exports |
| `src/gnn_pruning/` | Earlier general netlist/device-graph tools |
| `data/analoggenie/` | Committed circuit JSON, manifest, schema and audit |
| `AnalogGenie/` | Pinned upstream Git submodule: original sources/assets |
| `queries/`, `docs/queries/` | Cypher examples |
| `tests/` | Unit, environment-gated integration and UI helper tests |
| `visualizations/` | Prebuilt offline HTML graph snapshot |
| `output/` | Ignored local catalog, uploads, model cache and runtime credentials |

## Data, privacy and maintenance

The default web URL is `http://127.0.0.1:8766/`; Neo4j Browser is
`http://127.0.0.1:7474/`. Both database ports bind to loopback for new setups.
Neo4j has a locally generated password; Circuit Atlas reuses it without a login
prompt. Docker packages the database so Java/Neo4j need not be installed separately.

Your annotations, uploads, vectors and query history stay in
`output/workbench/`. Database data stays in Docker volume
`topology-querying-neo4j-data`. Newly generated runtime credentials are stored
privately in `output/runtime/neo4j.env`; existing containers retain their own
credentials. These are **not distributed through Git**.

Do not delete `output/`, remove the Docker volume, or use the replacing legacy
import command as a troubleshooting shortcut. See
[backup/restore and troubleshooting](docs/setup.md#backups-and-local-data).

To diagnose without changing data:

```bash
bash scripts/run-workbench.sh --doctor
```

## Development and tests

After setup:

```bash
.venv/bin/python -m pip install -e '.[workbench,test]'
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Integration tests requiring Neo4j are gated; skips do not mean they passed.
For live-workbench verification with Neo4j/indexing ready:

```bash
PYTHONPATH=src .venv/bin/python scripts/verify-workbench.py
```

The live check writes successful query history but does not edit circuit content.
Optional UI helper tests use `node --test tests/ui/viewer-controls.test.mjs`;
Node is **not** required to run the application.

See [CONTRIBUTING.md](CONTRIBUTING.md) for Git cloning, branch/pull/push workflow,
GitHub authentication and when `git init` is appropriate.

## Upstream and licensing

Original circuit assets come from [AnalogGenie](https://github.com/xz-group/AnalogGenie),
pinned at `efc25358939c6bedd247f28d3df61066964f3a90`.
Our app reads its dataset; it does not run its training code or require Conda.
Respect the upstream license and any separately applicable source-figure rights.

Bundled visualization assets retain their third-party license notices.
This repository currently has no top-level license grant for its own code;
do not assume one from a dependency's license.
