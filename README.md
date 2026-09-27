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
