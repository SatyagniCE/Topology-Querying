"""Render versioned DeviceGraph JSON as a self-contained pyvis HTML viewer."""

from __future__ import annotations

import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path
import re

import networkx as nx
from pyvis.network import Network

from gnn_pruning.contracts import DeviceGraph
from gnn_pruning.conversion.graph import read_device_graph


# The same key drives the nodes and the in-page legend.
DEVICE_STYLE = {
    "nmos": ("#4596d8", "dot"),
    "pmos": ("#e47b63", "dot"),
    "resistor": ("#e0a03f", "box"),
    "capacitor": ("#69b980", "square"),
    "inductor": ("#b78ad5", "diamond"),
    "diode": ("#de6da2", "triangle"),
    "npn": ("#66b2b3", "triangleDown"),
    "pnp": ("#bf83ae", "triangleDown"),
    "current_source": ("#8caa60", "hexagon"),
    "voltage_source": ("#c7ad5d", "hexagon"),
    "balun": ("#91a3cd", "star"),
    "load": ("#aa9a87", "box"),
    "port": ("#96a6ae", "ellipse"),
}


def _known_terminal_nets(graph: DeviceGraph) -> dict[tuple[str, str], str]:
    """Use exact maps when available; infer retained edges for legacy graphs."""
    known = {
        (node.id, terminal): net
        for node in graph.nodes
        for terminal, net in node.terminal_nets
    }
    for edge in graph.edges:
        known.setdefault((edge.src, edge.src_terminal), edge.net)
        known.setdefault((edge.dst, edge.dst_terminal), edge.net)
    for node in graph.nodes:
        for first, second in node.terminal_equivalence:
            net = known.get((node.id, first), known.get((node.id, second)))
            if net is not None:
                known[(node.id, first)] = net
                known[(node.id, second)] = net
    return known


def to_networkx(graph: DeviceGraph) -> nx.MultiDiGraph:
    """Keep every ordered terminal connection, keyed by its parallel index."""
    graph.validate()
    result = nx.MultiDiGraph()
    known_nets = _known_terminal_nets(graph)
    for node in graph.nodes:
        fill, shape = DEVICE_STYLE[node.kind]
        rails = tuple(flag for flag in ("vdd", "gnd") if flag in node.interface_flags)
        if len(rails) == 2:
            border = "#6c52a3"
        elif "vdd" in rails:
            border = "#cb8b22"
        elif "gnd" in rails:
            border = "#267c82"
        else:
            border = "#34475e"
        badges = "\n" + " · ".join(rail.upper() for rail in rails) if rails else ""
        connections = "\n".join(
            f"{role} → "
            f"{known_nets.get((node.id, role), 'net unavailable in graph.json')}"
            for role in node.terminal_roles
        ) or "none"
        title = (f"{node.id}\nDevice: {node.kind}\n"
                 f"Connections:\n{connections}")
        if rails:
            title += "\nRail contact: " + ", ".join(rail.upper() for rail in rails)
            title += (" (no rail edge)" if node.terminal_nets else
                      " (no rail edge; exact terminal is not retained in this legacy graph.json)")
        other_flags = [flag for flag in node.interface_flags if flag not in rails]
        if other_flags:
            title += "\nInterface: " + ", ".join(other_flags)
        result.add_node(
            node.id, label=node.id + badges, title=title, shape=shape,
            color={"background": fill, "border": border,
                   "highlight": {"background": fill, "border": border}},
            borderWidth=4 if rails else 2,
            size=25,
            font={"color": "#162336", "face": "Arial", "size": 16,
                  "strokeWidth": 3, "strokeColor": "#ffffff"},
        )

    for edge in graph.edges:
        # Clockwise curves on reciprocal directed edges occupy opposite sides.
        # The pair-local index fans multiple nets apart on each side.
        result.add_edge(
            edge.src, edge.dst, key=edge.parallel_index,
            id=json.dumps([edge.src, edge.dst, edge.parallel_index],
                          ensure_ascii=False, separators=(",", ":")),
            net=edge.net, label="",
            title=(f"{edge.net}: "
                   f"{edge.src}.{edge.src_terminal} ↔ "
                   f"{edge.dst}.{edge.dst_terminal}\n"
                   f"Role: {edge.net_role}; "
                   f"parallel edge #{edge.parallel_index}"),
            arrows="to", width=1.5,
            color={"color": "#7b8798", "highlight": "#355b9d"},
            smooth={"enabled": True, "type": "curvedCW",
                    "roundness": min(0.12 + 0.15 * edge.parallel_index, 0.8)},
            font={"size": 12, "color": "#48556a", "strokeWidth": 3,
                  "strokeColor": "#ffffff", "align": "middle"},
        )
    return result


def _legend(graph: DeviceGraph) -> str:
    counts = Counter(node.kind for node in graph.nodes)
    entries = "".join(
        f'<li><span class="swatch" style="background:{DEVICE_STYLE[kind][0]}"></span>'
        f'{escape(kind.replace("_", " "))} <small>({counts[kind]})</small></li>'
        for kind in DEVICE_STYLE if kind in counts
    )
    rail_note = (
        "Rails have no edges; hover a node for exact rail-connected terminals."
        if all(node.terminal_nets or not node.terminal_roles for node in graph.nodes)
        else "Rails have no edges; older graph.json files may omit exact rail terminals."
    )
    return (
        '<style>'
        'body{margin:0;background:#f7f9fc;font-family:Arial,sans-serif}'
        '#circuit-legend{position:fixed;z-index:10;top:12px;left:12px;'
        'max-height:calc(100vh - 24px);overflow:auto;box-sizing:border-box;'
        'width:220px;padding:13px 15px;background:rgba(255,255,255,.96);'
        'border:1px solid #d7dfe9;border-radius:10px;box-shadow:0 3px 14px #22334822;'
        'font-size:13px;color:#26374b}'
        '#circuit-legend h2{font-size:15px;margin:0 0 8px}'
        '#circuit-legend ul{list-style:none;padding:0;margin:0 0 9px}'
        '#circuit-legend li{margin:5px 0;display:flex;align-items:center;gap:7px}'
        '#circuit-legend small{color:#6e7988}'
        '#circuit-legend .swatch{display:inline-block;width:13px;height:13px;'
        'border:1px solid #536274;border-radius:3px;flex:none}'
        '#circuit-legend p{margin:7px 0 0;line-height:1.35}'
        '.vis-tooltip{white-space:pre-line!important;max-width:440px;line-height:1.4}'
        '</style>'
        '<aside id="circuit-legend" aria-label="Device and rail legend">'
        '<h2>Device legend</h2><ul>' + entries + '</ul>'
        '<p><strong>VDD / GND badge and thick border:</strong> rail contact. '
        + rail_note + '</p>'
        '<p>Hover nodes for terminal nets and edges for endpoint terminals. '
        'Arrows show directed graph edges. '
        'Drag to move; scroll to zoom.</p>'
        '</aside>'
    )


def render_graph_file(source: Path, output: Path) -> Path:
    """Validate one graph JSON and write a complete, offline HTML page."""
    graph = read_device_graph(Path(source))
    network = Network(
        height="100vh", width="100%", directed=True,
        bgcolor="#f7f9fc", cdn_resources="in_line",
    )
    network.from_nx(to_networkx(graph))
    network.set_options('''{
      "physics": {"barnesHut": {"gravitationalConstant": -5000,
        "centralGravity": 0.15, "springLength": 140},
        "stabilization": {"iterations": 180}},
      "interaction": {"hover": true, "navigationButtons": true,
        "keyboard": true}
    }''')
    html = network.generate_html()
    # pyvis 0.3.2 includes unused Bootstrap CDN tags even with inline assets.
    html = re.sub(
        r'<(?:link|script)\b[^>]*\b(?:href|src)="https://cdn\.jsdelivr\.net/npm/bootstrap[^\"]*"[^>]*>(?:</script>)?',
        "", html, flags=re.I | re.S,
    )
    html = html.replace("<body>", "<body>" + _legend(graph), 1)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination


def render_folder(source: Path, output: Path) -> list[Path]:
    """Render graph.json and *.graph.json below a folder, preserving paths."""
    source = Path(source)
    output = Path(output)
    paths = sorted(
        path for path in source.rglob("*.json")
        if path.name == "graph.json" or path.name.endswith(".graph.json")
    )
    if not paths:
        raise ValueError(f"no graph.json files found in {source}")
    rendered = []
    for path in paths:
        relative = path.relative_to(source)
        if relative.name == "graph.json":
            name = "graph.html"
        elif relative.name == "graph.graph.json":
            name = "graph.graph.html"
        else:
            name = relative.name.removesuffix(".graph.json") + ".html"
        rendered.append(render_graph_file(path, output / relative.parent / name))
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="graph JSON file or folder of graph JSON files")
    parser.add_argument("--out", type=Path, required=True, help="HTML file or output folder")
    args = parser.parse_args(argv)
    if args.source.is_file():
        paths = [render_graph_file(args.source, args.out)]
    elif args.source.is_dir():
        paths = render_folder(args.source, args.out)
    else:
        parser.error(f"source does not exist: {args.source}")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
