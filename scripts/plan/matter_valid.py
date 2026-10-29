#!/usr/bin/env python3
# design: docs/design/sandbox/matter-ontology-v1/matter_ontology.vsm
"""matter_valid.py — validate the matter ABox invariants (pilot form).

Read-only. Checks the ABox + TASKS.vsm cross-reference:
  R1 parent-or-purpose     R2 no phantom tasks     R3 no orphan tasks
  R4 purpose authority      R5 close needs evidence + synthesis
  R6 no duplicate/cycle     R7 ABox never declares task status
  R8 graph edges resolve    R9 depends_on is acyclic

Exit 0 if no errors, 1 otherwise. --self-test builds broken fixtures and
asserts that the validator discriminates them (negative control).
"""
import argparse
import os
import re
import sys
import tempfile

import matter_path as mp

ROOT = mp.ROOT
PILOT_ABOX = mp.PILOT_ABOX
TASKS = mp.TASKS

RAW_ID_RE = re.compile(r'^\s*matter\("([^"]+)"', re.M)
STATUS_DECL_RE = re.compile(r'^\s*matter\([^\n]*\bstatus\s*=', re.M)

DONE = {"done", "closed"}


def _dep_cycle(edges):
    """Return the first depends_on cycle as a list, or None (deterministic)."""
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    state = {}          # 0/absent unvisited, 1 visiting, 2 done
    stack = []

    def dfs(node):
        state[node] = 1
        stack.append(node)
        for nxt in sorted(adj.get(node, [])):
            if state.get(nxt, 0) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if state.get(nxt, 0) == 0:
                cyc = dfs(nxt)
                if cyc:
                    return cyc
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(adj):
        if state.get(node, 0) == 0:
            cyc = dfs(node)
            if cyc:
                return cyc
    return None


def validate_graph(matters, tasks):
    """Validate graph integrity: edges resolve, depends_on acyclic, synthesis
    points to an ancestor. Returns (graph, errors). Deterministic (R10)."""
    graph = mp.build_graph(matters, tasks)
    errors = []
    ids = [n["id"] for n in graph["nodes"]]
    id_set = set(ids)

    seen = set()
    for nid in ids:
        if nid in seen:
            errors.append(("DUPLICATE_NODE", nid, "node id repeated"))
        seen.add(nid)

    for e in graph["edges"]:
        if e["from"] not in id_set:
            errors.append(("EDGE_MISSING_NODE", e["from"],
                           "edge source missing (%s→%s)" % (e["from"], e["to"])))
        if e["to"] not in id_set:
            errors.append(("EDGE_MISSING_NODE", e["to"],
                           "edge target missing (%s→%s)" % (e["from"], e["to"])))

    for n in graph["nodes"]:
        if n.get("source") == "missing":
            errors.append(("MISSING_DEP", n["id"],
                           "depends_on target not in TASKS.vsm"))

    dep_edges = [(e["from"], e["to"]) for e in graph["edges"] if e["type"] == "depends_on"]
    cyc = _dep_cycle(dep_edges)
    if cyc:
        errors.append(("DEP_CYCLE", " → ".join(cyc), "depends_on cycle"))

    for e in graph["edges"]:
        if e["type"] != "synthesis":
            continue
        try:
            chain = mp.trunk(e["from"], matters)
        except Exception:
            continue
        if e["to"] == e["from"] or e["to"] not in chain:
            errors.append(("SYNTHESIS_NOT_ANCESTOR", e["from"],
                           "synthesis target %s is not an ancestor" % e["to"]))

    return graph, errors


def validate(abox_path, tasks_path=TASKS):
    text = open(abox_path, encoding="utf-8").read()
    matters = mp.parse_abox(abox_path)
    tasks = mp.parse_tasks(tasks_path)
    children = mp.build_children(matters)

    errors = []
    warnings = []

    def err(code, mid, msg):
        errors.append((code, mid, msg))

    def warn(code, mid, msg):
        warnings.append((code, mid, msg))

    # R6 — duplicate ids (parser collapses them, so count raw calls)
    raw_ids = RAW_ID_RE.findall(text)
    seen = set()
    for mid in raw_ids:
        if mid in seen:
            err("DUPLICATE_ID", mid, "id declared more than once")
        seen.add(mid)

    # R7 — the ABox never declares task status
    for m in STATUS_DECL_RE.finditer(text):
        snippet = m.group(0).strip()
        err("STATUS_IN_ABOX", snippet, "status is TASKS.vsm canon; remove it from the ABox")

    for mid, rec in sorted(matters.items()):
        kind = rec.get("kind") or ""
        roles = rec.get("roles") or []
        parent = rec.get("parent")

        # R1 / R3 — parent-or-purpose
        is_purpose = kind == "purpose" or "purpose" in roles
        if not parent:
            if kind == "task":
                err("ORPHAN_TASK", mid, "task has no parent matter")
            elif not is_purpose:
                err("ORPHAN", mid, "non-purpose matter has no parent")
        elif parent not in matters:
            err("MISSING_PARENT", mid, "parent not in ABox: %s" % parent)

        # R4 — purpose roots carry an authority ref
        if is_purpose and not parent and not rec.get("authority"):
            err("PURPOSE_NO_AUTHORITY", mid, "purpose root has no authority ref")

        # R2 — task references resolve in TASKS.vsm
        if kind == "task":
            if mid not in tasks:
                err("PHANTOM_TASK", mid, "task not found in TASKS.vsm")
            elif tasks[mid].get("status") in DONE and not rec.get("evidence"):
                warn("DONE_TASK_NO_EVIDENCE", mid, "done task has no evidence ref in the ABox")

        # R5 — closed matters need evidence + synthesis to the parent
        if kind != "task":
            try:
                state = mp.derived_state(mid, matters, children, tasks)
            except Exception:
                state = "?"
            if state == "closed":
                if not rec.get("evidence"):
                    err("CLOSE_NO_EVIDENCE", mid, "closed matter has no evidence ref")
                if not rec.get("synthesis"):
                    err("CLOSE_NO_SYNTHESIS", mid, "closed matter has no synthesis edge")

    # R6 — cycles
    for mid in matters:
        try:
            mp.trunk(mid, matters)
        except ValueError as exc:
            err("CYCLE", mid, str(exc))
        except KeyError as exc:
            # already reported as MISSING_PARENT; keep a single diagnostic
            if not any(c == "MISSING_PARENT" and i == mid for c, i, _ in errors):
                err("MISSING_PARENT", mid, str(exc))

    # R8/R9 — graph integrity
    graph, gerrors = validate_graph(matters, tasks)
    errors.extend(gerrors)

    return matters, tasks, graph, errors, warnings


def print_report(abox_path, matters, tasks, graph, errors, warnings):
    print("MATTER VALID — %s" % abox_path)
    print("matters: %d  tasks: %d  purposes: %d  graph_nodes: %d  edges: %d" % (
        len(matters),
        sum(1 for r in matters.values() if r.get("kind") == "task"),
        sum(1 for mid, r in matters.items() if not r.get("parent") and ("purpose" in (r.get("roles") or []) or r.get("kind") == "purpose")),
        len(graph["nodes"]),
        len(graph["edges"]),
    ))
    by_type = {}
    for e in graph["edges"]:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    if by_type:
        print("edge types: %s" % ", ".join("%s=%d" % (k, by_type[k]) for k in sorted(by_type)))
    for code, mid, msg in errors:
        print("ERROR [%s] %s — %s" % (code, mid, msg))
    for code, mid, msg in warnings:
        print("WARN  [%s] %s — %s" % (code, mid, msg))
    print("")
    print("%s: %d errors, %d warnings" % ("OK" if not errors else "FAIL", len(errors), len(warnings)))
    return 0 if not errors else 1


def self_test_graph():
    """Synthetic graph fixture: missing dep, depends_on cycle, bad synthesis,
    missing edge target. The validator must report every seeded defect."""
    matters = {
        "ROOT": {"id": "ROOT", "kind": "paper", "parent": None, "roles": ["purpose"],
                 "authority": "S5", "evidence": [], "synthesis": None},
        "A": {"id": "A", "kind": "task", "parent": "ROOT", "roles": ["work"],
              "authority": "parent", "evidence": [], "synthesis": None},
        "B": {"id": "B", "kind": "task", "parent": "ROOT", "roles": ["work"],
              "authority": "parent", "evidence": [], "synthesis": None},
        "C": {"id": "C", "kind": "artifact", "parent": "ROOT", "roles": ["evidence"],
              "authority": "parent", "evidence": ["x"], "synthesis": "B"},
        "D": {"id": "D", "kind": "artifact", "parent": "ROOT", "roles": ["evidence"],
              "authority": "parent", "evidence": [], "synthesis": "NOPE"},
    }
    tasks = {
        "A": {"status": "active", "deps": ["B", "MISSING"]},
        "B": {"status": "active", "deps": ["A"]},
    }
    graph, errors = validate_graph(matters, tasks)
    codes = set(code for code, _, _ in errors)
    expected = {"MISSING_DEP", "DEP_CYCLE", "SYNTHESIS_NOT_ANCESTOR", "EDGE_MISSING_NODE"}
    missing = sorted(expected - codes)
    print("SELF-TEST GRAPH — synthetic fixture")
    print("nodes: %d  edges: %d  errors: %d" % (len(graph["nodes"]), len(graph["edges"]), len(errors)))
    print("codes: %s" % ", ".join(sorted(codes)))
    if missing:
        print("FAIL: graph validator missed: %s" % ", ".join(missing))
        return 1
    print("PASS: graph validator discriminates every seeded defect")
    return 0


def self_test(tasks_path=TASKS):
    fixture = "\n".join([
        'matter("ROOT", kind="paper", roles=["purpose"], authority="S5")',
        'matter("ORPHAN-TASK", kind="task", roles=["work"], authority="parent")',
        'matter("ORPHAN-MATTER", kind="phase", roles=["work"], authority="parent")',
        'matter("PURPOSE-NO-AUTH", kind="paper", roles=["purpose"])',
        'matter("MISSING-PARENT", kind="phase", parent="NOPE", roles=["work"], authority="parent")',
        'matter("PHANTOM-TASK", kind="task", parent="ROOT", roles=["work"], authority="parent")',
        'matter("CYCLE-A", kind="phase", parent="CYCLE-B", roles=["work"], authority="parent")',
        'matter("CYCLE-B", kind="phase", parent="CYCLE-A", roles=["work"], authority="parent")',
        'matter("DUP", kind="artifact", parent="ROOT", roles=["evidence"], authority="parent")',
        'matter("DUP", kind="artifact", parent="ROOT", roles=["evidence"], authority="parent")',
        'matter("BAD-STATUS", kind="task", parent="ROOT", roles=["work"], authority="parent", status="active")',
        'matter("CLOSED-NO-SYNTH", kind="artifact", parent="ROOT", roles=["evidence"], authority="parent", evidence=["x"])',
        "",
    ])
    fd, path = tempfile.mkstemp(prefix="matter_valid_selftest_", suffix=".vsm")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(fixture)
        _, _, _, errors, _ = validate(path, tasks_path)
        codes = set(code for code, _, _ in errors)
        expected = {
            "ORPHAN_TASK", "ORPHAN", "PURPOSE_NO_AUTHORITY", "MISSING_PARENT",
            "PHANTOM_TASK", "CYCLE", "DUPLICATE_ID", "STATUS_IN_ABOX",
            "CLOSE_NO_SYNTHESIS",
        }
        missing = sorted(expected - codes)
        print("SELF-TEST — broken fixture")
        print("errors detected: %d" % len(errors))
        print("codes: %s" % ", ".join(sorted(codes)))
        if missing:
            print("FAIL: validator missed: %s" % ", ".join(missing))
            return 1
        print("PASS: validator discriminates every seeded defect")
        return self_test_graph()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate matter ABox invariants (read-only).")
    ap.add_argument("--abox", default=None, help="ABox path (default: MATTERS.vsm if present, else pilot)")
    ap.add_argument("--tasks", default=TASKS, help="TASKS.vsm path")
    ap.add_argument("--self-test", action="store_true", help="run the negative-control fixture")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test(args.tasks)

    abox = args.abox
    if not abox:
        root_abox = os.path.join(ROOT, "MATTERS.vsm")
        abox = root_abox if os.path.exists(root_abox) else PILOT_ABOX
    if not os.path.exists(abox):
        print("ERROR: ABox not found: %s" % abox, file=sys.stderr)
        return 2
    if not os.path.exists(args.tasks):
        print("ERROR: TASKS not found: %s" % args.tasks, file=sys.stderr)
        return 2

    matters, tasks, graph, errors, warnings = validate(abox, args.tasks)
    return print_report(abox, matters, tasks, graph, errors, warnings)


if __name__ == "__main__":
    sys.exit(main())
