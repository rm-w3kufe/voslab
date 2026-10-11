"""discovery.py — FASE-3b motor de descubrimiento (plan ratificado S5).

Propone ARISTAS con evidencia en `discovery_queue` semi-automatica — el
motor INFIERE aristas que no estan escritas en ninguna fuente (a diferencia
de fase-2 que DERIVA de campos explicitos). Advisory until S5 ratifica
(D-1 del plan: semi-automatic como gaps). NO-NEW-TRUTH: nunca escribe
verdad nueva; la cola es candidatos con score cerrado + motivo.

Metodos (fundamentos_matematical.descubrimiento, todos DETERMINISTICOS R10):
  link_prediction   — AA/CN/PA sobre no-dirigida por capa (claim-claim en
                      consenso/contradicts; claim-predicate bipartito en
                      certificacion). Score cerrado, orden por (-score, u, v).
  comunidades       — label-propagation PROPIA (orden fijo por id de nodo,
                      sin random; Louvain excluido por componente aleatoria).
                      Comunidades densas con pocas aristas entre ellas =
                      frontera; puentes betweenness-sin-arista = descubrimiento.
  motivos           — triada incompleta dirigida: A->B, B->C, falta A->C
                      en las MISMAS kinds dirigidas (child_of, derived_from,
                      supersedes). contradicts es simetrico por diseno — NO
                      entra en closure (2-ciclos esperados, no evidencia).
  temporalidad      — camino time-respecting: A supersedes B con ts(A) > ts(B)
                      donde la arista supersedes no existe aun — evidencia
                      para supersedes/refutes faltantes (q3 backlog).

Defaults documentados (S5 'adelante' 2026-10-11, q1-q4 abiertas):
  q1 contradicts  — queda SIMETRICA (patron ratified fase-2); 3c decide.
  q2 umbral       — MIN_SCORE_PROVISIONAL=0.5 (percentil ~top por capa);
                    S5 fija umbral definitivo antes de gate.
  q3 backlog 699  — unmatched traces se tratan como RUIDO DE SAMPLING por
                    ahora (context.claim_id sin claim registrado); no es
                    fuente de certified_by faltantes hasta que S5 decida.
  q4 orden        — 3b -> 3c -> 3d (orden del plan; 3d indexa triage luego).

Usage:
    from epistemic_graph.discovery import discover
    q = discover(graph, min_score=0.5)
    # q = {schema, fingerprint, candidates:[...], denominators:{...}, meta}
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import networkx as nx

# Capas dirigidas para closure de motivos (contradicts excluido: simetrico)
MOTIF_DIRECTED_KINDS: tuple[str, ...] = ("child_of", "derived_from", "supersedes")
# Capas para link prediction (pares de nodos del MISMO kind)
LINK_PREDICTION_KINDS: tuple[str, ...] = ("claim", "predicate")
# Defaults (q2/q3 — S5 fija antes de gate)
MIN_SCORE_PROVISIONAL = 0.5
SCHEMA = "discovery_queue-v1"


# ---------------------------------------------------------------- communities
# Label-propagation PROPIA: deterministic, synchronous rounds, fixed
# order by node id. No random. Louvain excluded (componente aleatoria).

def label_propagation_deterministic(g: nx.Graph) -> dict[str, str]:
    """Synchronous label propagation with fixed iteration order.

    Returns {node_id: community_id} where community_id = min node id in
    the community (content-keyed, stable). Deterministic R10: same graph
    -> same labels, independent of dict iteration order (sorted by id).
    """
    if g.number_of_nodes() == 0:
        return {}
    # init: each node its own label (= its id)
    labels = {n: n for n in g.nodes()}
    nodes_sorted = sorted(g.nodes())
    # iterate until stable (bounded rounds = n, guaranteed termination)
    for _ in range(g.number_of_nodes()):
        changed = False
        for u in nodes_sorted:
            neigh = [labels[v] for v in sorted(g.neighbors(u))]
            if not neigh:
                continue
            # majority label (ties: smallest label id — deterministic)
            counts: dict[str, int] = defaultdict(int)
            for lab in neigh:
                counts[lab] += 1
            best = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if labels[u] != best:
                labels[u] = best
                changed = True
        if not changed:
            break
    # normalize: community_id = min node id within community
    by_label: dict[str, list[str]] = defaultdict(list)
    for n, lab in labels.items():
        by_label[lab].append(n)
    return {n: min(members) for lab, members in by_label.items()
            for n in members}


def communities(graph: dict, layer_kinds: tuple[str, ...]) -> dict[str, str]:
    """Undirected projection of layer_kinds -> deterministic communities."""
    edges = [e for e in graph["edges"] if e["kind"] in layer_kinds]
    ids = {e["source"] for e in edges} | {e["target"] for e in edges}
    g = nx.Graph()
    for nid in sorted(ids):
        g.add_node(nid)
    for e in sorted(edges, key=lambda e: (e["source"], e["target"], e["kind"])):
        g.add_edge(e["source"], e["target"])
    return label_propagation_deterministic(g)


# ---------------------------------------------------------------- link prediction

def _link_prediction_pairs(graph: dict, kind: str,
                           min_score: float) -> list[dict]:
    """AA/CN/PA on undirected projection of same-kind pairs (non-edges)."""
    # nodes of this kind
    nodes = sorted(n["id"] for n in graph["nodes"] if n["kind"] == kind)
    if len(nodes) < 2:
        return []
    # undirected adjacency among these nodes (any edge kind between them)
    node_set = set(nodes)
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for e in graph["edges"]:
        s, t = e["source"], e["target"]
        if s in node_set and t in node_set and s != t:
            adj[s].add(t)
            adj[t].add(s)
    # degree map for AA/PA
    deg = {n: len(adj[n]) for n in nodes}
    # enumerate non-edges (u < v by sort order), score
    cands: list[dict] = []
    for i, u in enumerate(nodes):
        for v in nodes[i + 1:]:
            if v in adj[u]:
                continue  # existing edge — not a candidate
            common = adj[u] & adj[v]
            cn = len(common)
            # AA: sum 1/log(k_w) over common neighbors (k_w >= 2 to avoid /0)
            aa = sum(1.0 / __import__("math").log(deg[w])
                     for w in common if deg[w] >= 2)
            pa = deg[u] * deg[v]
            # closed score: max-normalized per method then averaged
            # (raw AA can be small; we report the raw values + a
            #  combined score in [0,1] via per-pair min-max over cands)
            cands.append({"u": u, "v": v, "cn": cn, "aa": round(aa, 12),
                          "pa": pa, "kind": kind})
    if not cands:
        return []
    # combined score in [0,1]: normalize cn, aa, pa independently then mean
    def _norm(vals: list[float]) -> list[float]:
        lo, hi = min(vals), max(vals)
        if hi == lo:
            return [0.0] * len(vals)
        return [(x - lo) / (hi - lo) for x in vals]
    n_cn = _norm([c["cn"] for c in cands])
    n_aa = _norm([c["aa"] for c in cands])
    n_pa = _norm([c["pa"] for c in cands])
    for c, a, b, d in zip(cands, n_cn, n_aa, n_pa):
        c["score"] = round((a + b + d) / 3.0, 12)
    # keep only >= min_score, sort by (-score, u, v) — R10
    kept = [c for c in cands if c["score"] >= min_score]
    kept.sort(key=lambda c: (-c["score"], c["u"], c["v"]))
    return kept


# ---------------------------------------------------------------- motivos (triad closure)

def _motif_closure(graph: dict) -> list[dict]:
    """Incomplete directed triads: A->B, B->C, missing A->C (same kind)."""
    cands: list[dict] = []
    for kind in MOTIF_DIRECTED_KINDS:
        edges = [(e["source"], e["target"]) for e in graph["edges"]
                 if e["kind"] == kind]
        if not edges:
            continue
        adj: dict[str, set[str]] = defaultdict(set)
        for s, t in edges:
            adj[s].add(t)
        # for each A->B->C where A->C missing
        for a in sorted(adj):
            for b in sorted(adj[a]):
                for c in sorted(adj[b]):
                    if c == a or c in adj[a]:
                        continue
                    cands.append({"u": a, "v": c, "via": b, "kind": kind,
                                  "method": "triad_closure",
                                  "score": 1.0})
    # dedupe (a,c,kind) keeping first via (sorted)
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for c in sorted(cands, key=lambda x: (x["kind"], x["u"], x["v"], x["via"])):
        key = (c["u"], c["v"], c["kind"])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# ---------------------------------------------------------------- temporalidad

def _time_respecting_supersedes(graph: dict) -> list[dict]:
    """A supersedes B candidate where ts(A) > ts(B) but edge absent.

    Evidence: A is a later claim on the same (source_id, quantity, value)
    group as B — fase-2 already derives supersedes for those with different
    text_hash; here we catch the ones fase-2 skipped (same text_hash =
    restatement) or where the edge kind is missing for temporal reasons.
    Simpler: claims sharing (source_id, quantity, value) where newer has
    no supersedes edge to older — propose it.
    """
    # index claim nodes by (source_id, quantity, value) via dims
    claim_nodes = [n for n in graph["nodes"] if n["kind"] == "claim"]
    by_sqv: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for n in sorted(claim_nodes, key=lambda x: x["id"]):
        d = n["dims"]
        sid = str(d.get("source_id") or "")
        qty = str(d.get("quantity") or "")
        val = str(d.get("value") or "")
        ts = str(d.get("ts") or "")
        if sid and qty and val and ts:
            by_sqv[(sid, qty, val)].append({"id": n["id"], "ts": ts})
    # existing supersedes edges (both directions)
    existing = set()
    for e in graph["edges"]:
        if e["kind"] == "supersedes":
            existing.add((e["source"], e["target"]))
    cands: list[dict] = []
    for key in sorted(by_sqv):
        grp = sorted(by_sqv[key], key=lambda x: (x["ts"], x["id"]))
        # newest supersedes older (temporal: ts(new) > ts(old))
        for i in range(len(grp) - 1, 0, -1):
            newer = grp[i]
            for older in grp[:i]:
                if newer["ts"] <= older["ts"]:
                    continue
                if (newer["id"], older["id"]) in existing:
                    continue
                cands.append({"u": newer["id"], "v": older["id"],
                              "kind": "supersedes",
                              "method": "time_respecting",
                              "score": 0.8,
                              "evidence": {"ts_newer": newer["ts"],
                                           "ts_older": older["ts"],
                                           "group": list(key)}})
    cands.sort(key=lambda c: (c["kind"], c["u"], c["v"]))
    return cands


# ---------------------------------------------------------------- main

def discover(graph: dict, min_score: float = MIN_SCORE_PROVISIONAL) -> dict:
    """Discovery queue — determinista (R10), advisory, NO-NEW-TRUTH."""
    # link prediction per kind
    lp: list[dict] = []
    for kind in LINK_PREDICTION_KINDS:
        for c in _link_prediction_pairs(graph, kind, min_score):
            lp.append({"u": c["u"], "v": c["v"], "kind": "correlates_with",
                       "method": "link_prediction", "score": c["score"],
                       "evidence": {"cn": c["cn"], "aa": c["aa"],
                                    "pa": c["pa"], "node_kind": kind}})
    lp.sort(key=lambda c: (-c["score"], c["u"], c["v"]))

    # triad closure (motifs)
    motifs = _motif_closure(graph)

    # time-respecting supersedes
    temporal = _time_respecting_supersedes(graph)

    # communities on consenso layer (for frontier context in report)
    comm = communities(graph, ("contradicts", "supersedes"))

    all_cands = lp + motifs + temporal
    all_cands.sort(key=lambda c: (-c["score"], c["kind"], c["u"], c["v"]))

    meta = graph.get("meta", {})
    return {
        "schema": SCHEMA,
        "fingerprint": meta.get("fingerprint"),
        "min_score": min_score,
        "candidates": all_cands,
        "denominators": {
            "link_prediction": {
                "kinds": list(LINK_PREDICTION_KINDS),
                "min_score": min_score,
                "emitted": len(lp),
            },
            "motif_closure": {
                "kinds": list(MOTIF_DIRECTED_KINDS),
                "emitted": len(motifs),
            },
            "time_respecting": {
                "kind": "supersedes",
                "emitted": len(temporal),
            },
            "communities_consenso": {
                "nodes": len(comm),
                "communities": len(set(comm.values())),
            },
        },
        "meta": {"total_candidates": len(all_cands)},
    }


def write_queue(q: dict, path: Path | None = None) -> Path:
    """Write discovery queue as JSONL (append-only convention for the
    persisted queue; here we write a full snapshot for inspection)."""
    import os
    root = Path(os.environ.get("VOSLAB_PATH",
                               Path(__file__).resolve().parents[3]))
    out = path or root / "state" / "epistemic" / "discovery_queue.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "snapshot", **q}, sort_keys=True,
                            ensure_ascii=False) + "\n")
        for c in q["candidates"]:
            fh.write(json.dumps({"type": "candidate", "status": "pending",
                                 **c}, sort_keys=True, ensure_ascii=False)
                     + "\n")
    return out
