"""Export offline browser views for canonical NetworkX circuit graphs."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import shutil
import sys

from pyvis import __file__ as pyvis_file

from circuit_ingest.models import CircuitRecord
from circuit_ingest.networkx_graph import build_networkx_graph


COLORS = {
    "npn": "#75b8c0", "pnp": "#b98cb8", "nmos": "#66a7d8",
    "pmos": "#e89a83", "resistor": "#e2b253", "capacitor": "#75bd8a",
    "inductor": "#a38bd0", "diode": "#d77da8",
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _filename(circuit_id: str) -> str:
    if not circuit_id.startswith("analoggenie:") or not circuit_id[12:].isdigit():
        raise ValueError(f"unexpected circuit ID: {circuit_id}")
    return f"analoggenie_{circuit_id[12:]}.html"


def _page(circuit_id: str, record_json: str) -> str:
    graph = build_networkx_graph(CircuitRecord.model_validate_json(record_json))
    nodes = []
    edges = []
    for node_id, attrs in graph.nodes(data=True):
        kind = attrs["kind"]
        if kind == "Device":
            label = attrs["source_instance"]
            color = COLORS.get(attrs["canonical_type"], "#8da4bf")
            shape = "dot"
            title = (f"<b>{escape(label)}</b> ({escape(attrs['canonical_type'])})"
                     f"<br>{escape(node_id)}")
        elif kind == "Net":
            label = attrs["name"]
            color = "#d1dae5"
            shape = "box"
            title = (f"<b>Net {escape(label)}</b><br>"
                     f"{attrs['degree_by_terminal']} terminal connections")
        else:
            label = attrs["name"]
            color = "#a9d9a8"
            shape = "ellipse"
            title = f"<b>Port {escape(label)}</b>"
        nodes.append({"id": node_id, "label": label, "title": title,
                      "color": color, "shape": shape})
    for source, target, key, attrs in graph.edges(keys=True, data=True):
        edges.append({"from": source, "to": target, "title": escape(
            attrs.get("terminal", attrs["kind"])), "color": "#98a7b9"})
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(circuit_id)} · circuit graph</title>
<link rel="stylesheet" href="assets/vis-network.css">
<style>
body{{margin:0;font:14px system-ui,sans-serif;background:#f7f9fc;color:#243246}}
#graph{{width:100vw;height:100vh}}
aside{{position:fixed;z-index:5;top:12px;left:12px;max-width:320px;padding:12px 15px;background:#ffffffed;border:1px solid #d0d9e4;border-radius:9px;box-shadow:0 4px 16px #0002}}
aside p{{margin:6px 0}}a{{color:#245d94}}small{{color:#536274}}
</style></head><body>
<aside><a href="index.html">← All circuits</a><h2>{escape(circuit_id)}</h2>
<p>{graph.number_of_nodes()} nodes · {graph.number_of_edges()} connections</p>
<small>Blue and other colors: devices. Gray: nets. Green: ports. Hover for details; drag and zoom to explore.</small></aside>
<div id="graph"></div><script src="assets/vis-network.min.js"></script><script>
const nodes = new vis.DataSet({_json(nodes)});
const edges = new vis.DataSet({_json(edges)});
new vis.Network(document.getElementById('graph'), {{nodes, edges}}, {{
  interaction: {{hover:true, navigationButtons:true, keyboard:true}},
  physics: {{barnesHut: {{gravitationalConstant:-3600, springLength:110}}, stabilization: {{iterations:140}}}},
  edges: {{smooth: {{type:'dynamic'}}, width:1.3}},
  nodes: {{font: {{face:'Arial',size:13}}, size:19}},
}});
</script></body></html>'''


def _index(ids: list[str]) -> str:
    entries = [{"id": circuit_id, "file": _filename(circuit_id)} for circuit_id in ids]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Circuit graph index</title><style>body{{max-width:780px;margin:32px auto;padding:0 18px;font:16px system-ui,sans-serif;color:#243246}}
input{{font:inherit;padding:10px;width:100%;box-sizing:border-box}}ul{{columns:3;list-style:none;padding:0;line-height:1.8}}
li{{break-inside:avoid}}a{{color:#245d94}}small{{color:#536274}}</style></head><body>
<h1>Circuit graphs</h1><p>{len(ids)} NetworkX circuit graphs. Paste a circuit ID from a Neo4j query to find its view.</p>
<input id="search" type="search" placeholder="Example: analoggenie:1060" aria-label="Find circuit ID" autofocus>
<p id="count"></p><ul id="results"></ul><script>
const circuits={_json(entries)};
const search=document.getElementById('search'), results=document.getElementById('results'), count=document.getElementById('count');
function show(){{const term=search.value.trim().toLowerCase();const matches=circuits.filter(x=>x.id.toLowerCase().includes(term));
count.textContent=matches.length+' matching circuits'+(matches.length>100?' (showing first 100)':'');
results.replaceChildren(...matches.slice(0,100).map(x=>{{const li=document.createElement('li');const a=document.createElement('a');
a.href=x.file;a.textContent=x.id;li.append(a);return li;}}));}}
search.addEventListener('input',show);show();</script></body></html>'''


def export_corpus(input_dir: Path, output: Path) -> int:
    """Write one HTML page per canonical JSON file plus a searchable index."""
    paths = sorted((Path(input_dir) / "circuits").glob("*.json"))
    if not paths:
        raise ValueError(f"no circuit JSON files found in {Path(input_dir) / 'circuits'}")
    output = Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    source = Path(pyvis_file).parent / "templates/lib/vis-9.1.2"
    shutil.copyfile(source / "vis-network.min.js", assets / "vis-network.min.js")
    shutil.copyfile(source / "vis-network.css", assets / "vis-network.css")
    shutil.copyfile(Path(__file__).parent / "assets/LICENSE-vis-network-MIT.txt",
                    assets / "LICENSE-vis-network-MIT.txt")
    ids: list[str] = []
    for path in paths:
        record_json = path.read_text(encoding="utf-8")
        circuit_id = CircuitRecord.model_validate_json(record_json).circuit_id
        (output / _filename(circuit_id)).write_text(
            _page(circuit_id, record_json), encoding="utf-8"
        )
        ids.append(circuit_id)
    (output / "index.html").write_text(_index(ids), encoding="utf-8")
    return len(ids)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="circuit-html")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        count = export_corpus(args.input_dir, args.output_dir)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"HTML views: {count} circuits at {args.output_dir}")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
