#!/usr/bin/env python3
"""audit_write_events.py — G-28: wire the kernel runtime surface to the
write path (audit-only, phase 1).

Invoked by scripts/shared/git_pre_commit.sh over every staged file.
For each event it runs BOTH runtime surfaces that previously had zero
production callers:

  1. vos_kernel.invariants.InvariantChecker.check_preconditions
     (a0_no_prohibited, trust_bounds, file_protection)
  2. vos_kernel.enforcer.AuditEnforcer.audit (covenant A0.1/TRUST/A5)

Phase-1 contract (enforcer.py): never blocks, never raises — the
counterfactual lands in the unified log (logs/agent_plugin.jsonl,
standard {ts,pid,instrument,hook,action,result,detail} format).
Promotion to enforcement is an S5 call, gated on this audit trail.

Exit codes: 0 always (audit must not break commits); --self-test exits
1 if the surfaces fail to produce a record (discriminating fixture).

Usage:
    python3 scripts/ops/audit_write_events.py            # staged files
    python3 scripts/ops/audit_write_events.py --self-test
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "framework"))

from vos_kernel.enforcer import AuditEnforcer  # noqa: E402
from vos_kernel.invariants import InvariantChecker  # noqa: E402

INSTRUMENT = "vos-kernel-write-audit"
HOOK = "pre-commit"
LOG_PATH = Path(os.environ.get("VOS_LOG_DIR", REPO / "logs")) / "agent_plugin.jsonl"
#: trust granted to a human-confirmed commit (not an autonomous write)
COMMIT_TRUST = 0.8
COMMIT_AUTONOMY = 0.5


def _log(action: str, result: str, detail: dict) -> None:
    # schema per agent-policy/agent_instruments.vsm + check_agent_log.py:
    # ts (ISO offset), source, event_type, action, result are required;
    # instrument/hook carry the G-28 claim context.
    now = datetime.now(timezone.utc)
    record = {
        "ts": now.isoformat(),
        "pid": os.getpid(),
        "level": "activation",
        "source": INSTRUMENT,
        "event_type": "write.audit",
        "event_id": f"{INSTRUMENT}:{action}:{now.timestamp():.0f}",
        "instrument": INSTRUMENT,
        "hook": HOOK,
        "action": action,
        "result": result,
        "detail": detail,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _staged_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, cwd=REPO, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _staged_content(path: str) -> str:
    try:
        return subprocess.run(
            ["git", "show", f":{path}"],
            capture_output=True, text=True, cwd=REPO, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return ""


def audit_event(event: dict, content: str = "") -> dict:
    """Run both runtime surfaces over one event. Never raises."""
    checker = InvariantChecker()
    try:
        pre = checker.check_preconditions(
            action="write",
            file=event.get("file", ""),
            content=content,
            trust=float(event.get("s5_trust", COMMIT_TRUST)),
            autonomy=float(event.get("autonomy", COMMIT_AUTONOMY)),
        )
        pre_detail = {"passed": pre.passed, "failures": pre.failures}
    except Exception as exc:  # noqa: BLE001 — audit must not break commits
        pre_detail = {"passed": False, "failures": [f"check_error: {exc}"]}
    verdict = AuditEnforcer().audit(event)
    return {
        "file": event.get("file", ""),
        "invariants": pre_detail,
        "covenant": {"would_block": verdict.would_block, "rule": verdict.rule},
    }


def run_staged() -> int:
    checker = InvariantChecker()
    enforcer = AuditEnforcer()
    if not checker._pre_checks.get("write") or enforcer is None:
        # surface regression: make it visible without blocking the commit
        _log("kernel_write_surface", "error",
             {"detail": "no write pre-checks registered (G-28 regression)"})
        return 0
    for path in _staged_files():
        content = _staged_content(path)
        detail = audit_event(
            {"tool": "write", "file": path,
             "s5_trust": COMMIT_TRUST, "autonomy": COMMIT_AUTONOMY},
            content=content,
        )
        result = "ok"
        if not detail["invariants"]["passed"] or detail["covenant"]["would_block"]:
            result = "would_block"
        _log("kernel_write_audit", result, detail)
    return 0


def self_test() -> int:
    """Fixture event that MUST produce a record (discriminating)."""
    before = LOG_PATH.read_text() if LOG_PATH.exists() else ""
    detail = audit_event(
        {"tool": "write", "file": "selftest.txt",
         "s5_trust": 0.8, "autonomy": 0.5},
        content="clean content for audit",
    )
    _log("kernel_write_audit", "selftest", detail)
    after = LOG_PATH.read_text() if LOG_PATH.exists() else ""
    if after == before or not detail["invariants"]["passed"]:
        sys.stderr.write(f"self-test failed: {detail}\n")
        return 1
    # negative discrimination: prohibited keyword must flip invariants
    bad = audit_event(
        {"tool": "write", "file": "selftest.txt",
         "s5_trust": 0.8, "autonomy": 0.5},
        content="warfare is prohibited content",
    )
    if bad["invariants"]["passed"]:
        sys.stderr.write(f"discrimination failed: {bad}\n")
        return 1
    print(f"self-test ok: {detail['covenant']['would_block']=}, "
          f"clean_pass={detail['invariants']['passed']}, "
          f"dirty_fail={not bad['invariants']['passed']}")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    return run_staged()


if __name__ == "__main__":
    sys.exit(main())
