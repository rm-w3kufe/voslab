# design: docs/plans/system_backlog.vsm (SUT: scripts/state/tasks/focus_maintain.py)
"""Tests for focus_maintain.py (tasks-maintenance rewire, S5 2026-10-03).

The handler's four modes must discriminate: validate rejects violations
(rc!=0), while reconcile/check/closed are advisory reports (rc=0) that
still surface their findings as output. All state is fixture-based —
no live current_focus.json dependency.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

VOS_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = VOS_ROOT / "scripts" / "state" / "tasks" / "focus_maintain.py"


def _entry(ref: str, status: str = "done", note: str = "short note",
           started: str = "2026-10-01T01:02:03Z",
           updated: str | None = None, **extra) -> dict:
    if updated is None:
        # Dynamic "recent" default — hardcoding dates made this a time-bomb
        # (fixture 2026-10-02 went stale once wall-clock passed 2026-10-09).
        updated = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    entry = {"ref": ref, "status": status, "note": note,
             "started_at": started, "updated_at": updated}
    entry.update(extra)
    return entry


@pytest.fixture()
def focus_env(tmp_path):
    """focus_maintain pointed at a temp focus file + details dir."""
    focus = tmp_path / "current_focus.json"
    details = tmp_path / "state" / "focus_details"
    details.mkdir(parents=True)
    focus.write_text(json.dumps([_entry("T-OK")]), encoding="utf-8")
    # Load the real script (module-level _VOS_ROOT resolves from its own
    # __file__), then rebind its state paths to the fixture.
    import importlib.util
    spec = importlib.util.spec_from_file_location("focus_maintain", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.FOCUS_FILE = focus
    mod.FOCUS_DETAILS = details
    mod._VOS_ROOT = tmp_path
    return mod


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30,
    )


def test_validate_ok_on_valid_fixture(focus_env):
    assert focus_env.cmd_validate(None) == 0


def test_validate_rejects_violations(focus_env):
    focus_env.FOCUS_FILE.write_text(json.dumps([
        _entry("T-BAD", status="wrong", note="x" * 600,
               started="not-a-date", extra_field=1),
    ]), encoding="utf-8")
    assert focus_env.cmd_validate(None) == 1


def test_reconcile_flags_missing_detail_file(focus_env, capsys):
    focus_env.FOCUS_FILE.write_text(json.dumps([
        _entry("T-LOST", detail="state/focus_details/T-LOST.md"),
    ]), encoding="utf-8")
    assert focus_env.cmd_reconcile(None) == 0  # advisory: rc=0
    out = capsys.readouterr().out
    assert "1 finding(s)" in out and "file missing" in out


def test_reconcile_flags_time_inversion(focus_env, capsys):
    focus_env.FOCUS_FILE.write_text(json.dumps([
        _entry("T-TIME", started="2026-10-05T00:00:01Z",
               updated="2026-10-04T00:00:01Z"),
    ]), encoding="utf-8")
    assert focus_env.cmd_reconcile(None) == 0
    assert "later than" in capsys.readouterr().out


def test_check_counts_and_stale_active(focus_env, capsys):
    focus_env.FOCUS_FILE.write_text(json.dumps([
        _entry("T-ACT-OLD", status="active", updated="2026-09-01T01:02:03Z"),
        _entry("T-ACT-NEW", status="active"),
        _entry("T-PAUSED", status="paused"),
        _entry("T-DONE", status="done"),
    ]), encoding="utf-8")
    assert focus_env.cmd_check(None) == 0
    out = capsys.readouterr().out
    assert "2 active · 1 paused · 1 done" in out
    assert "stale active: T-ACT-OLD" in out
    assert "stale active: T-ACT-NEW" not in out


def test_closed_dry_run_lists_only_old_done(focus_env, capsys):
    focus_env.FOCUS_FILE.write_text(json.dumps([
        _entry("T-OLD", status="done", updated="2026-01-01T01:02:03Z"),
        _entry("T-RECENT", status="done"),
        _entry("T-ACTIVE-STALE", status="active", updated="2026-01-01T01:02:03Z"),
    ]), encoding="utf-8")
    assert focus_env.cmd_closed(None) == 0
    out = capsys.readouterr().out
    assert "1 archive candidate" in out and "T-OLD" in out
    assert "T-RECENT" not in out and "T-ACTIVE-STALE" not in out


def test_cli_validate_live_focus(focus_env):
    """CLI path against the repo's real current_focus.json must be valid
    (the focus-format gate contract, via the script's rc discrimination)."""
    proc = _run("--validate")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bridge_task_context_maps_focus_statuses():
    """G-19: query context must treat focus statuses (active/paused) as work,
    not the legacy open/in_progress vocabulary that never matches."""
    sys.path.insert(0, str(VOS_ROOT / ".opencode" / "plugins" / "operational"))
    from tool_integration_bridge import get_current_task_context  # noqa: E402

    tasks = [_entry("T1", status="active"), _entry("T2", status="paused"),
             _entry("T3", status="done")]
    ctx = get_current_task_context(tasks)
    assert ctx["has_work"] is True
    assert ctx["in_progress_count"] == 1
    assert ctx["open_count"] == 1
    assert ctx["active_task"]["ref"] == "T1"

    assert get_current_task_context([_entry("T3", status="done")])["has_work"] is False
    assert get_current_task_context([])["has_work"] is False


def test_bridge_socratic_canon_sessions_routes_to_log_spans(monkeypatch, capsys):
    """G-19 sub (W-5): domain 'sessions' must not fall through to the
    provider's phantom session() domain (task_tracking phase_1, never
    built -> always 0). It routes to query_sessions() — the log-span scan
    — same dead-cable class as the G-19 'tasks'->focus alias. Unknown
    domains still return count 0. Deterministic (R10): the log scan is
    monkeypatched so the assertion holds on any disk state (a fresh clone
    has no heartbeat spans yet)."""
    sys.path.insert(0, str(VOS_ROOT / ".opencode" / "plugins" / "operational"))
    import tool_integration_bridge as bridge  # noqa: E402

    fake = [{"id": "agent_plugin.jsonl.123.jsonl.gz",
             "started": "2026-10-07T10:00:00Z",
             "ended": "2026-10-07T10:30:00Z", "idles": 2,
             "rotated_at": "2026-10-07T11:00:00+00:00",
             "last_result": "ok"}]
    seen: dict = {}

    def _fake_query_sessions(filter_dict=None):
        seen["filter"] = filter_dict
        return list(fake)

    monkeypatch.setattr(bridge, "query_sessions", _fake_query_sessions)

    bridge.cmd_socratic_canon(["sessions", '{"last_result": "ok"}'])
    out = json.loads(capsys.readouterr().out)
    assert out == {"domain": "sessions", "count": 1, "results": fake}
    assert seen["filter"] == {"last_result": "ok"}  # filter reaches the scan

    bridge.cmd_socratic_canon(["nonexistent-domain", "{}"])
    out = json.loads(capsys.readouterr().out)
    assert out == {"domain": "nonexistent-domain", "count": 0, "results": []}
