#!/usr/bin/env python3
"""fork_watch.py — import-contamination check (S5 containment).

History: this used to watch drift between the pip-editable vos_kernel copy
(~/packages/... canonical RUNTIME) and the vOSlab dev line (S5 hybrid path
2026-09-23). The 2026-10-04 S5 containment circle repointed every editable
install at the vOSlab sources, so there is no fork left to watch — the
remaining failure mode is contamination: a package resolving OUTSIDE the
workspace again.

Now: for each vendored package, assert its import resolves under vOSlab.
Exit 0 = all clean; 1 = any package resolves outside (or import fails).

Usage: python3 scripts/ops/fork_watch.py [--json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[2]

# Vendored editable packages (S5 containment): name -> expected prefix
VENDORED = {
    "vos_kernel": VOSLAB / "packages" / "framework",
    "socratic_engine": VOSLAB / "packages" / "public" / "socratic-engine",
    "state_canon": VOSLAB / "packages" / "public" / "state-canon-mcp",
    "vsf_rsi": VOSLAB / "packages" / "public" / "vsf-rsi",
}


def check() -> dict:
    results: dict[str, dict] = {}
    for name, expected in VENDORED.items():
        try:
            mod = __import__(name)
            origin = str(getattr(mod, "__file__", "") or "")
            inside = origin.startswith(str(VOSLAB))
            results[name] = {
                "inside": inside,
                "origin": origin,
                "expected_prefix": str(expected),
            }
        except Exception as exc:
            results[name] = {"inside": False, "error": str(exc)[:200]}
    return results


def main() -> int:
    results = check()
    outside = {k: v for k, v in results.items() if not v.get("inside")}
    if "--json" in sys.argv:
        print(json.dumps({"clean": not outside, "packages": results}, indent=2))
    else:
        for name, info in results.items():
            mark = "ok  " if info.get("inside") else "OUT "
            detail = info.get("origin") or info.get("error", "")
            print(f"  {mark} {name:16} {detail}")
        if outside:
            print(f"CONTAMINATION — {len(outside)} package(s) resolve outside vOSlab")
        else:
            print(f"CLEAN — {len(results)} vendored packages resolve inside vOSlab")
    return 1 if outside else 0


if __name__ == "__main__":
    sys.exit(main())
