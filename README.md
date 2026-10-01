# Topology Querying

A small Python library for converting supported analog `.cir` netlists into deterministic, terminal-aware device graphs. It parses device instances and subcircuit calls, maps netlist device names to graph types, assigns explicit rail and net roles, and writes versioned graph JSON. The conversion code uses only the Python standard library.

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

`fixed_values` maps names to numeric values for bare-symbol attributes. Compound expressions stay unevaluated. `TopologyAnnotations` uses exact net names; its roles must refer to nets present in the parsed circuit. `read_device_graph` validates versioned JSON when loading it.

## AnalogGenie corpus

The upstream [AnalogGenie](https://github.com/xz-group/AnalogGenie) corpus is included as a submodule at commit `efc25358939c6bedd247f28d3df61066964f3a90`. Clone with `git clone --recurse-submodules`, or run `git submodule update --init` after cloning. The library does not import AnalogGenie code.

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
source and parser version; generated files stay outside Git. `audit-analoggenie`
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

Run the parser generation step above first. It creates both the circuit JSON
files and their matching audit report in `output/analoggenie`. Then export the
local connection settings and import the generated files:

```bash
python -m pip install -e '.[neo4j,test]'
set -a
source ~/.config/query-retrieve/neo4j.env
set +a
circuit-neo4j import --input-dir output/analoggenie
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
circuit-neo4j audit --report output/analoggenie/audit-report.json
NEO4J_TEST_REQUIRED=1 NEO4J_CORPUS_TEST=1 python -m pytest -q
```

The audit reads expected totals and device-type counts from that report at run
time. It also checks terminal and port relationship integrity and the circuit
755/Q30 substrate connection to net `0`. A nonzero exit means a mismatch or a
connection/report error; the command prints each mismatch to stderr.

## Cache canonical circuits as NetworkX graphs

After generating `output/analoggenie` with the parser command above, build a
separate directed multigraph for each circuit:

```bash
circuit-networkx build --input-dir output/analoggenie --output-dir output/networkx
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
