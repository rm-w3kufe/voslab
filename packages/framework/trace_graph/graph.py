"""Graph building: per-trace evaluation trees + cross-trace aggregation.

Node identity across traces keys on the recorded VSL `text` (F3) — the
canonical branch literal — never on the per-trace local node_id. Rows
without text fall back to `type:name` and the fallback is REPORTED in
meta (honesty: the aggregate says how it was keyed). Sibling duplicates
get a deterministic `#2` suffix within one trace.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .load import family


def _node_key(nd: dict, seen: Counter) -> tuple[str, bool]:
    text = nd.get("text")
    if isinstance(text, str) and text:
        base, fallback = text, False
    else:
        base = f"{nd.get('type', '?')}:{nd.get('name', '?')}"
        fallback = True
    seen[base] += 1
    n = seen[base]
    return (base if n == 1 else f"{base}#{n}"), fallback


def per_trace(trace: dict) -> dict:
    """One trace -> exact evaluation graph (local node_ids as recorded)."""
    nodes = []
    edges = []
    for nd in trace.get("nodes", []):
        nodes.append({
            "id": str(nd.get("node_id")),
            "name": nd.get("name"),
            "type": nd.get("type"),
            "truth": str(nd.get("truth")),
            "certified": bool(nd.get("certified")),
            "text": nd.get("text"),
            "question": nd.get("question"),
            "evidence": nd.get("evidence"),
        })
        for ch in nd.get("children", []):
            edges.append((str(nd.get("node_id")), str(ch)))
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "trace_id": trace.get("trace_id"),
            "ts": trace.get("ts"),
            "session_id": trace.get("session_id"),
            "tree_shape": trace.get("tree_shape"),
            "family": family(trace.get("tree_shape")),
            "home": trace.get("home"),
            "final_truth": str(trace.get("final_truth")),
            "final_certified": trace.get("final_certified"),
            "context": trace.get("context"),
            "latency_ms": trace.get("total_latency_ms"),
        },
    }


def aggregate(traces: list[dict], tree: str | None = None) -> dict:
    """Cross-trace aggregate keyed by canonical node text.

    `tree` filters by family name ('claim_gate', 'type_prefix', ...).
    Meta carries every denominator: how many traces had nodes, how many
    nodes were keyed by text vs fallback, home distribution.
    """
    nodes: dict[str, dict] = {}
    edges: Counter = Counter()
    homes: Counter = Counter()
    keyed_text = 0
    keyed_fallback = 0
    used = 0
    no_nodes = 0

    for tr in traces:
        if tree and family(tr.get("tree_shape")) != tree:
            continue
        used += 1
        if tr.get("home"):
            homes[str(tr["home"])] += 1
        nds = tr.get("nodes") or []
        if not nds:
            no_nodes += 1
            continue
        seen: Counter = Counter()
        key_by_id: dict[str, str] = {}
        per_edges: set = set()
        for nd in nds:
            key, fallback = _node_key(nd, seen)
            key_by_id[str(nd.get("node_id"))] = key
            agg = nodes.get(key)
            if agg is None:
                agg = nodes[key] = {
                    "key": key,
                    "name": nd.get("name"),
                    "type": nd.get("type"),
                    "text": nd.get("text"),
                    "question": nd.get("question"),
                    "evals": 0,
                    "truths": Counter(),
                    "certified": 0,
                    "keyed_by": "fallback" if fallback else "text",
                }
                if fallback:
                    keyed_fallback += 1
                else:
                    keyed_text += 1
            agg["evals"] += 1
            agg["truths"][str(nd.get("truth"))] += 1
            if nd.get("certified"):
                agg["certified"] += 1
            if agg["question"] is None and nd.get("question"):
                agg["question"] = nd.get("question")
        for nd in nds:
            p = key_by_id.get(str(nd.get("node_id")))
            for ch in nd.get("children", []):
                c = key_by_id.get(str(ch))
                if p is not None and c is not None and p != c:
                    per_edges.add((p, c))
        edges.update(per_edges)

    return {
        "family": tree or "all",
        "nodes": {k: {**{kk: vv for kk, vv in v.items()
                         if kk != "truths"},
                      "truths": dict(v["truths"])}
                  for k, v in sorted(nodes.items())},
        "edges": [ {"source": a, "target": b, "weight": w}
                   for (a, b), w in sorted(edges.items()) ],
        "meta": {
            "family": tree or "all",
            "traces": used,
            "traces_without_nodes": no_nodes,
            "homes": dict(sorted(homes.items())),
            "keyed_by_text": keyed_text,
            "keyed_by_fallback": keyed_fallback,
        },
    }


def families(traces: list[dict]) -> dict:
    """family -> trace count (what the file contains)."""
    out: Counter = Counter()
    for tr in traces:
        out[family(tr.get("tree_shape"))] += 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))
