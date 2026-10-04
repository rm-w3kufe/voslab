#!/usr/bin/env python3
"""drift_inventory.py — regenerate the consolidated drift inventory (S4).

One command, every mechanical declared-vs-observed source in vOSlab:

  1. state-canon reconcilers (focus + tasks domains) — the same instance
     module the MCP server runs, loaded in-process (no MCP round-trip)
  2. instrument-set audit — vsf_checks/checks_manifest.json vs checks/

Writes state/drift_inventory.json (append-safe snapshot: ts, per-source
entries, counts). rc 0 = inventory written (detection is the product —
drift entries are content, not failure); rc 1 only on internal error.

Usage:
    python3 scripts/state/canon/drift_inventory.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
OUT = VOSLAB / "state" / "drift_inventory.json"


def _canon_drifts() -> dict:
    """Fresh diff from the state-canon instance reconcilers."""
    inst = VOSLAB / "scripts" / "state" / "canon" / "voslab_instance.py"
    spec = importlib.util.spec_from_file_location("voslab_instance", inst)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _provider, reconcilers = mod.load(str(VOSLAB / "current_focus.json"))
    domains: dict[str, list] = {}
    for rec in reconcilers:
        domains[str(getattr(rec, "domain", "?"))] = [
            d.as_dict() for d in rec.diff()
        ]
    return domains


def _instrument_set() -> dict:
    """Declared vs observed for the checks manifest."""
    vsf = VOSLAB / "packages" / "public" / "vsf-checks"
    spec = importlib.util.spec_from_file_location(
        "vsf_regen_manifest", vsf / "vsf_checks" / "regen_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    problems = mod.drift_problems()
    return {
        "consistent": not problems,
        "declared": len(mod.declared_index()),
        "observed": len(mod.observed()),
        "problems": problems,
    }


def main() -> int:
    try:
        canon = _canon_drifts()
        instrument = _instrument_set()
    except Exception as e:
        print(f"drift inventory FAILED: {e}", file=sys.stderr)
        return 1

    canon_drifts = sum(len(v) for v in canon.values())
    inv = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "canon": {
            "domains": sorted(canon),
            "drift_count": canon_drifts,
            "drifts": {k: v for k, v in canon.items() if v},
        },
        "instrument_set": instrument,
        "total_drift": canon_drifts + len(instrument["problems"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(inv, indent=2, ensure_ascii=False) + "\n")

    print(f"drift inventory -> {OUT.relative_to(VOSLAB)}")
    print(f"  canon: {canon_drifts} drift(s) across {len(canon)} domain(s) "
          f"({', '.join(sorted(canon))})")
    state = "consistent" if instrument["consistent"] else "DRIFT"
    print(f"  instrument set: {state} "
          f"({instrument['declared']} declared / {instrument['observed']} observed)")
    for p in instrument["problems"]:
        print(f"    {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
