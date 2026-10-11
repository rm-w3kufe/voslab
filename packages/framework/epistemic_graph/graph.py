"""Graph building: deterministic projection over the 7 sources.

MVP scope (docs/plans/graph_epistemic_proposal.vsm, ratified):
  nodes  — 9 kinds: document, claim, predicate, certificate, answer,
           experiment, decision, gap, rule
  edges  — 6 MVP: child_of, extracted_from, certified_by, derived_from,
           correlates_with (both directions, ratificado '<->'), answers
  dims   — base {kind, status, source, ts} on EVERY node (null when N/A)
           + per-kind extras (level, truth, provenance, risk, family,
           coverage, ...)

FASE-2 (S5 approved 2026-10-11, graph proposal fase-2 + backlog):
  edges  — 4 more: contradicts, refutes, supersedes, resolves
  vistas — by_edge(kind): claim->predicate certificador (certified_by
           cruzado), decision->gap resuelto (resolves), experiment->claim
           (correlates_with) — one generic edge view covers all three.
  Derivations (source-encoded only, denominators per rule):
    certified_by cruzado : trace.context.claim_id matches a sidecar claim
                           id -> claim -> roots of that trace's tree
    contradicts          : claim_ingest design("CONTRADICTION") — same
                           source_id + quantity, different value (pair,
                           both directions like ratified '<->')
    refutes              : a comparable pair with exactly one REFUTED
                           endpoint -> counter-claim -> refuted claim
    supersedes           : same (source_id, quantity, value), different
                           text_hash -> highest ordinal -> older restatements
    resolves             : gap.status resolved-ish AND a decision note
                           naming it -> decision -> gap (0 until gaps
                           carry a status field — honest denominator)

Identity is content-keyed (D3): never a session-local id, never a mtime.
NO-NEW-TRUTH: this module only READS — the graph is a view; every truth
stays in its canonical sidecar/ledger (R5) and the whole graph can be
rebuilt from scratch.

Determinism (R10): fixed iteration orders, sorted output, no randomness,
no wall-clock. Same sources -> byte-identical graph.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from . import load as L

EXP_TOKEN_RE = L._EXP_RE  # shared token grammar (one definition)

KINDS = ("document", "claim", "predicate", "certificate", "answer",
         "experiment", "decision", "gap", "rule")
EDGE_KINDS = ("child_of", "extracted_from", "certified_by", "derived_from",
              "correlates_with", "answers",
              # FASE-2 (S5 2026-10-11)
              "contradicts", "refutes", "supersedes", "resolves")


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
            "homes": key_meta["homes"],
            # fase-2: roots needed for certified_by cruzado (popped in build)
            "roots_by_trace": roots_by_trace}


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
            "sidecars_depth_files": depth["files"],
            # fase-2: claim id -> node id (popped in build)
            "claim_node_of": claim_node_of}


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


# ---------------------------------------------------------------- fase-2

_ORDINAL_RE = re.compile(r"-C(\d+)$")
_RESOLVED_STATUS = frozenset({"resolved", "done", "closed", "complete",
                              "completed"})


def _ordinal(claim_id: str) -> int:
    """Trailing -C### ordinal; 0 when absent (lexicographic id order below
    is the deterministic fallback for non-conforming ids)."""
    m = _ORDINAL_RE.search(claim_id)
    return int(m.group(1)) if m else 0


def _fase2(b: _Builder, traces: list[dict], roots_by_trace: dict,
           claim_node_of: dict, claims: dict) -> dict:
    """FASE-2 derivations (S5 2026-10-11): certified_by cruzado,
    contradicts, refutes, supersedes, resolves — every edge source-encoded,
    every rule reports its denominator (COVERAGE-DENOMINATOR)."""
    # ---- certified_by cruzado: trace.context.claim_id -> claim's roots
    ref = matched = unmatched = 0
    for tr in sorted(traces, key=lambda t: str(t.get("trace_id"))):
        cid = str((tr.get("context") or {}).get("claim_id") or "")
        if not cid:
            continue
        ref += 1
        nid = claim_node_of.get(cid)
        if nid is None:
            unmatched += 1
            continue
        matched += 1
        for r in sorted(roots_by_trace.get(str(tr.get("trace_id")), ())):
            b.edge(nid, f"predicate:{r}", "certified_by")

    # ---- pair derivations (contradicts / refutes) + restatement
    #      derivations (supersedes)
    comparable = 0
    by_sq: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_sqv: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for c in sorted(claims["claims"], key=lambda x: str(x.get("id"))):
        if not c.get("source_id") or c.get("quantity") is None \
                or c.get("value") is None:
            continue
        comparable += 1
        by_sq[(str(c["source_id"]), str(c["quantity"]))].append(c)
        by_sqv[(str(c["source_id"]), str(c["quantity"]),
                str(c["value"]))].append(c)

    pairs = refutes_emitted = 0
    for key in sorted(by_sq):
        grp = sorted(by_sq[key], key=lambda x: str(x.get("id")))
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, c = grp[i], grp[j]
                if str(a.get("value")) == str(c.get("value")):
                    continue
                na = claim_node_of.get(str(a.get("id")))
                nc = claim_node_of.get(str(c.get("id")))
                if na is None or nc is None:
                    continue
                pairs += 1
                b.edge(na, nc, "contradicts")   # symmetric pair: both arcs
                b.edge(nc, na, "contradicts")
                # exactly one REFUTED endpoint -> counter refutes refuted
                ra = a.get("status") == "REFUTED"
                rc = c.get("status") == "REFUTED"
                if ra != rc:
                    b.edge(nc if ra else na, na if ra else nc, "refutes")
                    refutes_emitted += 1

    sup_groups = sup_emitted = sup_same_hash = 0
    for key in sorted(by_sqv):
        grp = sorted(by_sqv[key],
                     key=lambda x: (_ordinal(str(x.get("id"))),
                                    str(x.get("id"))))
        if len(grp) < 2:
            continue
        sup_groups += 1
        latest = grp[-1]
        lnid = claim_node_of.get(str(latest.get("id")))
        lhash = str(latest.get("text_hash") or "")
        for older in grp[:-1]:
            onid = claim_node_of.get(str(older.get("id")))
            if lnid is None or onid is None:
                continue
            if str(older.get("text_hash") or "") == lhash:
                sup_same_hash += 1
                continue
            b.edge(lnid, onid, "supersedes")
            sup_emitted += 1

    # ---- resolves: gap carries a resolved status AND a decision names it
    #      (today's gaps carry no status field -> 0 edges, denominator
    #      reports it; edges appear the moment a gap is marked resolved)
    gaps_resolved = decisions_naming = resolves_emitted = 0
    for gp in sorted(L.load_gaps()["gaps"], key=lambda x: str(x.get("id"))):
        if str(gp.get("status") or "").lower() not in _RESOLVED_STATUS:
            continue
        gaps_resolved += 1
        gid = f"gap:{gp.get('id')}"
        for d in sorted(L.load_decisions()["decisions"],
                        key=lambda x: str(x.get("id"))):
            if str(gp.get("id")) in str(d.get("label") or ""):
                decisions_naming += 1
                b.edge(d["id"], gid, "resolves")
                resolves_emitted += 1

    return {
        "certified_by_cruzado": {"traces_with_claim_ref": ref,
                                 "matched_claim_nodes": matched,
                                 "unmatched_claim_refs": unmatched},
        "contradicts": {"claims_quantity_comparable": comparable,
                        "pairs_different_value": pairs},
        "refutes": {"pairs_refuted_endpoint": refutes_emitted},
        "supersedes": {"groups_same_value": sup_groups,
                       "edges_different_text": sup_emitted,
                       "skipped_same_text_hash": sup_same_hash},
        "resolves": {"gaps_resolved_status": gaps_resolved,
                     "decisions_naming": decisions_naming,
                     "edges": resolves_emitted},
    }


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
    pa = _predicates(b, traces, skipped_traces)
    roots_by_trace = pa.pop("roots_by_trace")
    src_counts["predicates_answers"] = pa
    dc = _documents_and_claims(b, depth, claims)
    claim_node_of = dc.pop("claim_node_of")
    src_counts["documents_claims"] = dc
    # fase-2 last: needs predicates (roots), claims (nodes), gaps+decisions
    src_counts["fase2"] = _fase2(b, traces, roots_by_trace, claim_node_of,
                                 claims)

    graph = b.snapshot({
        "fingerprint": fp,
        "cache_hit": False,
        "kinds": list(KINDS),
        "edge_kinds": list(EDGE_KINDS),
        "edge_kinds_mvp": list(EDGE_KINDS[:6]),
        "edge_kinds_fase2": list(EDGE_KINDS[6:]),
        "sources": src_counts,
        "views": {"by_kind": list(KINDS),
                  "by_edge": list(EDGE_KINDS),
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


def by_edge(graph: dict, kind: str) -> dict:
    """FASE-2 vista: subgraph induced by edges of one kind (endpoints kept
    whatever their node kind — the cross views: claim->predicate via
    certified_by, decision->gap via resolves, experiment<->claim via
    correlates_with)."""
    edges = [e for e in graph["edges"] if e["kind"] == kind]
    ids = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = [n for n in graph["nodes"] if n["id"] in ids]
    return {"nodes": nodes, "edges": edges,
            "meta": {**graph["meta"], "view": f"edge:{kind}",
                     "nodes_total": len(nodes), "edges_total": len(edges),
                     "edges_by_kind": {kind: len(edges)},
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
