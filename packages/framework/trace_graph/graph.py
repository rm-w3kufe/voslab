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


def _ctx_fingerprint(ctx: dict) -> str:
    """Deterministic short id for a routing context (old rows without
    claim_id still link to a claim-context node)."""
    import hashlib
    import json
    blob = json.dumps(ctx, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def flow(traces: list[dict], tree: str | None = None,
         session: str | None = None) -> dict:
    """Vista 3 — temporal/routing flow: claim → trace → home, with
    temporal chains between consecutive traces inside each session.

    Claim node key: ctx['claim_id'] (rows routed after the router fix),
    else a sha256 fingerprint of the sorted context (older rows), else
    no claim node — counted in meta.claims.missing_context.
    Edge kinds: link (claim→trace), route (trace→home),
    temporal (trace→trace by ts inside a session group).
    """
    sel = []
    for t in traces:
        if tree and family(t.get("tree_shape")) != tree:
            continue
        if session is not None and t.get("session_id") != session:
            continue
        sel.append(t)
    sel.sort(key=lambda t: (str(t.get("session_id") or ""),
                            str(t.get("ts") or ""),
                            str(t.get("trace_id") or "")))

    nodes: dict[str, dict] = {}
    edges: set = set()
    homes: Counter = Counter()
    by_id = by_fp = missing_ctx = 0

    def _node(nid: str, kind: str, text: str, **attrs):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": kind, "text": text, **attrs}

    for t in sel:
        tid = str(t.get("trace_id"))
        ctx = t.get("context") or {}
        fam = family(t.get("tree_shape"))
        home = t.get("home") or None
        if home:
            homes[str(home)] += 1
        _node(tid, "trace",
              f"{fam} → {home or '-'}",
              family=fam, home=home, ts=t.get("ts"),
              session=t.get("session_id"), truth=str(t.get("final_truth")),
              latency=t.get("total_latency_ms"))
        claim_id = ctx.get("claim_id")
        if claim_id:
            cid = f"claim:{claim_id}"
            _node(cid, "claim", str(claim_id), keyed_by="claim_id")
            by_id += 1
            edges.add((cid, tid, "link"))
        elif ctx:
            fp = _ctx_fingerprint(ctx)
            cid = f"ctx:{fp}"
            _node(cid, "claim", f"ctx:{fp}",
                  keyed_by="context-fingerprint",
                  claim_type=ctx.get("claim_type"),
                  falsifier=ctx.get("falsifier"))
            by_fp += 1
            edges.add((cid, tid, "link"))
        else:
            missing_ctx += 1
        if home:
            hid = f"home:{home}"
            _node(hid, "home", str(home), shape="home")
            edges.add((tid, hid, "route"))

    # temporal chains: consecutive traces inside each session group
    groups: dict[str, list[str]] = {}
    for t in sel:
        groups.setdefault(str(t.get("session_id") or ""), []).append(
            str(t.get("trace_id")))
    for _sess, ids in sorted(groups.items()):
        for a, b in zip(ids, ids[1:]):
            edges.add((a, b, "temporal"))

    return {
        "kind": "flow",
        "family": tree or "all",
        "nodes": [nodes[k] for k in sorted(nodes)],
        "edges": [{"source": a, "target": b, "kind": k, "weight": 1}
                  for a, b, k in sorted(edges)],
        "meta": {
            "kind": "flow",
            "family": tree or "all",
            "session": session,
            "traces": len(sel),
            "claims": {"by_claim_id": by_id,
                       "by_context_fingerprint": by_fp,
                       "missing_context": missing_ctx},
            "homes": dict(sorted(homes.items())),
            "sessions": len(groups),
        },
    }
