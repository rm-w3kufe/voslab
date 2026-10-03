"""Counterfactual shadow harness — CC-8.1 core.

Contract (tutored_autonomy_cc8_plan, CC-8.1 deliverables):
    "shadow harness: on each candidate predicate/fix, append would-be
     action + bounds-check result"
    "divergence review: shadow vs reality side by side in the evolution report"

The shadow LOGS what the system would do — it never executes
(autonomy_granted: none; still observation, but of DECISIONS).

Ledger: state/epistemic/shadow.jsonl (append-only).
R10: `record` is a pure append; `analyze` is deterministic for a fixed
ledger + git state (no randomness anywhere).

Entry schema:
    {"ts", "id", "source", "action", "bounds": {"pass": bool, "reasons": [...]},
     "blocked_by": [...], "target": str|null}
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import subprocess
from typing import Any

WORKSPACE = pathlib.Path(__file__).resolve().parents[3]
LEDGER = WORKSPACE / "state" / "epistemic" / "shadow.jsonl"

_REQUIRED = ("ts", "id", "source", "action", "bounds", "blocked_by", "target")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _validate(entry: dict[str, Any]) -> None:
    missing = [k for k in _REQUIRED if k not in entry]
    if missing:
        raise ValueError(f"shadow entry missing fields: {missing}")
    if not isinstance(entry["source"], str) or not entry["source"]:
        raise ValueError("shadow source must be a non-empty string")
    if isinstance(entry["action"], dict):
        entry["action"] = json.dumps(entry["action"], sort_keys=True,
                                     ensure_ascii=False)
    if not isinstance(entry["action"], str) or not entry["action"]:
        raise ValueError("shadow action must be a non-empty string")
    bounds = entry["bounds"]
    if not isinstance(bounds, dict) or not isinstance(bounds.get("pass"), bool):
        raise ValueError("shadow bounds must be {'pass': bool, 'reasons': [...]}")
    if not isinstance(bounds.get("reasons"), list):
        raise ValueError("shadow bounds.reasons must be a list")
    if not isinstance(entry["blocked_by"], list):
        raise ValueError("shadow blocked_by must be a list")
    if entry["target"] is not None and not isinstance(entry["target"], str):
        raise ValueError("shadow target must be a path string or null")


def record(source: str, action: Any, bounds: dict[str, Any],
           blocked_by: list[str] | None = None, target: str | None = None,
           entry_id: str | None = None,
           ledger: pathlib.Path | None = None) -> dict[str, Any]:
    """Append one would-be action + its bounds-check to the shadow ledger."""
    if entry_id is None:
        digest = hashlib.sha256(
            f"{source}|{json.dumps(action, sort_keys=True, default=str)}".encode()
        ).hexdigest()[:12]
        entry_id = f"SHD-{digest}"
    entry: dict[str, Any] = {
        "ts": _now(),
        "id": entry_id,
        "source": source,
        "action": action,
        "bounds": bounds,
        "blocked_by": blocked_by or [],
        "target": target,
    }
    _validate(entry)
    path = ledger or LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load(ledger: pathlib.Path | None = None) -> list[dict[str, Any]]:
    path = ledger or LEDGER
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def _git_changed_since(since: str, target: str,
                       repo_root: pathlib.Path) -> bool | None:
    """True if `target` was touched by a commit after `since` (None = unknown)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "log",
             f"--since={since}", "--format=%h", "--", target],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return bool(proc.stdout.strip())


def analyze(cutoff: dt.datetime, ledger: pathlib.Path | None = None,
            repo_root: pathlib.Path | None = None) -> dict[str, Any]:
    """Shadow-vs-reality review since `cutoff`. Deterministic (R10)."""
    repo = repo_root or WORKSPACE
    entries = load(ledger)
    total = len(entries)
    new = [e for e in entries
           if (ts := _parse_ts(e.get("ts"))) is not None and ts >= cutoff]
    blocked = [e for e in new if not e.get("bounds", {}).get("pass", False)]
    divergences: list[dict[str, str]] = []
    aligned = 0
    for entry in new:
        target = entry.get("target")
        if not target:
            continue
        materialized = _git_changed_since(entry["ts"], target, repo)
        would_run = bool(entry.get("bounds", {}).get("pass", False))
        if materialized is None:
            kind = "unverifiable"
        elif would_run and materialized:
            kind = "aligned-executed"
        elif not would_run and not materialized:
            kind = "aligned-blocked"
        elif would_run and not materialized:
            kind = "would-run-not-materialized"
        else:  # blocked by bounds, yet materialized in reality
            kind = "blocked-but-materialized"
        if kind.startswith("aligned"):
            aligned += 1
        else:
            divergences.append({
                "id": entry.get("id", "?"),
                "kind": kind,
                "target": target,
                "ts": entry.get("ts", ""),
            })
    return {
        "total": total,
        "new_count": len(new),
        "new": new,
        "blocked_count": len(blocked),
        "blocked_ids": [e.get("id", "?") for e in blocked],
        "divergences": divergences,
        "aligned_count": aligned,
        "untracked_targets": sum(1 for e in new if not e.get("target")),
    }
