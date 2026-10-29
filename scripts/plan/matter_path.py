#!/usr/bin/env python3
# design: docs/design/sandbox/matter-ontology-v1/matter_ontology.vsm
"""matter_path.py — derive the matter trunk from an ABox + TASKS.vsm.

Read-only. The ABox (matters_pilot.vsm / MATTERS.vsm) declares STRUCTURE
only: id, kind, parent, roles, authority, purpose, evidence. Task status is
read from TASKS.vsm (R7: one status canon; the ABox never duplicates it).
The derived tree is computed every run — no state is stored in the doc (R10).

Usage:
  matter_path.py A01-01-RUST-TRANSLATION
  matter_path.py A01-01-RUST-TRANSLATION --json
  matter_path.py --graph [--abox <path> --tasks <path>]
  matter_path.py --trunk [--abox <path> --tasks <path>]
  matter_path.py A01-01-RUST-TRANSLATION --abox <path> --tasks <path>

--graph emits nodes + edges (contains, evidences, synthesis, depends_on);
it is the graph view, not just the trunk. --trunk prints the lineage of
every task whose status in TASKS.vsm is active (boot view). Read-only,
deterministic (R10).
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PILOT_ABOX = os.path.join(
    ROOT, "docs", "spec_revision", "sandbox", "matter-ontology-v1", "matters_pilot.vsm"
)
TASKS = os.path.join(ROOT, "TASKS.vsm")

MATTER_RE = re.compile(r'^\s*matter\("', re.M)
TASK_RE = re.compile(r'task\("([A-Z0-9\-_]+)"[^)]*\)\s*=\s*\{')
STATUS_RE = re.compile(r'^\s*status:\s*([a-z_]+)', re.M)
DEP_RE = re.compile(r'^\s*(?:depends_on|blocked_on):\s*(.+)$', re.M)
TASK_ID_RE = re.compile(r'^[A-Z0-9\-_]+$')

DONE_STATUSES = {"done", "closed"}
ACTIVE_STATUSES = {
    "active", "in_progress", "open", "partial", "discovery", "seeded",
    "queued", "deployed", "reopened",
}


def _split_top(s, sep=","):
    """Split on sep at top level, respecting quotes and [] {} ()."""
    out, buf = [], []
    depth = 0
    quote = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and quote and i + 1 < len(s):
            buf.append(c)
            buf.append(s[i + 1])
            i += 2
            continue
        if c == '"':
            quote = not quote
        elif not quote:
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == sep and depth == 0:
                out.append("".join(buf).strip())
                buf = []
                i += 1
                continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1]
    return v


def _parse_value(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_unquote(x) for x in _split_top(inner) if x.strip()]
    return _unquote(v)


def _matching_paren(text, open_idx):
    depth = 0
    quote = False
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "\\" and quote:
            i += 2
            continue
        if c == '"':
            quote = not quote
        elif not quote:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def parse_abox(path):
    """Parse matter(...) calls. Returns id -> dict."""
    text = open(path, encoding="utf-8").read()
    matters = {}
    for m in MATTER_RE.finditer(text):
        open_idx = text.index("(", m.start())
        close_idx = _matching_paren(text, open_idx)
        if close_idx < 0:
            continue
        args = text[open_idx + 1:close_idx]
        parts = _split_top(args)
        if not parts:
            continue
        mid = _unquote(parts[0])
        rec = {
            "id": mid,
            "kind": "",
            "parent": None,
            "roles": [],
            "authority": "",
            "purpose": "",
            "evidence": [],
            "synthesis": None,
        }
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip()
            if key in ("kind", "parent", "authority", "purpose", "synthesis"):
                rec[key] = _parse_value(val)
            elif key == "roles":
                rec[key] = _parse_value(val)
            elif key == "evidence":
                rec[key] = _parse_value(val)
        matters[mid] = rec
    return matters


def parse_tasks(path=TASKS):
    """Parse task blocks: id -> {status, deps}. Same block scanner as task_tree.py."""
    text = open(path, encoding="utf-8").read()
    tasks = {}
    for m in TASK_RE.finditer(text):
        start = m.end()
        depth = 1
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
        sm = STATUS_RE.search(body)
        dm = DEP_RE.search(body)
        deps = []
        if dm:
            raw = dm.group(1).strip()
            # supports: "A", ["A", "B"], A+B, A, B
            for part in re.split(r'[",\[\]\s+]+', raw):
                part = part.strip()
                if part and TASK_ID_RE.match(part):
                    deps.append(part)
        tasks[m.group(1)] = {
            "status": sm.group(1) if sm else "?",
            "deps": deps,
        }
    return tasks


def build_children(matters):
    children = defaultdict(list)
    for mid, rec in matters.items():
        if rec.get("parent"):
            children[rec["parent"]].append(mid)
    for kids in children.values():
        kids.sort()
    return children


def build_graph(matters, tasks):
    """Build the matter graph (nodes + edges), deterministic order (R10).

    Edges emitted today:
      contains   parent → child (ABox parent)
      evidences  matter → evidence ref (ABox evidence; refs become nodes)
      synthesis  matter → ancestor (ABox synthesis)
      depends_on task → task (TASKS.vsm depends_on/blocked_on; direct scope)

    Other TBox relations (ratifies, produces, supersedes, informs, blocks)
    are declared in the design but are not populated by the ABox yet.
    """
    nodes = {}
    edges = []
    seen_edges = set()

    def add_node(mid, rec, source="ABox"):
        if mid in nodes:
            return
        node = {
            "id": mid,
            "kind": rec.get("kind") or "",
            "roles": list(rec.get("roles") or []),
            "authority": rec.get("authority") or "",
            "source": source,
            "parent": rec.get("parent"),
        }
        if rec.get("kind") == "task":
            node["status"] = tasks.get(mid, {}).get("status", "?")
        nodes[mid] = node

    def add_edge(a, b, typ):
        if not a or not b:
            return
        key = (a, b, typ)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": a, "to": b, "type": typ})

    for mid, rec in matters.items():
        add_node(mid, rec)

    for mid, rec in matters.items():
        parent = rec.get("parent")
        if parent:
            add_edge(parent, mid, "contains")

        for ev in rec.get("evidence") or []:
            ev = str(ev).strip()
            if not ev:
                continue
            eid = "ref:" + ev
            if eid not in nodes:
                nodes[eid] = {
                    "id": eid,
                    "kind": "evidence-ref",
                    "source": "ABox.evidence",
                    "ref": ev,
                }
            add_edge(mid, eid, "evidences")

        syn = rec.get("synthesis")
        if syn:
            add_edge(mid, syn, "synthesis")

    for mid, rec in matters.items():
        if rec.get("kind") != "task":
            continue
        for dep in tasks.get(mid, {}).get("deps", []):
            if dep not in nodes:
                dep_rec = tasks.get(dep)
                nodes[dep] = {
                    "id": dep,
                    "kind": "task",
                    "roles": ["work"],
                    "authority": "gate/parent",
                    "source": "TASKS.vsm" if dep_rec else "missing",
                    "status": dep_rec.get("status", "?") if dep_rec else "?",
                    "parent": None,
                }
            add_edge(mid, dep, "depends_on")

    return {
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: (e["from"], e["type"], e["to"])),
    }


def trunk(ref, matters):
    """Root-to-ref lineage. Raises KeyError for unknown ref or missing parent."""
    if ref not in matters:
        raise KeyError(ref)
    chain = []
    seen = set()
    cur = ref
    while cur:
        if cur in seen:
            raise ValueError("cycle at %s" % cur)
        seen.add(cur)
        chain.append(cur)
        cur = matters[cur].get("parent")
        if cur and cur not in matters:
            raise KeyError("missing parent %s" % cur)
    return list(reversed(chain))


def descendants(ref, children):
    out = []
    seen = set()
    stack = list(children.get(ref, []))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        out.append(cur)
        stack.extend(children.get(cur, []))
    return out


def derived_state(ref, matters, children, tasks):
    rec = matters[ref]
    if rec.get("kind") == "task":
        st = tasks.get(ref, {}).get("status", "?")
        if st in DONE_STATUSES:
            return "done"
        if st in ACTIVE_STATUSES:
            return "active"
        return st
    kids = descendants(ref, children)
    task_ids = [k for k in kids if matters[k].get("kind") == "task"]
    if task_ids:
        done = sum(1 for k in task_ids if tasks.get(k, {}).get("status") in DONE_STATUSES)
        if done == len(task_ids) and rec.get("evidence"):
            return "closed"
        if done == len(task_ids):
            return "review"
        if any(tasks.get(k, {}).get("status") in ACTIVE_STATUSES for k in task_ids):
            return "active"
        return "proposed"
    if rec.get("evidence"):
        return "closed"
    return "seed"


def summarize(ref, matters, children, tasks):
    rec = matters[ref]
    kids = descendants(ref, children)
    task_ids = [k for k in kids if matters[k].get("kind") == "task"]
    if rec.get("kind") == "task":
        task_ids = [ref] + task_ids
    done = sum(1 for k in task_ids if tasks.get(k, {}).get("status") in DONE_STATUSES)
    return {
        "id": ref,
        "kind": rec.get("kind"),
        "roles": rec.get("roles", []),
        "authority": rec.get("authority"),
        "derived": derived_state(ref, matters, children, tasks),
        "tasks_total": len(task_ids),
        "tasks_done": done,
        "evidence": rec.get("evidence", []),
        "trunk": trunk(ref, matters),
    }


def print_tree(ref, matters, children, tasks, indent=0, out=None):
    out = out or sys.stdout
    rec = matters[ref]
    state = derived_state(ref, matters, children, tasks)
    roles = ",".join(rec.get("roles", [])) or "-"
    line = "%s%s  [%s | %s | %s]" % ("  " * indent, ref, rec.get("kind") or "-", roles, rec.get("authority") or "-")
    if rec.get("kind") == "task":
        line += "  status=%s" % tasks.get(ref, {}).get("status", "?")
    line += "  derived=%s" % state
    print(line, file=out)
    for kid in children.get(ref, []):
        print_tree(kid, matters, children, tasks, indent + 1, out=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Derive the matter trunk (read-only).")
    ap.add_argument("ref", nargs="?", help="matter id, e.g. A01-01-RUST-TRANSLATION (omit with --graph)")
    ap.add_argument("--abox", default=None, help="ABox path (default: MATTERS.vsm if present, else pilot)")
    ap.add_argument("--tasks", default=TASKS, help="TASKS.vsm path")
    ap.add_argument("--json", action="store_true", help="machine-readable output for the trunk")
    ap.add_argument("--graph", action="store_true", help="emit nodes + edges JSON (contains, evidences, synthesis, depends_on)")
    ap.add_argument("--trunk", action="store_true", help="print the trunk line(s) for every active task")
    args = ap.parse_args(argv)
    if args.graph and args.trunk:
        ap.error("--graph and --trunk are mutually exclusive")

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

    matters = parse_abox(abox)
    tasks = parse_tasks(args.tasks)

    if args.graph:
        out = {
            "abox": abox,
            "tasks": args.tasks,
            "scope": "ABox + direct TASKS deps",
        }
        out.update(build_graph(matters, tasks))
        print(json.dumps(out, indent=2))
        return 0

    if not args.ref and not args.trunk:
        ap.error("ref is required unless --graph or --trunk is used")
    children = build_children(matters)

    # Fail loud on a broken lineage before deriving anything (R10: no hang,
    # no partial tree on a cycle or a missing parent).
    for mid in matters:
        try:
            trunk(mid, matters)
        except (KeyError, ValueError) as exc:
            print("ERROR: broken lineage at %s: %s" % (mid, exc), file=sys.stderr)
            return 2

    if args.trunk:
        lines = []
        for mid, rec in matters.items():
            if rec.get("kind") != "task":
                continue
            if tasks.get(mid, {}).get("status") not in ACTIVE_STATUSES:
                continue
            line = "trunk: %s" % " → ".join(trunk(mid, matters))
            if line not in lines:
                lines.append(line)
        if args.json:
            print(json.dumps({"trunks": lines}, indent=2))
        elif lines:
            print("\n".join(lines))
        else:
            print("trunk: (no active task)")
        return 0

    try:
        info = summarize(args.ref, matters, children, tasks)
    except KeyError as exc:
        print("ERROR: matter not found or parent missing: %s" % exc, file=sys.stderr)
        return 2
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(info, indent=2))
        return 0

    print("MATTER PATH — %s" % args.ref)
    print("trunk: %s" % " → ".join(info["trunk"]))
    print()
    print_tree(info["trunk"][0], matters, children, tasks)
    print()
    print("derived: %s" % info["derived"])
    print("tasks: %d/%d done" % (info["tasks_done"], info["tasks_total"]))
    print("evidence: %d%s" % (
        len(info["evidence"]),
        (" (" + ", ".join(info["evidence"]) + ")") if info["evidence"] else "",
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
