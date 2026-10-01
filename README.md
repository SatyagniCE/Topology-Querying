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
