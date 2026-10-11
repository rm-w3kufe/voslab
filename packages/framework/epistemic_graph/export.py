"""Exporters: DOT (graphviz), JSON nodes/links (gephi/d3), networkx (notebook).

All exports deterministic (R10): sorted iteration, no randomness. Node
coloring by kind; answer/predicate accents by truth. Edge styling by edge
kind (the 6 ratified MVP relations).
"""
from __future__ import annotations

_KIND_STYLE = {
    # kind: (shape, fill)
    "document":   ("box3d", "#cfe2ff"),
    "claim":      ("diamond", "#fff3cd"),
    "predicate":  ("box", None),              # truth-colored
    "certificate": ("hexagon", "#e2d9f3"),
    "answer":     ("ellipse", None),          # truth-colored
    "experiment": ("cylinder", "#d1e7dd"),
    "decision":   ("component", "#ffe5d0"),
    "gap":        ("octagon", "#f8d7da"),
    "rule":       ("cds", "#e8daef"),
}
_TRUTH_FILL = {
    "Truth.TRUE": "#d4edda",
    "Truth.FALSE": "#f8d7da",
    "Truth.UNKNOWN": "#f0f0f0",
    "TRUE": "#d4edda",
    "FALSE": "#f8d7da",
    "UNKNOWN": "#f0f0f0",
}
_EDGE_STYLE = {
    "child_of":         'color="#6c757d", style=solid',
    "extracted_from":   'color="#0d6efd", style=dashed',
    "certified_by":     'color="#198754", style=solid',
    "derived_from":     'color="#198754", style=dashed',
    "correlates_with":  'color="#6f42c1", style=dotted',
    "answers":          'color="#fd7e14", style=bold',
}


def _esc(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", ""))


def _label_line(text, limit: int = 64) -> str:
    s = str(text or "").split("\n", 1)[0]
    return s if len(s) <= limit else s[: limit - 1] + "…"


def to_dot(graph: dict, name: str = "epistemic") -> str:
    """Graph -> DOT string (nodes sorted by id, edges by kind/src/dst)."""
    nodes = sorted(graph.get("nodes", []), key=lambda n: n["id"])
    id_map = {n["id"]: f"n{i}" for i, n in enumerate(nodes)}
    lines = [f'digraph {_esc(name)} {{',
             '  rankdir=TB; node [fontname="monospace", fontsize=9];']
    for n in nodes:
        shape, fill = _KIND_STYLE.get(n["kind"], ("box", "#f0f0f0"))
        if fill is None:
            fill = _TRUTH_FILL.get((n["dims"] or {}).get("truth"), "#f0f0f0")
        label = _esc(_label_line(n.get("label")) or n["id"])
        attrs = [f'label="{label}\\n[{n["kind"]}]"', f'shape={shape}',
                 'style=filled', f'fillcolor="{fill}"']
        tip = [n["id"]]
        for k in sorted((n.get("dims") or {}).keys()):
            if k != "kind" and n["dims"].get(k) is not None:
                tip.append(f"{k}={n['dims'][k]}")
        attrs.append(f'tooltip="{_esc(chr(10).join(tip))}"')
        lines.append(f'  {id_map[n["id"]]} [{", ".join(attrs)}];')
    for e in sorted(graph.get("edges", []),
                    key=lambda e: (e["kind"], e["source"], e["target"])):
        src, dst = id_map.get(e["source"]), id_map.get(e["target"])
        if src is None or dst is None:
            continue
        style = _EDGE_STYLE.get(e["kind"], "")
        w = f"label={e.get('weight', 1)}, " if e.get("weight", 1) != 1 else ""
        lines.append(f'  {src} -> {dst} [{w}{style}];')
    m = graph.get("meta", {})
    lines.append(
        f'  labelloc="t"; label="{_esc(name)}: '
        f'{m.get("nodes_total", 0)} nodes, {m.get("edges_total", 0)} edges, '
        f'kinds {_esc(m.get("nodes_by_kind", {}))}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_json(graph: dict) -> dict:
    """Uniform nodes/links envelope (gephi/d3/cytoscape-friendly)."""
    return {
        "graph": "epistemic",
        "nodes": [dict(n) for n in graph.get("nodes", [])],
        "links": [dict(e) for e in graph.get("edges", [])],
        "meta": graph.get("meta", {}),
    }


def to_networkx(graph: dict):
    """nodes/links envelope -> nx.DiGraph (lazy import; notebook path)."""
    try:
        import networkx as nx
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "networkx not installed — pip install networkx") from e
    env = to_json(graph)
    g = nx.DiGraph()
    for n in env["nodes"]:
        g.add_node(n["id"], kind=n["kind"], label=n.get("label"),
                   **{k: v for k, v in (n.get("dims") or {}).items()
                      if k != "kind"})
    for e in env["links"]:
        if e["source"] in g and e["target"] in g:
            g.add_edge(e["source"], e["target"],
                       kind=e["kind"], weight=e.get("weight", 1))
    return g
