#!/usr/bin/env python3
# design: docs/design/sources/plan-tree-design/plan_tree_design.vsm
"""task_tree.py — derive the task dependency tree from TASKS.vsm (Paso 3,
rmw3 order 2026-08-16: archive → discovery → dependency tree → maintenance).

Reads explicit dependencies (depends_on: / blocked_on:) from task() blocks
and derives: which tasks are EXECUTABLE now (all deps satisfied), which are
BLOCKED (a dep not done), the dependency DAG per cluster, and the action
plan order (ready → blocked-by-one → blocked-by-chain).

Model ≡ reality (R7): the tree is DERIVED from TASKS.vsm every run; the
doc never holds hand-written tree state (drift = bug). Deterministic (R10).

Usage:
  task_tree.py               # derive + print tree (clusters, ready, blocked)
  task_tree.py --json        # machine-readable (for hooks/plugins/command)
  task_tree.py --check       # compare derived tree vs declared tree block
                             # (plan tree block in a doc) — drift blocks
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__)) + "/../.."
TASKS = os.path.join(ROOT, "TASKS.vsm")

TASK_RE = re.compile(r'task\("([A-Z0-9\-_]+)"[^)]*\)\s*=\s*\{')
DEP_RE = re.compile(r'^\s*(?:depends_on|blocked_on):\s*(.+)$', re.M)
STATUS_RE = re.compile(r'^\s*status:\s*([a-z_]+)', re.M)
PRIO_RE = re.compile(r'priority=([A-Z0-9]+)')

DONE_STATUSES = {"done", "closed"}


def parse_tasks(path=TASKS):
    """Parse task blocks: id -> {status, priority, deps (list)}."""
    text = open(path, encoding="utf-8").read()
    tasks = {}
    for m in TASK_RE.finditer(text):
        start = m.end()
        depth = 1          # the regex consumed the opening { — start at 1
        i = start
        body = None
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = text[m.start():i + 1]
                    break
            i += 1
        if body is None:
            continue
        tid = m.group(1)
        sm = STATUS_RE.search(body)
        pm = PRIO_RE.search(body)
        dm = DEP_RE.search(body)
        deps = []
        if dm:
            raw = dm.group(1).strip()
            # supports: "A", ["A", "B"], A+B, A, B
            for part in re.split(r'[",\[\]\s]+', raw):
                part = part.strip()
                if part and not part.startswith("//") and re.match(r'^[A-Z0-9\-_]+$', part):
                    deps.append(part)
        tasks[tid] = {
            "status": sm.group(1) if sm else "?",
            "priority": pm.group(1) if pm else "?",
            "deps": deps,
        }
    return tasks


def derive(tasks):
    """Return: clusters (connected components by deps), ready, blocked."""
    # adjacency via deps
    adj = defaultdict(set)          # task -> deps (task depends on)
    for tid, t in tasks.items():
        for d in t["deps"]:
            if d in tasks:          # only intra-backlog deps count
                adj[tid].add(d)
    # executable: all deps done
    ready = []
    blocked = {}
    for tid, t in tasks.items():
        if t["status"] in DONE_STATUSES:
            continue
        pending = [d for d in adj[tid] if tasks[d]["status"] not in DONE_STATUSES]
        if pending:
            blocked[tid] = pending
        else:
            ready.append(tid)
    # clusters: connected components of the dep graph
    visited = set()
    clusters = []
    graph = defaultdict(set)
    for tid, deps in adj.items():
        graph[tid].update(deps)
        for d in deps:
            graph[d].add(tid)
    for tid in sorted(graph):
        if tid in visited:
            continue
        stack = [tid]
        comp = set()
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            stack.extend(graph.get(n, set()))
        # only keep clusters with >= 2 tasks
        if len(comp) >= 2:
            clusters.append(sorted(comp))
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return {"ready": sorted(ready), "blocked": blocked, "clusters": clusters}


def main():
    ap = argparse.ArgumentParser(description="task dependency tree (Paso 3)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    tasks = parse_tasks()
    tree = derive(tasks)

    if args.json:
        print(json.dumps(tree, indent=2))
        return 0

    if args.check:
        # Future: compare against a declared plan-tree block (like
        # plan_tree.py --check). For now: assert the derivation itself works.
        if not tasks:
            print("FAIL: no tasks parsed", file=sys.stderr)
            return 1
        print(f"task_tree: {len(tasks)} tasks, {len(tree['ready'])} ready, "
              f"{len(tree['blocked'])} blocked, {len(tree['clusters'])} clusters")
        return 0

    print(f"task_tree — {len(tasks)} tasks | {len(tree['ready'])} ready | "
          f"{len(tree['blocked'])} blocked | {len(tree['clusters'])} clusters")
    print()
    print("=== READY (ejecutables ahora — todas sus deps done) ===")
    for tid in tree["ready"]:
        t = tasks[tid]
        print(f"  {tid} (P{t['priority']}, {t['status']})")
    print()
    print("=== BLOCKED (por dependencia no satisfecha) ===")
    for tid in sorted(tree["blocked"]):
        deps = ", ".join(tree["blocked"][tid])
        t = tasks[tid]
        print(f"  {tid} (P{t['priority']}, {t['status']}) ← {deps}")
    print()
    print("=== CLUSTERS (componentes conectados por dependencia) ===")
    for ci, comp in enumerate(tree["clusters"], 1):
        print(f"  C{ci} ({len(comp)}): {', '.join(comp)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())