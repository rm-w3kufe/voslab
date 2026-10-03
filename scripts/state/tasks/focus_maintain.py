#!/usr/bin/env python3
"""focus_maintain.py — task maintenance over vOSlab's actual task registry.

Rewire (S5 order 2026-10-03): the tasks-maintenance handler used the four
upstream TASKS.vsm scripts in this directory (validate/reconcile/maintain/
archive), which target ~/vsf/TASKS.vsm — a domain outside vOSlab authority
(backlog G-05: boundary AUTHORITY). vOSlab's task registry is
current_focus.json (bridge TASKS_VSM, boot protocol step 3). These modes
mirror the upstream slot contract against that registry instead:

  --validate    format of current_focus.json. Delegates to the focus-format
                gate's validate_focus() — single source of policy (D-03/A-7),
                no rule duplication. rc=1 on any violation.

  --reconcile   model≡reality findings (rc=0, advisory — mirrors upstream
                reconcile returning 0 with findings):
                  * detail declared but state/focus_details/<ref> missing
                  * started_at later than updated_at
                  * detail field not under state/focus_details/

  --check       health report (rc=0; upstream --check is also a report):
                  * counts per status (active / paused / done)
                  * stale active entries: updated_at older than STALE_DAYS

  --closed      dry-run archive candidates (rc=0, never writes — same
                dry-run contract as upstream tasks_archive --closed):
                done entries whose updated_at is older than ARCHIVE_DAYS.

Deterministic (R10): all checks derive from file contents + wall-clock age
classification; no randomness. Exit codes discriminate: rc!=0 only for
unreadable/invalid state (validate violations), never for advisory findings.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Single source of focus policy: the focus-format gate (harness register
# runs at import; harmless — we only call validate_focus()).
_VOS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_VOS_ROOT / "packages" / "framework"))
from gate_suite.gates.focus_format import validate_focus  # noqa: E402

FOCUS_FILE = _VOS_ROOT / "current_focus.json"
FOCUS_DETAILS = _VOS_ROOT / "state" / "focus_details"

#: Active entries not updated for this long are flagged stale (report only).
STALE_DAYS = 7
#: Done entries older than this are listed as archive candidates (dry run).
ARCHIVE_DAYS = 30


def _load() -> list[dict]:
    with open(FOCUS_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("focus must be a JSON array of entries")
    return data


def _ts(value: object) -> datetime | None:
    """Parse an ISO-8601 UTC 'Z' timestamp; None if unparsable."""
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def cmd_validate(_args: argparse.Namespace) -> int:
    fails = validate_focus(json.loads(FOCUS_FILE.read_text(encoding="utf-8")))
    if not fails:
        print(f"focus_validate: OK ({FOCUS_FILE.name})")
        return 0
    for fail in fails:
        print(f"  {fail}")
    return 1


def cmd_reconcile(_args: argparse.Namespace) -> int:
    findings: list[str] = []
    for entry in _load():
        ref = entry.get("ref") or "?"
        detail = entry.get("detail")
        if isinstance(detail, str) and detail:
            if not detail.startswith("state/focus_details/"):
                findings.append(f"{ref}: detail outside state/focus_details/: {detail}")
            elif not (_VOS_ROOT / detail).exists():
                findings.append(f"{ref}: detail declared but file missing: {detail}")
        started, updated = _ts(entry.get("started_at")), _ts(entry.get("updated_at"))
        if started and updated and started > updated:
            findings.append(
                f"{ref}: started_at {entry['started_at']} later than "
                f"updated_at {entry['updated_at']}"
            )
    if findings:
        print(f"focus_reconcile: {len(findings)} finding(s)")
        for f in findings:
            print(f"  {f}")
    else:
        print("focus_reconcile: 0 findings (model == reality)")
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    data = _load()
    now = datetime.now(timezone.utc)
    counts = {"active": 0, "paused": 0, "done": 0, "other": 0}
    stale: list[str] = []
    for entry in data:
        status = entry.get("status")
        counts[status if status in counts else "other"] += 1
        if status == "active":
            updated = _ts(entry.get("updated_at"))
            if updated and now - updated > timedelta(days=STALE_DAYS):
                stale.append(f"{entry.get('ref')} (last update {entry.get('updated_at')})")
    print(
        f"focus_check: {len(data)} entries · {counts['active']} active · "
        f"{counts['paused']} paused · {counts['done']} done"
    )
    for s in stale:
        print(f"  stale active: {s}")
    return 0


def cmd_closed(_args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ARCHIVE_DAYS)
    candidates = [
        entry
        for entry in _load()
        if entry.get("status") == "done"
        and (_ts(entry.get("updated_at")) or now) < cutoff
    ]
    print(f"focus_closed: {len(candidates)} archive candidate(s) older than {ARCHIVE_DAYS}d")
    for entry in candidates:
        print(f"  {entry.get('ref')}  done since {entry.get('updated_at')}")
    print("  dry run — report only (no --apply side effects by design)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--reconcile", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--closed", action="store_true")
    args = ap.parse_args()
    try:
        if args.validate:
            return cmd_validate(args)
        if args.reconcile:
            return cmd_reconcile(args)
        if args.check:
            return cmd_check(args)
        return cmd_closed(args)
    except (OSError, ValueError) as exc:
        print(f"focus_maintain: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
