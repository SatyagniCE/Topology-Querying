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

## Local Neo4j runtime

Install the pinned Neo4j Community 2026.09.0 and Temurin 21 JRE in your own
home directory, then start or stop the database with:

```bash
scripts/neo4j-local.sh install
scripts/neo4j-local.sh start
scripts/neo4j-local.sh stop
scripts/neo4j-local.sh status
```

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
