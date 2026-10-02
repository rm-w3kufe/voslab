#!/usr/bin/env python3
# design: sandbox/plan_tree_design.vsm
# (R16_impl_with_design — plan-as-live-tree mechanism; ver PLAN-TREE-DESIGN)
"""plan_tree.py — derive a plan-tree block from LIVE state (R7: model≡reality).

For a declared plan (see --plan), walks the real tree and computes, per
branch (organ):
  * docs found (count) + @status ratified/active/proposed/missing
  * tasks in TASKS.vsm that cite this branch (open vs done)
  * branch status: done / active / stalled / unstarted
Then emits a VSL plan() block with progress + current + next, so the
plan document NEVER lies: it is derived, not hand-written.

Recursion note: each branch is an ORGAN of the plan (S1..S5 of the
revision organism); dependencies between branches are φ↑/φ↓ channels.

Usage:
  python3 scripts/plan/plan_tree.py --plan REVISION-ARC [--check]
  --check  exit 0 if the emitted block matches the one in the plan doc,
           exit 1 on drift (use by checks/plan-tree-valid).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYSTEM = os.path.join(ROOT, "docs/spec_revision/system")
PLAN_DIR = os.path.join(ROOT, "docs/spec_revision/plan")
TASKS = os.path.join(ROOT, "TASKS.vsm")

# ── plan definitions: branch -> (system/ dir or doc path, alias list) ──
# Each plan declares which organ dirs are its branches. REVISION-ARC maps
# the revision_plan.vsm phases to the real tree (post-2026-08-15 reconcile).
PLANS = {
    "REVISION-ARC": {
        "label": "arco de revisión VSL — de la idea al árbol system/",
        "doc": "revision-arc-tree/revision_arc_tree.vsm",
        "order": ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"],
        "branches": {
            "B0": {"name": "boot", "dir": "boot"},
            "B1": {"name": "kernel", "dir": "kernel"},
            "B2": {"name": "s5-policy", "dir": "s5-policy"},
            "B3": {"name": "s4-intelligence", "dir": "s4-intelligence"},
            "B4": {"name": "s3-control", "dir": "s3-control"},
            "B5": {"name": "s3star-audit", "dir": "s3star-audit"},
            "B6": {"name": "s2-coordination", "dir": "s2-coordination"},
            "B7": {"name": "s1-operations", "dir": "s1-operations"},
            "B8": {"name": "instance", "dir": "instance"},
        },
        "extra_dirs": [],  # dirs declared in plan but NOT branches (infra/plan/spec moved)
    },
    "STRATEGIC": {
        "label": "arco estratégico I/A — horizontes de actuación",
        "doc": "plan-01/plans_active.vsm",
        "order": ["S4", "S5", "S3", "S3*", "S2", "S1"],
        "branches": {
            "S4": {"name": "s4-intelligence", "dir": "s4-intelligence"},
            "S5": {"name": "s5-policy", "dir": "s5-policy"},
            "S3": {"name": "s3-control", "dir": "s3-control"},
            "S3*": {"name": "s3star-audit", "dir": "s3star-audit"},
            "S2": {"name": "s2-coordination", "dir": "s2-coordination"},
            "S1": {"name": "s1-operations", "dir": "s1-operations"},
        },
        "extra_dirs": [],
    },
}


def read_tasks():
    """Return {task_ref: (status, body)} from TASKS.vsm (block scan)."""
    if not os.path.exists(TASKS):
        return {}
    tasks = {}
    with open(TASKS, encoding="utf-8") as fh:
        text = fh.read()
    # task blocks: task("REF", ...) = { ... status: X ... }
    # and task(REF): ... status = X
    pat = re.compile(r'task\(["\']?([^"\')]+)["\']?\s*[,:)]', re.M)
    for m in pat.finditer(text):
        ref = m.group(1).strip()
        start = m.end()
        # find block close: next '\n}' at depth 0 after '{'
        body = text[start:start + 6000]
        st = re.search(r'status\s*[:=]\s*["\']?([A-Za-z_0-9-]+)', body)
        tasks[ref] = (st.group(1) if st else "unknown", body)
    return tasks


def branch_status(docs_ratified, docs_active, docs_total, tasks_open, tasks_done):
    """Classify branch: done / active / stalled / unstarted — cybernetic read.
    The branch organ is DONE when its docs are ratified (the arco's work unit
    is ratification, not task churn); tasks_open is a signal, not a blocker."""
    if docs_total == 0:
        return "unstarted"
    if docs_ratified == docs_total:
        return "done"
    if tasks_open > 0 or docs_active > 0:
        return "active"
    return "stalled"


def analyze_branch(branch, tasks):
    """Analyze one branch organ: docs census + task census.

    Docs census is RECURSIVE (rglob *.vsm over the whole organ subtree),
    so a branch reports the REAL doc count — s5-policy includes its
    subdirectories (vsl-language/, agent-policy/, …), not just the top
    level. The branch organ dir is the recursion root."""
    bdir = os.path.join(SYSTEM, branch["dir"])
    docs = []
    if os.path.isdir(bdir):
        docs = sorted(
            str(p.relative_to(bdir))
            for p in Path(bdir).rglob("*.vsm")
            if p.is_file()
        )
    # docs census
    ratified = active = proposed = missing = 0
    for d in docs:
        p = os.path.join(bdir, d)
        try:
            with open(p, encoding="utf-8") as fh:
                head = fh.read(4000)
        except OSError:
            missing += 1
            continue
        if "@status ratified" in head:
            ratified += 1
        elif "@status active" in head:
            active += 1
        elif "@status proposed" in head:
            proposed += 1
        else:
            missing += 1
    # task census: tasks whose BLOCK cites the branch dir path (system/<dir>/)
    tasks_open = tasks_done = 0
    dirpath = f"system/{branch['dir']}/"
    for ref, (st, body) in tasks.items():
        if dirpath in body or f"system/{branch['dir']}" in body:
            if st in ("done", "closed"):
                tasks_done += 1
            elif st not in ("unknown",):
                tasks_open += 1
    return {
        "docs_total": len(docs),
        "ratified": ratified,
        "active": active,
        "proposed": proposed,
        "no_status": missing,
        "tasks_open": tasks_open,
        "tasks_done": tasks_done,
        "status": branch_status(len(docs) and ratified or 0,
                                active, len(docs), tasks_open, tasks_done),
    }


def emit_block(plan_name):
    """Emit the derived VSL plan() block for the named plan."""
    if plan_name not in PLANS:
        sys.stderr.write(f"unknown plan: {plan_name} (known: {', '.join(PLANS)})\n")
        sys.exit(2)
    cfg = PLANS[plan_name]
    tasks = read_tasks()
    lines = []
    lines.append(f'plan("{plan_name}") {{')
    lines.append(f"  status: active,")
    lines.append(f'  label: "{cfg["label"]}",')
    lines.append(f"  derived: \"auto by scripts/plan/plan_tree.py — do not hand-edit\",")

    total = done_total = 0
    branches = []
    for bid in cfg["order"]:
        b = cfg["branches"][bid]
        a = analyze_branch(b, tasks)
        branches.append((bid, b, a))
        total += a["docs_total"] + a["tasks_open"] + a["tasks_done"]
        # done work: ratified docs + done tasks (work unit = ratification)
        done_total += a["ratified"] + a["tasks_done"]

    lines.append("  branches: {")
    for bid, b, a in branches:
        lines.append(
            f'    {bid}: {{ name: "{b["name"]}", dir: "{b["dir"]}",'
            f' status: {a["status"]}, docs: {a["docs_total"]},'
            f' ratified: {a["ratified"]}, active: {a["active"]},'
            f' no_status: {a["no_status"]}, tasks_open: {a["tasks_open"]},'
            f' tasks_done: {a["tasks_done"]} }},'
        )
    lines.append("  },")

    # progress + current + next
    pct = int(round(done_total * 100.0 / total)) if total else 0
    current = next_branch = "—"
    for bid, b, a in branches:
        if a["status"] in ("active", "stalled") and current == "—":
            current = f'{bid} — {b["name"]}'
            if a["tasks_open"]:
                current += f" ({a['tasks_open']} tasks open)"
            if a["no_status"]:
                current += f" ({a['no_status']} docs sin @status)"
            # next after current
            idx = cfg["order"].index(bid)
            for nbid in cfg["order"][idx + 1:]:
                nb = cfg["branches"][nbid]
                na = dict((k, v) for k, v in branches if k == nbid)[0][2] if False else None
            break
    # simpler next: first non-done after current
    seen_current = False
    for bid, b, a in branches:
        if bid == current.split(" ")[0] if current != "—" else False:
            seen_current = True
            continue
        if seen_current and a["status"] != "done":
            next_branch = f'{bid} — {b["name"]}'
            break

    lines.append(f"  progress: {{ total: {total}, done: {done_total}, pct: {pct} }},")
    lines.append(f'  current: "{current}",')
    lines.append(f'  next: "{next_branch}",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def extract_declared_block(docpath):
    """Extract the declared plan() block from the plan doc (for --check)."""
    if not os.path.exists(docpath):
        return None
    with open(docpath, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r'plan\("([^"]+)"\)\s*\{', text)
    if not m:
        return None
    # naive brace balance to the closing '}'
    start = m.start()
    depth = 0
    i = m.end() - 1
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="plan name (REVISION-ARC | STRATEGIC)")
    ap.add_argument("--check", action="store_true", help="exit 0 if plan doc matches derived")
    args = ap.parse_args()

    block = emit_block(args.plan)
    if not args.check:
        print(block)
        return 0

    cfg = PLANS[args.plan]
    docpath = os.path.join(PLAN_DIR, cfg["doc"])
    declared = extract_declared_block(docpath)
    if declared is None:
        print(f"FAIL: {docpath} has no plan(\"{args.plan}\") block")
        return 1
    # compare progress line (the derived truth)
    dm = re.search(r'progress: \{[^}]+\}', declared)
    em = re.search(r'progress: \{[^}]+\}', block)
    if dm and em and dm.group(0) != em.group(0):
        print(f"FAIL: plan {args.plan} drifted — declared {dm.group(0)} ≠ derived {em.group(0)}")
        print("run: python3 scripts/plan/plan_tree.py --plan %s" % args.plan)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())