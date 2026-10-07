#!/usr/bin/env python3
"""persistence_nudge.py — close-checklist advisory nudge (§6.1, REFS-OPT-001 F4.1).

Three deterministic (R10) checks a session close should not skip:

  focus_fresh    current_focus.json readable, non-empty, newest updated_at
                 within FOCUS_MAX_AGE_H (default 24h).
  session_block  last commit body carries the session(...) block.
  learn_fresh    newest state/epistemic/rounds/ROUND-*.json within
                 LEARN_MAX_AGE_H (default 168h = 7d).

Advisory contract: rc=0 whenever a report could be produced — a failing
checklist is a reminder, never a blocker (rc=2 only for usage/internal
errors). Emission throttle: marker state/rsi/.persistence_nudge_last
(mtime vs NUDGE_INTERVAL_H, default 6h); reported as `throttled`. This
script never writes — the persistence-nudge handler writes the marker
after it emits the reminder.

Reads only file contents + wall clock (no randomness). Paths and windows
are overridable (--focus/--rounds-dir/--marker/--repo, *_max_age_h) so
tests run hermetic against fixtures.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_VOS_ROOT = Path(__file__).resolve().parents[3]
FOCUS_FILE = _VOS_ROOT / "current_focus.json"
ROUNDS_DIR = _VOS_ROOT / "state" / "epistemic" / "rounds"
MARKER = _VOS_ROOT / "state" / "rsi" / ".persistence_nudge_last"

#: Focus not updated for this long → focus_fresh fails (hours).
FOCUS_MAX_AGE_H = 24.0
#: Newest learn round older than this → learn_fresh fails (hours).
LEARN_MAX_AGE_H = 168.0
#: Emission throttle window (hours) — same shape as _evolution_daily.
NUDGE_INTERVAL_H = 6.0


def _now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _ts(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp ('Z' or offset); None if unparsable."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _age_h(ts: datetime, now: datetime) -> float:
    return (now - ts).total_seconds() / 3600.0


def _round_ts(path: Path) -> datetime | None:
    """ROUND-YYYYmmddTHHMMSSffffffZ.json → UTC datetime; fallback mtime."""
    stamp = path.stem[len("ROUND-"):] if path.stem.startswith("ROUND-") else path.stem
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def check_focus(focus_file: Path, max_age_h: float, now: datetime
                ) -> tuple[dict, list[str], str | None]:
    """focus_fresh check → (check, active focus refs, newest active ref)."""
    cid = "focus_fresh"
    if not focus_file.is_file():
        return ({"id": cid, "ok": False,
                 "detail": f"{focus_file.name} missing"}, [], None)
    try:
        data = json.loads(focus_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ({"id": cid, "ok": False,
                 "detail": f"unreadable: {exc}"}, [], None)
    if not isinstance(data, list) or not data:
        return ({"id": cid, "ok": False, "detail": "no focus entries"},
                [], None)

    newest: datetime | None = None
    for entry in data:
        if not isinstance(entry, dict):
            continue
        ts = _ts(entry.get("updated_at"))
        if ts is not None and (newest is None or ts > newest):
            newest = ts
    if newest is None:
        return ({"id": cid, "ok": False,
                 "detail": "no parseable updated_at"}, [], None)

    age = _age_h(newest, now)
    # Negative age = clock skew / future stamp → treat as fresh.
    ok = age <= max_age_h
    detail = f"newest updated_at {max(age, 0.0):.1f}h ago (max {max_age_h:g}h)"

    active = [e for e in data
              if isinstance(e, dict) and e.get("status") == "active"]
    refs = [str(e["ref"]) for e in active if e.get("ref")]
    newest_ref: str | None = None
    newest_ref_ts: datetime | None = None
    for entry in active:
        ts = _ts(entry.get("updated_at"))
        if ts is not None and (newest_ref_ts is None or ts > newest_ref_ts):
            newest_ref_ts, newest_ref = ts, str(entry.get("ref"))
    return {"id": cid, "ok": ok, "detail": detail}, refs, newest_ref


def check_session_block(repo: Path) -> dict:
    """session_block check — last commit body carries `session(`."""
    cid = "session_block"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {"id": cid, "ok": True, "detail": "git unavailable (skip)"}
    if proc.returncode != 0:
        return {"id": cid, "ok": True, "detail": "not a git repo (skip)"}
    body = (proc.stdout or "").strip()
    if not body:
        return {"id": cid, "ok": True, "detail": "no commits yet (skip)"}
    if "session(" in body:
        return {"id": cid, "ok": True,
                "detail": "last commit carries session block"}
    subject = body.splitlines()[0][:80]
    return {"id": cid, "ok": False,
            "detail": f"last commit missing session(...): {subject}"}


def check_learn(rounds_dir: Path, max_age_h: float, now: datetime) -> dict:
    """learn_fresh check — newest ROUND-*.json within the window."""
    cid = "learn_fresh"
    if not rounds_dir.is_dir():
        return {"id": cid, "ok": False, "detail": "rounds dir missing"}
    rounds = sorted(rounds_dir.glob("ROUND-*.json"))
    if not rounds:
        return {"id": cid, "ok": False, "detail": "no ROUND-*.json"}
    newest: datetime | None = None
    newest_name = ""
    for path in rounds:
        ts = _round_ts(path)
        if ts is not None and (newest is None or ts > newest):
            newest, newest_name = ts, path.name
    if newest is None:
        return {"id": cid, "ok": False, "detail": "rounds unparsable"}
    age = _age_h(newest, now)
    ok = age <= max_age_h
    detail = (f"newest {newest_name} {max(age, 0.0):.1f}h ago "
              f"(max {max_age_h:g}h)")
    return {"id": cid, "ok": ok, "detail": detail}


def is_throttled(marker: Path, interval_h: float, now: datetime) -> bool:
    """True when the emission marker is younger than the interval."""
    try:
        mtime = datetime.fromtimestamp(marker.stat().st_mtime,
                                       tz=timezone.utc)
    except OSError:
        return False
    return _age_h(mtime, now) < interval_h


def evaluate(focus_file: Path, rounds_dir: Path, repo: Path,
             focus_max_age_h: float, learn_max_age_h: float,
             now: datetime | None = None) -> dict:
    """Run all three checks → full report dict."""
    now = _now(now)
    focus_check, refs, newest_ref = check_focus(focus_file, focus_max_age_h,
                                                now)
    checks = [
        focus_check,
        check_session_block(repo),
        check_learn(rounds_dir, learn_max_age_h, now),
    ]
    failed = [c["id"] for c in checks if not c["ok"]]
    return {
        "checks": checks,
        "ok": not failed,
        "failed": failed,
        "focus_refs": refs,
        "newest_ref": newest_ref,
        "ts": now.isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="§6.1 close-checklist advisory nudge (never blocks)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable report (handler contract)")
    parser.add_argument("--focus", type=Path, default=None,
                        help="focus file (default: current_focus.json)")
    parser.add_argument("--rounds-dir", type=Path, default=None,
                        help="learn rounds dir (default: state/epistemic/rounds)")
    parser.add_argument("--marker", type=Path, default=None,
                        help="throttle marker (default: state/rsi/.persistence_nudge_last)")
    parser.add_argument("--repo", type=Path, default=None,
                        help="git repo for the session-block check (default: workspace)")
    parser.add_argument("--focus-max-age-h", type=float,
                        default=FOCUS_MAX_AGE_H)
    parser.add_argument("--learn-max-age-h", type=float,
                        default=LEARN_MAX_AGE_H)
    parser.add_argument("--interval-h", type=float, default=NUDGE_INTERVAL_H)
    args = parser.parse_args(argv)

    focus_file = args.focus or FOCUS_FILE
    rounds_dir = args.rounds_dir or ROUNDS_DIR
    marker = args.marker or MARKER
    repo = args.repo or _VOS_ROOT

    try:
        now = _now()
        report = evaluate(focus_file, rounds_dir, repo,
                          args.focus_max_age_h, args.learn_max_age_h, now)
        report["throttled"] = is_throttled(marker, args.interval_h, now)
        report["interval_hours"] = args.interval_h
        report["marker"] = str(marker)
    except Exception as exc:  # internal bug → usage-level rc, never silent
        print(f"persistence_nudge: internal error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0

    for check in report["checks"]:
        status = "ok  " if check["ok"] else "FAIL"
        print(f"{check['id']:<14} {status}  {check['detail']}")
    verdict = "checklist green" if report["ok"] else \
        f"reminder: {','.join(report['failed'])}"
    throttle = "yes" if report["throttled"] else "no"
    print(f"summary: {verdict} | throttled: {throttle} "
          f"(interval {args.interval_h:g}h)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
