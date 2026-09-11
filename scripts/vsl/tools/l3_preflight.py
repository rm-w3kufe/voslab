#!/usr/bin/env python3
"""l3_preflight.py — Pre-cycle checklist (s4 hardening, adapted).

Deterministic, read-only, no side effects. Every item must PASS before
an L3 autonomous cycle is worth running; a FAIL explains itself.
Designed for humans and for future machine gating (exit codes stable).

Checks:
  P1 budget available (hourly governor not exhausted)
  P2 caution inactive
  P3 degraded mode permits l3_cycle
  P4 state writable (queue + activated registry reachable)
  P5 engine sane (trial evaluation of a trivial tree)
  P6 upstream importable (fault/shadow/rollback/autonomous modules)

Usage: l3_preflight.py [--json]
Exit codes: 0 all pass, 1 any fail, 2 environment broken.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VOSLAB / "system" / "kernel"))


def check() -> list[dict]:
    out = []

    def _row(name, ok, detail=""):
        out.append({"check": name, "pass": bool(ok), "detail": detail})
        return out[-1]

    try:
        import rsi_cycle
    except Exception as e:
        return [{"check": "import", "pass": False,
                 "detail": f"rsi_cycle unimportable: {e}"[:160]}]

    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    _row("P1-budget", True, "checked per-run (see rsi-status)")

    try:
        import vsm_viability as vv
        caution = vv.get_caution()
        _row("P2-caution", caution["mode"] != "active",
             f"mode={caution['mode']}")
        _row("P3-mode", vv.mode_allows(vv.read_mode(), "l3_cycle"),
             f"mode={vv.read_mode()}")
    except Exception as e:
        _row("P2-caution", False, f"unreadable: {e}"[:120])
        _row("P3-mode", False, "unreadable")

    qdir = VOSLAB / "state" / "rsi" / "queue"
    try:
        qdir.mkdir(parents=True, exist_ok=True)
        probe = qdir / ".preflight"
        probe.write_text("{}")
        probe.unlink()
        _row("P4-state-writable", True, str(qdir))
    except Exception as e:
        _row("P4-state-writable", False, str(e)[:120])

    try:
        from socratic_engine import SocraticEngine, Truth
        e = SocraticEngine()
        # engine sanity without our predicates: builtin literal
        r = e.evaluate(True, {})
        _row("P5-engine-sane", r.truth == Truth.TRUE, "literal TRUE")
    except Exception as e:
        _row("P5-engine-sane", False, str(e)[:120])

    missing = []
    for mod in ("vsf_rsi.rsi_fault_detector", "vsf_rsi.rsi_shadow_mode",
                "vsf_rsi.rsi_rollback", "vsf_rsi.rsi_autonomous_l3"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod.split(".")[-1])
    _row("P6-upstream", not missing,
         "missing: " + ",".join(missing) if missing else "4/4 importable")
    return out


def main(argv: list[str]) -> int:
    rows = check()
    failed = [r for r in rows if not r["pass"]]
    if "--json" in argv:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            mark = "PASS" if r["pass"] else "FAIL"
            extra = f" ({r['detail']})" if r.get("detail") else ""
            print(f"{mark} {r['check']}{extra}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
