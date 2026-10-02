# Topology Querying

Parse AnalogGenie circuits, store and query their topology in Neo4j, build
NetworkX graphs, and inspect every circuit in a browser. This repository includes
the validated 3,350-circuit canonical snapshot in `data/analoggenie` and 3,350
offline HTML graph views in `visualizations`. The raw AnalogGenie source is pinned
as a Git submodule; it is only needed when regenerating the canonical snapshot.

## Quick start on a fresh machine

The automated setup targets **Ubuntu 24.04 x86_64** with internet access and
an account that can use `sudo`. Python, Java, and Neo4j need not be installed.
Install Git, clone this repository, then run the setup script:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone --recurse-submodules https://github.com/SatyagniCE/Topology-Querying.git
cd Topology-Querying
bash scripts/setup-ubuntu.sh
bash scripts/run-local.sh
```

Leave `run-local.sh` open. Browse the [circuit index](http://127.0.0.1:8765/)
or open `visualizations/index.html` directly without running a server. Open
[Neo4j Browser](http://127.0.0.1:7474/) to query the database. Connect to
`bolt://127.0.0.1:7687`, database `neo4j`, user `neo4j`; find the generated
password in `~/.config/query-retrieve/neo4j.env` on your own machine.

Paste `queries/shared-emitter-npn.cypher` into Neo4j Browser for a topology
query that includes a `graph_url` column. Open that URL to inspect the full
NetworkX graph for a matching circuit. For a known ID, use
`http://127.0.0.1:8765/analoggenie_1060.html`.

Setup imports the committed canonical JSON into a private local Neo4j instance
and builds the NetworkX cache under `output/networkx`. It skips the import when
the database already matches the committed audit report. Neo4j persists data on
disk across restarts; it does not need to be repopulated each time. The runtime,
credentials, virtual environment, and NetworkX pickle cache remain local.

## Repository layout

| Path | Contents |
| --- | --- |
| `data/analoggenie/` | Canonical JSON for all circuits, manifest, audit, and schema |
| `visualizations/` | Searchable index and one HTML graph per circuit |
| `src/circuit_ingest/` | Parser, Neo4j storage, NetworkX cache, HTML exporter |
| `src/gnn_pruning/` | General netlist conversion and device graph viewer |
| `queries/` | Example Cypher with graph links |
| `scripts/` | Fresh-machine setup and local runtime commands |
| `examples/` | Earlier graph/viewer examples and a previous audit report |
| `AnalogGenie/` | Pinned upstream submodule; fetch to reparse source data |

Generated build outputs in `output/` are ignored by Git. To regenerate the
committed HTML snapshot from canonical JSON, run
`circuit-html --input-dir data/analoggenie --output-dir output/circuit_html`
from an installed environment.

## Install and test

```bash
python -m pip install -e '.[test]'
python -m pytest
```

## Convert a netlist

```python
from pathlib import Path
from gnn_pruning.conversion.netlist import parse_netlist
from gnn_pruning.conversion.graph import (
    TopologyAnnotations, build_device_graph, write_device_graph,
)

source = Path("example.cir")
parsed = parse_netlist(source.read_text(encoding="utf-8"), {}, path=str(source))
annotations = TopologyAnnotations(
    rail_aliases={"0": "gnd", "VSS": "gnd", "VDD": "vdd"},
    net_roles={"out": "output"},
)
graph = build_device_graph(parsed, annotations)
write_device_graph(Path("example.graph.json"), graph)
```

`fixed_values` maps names to numeric values for bare-symbol attributes. Compound expressions stay unevaluated. `TopologyAnnotations` uses exact net names; its roles must refer to nets present in the parsed circuit. `read_device_graph` validates versioned JSON when loading it. New graphs add `terminal_nets` to each node as ordered `[terminal_role, net_name]` pairs, including rails. Older graph JSON without this field remains readable and writable.

## View a graph

```bash
python -m gnn_pruning.visualization.render path/to/graph.json --out circuit.html
python -m gnn_pruning.visualization.render path/to/graphs --out path/to/html
```

The folder command finds `graph.json` and `*.graph.json` files recursively and preserves their relative folders. Each HTML file contains its visualization assets and can be opened locally. Colors identify device types; node badges and thick borders mark VDD or ground rail contact. Hover over nodes for every terminal's exact net, including rails, or over edges for net names and connected terminals. Edge names are hidden until hover to keep dense graphs readable. A viewer opened from older graph JSON infers only the connections that its edges retain and marks any other terminal net as unavailable.

## AnalogGenie corpus

The upstream [AnalogGenie](https://github.com/xz-group/AnalogGenie) corpus is included as a submodule at commit `efc25358939c6bedd247f28d3df61066964f3a90`. Clone with `git clone --recurse-submodules`, or run `git submodule update --init` after cloning when you need to regenerate the committed data. The library does not import AnalogGenie code.

The tests include a small checked-in `.cir` fixture and graph JSON fixtures; the full corpus is available for further conversion experiments.

## Step 1: Parse the AnalogGenie topology corpus

The `circuit_ingest` package parses official flattened `Dataset/<id>/<id>.cir` files
with their `Port<id>.txt` files into versioned canonical circuit records. It does
not run simulation, infer electrical values, build a graph, or create embeddings.
Parsing uses the trailing device type and preserves every terminal, including the
fourth BJT substrate connection. Raw instance names are retained for provenance;
internal device IDs are unique source-order ordinals.

```bash
git submodule update --init --recursive
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
circuit-ingest parse-analoggenie --dataset-root AnalogGenie/Dataset \
  --output-dir output/analoggenie --mode strict \
  --source-commit "$(git -C AnalogGenie rev-parse HEAD)"
```

`parse-analoggenie` writes `circuits/<id>.json`, `manifest.jsonl`, `issues.jsonl`,
`audit-report.json`, and `canonical-circuit.schema.json` under the output
directory. The circuit records and audit report are deterministic for the pinned
source and parser version. The committed snapshot is under `data/analoggenie`;
new runs under `output/` stay outside Git. `audit-analoggenie`
validates without writing circuit files;
pass `--report-path path/to/report.json` to save its summary. Both commands
accept `--source-commit` for source provenance.

Strict mode quarantines unknown device types. Lenient mode keeps them as opaque
devices with positional terminals and a warning. Syntax errors, known-device
arity errors, duplicate ports, and missing required files still quarantine or
fail a circuit. Quarantined records appear in the manifest and issues stream,
without a circuit JSON output. Exit code `0` means all discovered circuits are
safe to ingest, `1` means some were quarantined or failed, `2` means invalid
arguments or an inaccessible dataset, and `3` means an unexpected internal error.

The existing `parse_netlist` entry point now routes complete official primary
AnalogGenie bundles through this adapter. Its returned `ParsedNetlist` remains a
compatibility view for existing graph callers; the `CircuitRecord` JSON is the
stable boundary for future RAG stages. Generic or hierarchical netlists continue
through the existing parser.

The five documented unused ports are preserved as isolated external nets.

## Local Neo4j runtime

Install the pinned Neo4j Community 2026.09.0 and Temurin 21 JRE in your own
home directory, then start or stop the database with:

```bash
scripts/neo4j-local.sh install
scripts/neo4j-local.sh start
scripts/neo4j-local.sh stop
scripts/neo4j-local.sh status
```

If your execution environment stops background processes when a command ends,
run `scripts/neo4j-local.sh console` in a persistent terminal after `install`.

`install` checks the published SHA-256 values before extracting either archive,
sets a random initial password, and starts Neo4j. It refuses to overwrite an
existing installation. The database listens only on `127.0.0.1`: Bolt at
`bolt://127.0.0.1:7687` and Neo4j Browser at `http://127.0.0.1:7474`.
The runtime is under `~/.local/opt/`; its `data/`, `logs/`, and `conf/`
directories are under `~/.local/opt/neo4j-community-2026.09.0/`.
Credentials and connection settings are in
`~/.config/query-retrieve/neo4j.env` with mode `0600`. Source that file in
your shell when using the import commands; do not copy it into this repository.
The script supplies Java 21 only to Neo4j processes and does not alter the
system Java. Local Fleet discovery and usage reporting are disabled.

After installation, verify the runtime with:

```bash
bash -n scripts/neo4j-local.sh
scripts/neo4j-local.sh status
~/.local/opt/temurin-21/bin/java -version
curl -I http://localhost:7474
java -version
```

The private runtime must report Java 21, and the last command must still
report the system Java 8. The status command and HTTP request must succeed.

## Store canonical circuits in Neo4j

The committed `data/analoggenie` directory contains both the circuit JSON files
and their matching audit report. Export the local connection settings and import:

```bash
python -m pip install -e '.[neo4j,test]'
set -a
source ~/.config/query-retrieve/neo4j.env
set +a
circuit-neo4j import --input-dir data/analoggenie
```

The command creates ID constraints before writing, replaces each circuit in
one transaction, and reports imported and failed file counts. It exits nonzero
if any file fails. These Cypher examples return circuits by connected device
type and named Net, or by a declared Port whose Net has no device terminals:

```cypher
MATCH (c:Circuit)-[:HAS_DEVICE]->(d:Device {canonical_type: 'npn'})
      -[:CONNECTED_TO]->(n:Net {name: '0'})
RETURN DISTINCT c.id AS circuit_id
LIMIT 25;

MATCH (c:Circuit)-[:HAS_PORT]->(p:Port {referenced_by_device: false})
      -[:MAPS_TO]->(n:Net {degree_by_terminal: 0})
RETURN c.id AS circuit_id, p.name AS port, n.name AS net
LIMIT 25;
```

After loading the full corpus, compare the database with the current parser
audit report:

```bash
circuit-neo4j audit --report data/analoggenie/audit-report.json
NEO4J_TEST_REQUIRED=1 NEO4J_CORPUS_TEST=1 python -m pytest -q
```

The audit reads expected totals and device-type counts from that report at run
time. It also checks terminal and port relationship integrity and the circuit
755/Q30 substrate connection to net `0`. A nonzero exit means a mismatch or a
connection/report error; the command prints each mismatch to stderr.

## Cache canonical circuits as NetworkX graphs

Build a separate directed multigraph for each committed circuit:

```bash
circuit-networkx build --input-dir data/analoggenie --output-dir output/networkx
circuit-networkx audit --output-dir output/networkx \
  --report data/analoggenie/audit-report.json
```

Load a single graph by its canonical ID without a Neo4j connection:

```python
from pathlib import Path
from circuit_ingest.networkx_corpus import load_graph

graph = load_graph(Path("output/networkx"), "analoggenie:755")
```

The cache is a set of local pickle files plus a manifest keyed by `circuit_id`.
Only load caches you generated and trust: Python pickle can execute code when
opened. The canonical JSON remains the portable source for rebuilding graphs.
The audit reads expected totals and device-type counts from the generated
parser report, checks every graph, and traverses circuit 755's Q30 substrate
connection. A mismatch prints to stderr and returns a nonzero exit status.
