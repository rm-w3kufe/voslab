#!/usr/bin/env python3
# design: docs/plans/covenant_promotion_procedure.vsm (SUT: scripts/s5-governance/covenant_update.py)
"""test_covenant_update.py — tests for the expedited covenant procedure.

Covers the programmatic core (scripts/s5-governance/covenant_update.py)
and the tree-driven flow (covenant-update.tree.vsm evaluated through the
same bridge gap-resolver uses, so home derivation is tested end-to-end).

Standalone: python3 scripts/tests/test_covenant_update.py → exit 0/1.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "scripts" / "s5-governance" / "covenant_update.py"
BRIDGE = REPO / ".opencode" / "plugins" / "operational" / "tool_integration_bridge.py"
TREE = REPO / ".opencode" / "plugins" / "support" / "trees" / "covenant-update.tree.vsm"
GAPDEF = REPO / ".opencode" / "plugins" / "operational" / "gap-definitions" / "covenant-update.gap.json"

_failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _failures
    if cond:
        print(f"  PASS {name} — {detail}")
    else:
        _failures += 1
        print(f"  FAIL {name} — {detail}")


def run(args: list[str], timeout: int = 60) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                       cwd=str(REPO))
    return r.returncode, (r.stdout + r.stderr)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree_home(ctx: dict) -> dict:
    # 60s (was 30): the bridge is 1.5-3.8s normally but exceeded 30s once
    # under parallel battery contention (flaky TimeoutExpired found by scope
    # certification 2026-10-02, run1 rc=1 / run2-3 rc=0).
    rc, out = run([sys.executable, str(BRIDGE), "socratic-tree-file",
                   str(TREE), json.dumps(ctx)], timeout=60)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"error": f"rc={rc} out={out[:200]}"}


def main() -> int:
    print("=" * 60)
    print("covenant_update.py — expedited procedure tests")
    print("=" * 60)

    # ── plan ----------------------------------------------------------------
    rc, out = run([sys.executable, str(CLI), "plan", "--json"])
    check("plan --json exits 0", rc == 0, f"rc={rc}")
    try:
        d = json.loads(out)
        json_ok, json_detail = True, ""
    except json.JSONDecodeError as e:
        d, json_ok, json_detail = {}, False, str(e)
    check("plan --json parses", json_ok, json_detail)
    state = d.get("state", "")
    check("plan state is a known value",
          state in {"CONSISTENT", "DRIFT_LOCAL", "STAGED"},
          f"state={state}")
    check("plan hash is 64-hex",
          bool(re.fullmatch(r"[0-9a-f]{64}", d.get("hash") or "")),
          f"hash={(d.get('hash') or '?')[:16]}…")
    checks = d.get("checks") or []
    check("plan reports ≥4 witnesses", len(checks) >= 4,
          f"n={len(checks)}: {[c['name'] for c in checks]}")

    rc2, out2 = run([sys.executable, str(CLI), "plan"])
    check("plan (human) exits 0", rc2 == 0, f"rc={rc2}")

    # ── stage dry-run must NOT write ----------------------------------------
    targets = [REPO / "LICENSE", REPO / "core" / "s5_policy.default.json",
               REPO / "system" / "boot" / "covenant_hash_registry.vsm"]
    before = {p: sha(p) for p in targets}
    rc3, out3 = run([sys.executable, str(CLI), "stage"])
    after = {p: sha(p) for p in targets}
    check("stage (dry-run) exits 0", rc3 == 0, f"rc={rc3}")
    check("stage dry-run writes nothing", before == after,
          "changed: " + ", ".join(str(p.name) for p in targets if before[p] != after[p]) or "none")
    check("stage dry-run says DRY RUN", "DRY RUN" in out3,
          "banner present")

    # ── s5-plan --------------------------------------------------------------
    anchor = sha(REPO / "docs" / "governance" / "covenant.vsm")
    rc4, out4 = run([sys.executable, str(CLI), "s5-plan"])
    check("s5-plan exits 0", rc4 == 0, f"rc={rc4}")
    check("s5-plan carries the anchor", anchor in out4, f"anchor={anchor[:16]}…")
    check("s5-plan has the S5-on-n01 block", "S5 on n01" in out4, "step 3/6")
    check("s5-plan orders publish LAST", out4.find("publish LAST") >
          out4.find("S5 on n01"), "step 5 after step 3")
    check("s5-plan demands sha receipt", "sha256sum" in out4, "receipt by hash")
    check("s5-plan ends with verify", "verify --beacon --remote" in out4, "step 6")

    # ── verify (local) --------------------------------------------------------
    rc5, out5 = run([sys.executable, str(CLI), "verify"])
    check("verify (local) exits 0 on current state", rc5 == 0,
          f"rc={rc5} tail={out5.strip().splitlines()[-1] if out5.strip() else '?'}")

    # ── tree via the gap-resolver bridge (home derivation) ---------------------
    for st, home in [("CONSISTENT", "VERIFY_OK"),
                     ("DRIFT_LOCAL", "APPLY_LOCAL"),
                     ("STAGED", "S5_ACTIONS")]:
        res = tree_home({"covenantAudit_state": st, "covenantAudit": {"state": st}})
        check(f"tree {st} → {home}",
              res.get("home") == home and res.get("certified") is True,
              f"home={res.get('home')} certified={res.get('certified')} err={res.get('error', '')}")

    res_empty = tree_home({"filePath": "x"})
    check("tree without audit → UNKNOWN (R9)",
          res_empty.get("decision") == "UNKNOWN" and not res_empty.get("home"),
          f"decision={res_empty.get('decision')} home={res_empty.get('home')}")

    # state key present but unrecognized → deterministic else_home label
    # (distinct from R9's UNKNOWN, which only fires when the key is absent)
    res_bad = tree_home({"covenantAudit_state": "NONSENSE", "covenantAudit": {}})
    check("tree unrecognized state → else_home AUDIT_UNAVAILABLE",
          res_bad.get("home") == "AUDIT_UNAVAILABLE",
          f"home={res_bad.get('home')} decision={res_bad.get('decision')}")

    # ── gap-def / wiring ------------------------------------------------------
    try:
        gap = json.loads(GAPDEF.read_text())
        g_ok = True
    except (OSError, json.JSONDecodeError) as e:
        gap, g_ok = {}, False
        print(f"  gap-def read error: {e}")
    check("gap-def parses", g_ok, GAPDEF.name)
    conds = [a.get("condition") for a in gap.get("actions", [])]
    check("gap-def fires run-script on APPLY_LOCAL",
          any("APPLY_LOCAL" in (c or "") for c in conds), f"conds={conds}")
    check("gap-def fires show-s5-commands on S5_ACTIONS",
          any("S5_ACTIONS" in (c or "") for c in conds), f"conds={conds}")
    check("gap-def alerts on UNKNOWN (else_home, R9)",
          any("decision === 'UNKNOWN'" in (c or "") for c in conds), f"conds={conds}")
    check("gap-def alerts on AUDIT_UNAVAILABLE (recognized-key else_home)",
          any("decision === 'AUDIT_UNAVAILABLE'" in (c or "") for c in conds), f"conds={conds}")
    gath = gap.get("context", {}).get("gatherers", [])
    check("gap-def uses run-audit gatherer",
          any(g.get("type") == "run-audit" for g in gath), f"gatherers={[g.get('type') for g in gath]}")

    # ── registry count-guard (unit) --------------------------------------------
    sys.path.insert(0, str(CLI.parent))
    import covenant_update as cu
    good = '  current: {\n    hash:      "' + "a" * 64 + '",\n  }'
    _, h = cu._read_current(good)
    check("_read_current extracts hash", h == "a" * 64, h[:16])
    try:
        cu._read_current("no current block here")
        guard_ok, guard_detail = False, "no SystemExit raised"
    except SystemExit as e:
        guard_ok, guard_detail = True, str(e)[:60]
    check("_read_current count-guard aborts on malformed registry",
          guard_ok, guard_detail)

    print("=" * 60)
    if _failures:
        print(f"FAILED           ({_failures} check(s))")
        return 1
    print("ALL TESTS PASSED          (exit=0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
