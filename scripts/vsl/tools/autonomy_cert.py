#!/usr/bin/env python3
"""autonomy_cert.py — C1-C6 autonomy-ready drill (import plan P2.2).

Each autonomy class must PROVE its gate blocks (or learns) on live
behavior — declarations don't certify. Deterministic, no network.

  C1 forbidden commands block      (action_forbidden)
  C2 forbidden paths block         (path_forbidden, both directions)
  C3 policy file CLI-only          (policy_locked)
  C4 closed-lab writes             (write_scope_ok)
  C5 retry-loops block             (not_redundant, triple repeat)
  C6 scenario learns               (record + match roundtrip, DRILL- probe)

Usage: autonomy_cert.py [--json]
Exit codes: 0 all pass, 1 any fail (prints failing checks).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VOSLAB / "system" / "kernel"))

from socratic_engine import Truth  # noqa: E402


def _check(name, cond, detail=""):
    return {"check": name, "pass": bool(cond), "detail": detail}


def run() -> list[dict]:
    import rsi_cycle
    import stub_predicates as sp
    out = []

    r = rsi_cycle.action_forbidden("bash", "", "rm -rf /")
    out.append(_check("C1-forbidden-command",
                      r.truth == Truth.FALSE and r.certified))

    r = rsi_cycle.path_forbidden("/etc/shadow", tool="read")
    out.append(_check("C2-forbidden-path-read",
                      r.truth == Truth.FALSE and r.certified))
    r = sp.script_domain_ok("../../../root/.ssh")
    out.append(_check("C2-traversal",
                      r.truth == Truth.FALSE and r.certified))

    from access_policy import policy_path
    r = sp.policy_locked("write", str(policy_path()))
    out.append(_check("C3-policy-cli-only",
                      r.truth == Truth.FALSE and r.certified))

    r = sp.write_scope_ok("write", "/etc/cron.d/x")
    out.append(_check("C4-scope-outside-blocked",
                      r.truth == Truth.FALSE and r.certified))
    r = sp.write_scope_ok("write", str(VOSLAB / "docs" / "x.vsm"))
    out.append(_check("C4-scope-inside-allowed",
                      r.truth == Truth.TRUE and r.certified))

    recent = [{"tool": "bash", "file": "", "command": "do risky",
               "outcome": "error"}] * 3
    r = sp.not_redundant("bash", "", "do risky", recent_actions=recent)
    out.append(_check("C5-retry-loop-blocked",
                      r.truth == Truth.FALSE and r.certified))

    try:
        from vsf_rsi.scenario_memory import record, match
        eid = record(decision="DRILL autonomy-cert",
                     outcome="failure",
                     correction_path="autonomy_cert:C6",
                     fault_signature="DRILL-autonomy-cert-probe")
        hits = match("DRILL-autonomy-cert-probe", threshold=0.0) or []
        out.append(_check("C6-scenario-learns",
                          bool(eid) and len(hits) > 0,
                          f"id={eid} matches={len(hits)}"))
    except Exception as e:
        out.append(_check("C6-scenario-learns", False, str(e)[:120]))
    return out


def main(argv: list[str]) -> int:
    results = run()
    failed = [r for r in results if not r["pass"]]
    if "--json" in argv:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            mark = "PASS" if r["pass"] else "FAIL"
            extra = f" ({r['detail']})" if r.get("detail") else ""
            print(f"{mark} {r['check']}{extra}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
