"""test_rbac.py — SEC-001-2 thin slice: role table + enforcement.

Hermetic by construction: every case is a CLI subprocess with its own
VOS_ROLE env (the _run_bridge pattern). No module imports (vsf_rsi dir
freeze discipline), no audit-log assertions (deny lines go to the real
unified log — verified manually once, not per-run).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
BRIDGE = (VOSLAB / ".opencode" / "plugins" / "operational"
          / "tool_integration_bridge.py")


def _run(cmd, *args, role=None):
    env = dict(os.environ)
    if role is None:
        env.pop("VOS_ROLE", None)
    else:
        env["VOS_ROLE"] = role
    p = subprocess.run(
        [sys.executable, "-W", "ignore", str(BRIDGE), cmd, *args],
        capture_output=True, text=True, timeout=120, cwd=str(VOSLAB),
        env=env,
    )
    assert p.returncode == 0, f"bridge {cmd} rc={p.returncode}"
    raw = p.stdout.strip()
    return json.loads(raw[raw.index("{"):])


def test_observer_denied_governor_command():
    out = _run("rsi-approve", "no-such-pred", role="observer")
    assert "RBAC denied" in out.get("error", "")
    assert "governor" in out["error"]


def test_bogus_role_fails_closed_to_observer():
    out = _run("rsi-approve", "no-such-pred", role="root")
    assert "RBAC denied" in out.get("error", "")
    assert "role=observer" in out["error"]


def test_governor_covers_reads():
    out = _run("rsi-queue", "pending", role="governor")
    assert out.get("status_filter") == "pending"


def test_observer_allowed_reads():
    out = _run("session-report", role="observer")
    # Contract (session-lifecycle.ts session.created/idle reads these):
    # report.session.{total,success,failure} + report.tasks.{total,done}.
    # The stats-only shape asserted before the S2 repair made those
    # accesses TypeError (session_report_payload, 2026-10-03).
    assert "total" in out["session"]
    assert "success" in out["session"]
    assert "total" in out["tasks"]
    assert "done" in out["tasks"]
    assert "total" in out["sessions"]


def test_default_role_keeps_loop_working():
    out = _run("pipeline-before",
               json.dumps({"tool": "bash", "file": "", "command": "",
                           "is_state_changing": True}))
    assert out.get("mode") == "min"
    assert out["preCheck"]["ok"] is True


def test_operator_denied_governor_command():
    out = _run("rsi-threshold-set", "read_warn_bytes", "65536",
               role="operator")
    assert "RBAC denied" in out.get("error", "")
