# design: docs/plans/refs_optimization_proposal.vsm (SUT: scripts/state/monitoring/persistence_nudge.py)
"""Tests for persistence_nudge.py (§6.1 close-checklist nudge, F4.1).

Fixture-based (no live workspace dependency): temp focus file, temp
rounds dir, temp git repo. Unit tests inject `now` (deterministic R10);
subprocess tests inject it via --now (same contract, no wall-clock decay).
the CLI contract (--json) runs hermetic against the same fixtures.
Advisory contract under test: rc=0 whenever a report could be produced,
even when the checklist fails.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

VOS_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = VOS_ROOT / "scripts" / "state" / "monitoring" / "persistence_nudge.py"

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def _load_module():
    spec = importlib.util.spec_from_file_location("persistence_nudge", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _round_name(dt: datetime) -> str:
    return f"ROUND-{dt.strftime('%Y%m%dT%H%M%S%f')}Z.json"


def _entry(ref: str, status: str = "active",
           updated: datetime | None = None) -> dict:
    updated = updated or (NOW - timedelta(hours=1))
    return {"ref": ref, "status": status, "note": "n",
            "started_at": _iso(updated - timedelta(minutes=5)),
            "updated_at": _iso(updated)}


def _write_focus(path: Path, entries: list[dict]) -> Path:
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _mk_repo(path: Path, message: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *args: subprocess.run(  # noqa: E731
        args, cwd=path, capture_output=True, text=True, timeout=30)
    run("git", "init", "-q")
    run("git", "config", "user.email", "test@test")
    run("git", "config", "user.name", "t")
    (path / "f.txt").write_text("x\n", encoding="utf-8")
    run("git", "add", "f.txt")
    proc = run("git", "-c", "commit.gpgsign=false", "commit", "-q",
               "-m", message)
    assert proc.returncode == 0, proc.stderr
    return path


@pytest.fixture()
def env(tmp_path):
    """Fresh fixtures: green focus, fresh round, session-block commit."""
    focus = _write_focus(tmp_path / "current_focus.json",
                         [_entry("T-ACTIVE")])
    rounds = tmp_path / "rounds"
    rounds.mkdir()
    (rounds / _round_name(NOW - timedelta(hours=2))).write_text("{}")
    repo = _mk_repo(tmp_path / "repo", "feat: work\n\nsession(11:58Z)")
    marker = tmp_path / "state" / "rsi" / ".persistence_nudge_last"
    marker.parent.mkdir(parents=True)
    return {"focus": focus, "rounds": rounds, "repo": repo,
            "marker": marker, "tmp": tmp_path}


# ── unit: evaluate() over fixtures ──────────────────────────────────────────

def test_green_checklist(env):
    report = mod.evaluate(env["focus"], env["rounds"], env["repo"],
                          24.0, 168.0, NOW)
    assert report["ok"] is True
    assert report["failed"] == []
    assert [c["id"] for c in report["checks"]] == [
        "focus_fresh", "session_block", "learn_fresh"]
    assert all(c["ok"] for c in report["checks"])
    assert report["focus_refs"] == ["T-ACTIVE"]
    assert report["newest_ref"] == "T-ACTIVE"
    assert report["ts"] == _iso(NOW).replace("Z", "+00:00")


def test_stale_focus_fails(env):
    _write_focus(env["focus"],
                 [_entry("T-ACTIVE", updated=NOW - timedelta(hours=48))])
    report = mod.evaluate(env["focus"], env["rounds"], env["repo"],
                          24.0, 168.0, NOW)
    assert report["ok"] is False
    assert report["failed"] == ["focus_fresh"]
    detail = report["checks"][0]["detail"]
    assert "48.0h" in detail and "max 24h" in detail


def test_missing_focus_file(env):
    report = mod.evaluate(env["tmp"] / "nope.json", env["rounds"],
                          env["repo"], 24.0, 168.0, NOW)
    assert report["checks"][0]["ok"] is False
    assert "missing" in report["checks"][0]["detail"]


def test_empty_focus_fails(env):
    _write_focus(env["focus"], [])
    check, refs, newest = mod.check_focus(env["focus"], 24.0, NOW)
    assert check["ok"] is False
    assert "no focus entries" in check["detail"]
    assert refs == [] and newest is None


def test_unparsable_focus_timestamp_fails(env):
    _write_focus(env["focus"], [
        {"ref": "T1", "status": "active", "updated_at": "not-a-date"}])
    check, _, _ = mod.check_focus(env["focus"], 24.0, NOW)
    assert check["ok"] is False
    assert "no parseable" in check["detail"]


def test_focus_refs_only_active(env):
    _write_focus(env["focus"], [
        _entry("T-DONE", status="done", updated=NOW - timedelta(hours=2)),
        _entry("T-ACTIVE", updated=NOW - timedelta(hours=3)),
        _entry("T-PAUSED", status="paused", updated=NOW - timedelta(hours=4)),
    ])
    check, refs, newest = mod.check_focus(env["focus"], 24.0, NOW)
    assert check["ok"] is True  # newest overall = T-DONE (2h) → fresh
    assert refs == ["T-ACTIVE"]
    assert newest == "T-ACTIVE"


# ── unit: session_block ─────────────────────────────────────────────────────

def test_commit_without_session_block(env):
    repo = _mk_repo(env["tmp"] / "repo2", "fix: no session block here")
    check = mod.check_session_block(repo)
    assert check["ok"] is False
    assert "session(" in check["detail"]
    assert "fix: no session block here" in check["detail"]


def test_no_git_repo_skips(env):
    plain = env["tmp"] / "plain"
    plain.mkdir()
    check = mod.check_session_block(plain)
    assert check["ok"] is True
    assert "skip" in check["detail"]


def test_git_unavailable_skips(env, monkeypatch):
    def boom(*_args, **_kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(mod.subprocess, "run", boom)
    check = mod.check_session_block(env["repo"])
    assert check["ok"] is True
    assert "git unavailable" in check["detail"]


# ── unit: learn_fresh ───────────────────────────────────────────────────────

def test_stale_round_fails(env):
    stale_name = _round_name(NOW - timedelta(days=10))
    (env["rounds"] / stale_name).write_text("{}")
    # remove the fresh fixture round so the stale one is the newest
    for path in env["rounds"].glob("ROUND-*.json"):
        if path.name != stale_name:
            path.unlink()
    check = mod.check_learn(env["rounds"], 168.0, NOW)
    assert check["ok"] is False
    assert "240.0h" in check["detail"]  # 10 days


def test_newest_round_wins(env):
    (env["rounds"] / _round_name(NOW - timedelta(days=30))).write_text("{}")
    check = mod.check_learn(env["rounds"], 168.0, NOW)
    assert check["ok"] is True  # fresh fixture round (2h) is newest


def test_missing_rounds_dir(env):
    check = mod.check_learn(env["tmp"] / "no-rounds", 168.0, NOW)
    assert check["ok"] is False
    assert "missing" in check["detail"]


# ── unit: throttle marker ───────────────────────────────────────────────────

def test_throttle_marker_windows(env):
    marker = env["marker"]
    marker.write_text("t")
    fresh = (NOW - timedelta(hours=1)).timestamp()
    os.utime(marker, (fresh, fresh))
    assert mod.is_throttled(marker, 6.0, NOW) is True
    old = (NOW - timedelta(hours=7)).timestamp()
    os.utime(marker, (old, old))
    assert mod.is_throttled(marker, 6.0, NOW) is False
    marker.unlink()
    assert mod.is_throttled(marker, 6.0, NOW) is False


# ── CLI contract (hermetic subprocess) ──────────────────────────────────────

def _run(*args: str) -> subprocess.CompletedProcess:
    # reloj fijo: los fixtures se construyen sobre NOW — sin --now los
    # tests subprocess caducaban 24h despues de escribirse (time-bomb)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--now", _iso(NOW), *args],
        capture_output=True, text=True, timeout=30)


def test_json_contract_green(env):
    proc = _run("--json", "--focus", str(env["focus"]),
                "--rounds-dir", str(env["rounds"]),
                "--marker", str(env["marker"]),
                "--repo", str(env["repo"]))
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert set(report) >= {"checks", "ok", "failed", "focus_refs",
                           "newest_ref", "throttled", "interval_hours",
                           "marker", "ts"}
    assert report["ok"] is True
    assert report["failed"] == []
    assert report["throttled"] is False
    assert report["marker"].endswith(".persistence_nudge_last")
    assert {c["id"] for c in report["checks"]} == {
        "focus_fresh", "session_block", "learn_fresh"}


def test_json_rc0_when_checklist_fails(env):
    _write_focus(env["focus"],
                 [_entry("T-ACTIVE", updated=NOW - timedelta(hours=72))])
    proc = _run("--json", "--focus", str(env["focus"]),
                "--rounds-dir", str(env["rounds"]),
                "--marker", str(env["marker"]),
                "--repo", str(env["repo"]))
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    report = json.loads(proc.stdout)
    assert report["ok"] is False
    assert report["failed"] == ["focus_fresh"]


def test_human_mode_reports(env):
    proc = _run("--focus", str(env["focus"]),
                "--rounds-dir", str(env["rounds"]),
                "--marker", str(env["marker"]),
                "--repo", str(env["repo"]))
    assert proc.returncode == 0, proc.stderr
    assert "focus_fresh" in proc.stdout
    assert "checklist green" in proc.stdout
