"""Exporters: DOT (graphviz), JSON (nodes/links — gephi/d3), networkx (notebook).

All exports are deterministic (R10): sorted iteration, no randomness.
Truth colors: TRUE green, FALSE red, UNKNOWN gray. Homes are a TRACE-LEVEL
attribute — shown as a meta label, never as fake structural edges.
"""
from __future__ import annotations

_TRUTH_FILL = {
    "Truth.TRUE": "#d4edda",
    "Truth.FALSE": "#f8d7da",
    "Truth.UNKNOWN": "#f0f0f0",
}
_TRUTH_MARK = {"Truth.TRUE": "T", "Truth.FALSE": "F", "Truth.UNKNOWN": "U"}


def _esc(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", ""))


def _first_line(text: str | None) -> str:
    if not text:
        return ""
    return str(text).split("\n", 1)[0]


def _label_line(text: str | None, limit: int = 72) -> str:
    """Truncated label line (full text stays in tooltip). Deterministic."""
    s = _first_line(text)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _dominant(truths: dict) -> str:
    if not truths:
        return "Truth.UNKNOWN"
    return sorted(truths.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _penwidth(w: int, max_w: int) -> float:
    if max_w <= 0:
        return 1.0
    return round(1.0 + 3.0 * w / max_w, 2)


def to_dot(graph: dict, name: str = "graph") -> str:
    """Aggregate or per-trace graph -> DOT string."""
    meta = graph.get("meta", {})
    nodes = graph.get("nodes", [])
    if isinstance(nodes, dict):          # aggregate form
        items = [(k, v) for k, v in sorted(nodes.items())]
        aggregate_form = True
    else:                                # per-trace form (list)
        items = [(n["id"], n) for n in nodes]
        aggregate_form = False
    id_map = {orig: f"n{i}" for i, (orig, _) in enumerate(items)}

    lines = [f'digraph {_esc(name)} {{',
             '  rankdir=TB; node [shape=box, fontname="monospace", fontsize=9];']
    for orig, n in items:
        if aggregate_form:
            truths = n.get("truths", {})
            summary = "/".join(
                f"{truths.get(k, 0)}{_TRUTH_MARK.get(k, '?')}"
                for k in ("Truth.TRUE", "Truth.FALSE", "Truth.UNKNOWN"))
            base = _esc(_label_line(n.get("text")) or n.get("name") or "")
            label = f"{base}\\n{_esc(summary)} (n={n.get('evals')})"
            fill = _TRUTH_FILL.get(_dominant(truths), "#f0f0f0")
        else:
            truth = n.get("truth", "Truth.UNKNOWN")
            base = _esc(_label_line(n.get("text")) or n.get("name") or "")
            label = f"{n.get('id')}:{base}\\n{_esc(truth)}"
            fill = _TRUTH_FILL.get(truth, "#f0f0f0")
        attrs = [f'label="{label}"',
                 f'style=filled', f'fillcolor="{fill}"']
        tip = _esc(n.get("text") or n.get("name") or "")
        if n.get("question"):
            tip = f"{tip}\\n{_esc('q: ' + n['question'])}"
        if tip:
            attrs.append(f'tooltip="{tip}"')
        if n.get("keyed_by") == "fallback":
            attrs.append("color=blue")
        lines.append(f'  {id_map[orig]} [{", ".join(attrs)}];')

    edges = graph.get("edges", [])
    if edges and isinstance(edges[0], (tuple, list)):
        pairs = [((a, b), 1) for a, b in edges]
    else:
        pairs = [((e["source"], e["target"]), e.get("weight", 1))
                 for e in edges]
    max_w = max((w for _, w in pairs), default=1)
    for (a, b), w in sorted(pairs, key=lambda x: (str(x[0][0]), str(x[0][1]))):
        src, dst = id_map.get(str(a)), id_map.get(str(b))
        if src is None or dst is None:
            continue
        lines.append(f'  {src} -> {dst} [label={w}, '
                     f'penwidth={_penwidth(w, max_w)}];')

    homes = meta.get("homes") or {}
    if homes:
        h = ", ".join(f"{k}={v}" for k, v in sorted(homes.items()))
        lines.append(f'  labelloc="t"; label="homes: {_esc(h)}\\n'
                     f'traces={meta.get("traces", "?")} '
                     f'keyed_by_text={meta.get("keyed_by_text", "?")} '
                     f'fallback={meta.get("keyed_by_fallback", "?")}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_json(graph: dict) -> dict:
    """Uniform nodes/links envelope (gephi/d3/cytoscape-friendly)."""
    meta = graph.get("meta", {})
    nodes = graph.get("nodes", [])
    if isinstance(nodes, dict):
        items = sorted(nodes.items())
        out_nodes = [
            {"id": k, "label": _first_line(v.get("text")) or v.get("name"),
             "type": v.get("type"), "truths": v.get("truths", {}),
             "evals": v.get("evals"), "certified": v.get("certified"),
             "question": v.get("question"), "text": v.get("text"),
             "keyed_by": v.get("keyed_by")}
            for k, v in items]
        links = graph.get("edges", [])
    else:
        out_nodes = [dict(n) for n in nodes]
        links = [{"source": a, "target": b, "weight": 1}
                 for a, b in graph.get("edges", [])]
    return {
        "graph": (graph.get("family") or meta.get("family")
                  or meta.get("tree_shape") or "graph"),
        "nodes": out_nodes,
        "links": links,
        "meta": meta,
    }


def to_networkx(graph: dict):
    """nodes/links envelope -> nx.DiGraph (lazy import; notebook path)."""
    try:
        import networkx as nx
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "networkx not installed — pip install networkx") from e
    env = to_json(graph)
    g = nx.DiGraph(**{k: v for k, v in env["meta"].items()
                      if isinstance(v, (str, int))})
    for n in env["nodes"]:
        attrs = {k: v for k, v in n.items() if k != "id"}
        g.add_node(n["id"], **attrs)
    for e in env["links"]:
        if e["source"] in g and e["target"] in g:
            g.add_edge(e["source"], e["target"], weight=e.get("weight", 1))
    return g
