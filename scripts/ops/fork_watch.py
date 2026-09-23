#!/usr/bin/env python3
"""fork_watch.py — permanent drift check between vos_kernel copies (Path C).

S5 decision 2026-09-23: hybrid path. Pip copy
(/home/rmw3/packages/framework/vos_kernel) is canonical RUNTIME;
vOSlab copy (packages/framework/vos_kernel) is dev line under review.
While the modular architecture is not consolidated, this check runs
to push toward consolidation: it reports divergence drift and FAILS
if NEW divergence appears beyond the baselined set (i.e., someone
edits one copy without mirroring intent).

Compares two pairs (layouts differ):
  code:  <pip>/vos_kernel  vs  <vslab>/  (minus vslab-only top level:
          tests, handlers, pyproject.toml, README)
  tests: <pip>/tests       vs  <vslab>/tests

Usage: python3 scripts/ops/fork_watch.py [--json]
Exit 0 = no new divergence; 1 = new divergence or error.
"""
from __future__ import annotations

import filecmp
import json
import sys
from pathlib import Path

PIP_REPO = Path("/home/rmw3/packages/framework/vos_kernel")
VSL_REPO = Path("/home/rmw3/vOSlab/packages/framework/vos_kernel")

CODE_PAIR = (PIP_REPO / "vos_kernel", VSL_REPO)
CODE_SKIP_VSL = {"tests", "handlers", "pyproject.toml", "README.md",
                 ".pytest_cache", "__pycache__"}
TESTS_PAIR = (PIP_REPO / "tests", VSL_REPO / "tests")

# Baselined 2026-09-23 (relative to pair roots, S5 pending big-4).
KNOWN_DIVERGENT_CODE = {
    "backbone/backbone.py",
    "backbone/rsi_bridge.py",
    "backbone/socratic_bridge.py",
    "utils/vsm_kernel.py",
    "covenant.py",  # synced 2026-09-23, kept listed until stable
    "invariants.py",  # equivalent fragility, no functional delta
    "backbone/backbone_event.py",  # pip kept (vsf_common unimportable)
    "backbone/canon_bridge.py",  # pip kept (env-default beats hardcoded)
    "adapters/state_canon_agent.py",  # synced GAP-09 2026-09-23
}
KNOWN_VSLAB_ONLY = {
    "backbone/backbone_steps.py",
}
# pip-only modules baselined 2026-09-23 (pre-date the watch; part of the
# installed package surface, not new divergence)
KNOWN_PIP_ONLY_CODE = {
    "utils/agent_results.py",
    "utils/vsm_timestamp.py",
    "utils/focus_extended.py",
    "utils/__init__.py",
}
KNOWN_DIVERGENT_TESTS: set = set()
KNOWN_VSLAB_ONLY_TESTS: set = set()
KNOWN_PIP_ONLY_TESTS: set = {"test_vos_kernel.py"}


def _py_files(root: Path, skip_top: set) -> dict:
    out = {}
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root)
        if rel.parts[0] in skip_top:
            continue
        out[str(rel)] = p
    return out


def _compare(pair, skip, known_div, known_a_only, known_b_only,
             aname, bname, result):
    pa, pb = pair
    if not pa.is_dir() or not pb.is_dir():
        result["errors"].append(f"missing dir: {pa} / {pb}")
        return
    fa = _py_files(pa, set())
    fb = _py_files(pb, skip)
    for rel, p in fa.items():
        q = fb.get(rel)
        if q is None:
            if rel not in known_a_only:
                result[f"new_{aname}_only"].append(rel)
        elif not filecmp.cmp(p, q, shallow=False):
            if rel not in known_div:
                result["new_divergent"].append(rel)
        elif rel in known_div:
            result["resolved"].append(rel)
    for rel in fb:
        if rel not in fa and rel not in known_b_only:
            result[f"new_{bname}_only"].append(rel)


def run() -> dict:
    result = {"new_divergent": [], "new_pip_only": [],
              "new_voslab_only": [], "resolved": [], "errors": []}
    _compare(CODE_PAIR, CODE_SKIP_VSL, KNOWN_DIVERGENT_CODE,
             KNOWN_PIP_ONLY_CODE, KNOWN_VSLAB_ONLY, "pip", "voslab", result)
    _compare(TESTS_PAIR, set(), KNOWN_DIVERGENT_TESTS,
             KNOWN_PIP_ONLY_TESTS, KNOWN_VSLAB_ONLY_TESTS,
             "pip", "voslab", result)
    result["ok"] = not (result["new_divergent"] or result["new_pip_only"]
                        or result["new_voslab_only"] or result["errors"])
    return result


def main() -> int:
    as_json = "--json" in sys.argv
    try:
        r = run()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    if as_json:
        print(json.dumps(r, indent=2))
    else:
        if r["ok"]:
            print(f"fork-watch OK: no new divergence "
                  f"({len(r['resolved'])} baselined files now identical)")
        else:
            print("fork-watch FAIL: new divergence detected")
            for k in ("new_divergent", "new_pip_only", "new_voslab_only",
                      "errors"):
                for f in r[k]:
                    print(f"  {k}: {f}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
