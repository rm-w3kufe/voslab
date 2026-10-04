#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/plan-tree-design/plan_tree_design.vsm
"""maintain.py — the maintenance loop (Paso 4, rmw3 order 2026-08-16).

When a task is closed (marked done/closed), the system must propagate:
  1. DEPENDENTS: which tasks were blocked by it → now ready (task_tree).
  2. ARCHIVE: move the closed body to tasks_closed/ (tasks_archive.py
     --closed) leaving a stub — the backlog holds live work only.
  3. RE-DERIVE: the tree must reflect the new state (R7 model≡reality).

This script ORCHESTRATES those steps deterministically (R10). It never
decides WHAT to close — the S3 agent marks the task done; this script
propagates the effects and reports.

Usage:
  maintain.py --close <TASK-ID> [--apply]   # propagate + (with --apply) archive
  maintain.py --check                        # maintenance coherent (gate)
  maintain.py --report                       # status: ready/blocked/clusters
"""
from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__)) + "/../.."
# task_tree + TASKS.vsm live under VSF_ROOT (same convention as
# tasks_validate.py / tasks_reconcile.py); FND-TASK-TREE-UNIMPLEMENTED-01
# was actually a path-drift: the module existed in ~/vsf but this script
# looked for it under vOSlab/scripts/plan and TASKS.vsm under vOSlab/.
# S5 containment 2026-10-04: workspace root default (VSF_ROOT env still
# wins for upstream/covenant workflows).
_VSF_ROOT = os.environ.get("VSF_ROOT") or os.environ.get("VOSLAB_PATH") \
    or str(Path(__file__).resolve().parents[3])
sys.path.insert(0, os.path.join(_VSF_ROOT, "scripts", "plan"))
import task_tree as tt

TASKS = os.path.join(_VSF_ROOT, "TASKS.vsm")


def propagate(tid, tasks):
    """After tid → done: which tasks were blocked by tid become ready?"""
    unblocked = []
    for other, t in tasks.items():
        if tid in t["deps"]:
            remaining = [d for d in t["deps"] if tasks[d]["status"] not in tt.DONE_STATUSES]
            if not remaining:
                unblocked.append(other)
    return sorted(unblocked)


def close_tid(tid, tasks, apply):
    if tid not in tasks:
        print(f"FAIL: task '{tid}' not found", file=sys.stderr)
        return 1
    st = tasks[tid]["status"]
    if st in tt.DONE_STATUSES:
        print(f"  {tid} ya {st} — sin cambio")
        return 0
    print(f"  marcar {tid}: {st} → done")
    if not apply:
        print("  (dry-run: usa --apply para marcar)")
    unblocked = propagate(tid, tasks)
    if unblocked:
        print(f"  desbloquea: {', '.join(unblocked)}")
    else:
        print("  sin dependientes bloqueados")
    if apply:
        # 1. mark done in TASKS.vsm
        text = open(TASKS, encoding="utf-8").read()
        m = re.search(r'task\("' + re.escape(tid) + r'"[^)]*\)\s*=\s*\{', text)
        if not m:
            print(f"FAIL: no block for {tid}", file=sys.stderr)
            return 1
        # find status: line and replace
        start = m.end(); depth = 1; i = start; body_end = None
        while i < len(text):
            if text[i] == "{": depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    body_end = i
                    break
            i += 1
        body = text[m.start():body_end + 1]
        new_body = re.sub(r'(^\s*status:\s*)[a-z_]+', r'\1done', body, count=1, flags=re.M)
        text = text[:m.start()] + new_body + text[body_end + 1:]
        open(TASKS, "w", encoding="utf-8").write(text)
        print(f"  ✓ {tid} marcado done en TASKS.vsm")
        # 2. archive via tasks_archive.py --closed --apply
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks_archive.py"),
                            "--closed", "--apply"], cwd=ROOT, capture_output=True, text=True)
        print(r.stdout.strip()[-500:] if r.stdout else "")
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
        # 3. re-derive
        tasks2 = tt.parse_tasks()
        tree2 = tt.derive(tasks2)
        print(f"  árbol tras cierre: {len(tasks2)} tasks · "
              f"{len(tree2['ready'])} ready · {len(tree2['blocked'])} blocked")
    return 0


def main():
    ap = argparse.ArgumentParser(description="maintenance loop (Paso 4)")
    ap.add_argument("--close", metavar="TASK-ID")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    tasks = tt.parse_tasks()

    if args.close:
        return close_tid(args.close, tasks, args.apply)

    if args.check:
        tree = tt.derive(tasks)
        print(f"maintain --check: {len(tasks)} tasks · {len(tree['ready'])} ready · "
              f"{len(tree['blocked'])} blocked · {len(tree['clusters'])} clusters")
        return 0

    if args.report or True:
        tree = tt.derive(tasks)
        print(f"maintain: {len(tasks)} tasks · {len(tree['ready'])} ready · "
              f"{len(tree['blocked'])} blocked · {len(tree['clusters'])} clusters")
        return 0


if __name__ == "__main__":
    sys.exit(main())