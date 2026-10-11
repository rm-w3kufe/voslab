"""Graph building: deterministic projection over the 7 sources.

MVP scope (docs/plans/graph_epistemic_proposal.vsm, ratified):
  nodes  — 9 kinds: document, claim, predicate, certificate, answer,
           experiment, decision, gap, rule
  edges  — 6 MVP: child_of, extracted_from, certified_by, derived_from,
           correlates_with (both directions, ratificado '<->'), answers
  dims   — base {kind, status, source, ts} on EVERY node (null when N/A)
           + per-kind extras (level, truth, provenance, risk, family,
           coverage, ...)

Identity is content-keyed (D3): never a session-local id, never a mtime.
NO-NEW-TRUTH: this module only READS — the graph is a view; every truth
stays in its canonical sidecar/ledger (R5) and the whole graph can be
rebuilt from scratch.

Determinism (R10): fixed iteration orders, sorted output, no randomness,
no wall-clock. Same sources -> byte-identical graph.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from . import load as L

EXP_TOKEN_RE = L._EXP_RE  # shared token grammar (one definition)

KINDS = ("document", "claim", "predicate", "certificate", "answer",
         "experiment", "decision", "gap", "rule")
EDGE_KINDS = ("child_of", "extracted_from", "certified_by", "derived_from",
              "correlates_with", "answers")


# ---------------------------------------------------------------- helpers

def _base(kind: str, source: str, status=None, ts=None) -> dict:
    """Base dims — present on EVERY node (contract: uniform queries)."""
    return {"kind": kind, "status": status, "source": source, "ts": ts}


def _dominant(counter: Counter) -> str | None:
    if not counter:
        return None
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: set[tuple[str, str, str]] = set()
        self.edge_weights: Counter = Counter()
        self.skipped: dict[str, int] = defaultdict(int)

    def node(self, nid: str, kind: str, label, dims: dict | None = None,
             source: str | None = None) -> dict:
        if nid in self.nodes:
            return self.nodes[nid]  # merge: dims already set (first wins)
        base = _base(kind, source or (dims or {}).get("source"))
        d = {**base, **(dims or {})}
        n = {"id": nid, "kind": kind, "label": label,
             "dims": {k: d.get(k, None) for k in
                      ("kind", "status", "source", "ts")}}
        extras = {k: v for k, v in d.items()
                  if k not in ("kind", "status", "source", "ts") and v is not None}
        if extras:
            n["dims"].update(extras)
        self.nodes[nid] = n
        return n

    def edge(self, src: str, dst: str, kind: str, weight: int = 1) -> None:
        if kind not in EDGE_KINDS:
            return
        if src == dst:
            self.skipped["edge_self_loop"] += 1
            return
        if src not in self.nodes or dst not in self.nodes:
            # never silent: a dropped edge means an unresolved endpoint
            self.skipped["edge_dropped_missing_endpoint"] += 1
            return
        self.edges.add((src, dst, kind))
        self.edge_weights[(src, dst, kind)] += weight

    def snapshot(self, meta: dict) -> dict:
        nodes = [self.nodes[k] for k in sorted(self.nodes)]
        edges = [{"source": a, "target": b, "kind": k,
                  "weight": self.edge_weights[(a, b, k)]}
                 for a, b, k in sorted(self.edges)]
        meta = {
            **meta,
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "nodes_by_kind": dict(sorted(Counter(n["kind"] for n in nodes).items())),
            "edges_by_kind": dict(sorted(Counter(e["kind"] for e in edges).items())),
            "skipped": dict(sorted(self.skipped.items())),
        }
        return {"nodes": nodes, "edges": edges, "meta": meta}


# ---------------------------------------------------------------- sources

def _predicates(b: _Builder, traces: list[dict], skipped_traces: int) -> dict:
    """Predicate layer via trace_graph (F3 text identity, fallback counted)
    + answer nodes (trace_id + final) wired to their trace roots."""
    from trace_graph.graph import aggregate, _node_key

    agg = aggregate(traces)
    b.skipped["traces_malformed"] += skipped_traces
    key_meta = agg["meta"]

    # family + truth dims per predicate key (one deterministic pass)
    fam_per_key: dict[str, Counter] = defaultdict(Counter)
    roots_by_trace: dict[str, set[str]] = {}
    pending_answer_edges: list[tuple[str, str]] = []
    answers_without_root = 0

    for tr in traces:
        nds = tr.get("nodes") or []
        if not nds:
            continue
        seen: Counter = Counter()
        key_by_id: dict[str, str] = {}
        for nd in nds:
            key, _fb = _node_key(nd, seen)
            key_by_id[str(nd.get("node_id"))] = key
            fam = str(tr.get("tree_shape") or "?").split("(", 1)[0].strip()
            fam_per_key[key][fam] += 1
        children: set[str] = set()
        for nd in nds:
            p = key_by_id.get(str(nd.get("node_id")))
            for ch in nd.get("children", []):
                c = key_by_id.get(str(ch))
                if p and c:
                    children.add(c)
        roots = {k for k in key_by_id.values() if k not in children}
        tid = str(tr.get("trace_id"))
        roots_by_trace[tid] = roots

        # answer node: identity = trace_id + final (per proposal NODES)
        final_truth = str(tr.get("final_truth"))
        aid = f"answer:{tid}|{final_truth}"
        if b.nodes.get(aid) is None:
            b.node(aid, "answer", f"{tid} → {final_truth}",
                   dims={"truth": final_truth,
                         "certified": bool(tr.get("final_certified")),
                         "family": fam,
                         "ts": tr.get("ts"),
                         "source": "state/rsi/tree_traces.jsonl"})
        if not roots:
            answers_without_root += 1
        for r in sorted(roots):
            pending_answer_edges.append((aid, f"predicate:{r}"))

    for key, rec in sorted(agg["nodes"].items()):
        nid = f"predicate:{key}"
        if rec.get("keyed_by") == "fallback":
            b.skipped["predicates_keyed_fallback"] += 1
        b.node(nid, "predicate",
               (rec.get("text") or rec.get("name") or key),
               dims={"truth": _dominant(rec.get("truths") or {}),
                     "family": _dominant(fam_per_key.get(key) or Counter()),
                     "keyed_by": rec.get("keyed_by"),
                     "evals": rec.get("evals"),
                     "certified": rec.get("certified"),
                     "source": "state/rsi/tree_traces.jsonl"})

    for e in agg["edges"]:
        b.edge(f"predicate:{e['source']}", f"predicate:{e['target']}", "child_of",
               weight=int(e.get("weight", 1)))

    # answer->predicate edges only once predicate nodes exist (edge() is
    # endpoint-checked: emitting earlier would silently drop them)
    for aid, pid in pending_answer_edges:
        b.edge(aid, pid, "answers")

    return {"traces": key_meta["traces"],
            "traces_without_nodes": key_meta["traces_without_nodes"],
            "keyed_by_text": key_meta["keyed_by_text"],
            "keyed_by_fallback": key_meta["keyed_by_fallback"],
            "answers_without_root": answers_without_root,
            "homes": key_meta["homes"]}


def _documents_and_claims(b: _Builder, depth: dict, claims: dict) -> dict:
    docs = depth["docs"]
    routes = claims["routes"]
    ts_by_stem = claims["ts_by_stem"]

    # ---- document nodes (identity = stem + fingerprint of the artifact)
    doc_by_stem: dict[str, str] = {}
    subjects = sorted({str(c["subject"]) for c in claims["claims"]
                       if isinstance(c.get("subject"), str) and c.get("subject")})

    for stem in sorted(set(docs) | {s.lower() for s in ts_by_stem}):
        rec = docs.get(stem, {})
        # artifact resolution: first claim subject whose stem matches + exists
        artifact: Path | None = None
        for subj in subjects:
            if Path(subj).stem.lower() == stem:
                cand = L.roots() / subj
                if cand.is_file():
                    artifact = cand
                    break
        if artifact is not None:
            fp = _fingerprint_file(artifact)
            art_rel = str(artifact.relative_to(L.roots()))
        elif rec.get("_file"):
            fp = _fingerprint_file(L.roots() / rec["_file"])
            art_rel = rec.get("_file")
        else:
            fp = _fingerprint_str(stem)
            art_rel = None
        # claims_count (from .claims.vsm) + ts: claims sidecar wins
        cname = f"{stem}.claims.vsm"
        n_claims = sum(1 for c in claims["claims"]
                       if Path(str(c.get("_file", ""))).name.lower()
                       == cname.lower())
        ts = ts_by_stem.get(stem) or rec.get("ts")
        status = rec.get("status")
        nid = f"document:{stem}|{fp[:12]}"
        doc_by_stem[stem] = nid
        b.node(nid, "document", stem,
               dims={"level": rec.get("span"),
                     "tools": rec.get("tools"),
                     "verdict": rec.get("verdict"),
                     "coverage": n_claims,
                     "artifact": art_rel,
                     "fingerprint": fp[:12],
                     "status": status, "ts": ts,
                     "source": rec.get("_file")})

    # ---- claim nodes (identity = source_id + text_hash, D3 content-keyed)
    claim_node_of: dict[str, str] = {}
    dup_counter: Counter = Counter()
    exp_edge_tokens = 0
    exp_edge_matched = 0
    for c in sorted(claims["claims"], key=lambda x: str(x.get("id"))):
        cid = str(c.get("id"))
        src_id = str(c.get("source_id") or cid.rsplit("-C", 1)[0])
        thash = str(c.get("text_hash") or "")
        base_id = f"claim:{src_id}|{thash[:16]}" if thash else f"claim:{cid}"
        dup_counter[base_id] += 1
        n = dup_counter[base_id]
        nid = base_id if n == 1 else f"{base_id}#{n}"
        claim_node_of[cid] = nid
        if n > 1:
            b.skipped["claim_duplicate_content"] += 1
        route = routes.get(cid) or {}
        b.node(nid, "claim", str(c.get("text") or cid)[:240],
               dims={"status": c.get("status"),
                     "risk": c.get("risk"),
                     "provenance": str(c.get("method") or
                                       str(c.get("provenance") or "")).split(":")[0]
                                        or None,
                     "claim_type": c.get("type"),
                     "route": route.get("route"),
                     "route_verdict": route.get("verdict"),
                     "source": c.get("_file"),
                     "ts": ts_by_stem.get(
                         Path(str(c.get("_file", ""))).name
                         .removesuffix(".claims.vsm").lower())})
        # certificate nodes (identity = claim_id + ordinal)
        certs = c.get("certs") or []
        if not isinstance(certs, list):
            certs = [certs]
        for i, crt in enumerate(certs):
            label = crt if isinstance(crt, str) else str(crt)
            kid = f"certificate:{cid}#{i}"
            b.node(kid, "certificate", label,
                   dims={"ordinal": i, "status": c.get("status"),
                         "source": c.get("_file")})
            b.edge(kid, nid, "derived_from")
            b.edge(nid, kid, "certified_by")
        # certified_by claim->predicate via routes (only when route names an
        # existing predicate key — zero invented edges)
        r = route.get("route")
        if isinstance(r, str) and f"predicate:{r}" in b.nodes:
            b.edge(nid, f"predicate:{r}", "certified_by")
        # extracted_from: claim -> document(s) with matching stem
        subj = c.get("subject")
        if isinstance(subj, str) and subj:
            stem = Path(subj).stem.lower()
            target = doc_by_stem.get(stem)
            if target:
                b.edge(nid, target, "extracted_from")
            else:
                b.skipped["claims_without_document"] += 1
        # correlates_with: EXP tokens in claim text <-> experiment nodes
        txt = str(c.get("text") or "")
        for tok in EXP_TOKEN_RE.findall(txt):
            exp_edge_tokens += 1
            eid = f"experiment:{tok}"
            if eid in b.nodes:
                b.edge(eid, nid, "correlates_with")
                b.edge(nid, eid, "correlates_with")
                exp_edge_matched += 1
            else:
                b.skipped["exp_tokens_without_experiment"] += 1

    return {"claims": len(claims["claims"]),
            "routes": len(routes),
            "documents": len(doc_by_stem),
            "certificates": sum(len(c.get("certs") or [])
                                for c in claims["claims"]),
            "correlates_tokens": exp_edge_tokens,
            "correlates_matched": exp_edge_matched,
            "sidecars_claims_files": claims["files"],
            "sidecars_depth_files": depth["files"]}


def _experiments(b: _Builder) -> dict:
    ex = L.load_experiments()
    if not ex["exists"]:
        b.skipped["paper_data_missing"] += 1
    for eid in ex["ids"]:
        b.node(f"experiment:{eid}", "experiment", eid,
               dims={"source": "docs/papers/attractor_convergence/paper_data.vsm"})
    return {"experiments": len(ex["ids"]), "exists": ex["exists"]}


def _rules(b: _Builder) -> dict:
    r = L.load_rules()
    if not r["exists"]:
        b.skipped["hard_rules_missing"] += 1
    for rec in r["rules"]:
        key = rec["key"]
        num = key.split("_", 1)[0]
        b.node(f"rule:{key}", "rule", key,
               dims={"rule": num, "status": r["status"], "ts": r["ts"],
                     "source": "docs/spec_revision/system/boot/hard_rules.vsm"})
    return {"rules": len(r["rules"]), "exists": r["exists"]}


def _gaps(b: _Builder) -> dict:
    g = L.load_gaps()
    for rec in sorted(g["gaps"], key=lambda x: str(x.get("id"))):
        gid = str(rec["id"])
        b.node(f"gap:{gid}", "gap", rec.get("name") or gid,
               dims={"status": rec.get("status"),
                     "trigger": (rec.get("trigger") or {}).get("type")
                     if isinstance(rec.get("trigger"), dict) else None,
                     "source": rec.get("_file")})
    return {"gaps": len(g["gaps"]), "files": g["files"]}


def _decisions(b: _Builder) -> dict:
    d = L.load_decisions()
    seen: set[str] = set()
    for rec in d["decisions"]:
        if rec["id"] in seen:
            b.skipped["decision_duplicate"] += 1
            continue
        seen.add(rec["id"])
        b.node(rec["id"], "decision", str(rec["label"])[:240],
               dims={"status": rec["status"], "ts": rec["ts"],
                     "source": rec["source"], "ref": rec["ref"]})
    return {"decisions": len(seen), "skipped": d["skipped"]}


def _fingerprint_file(p) -> str:
    import hashlib
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return _fingerprint_str(str(p))


def _fingerprint_str(s: str) -> str:
    import hashlib
    return hashlib.sha256(str(s).encode()).hexdigest()


# ---------------------------------------------------------------- build

def fingerprint_inputs() -> list:
    """Base sources + resolved document artifacts (a doc node id depends
    on the artifact's bytes, so artifacts must invalidate the cache too)."""
    paths = list(L.source_files())
    depth = L.load_depth()
    claims = L.load_claims()
    for rec in depth["docs"].values():
        subj = None
        for c in claims["claims"]:
            if Path(str(c.get("_file", ""))).name.lower() == \
                    f"{rec['stem']}.claims.vsm".lower() and c.get("subject"):
                subj = str(c["subject"])
                break
        if subj:
            cand = L.roots() / subj
            if cand.is_file():
                paths.append(cand)
    return paths


def build(use_cache: bool = True, cache_path=None) -> dict:
    """Full projection -> {nodes, edges, meta}. Cache: materialization by
    content fingerprint of sources — rebuild when any input byte changes,
    rebuild-complete (no partial) per decision S5-A."""
    from .cache import cache_load, cache_store
    cpath = cache_path or L.roots() / "state" / "epistemic" / "graph_cache.json"
    fp = L.fingerprint(fingerprint_inputs())
    if use_cache:
        cached = cache_load(cpath, fp)
        if cached is not None:
            cached["meta"]["cache_hit"] = True
            return cached

    b = _Builder()
    traces, skipped_traces = L.load_traces()
    depth = L.load_depth()
    claims = L.load_claims()

    # experiments first: correlates_with needs experiment nodes present
    src_counts = {}
    src_counts["experiments"] = _experiments(b)
    src_counts["rules"] = _rules(b)
    src_counts["gaps"] = _gaps(b)
    src_counts["decisions"] = _decisions(b)
    src_counts["predicates_answers"] = _predicates(b, traces, skipped_traces)
    src_counts["documents_claims"] = _documents_and_claims(b, depth, claims)

    graph = b.snapshot({
        "fingerprint": fp,
        "cache_hit": False,
        "kinds": list(KINDS),
        "edge_kinds": list(EDGE_KINDS),
        "sources": src_counts,
        "views": {"by_kind": list(KINDS),
                  "dims_base": ["kind", "status", "source", "ts"]},
    })
    if use_cache:
        cache_store(cpath, graph)
    return graph


# ---------------------------------------------------------------- views

def by_kind(graph: dict, kind: str) -> dict:
    """Subgraph of one node kind (MVP output: vista por kind)."""
    nodes = [n for n in graph["nodes"] if n["kind"] == kind]
    ids = {n["id"] for n in nodes}
    edges = [e for e in graph["edges"]
             if e["source"] in ids and e["target"] in ids]
    return {"nodes": nodes, "edges": edges,
            "meta": {**graph["meta"], "view": f"kind:{kind}",
                     "nodes_total": len(nodes), "edges_total": len(edges),
                     "nodes_by_kind": {kind: len(nodes)},
                     "dropped_edges": len(graph["edges"]) - len(edges)}}


def by_dim(graph: dict, dim: str, value) -> dict:
    """Subgraph of nodes whose dim == value (scalar compare; null matches
    explicit None). Edges kept only when both endpoints in view."""
    def _match(n: dict) -> bool:
        v = n["dims"].get(dim, None)
        if isinstance(value, bool) or isinstance(v, bool):
            return bool(v) is bool(value) and v is not None or v == value
        return v == value or (v is not None and str(v) == str(value))
    nodes = [n for n in graph["nodes"] if _match(n)]
    ids = {n["id"] for n in nodes}
    edges = [e for e in graph["edges"]
             if e["source"] in ids and e["target"] in ids]
    return {"nodes": nodes, "edges": edges,
            "meta": {**graph["meta"], "view": f"dim:{dim}={value!r}",
                     "nodes_total": len(nodes), "edges_total": len(edges),
                     "dropped_edges": len(graph["edges"]) - len(edges)}}
