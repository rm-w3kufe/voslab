"""bridge.py — FASE-3d puente al plan integrado (plan ratified S5).

Indexa tasks pre-voslab (TASKS.vsm refs como nodos decision) por
conectividad con comunidades vOS del grafo epistemico. Low-connectivity
= candidatas a descarte en el triage q1-q8 (reporte para S5, advisory —
NO-NEW-TRUTH: el grafo no toma el triage, solo lo indexa).

Metodo (3d deliverables, R10 determinista):
  1. Parse TASKS.vsm (formato doble: task(REF): y task("REF",...) =)
     -> {ref, title, status, priority} por task open/in_progress/queued.
  2. Match cada task ref/title contra nodos del grafo (claim/rule/gap/
     experiment/decision) via token overlap determinista (sorted tokens,
     no random). Score = |tokens_task ∩ tokens_graph| / |tokens_task|.
  3. Comunidades vOS = label-prop sobre capa consenso (contradicts +
     supersedes) — misma funcion que discovery.communities.
  4. Connectivity = # grafo nodes que comparten al menos un token con
     la task. Bajo = frontera de descarte para triage S5.

Denominadores honestos: total_tasks, matched_tasks, unmatched_tasks,
per-status breakdown. NO-NEW-TRUTH: vista pura, no muta el grafo ni
escribe verdad nueva; el triage es S5 (q1-q8 del integrated plan).

Usage:
    from epistemic_graph.bridge import bridge_view
    v = bridge_view(graph)  # -> {schema, tasks, communities, report}
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .discovery import communities as _communities

SCHEMA = "graph_bridge-v1"
# statuses considered "live" for triage (open/in_progress/queued/partial)
LIVE_STATUSES = frozenset({"open", "in_progress", "queued", "partial"})
# token overlap threshold for "matched" (>=1 shared token = connected)
MIN_SHARED_TOKENS = 1


def _parse_tasks_vsm(path: Path) -> list[dict]:
    """Parse TASKS.vsm (dual format) -> task records.

    Format A: task(REF):\\n  title = "...", status = "..."
    Format B: task("REF", priority=P1, ...) = { ... }
    Tolerant of partial SHAPES: old/partial formats never raise; reports
    skips. A missing canon FILE is different: it raises (T5 canon fail-loud,
    plan 2026-10-20) — the old `return []` made a poisoned VOSLAB_PATH
    indistinguishable from "zero tasks" and produced the live=0 incident.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"CANON missing: {path} — TASKS.vsm is the canonical task status "
            "(R5); silent [] here was the live=0 incident (T5 fail-loud)"
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    tasks: list[dict] = []
    seen: set[str] = set()

    # Format A: task(REF): — REF can be bare or quoted; allow leading whitespace
    for m in re.finditer(r'^\s*task\(([^)]+)\):\s*$', text, re.M):
        ref_raw = m.group(1).strip().strip('"').strip("'")
        # extract block until next task( or EOF
        start = m.end()
        next_m = re.search(r'^\s*task\(', text[start:], re.M)
        block = text[start:start + next_m.start()] if next_m else text[start:]
        title_m = re.search(r'title\s*=\s*"([^"]*)"', block)
        status_m = re.search(r'status\s*=\s*(\w+)', block)
        prio_m = re.search(r'priority\s*=\s*(\w+)', block)
        ref = ref_raw
        if ref not in seen:
            seen.add(ref)
            tasks.append({
                "ref": ref,
                "title": title_m.group(1) if title_m else "",
                "status": status_m.group(1) if status_m else "unknown",
                "priority": prio_m.group(1) if prio_m else None,
                "format": "A",
            })

    # Format B: task("REF", ...) = {  OR  task(REF) = {
    for m in re.finditer(r'^\s*task\(?["\']?([^"\',)]+)["\']?[^)]*\)\s*=\s*\{', text, re.M):
        ref = m.group(1).strip()
        if ref in seen:
            continue
        seen.add(ref)
        start = m.end()
        # find matching closing brace (naive: next \n} at col 0)
        end_m = re.search(r'^\}', text[start:], re.M)
        block = text[start:start + end_m.start()] if end_m else text[start:start + 2000]
        title_m = re.search(r'title\s*=\s*"([^"]*)"', block)
        # format B uses colon: status: open,  OR status = open
        status_m = re.search(r'status\s*[:=]\s*(\w+)', block)
        prio_m = re.search(r'priority\s*=\s*(\w+)', block)
        tasks.append({
            "ref": ref,
            "title": title_m.group(1) if title_m else "",
            "status": status_m.group(1) if status_m else "unknown",
            "priority": prio_m.group(1) if prio_m else None,
            "format": "B",
        })

    return tasks


def _tokens(s: str) -> set[str]:
    """Deterministic token set: lowercase, split non-alnum, drop short."""
    return {t for t in re.split(r'[^a-z0-9]+', s.lower()) if len(t) >= 3}


def _graph_token_index(graph: dict) -> dict[str, set[str]]:
    """token -> set of graph node ids (from id + label)."""
    idx: dict[str, set[str]] = defaultdict(set)
    for n in graph["nodes"]:
        toks = _tokens(str(n.get("id", "")) + " " + str(n.get("label", "")))
        for t in toks:
            idx[t].add(n["id"])
    return idx


def bridge_view(graph: dict, tasks_path: Path | None = None) -> dict:
    """Bridge view: tasks x graph connectivity, R10 deterministic."""
    import os
    root = Path(os.environ.get("VOSLAB_PATH",
                               Path(__file__).resolve().parents[3]))
    tpath = tasks_path or root / "TASKS.vsm"
    tasks = _parse_tasks_vsm(tpath)
    live = [t for t in tasks if t["status"] in LIVE_STATUSES]

    tok_idx = _graph_token_index(graph)
    comm = _communities(graph, ("contradicts", "supersedes"))

    matched = unmatched = 0
    per_status: dict[str, int] = defaultdict(int)
    task_rows: list[dict] = []
    for t in sorted(live, key=lambda x: x["ref"]):
        ttoks = _tokens(t["ref"] + " " + t["title"])
        connected_ids: set[str] = set()
        for tok in sorted(ttoks):
            connected_ids |= tok_idx.get(tok, set())
        conn = len(connected_ids)
        # per_status counts ALL live tasks (field = live_by_status); the
        # matched/unmatched split is a separate axis (fix 2026-10-20:
        # it used to increment only inside the matched branch, so the
        # denominator sum broke whenever any task was unmatched).
        per_status[t["status"]] += 1
        if conn >= MIN_SHARED_TOKENS:
            matched += 1
        else:
            unmatched += 1
        task_rows.append({
            "ref": t["ref"],
            "status": t["status"],
            "priority": t["priority"],
            "connectivity": conn,
            "matched": conn >= MIN_SHARED_TOKENS,
            "sample_nodes": sorted(connected_ids)[:5],
        })

    meta = graph.get("meta", {})
    return {
        "schema": SCHEMA,
        "fingerprint": meta.get("fingerprint"),
        "denominators": {
            "tasks_total_parsed": len(tasks),
            "tasks_live": len(live),
            "tasks_matched": matched,
            "tasks_unmatched": unmatched,
            "live_by_status": dict(sorted(per_status.items())),
            "graph_nodes": meta.get("nodes_total"),
            "graph_edges": meta.get("edges_total"),
            "communities_consenso": len(set(comm.values())),
        },
        "tasks": task_rows,
        "report": {
            "low_connectivity_candidates": sorted(
                [t["ref"] for t in task_rows if not t["matched"]]),
            "high_connectivity": sorted(
                [t["ref"] for t in task_rows
                 if t["matched"] and t["connectivity"] >= 10]),
        },
    }


def write_bridge(v: dict, path: Path | None = None) -> Path:
    import os
    root = Path(os.environ.get("VOSLAB_PATH",
                               Path(__file__).resolve().parents[3]))
    out = path or root / "state" / "epistemic" / "graph_bridge.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v, indent=2, sort_keys=True,
                              ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out
