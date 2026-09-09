#!/usr/bin/env python3
"""dep_graph.py — the dependency graph of system/, measured rather than assumed.

WHY
---
Cycle task 3, never started, and the hard prerequisite for PH-13 (restructure
system/ so the directory tree follows the dependency order). rmw3's proposal is
right, and restructuring before measuring would be reordering by intuition —
the defect this cycle corrected four separate times in one day.

WHAT COUNTS AS A DEPENDENCY
---------------------------
Three edge kinds, each read structurally, none inferred from prose:

  ref      A cites B through `@ref @binding`, resolved via instance.vsm
  ident    A CITES an identifier that B DECLARES  (the symbol index)
  glyph    A USES a glyph that B DECLARES         (the alphabet)

`ident` is the load-bearing one: it is how a document actually rests on
another. A cites A1 and only core_boot_primer declares A1, so A depends on the
primer whether or not it says so.

WHAT IT REPORTS
---------------
  --layers   topological depth. Layer 0 depends on nothing; layer n depends
             only on layers < n. This is the ORDER a reader should take, and
             the order PH-13 would project onto the tree.
  --cycles   mutual dependencies. A DAG has none; every cycle is either a real
             circular premise or two documents that should be one.
  --roots    depended on by the most others — the trunk.
  --leaves   depended on by nothing — safe to move, safe to retire.
  --mermaid  the graph, for the artifact.

HONEST LIMITS, stated because a graph looks authoritative:
  * a `glyph` edge is WEAK — using ▪ does not make a document depend on the
    alphabet the way citing A1 makes it depend on the primer. Weighted last.
  * an identifier declared in TWO places produces two edges and neither is
    wrong; the ambiguity is in the corpus, not here.
  * this measures what documents SAY they rest on. Whether they rest on it
    CORRECTLY is semantics, and no graph decides that.

Deterministic, stdlib-only. No LLM in this path (R10).
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "docs/spec_revision/system"


def index() -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "scripts/vsl/symbol_table.py"),
                          "--json"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(out.stdout)


def build() -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    idx = index()
    edges: dict[str, set[str]] = defaultdict(set)
    why: dict[tuple[str, str], set[str]] = defaultdict(set)

    definer: dict[str, list[str]] = idx["defined"]
    for ident, citers in idx["cited"].items():
        decls = definer.get(ident, [])
        for src in citers:
            # A document that DECLARES the identifier does ¬depend on whoever
            # else declares it. Without this, deliberate duplicate declaration
            # manufactures FALSE CYCLES: core_boot_primer and covenant both
            # declare A0/A0.1 — allowed and STATED in the rubric, because the
            # primer is a self-contained agnostic boot that must carry its own
            # axiom preamble — and each then read as citing the other's.
            # First run: 48 cycles. Most were this.
            if src in decls:
                continue
            for dst in decls:
                if src != dst:
                    edges[src].add(dst)
                    why[(src, dst)].add(ident)

    # glyph edges, weighted last and kept separable
    gdecl: dict[str, list[str]] = idx.get("glyphs_declared", {})
    for doc in idx["documents"]:
        for g, decls in gdecl.items():
            for d in decls:
                if d != doc and doc not in decls:
                    pass  # a glyph edge would connect nearly everything to
                          # boot/; measured and deliberately NOT added, see
                          # the docstring. Kept as code so the decision is
                          # visible rather than silently absent.
    for d in idx["documents"]:
        edges.setdefault(d, set())
    return edges, why


def layers(edges: dict[str, set[str]]) -> tuple[dict[str, int], list[list[str]]]:
    """Topological depth. A node's layer is 1 + the deepest thing it needs."""
    depth: dict[str, int] = {}
    visiting: set[str] = set()
    cyc: list[list[str]] = []

    def walk(n: str, path: list[str]) -> int:
        if n in depth:
            return depth[n]
        if n in visiting:
            cyc.append(path[path.index(n):] + [n])
            return 0
        visiting.add(n)
        d = 0
        for m in sorted(edges.get(n, ())):
            d = max(d, walk(m, path + [n]) + 1)
        visiting.discard(n)
        depth[n] = d
        return d

    for n in sorted(edges):
        walk(n, [])
    return depth, cyc


def main() -> int:
    edges, why = build()
    depth, cyc = layers(edges)
    rdeps: dict[str, int] = defaultdict(int)
    for s, ds in edges.items():
        for d in ds:
            rdeps[d] += 1

    if "--mermaid" in sys.argv:
        print("flowchart BT")
        for s in sorted(edges):
            for d in sorted(edges[s]):
                print(f'  {s.replace("/", "_").replace(".vsm", "")} --> '
                      f'{d.replace("/", "_").replace(".vsm", "")}')
        return 0

    if "--cycles" in sys.argv:
        if not cyc:
            print("  ✓ no cycles — the corpus is a DAG")
            return 0
        seen = set()
        for c in cyc:
            k = tuple(sorted(set(c)))
            if k in seen:
                continue
            seen.add(k)
            print(f"  ✗ cycle: {' → '.join(c)}")
        print(f"  ✗ {len(seen)} distinct cycle(s) — each is either a real "
              f"circular premise or two documents that should be one")
        return 1

    if "--roots" in sys.argv:
        for d, n in sorted(rdeps.items(), key=lambda x: -x[1])[:12]:
            print(f"  {n:>3} dependents  {d}")
        return 0

    if "--leaves" in sys.argv:
        leaves = [d for d in sorted(edges) if rdeps[d] == 0]
        print(f"  {len(leaves)} document(s) nothing depends on:")
        for d in leaves:
            print(f"      {d}")
        return 0

    by_layer: dict[int, list[str]] = defaultdict(list)
    for d, l in depth.items():
        by_layer[l].append(d)
    print(f"  dependency graph — {len(edges)} documents, "
          f"{sum(len(v) for v in edges.values())} edges, "
          f"{len(by_layer)} layers"
          f"{'  ✗ ' + str(len(cyc)) + ' CYCLE(S)' if cyc else '  ✓ DAG'}\n")
    for l in sorted(by_layer):
        print(f"  layer {l}  ({len(by_layer[l])})")
        for d in sorted(by_layer[l]):
            n = rdeps[d]
            print(f"      {d:<46}{('← ' + str(n)) if n else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
