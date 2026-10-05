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

CC-8.1 amendments (S5 ordered a+b+c, 2026-10-05):
  (b) divergences carry explanation state from an explanation ledger
      (state/epistemic/divergence_explanations.jsonl): exact-id rules
      beat class rules; unexplained > 0 is surfaced in the report and
      trips check shadow-divergences-explained.
  (c) for gap-resolver entries reality = the resolver's OWN execution
      record (logs/gap-resolution.jsonl autoExecuted), NOT file-level
      git noise: a bounds-blocked candidate whose target then changed
      via the primary workflow is ALIGNED (the gap action did not run);
      "blocked-but-executed" (executed despite bounds failure) is the
      real alarm. Non-gap sources keep the file-level check.

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
GAP_LOG = WORKSPACE / "logs" / "gap-resolution.jsonl"
EXPLANATIONS = WORKSPACE / "state" / "epistemic" / "divergence_explanations.jsonl"
_GAP_MATCH_WINDOW_S = 5.0  # shadow ts is second-precision; log row ms-precision

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


def _iso_epoch(value: Any) -> float | None:
    ts = _parse_ts(value)
    return ts.timestamp() if ts is not None else None


def load_explanations(path: pathlib.Path | None = None) -> list[dict[str, Any]]:
    """Divergence-explanation rules (CC-8.1(b)) — validated, deterministic.

    Rule shape: {"rule_id", "explanation", ("id" exact | "match" dict),
    "by", "ts", ...}. Rules missing rule_id, an explanation string, or both
    an id and a match dict are skipped (a rule that explains nothing cannot
    silently count as an explanation).
    """
    p = path or EXPLANATIONS
    if not p.exists():
        return []
    rules: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rule = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rule.get("rule_id"), str) or not rule["rule_id"]:
            continue
        if not isinstance(rule.get("explanation"), str) or not rule["explanation"]:
            continue
        has_id = isinstance(rule.get("id"), str) and bool(rule["id"])
        has_match = isinstance(rule.get("match"), dict) and bool(rule["match"])
        if not (has_id or has_match):
            continue
        rules.append(rule)
    return rules


def _load_gap_rows(gap_log: pathlib.Path
                   ) -> dict[tuple[str, str], list[tuple[float, bool]]]:
    """Index the resolver's execution log: (gapId, decision) -> sorted rows."""
    rows: dict[tuple[str, str], list[tuple[float, bool]]] = {}
    if not gap_log.exists():
        return rows
    for line in gap_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        epoch = _iso_epoch(row.get("timestamp"))
        if epoch is None:
            continue
        key = (str(row.get("gapId", "")), str(row.get("decision", "")))
        rows.setdefault(key, []).append((epoch, bool(row.get("autoExecuted"))))
    for key in rows:
        rows[key].sort()
    return rows


def _lookup_execution(action: str, ts: str,
                      rows: dict[tuple[str, str], list[tuple[float, bool]]]
                      ) -> bool | None:
    """autoExecuted of the nearest same-gap+decision log row within ±5s.

    None = no matching row → caller classifies as unverifiable (never a
    guess — the execution truth must be recorded, R10).
    """
    try:
        act = json.loads(action)
    except (ValueError, TypeError):
        return None
    shadow_epoch = _iso_epoch(ts)
    if shadow_epoch is None:
        return None
    key = (str(act.get("gap", "")), str(act.get("decision", "")))
    best: tuple[float, bool] | None = None
    for epoch, executed in rows.get(key, ()):  # sorted → first min wins ties
        delta = abs(epoch - shadow_epoch)
        if delta <= _GAP_MATCH_WINDOW_S and (best is None or delta < best[0]):
            best = (delta, executed)
    return best[1] if best else None


def _explain(div: dict[str, Any],
             rules: list[dict[str, Any]]) -> tuple[bool, str, str]:
    """Exact-id rules first, then class rules (every match field equal)."""
    for rule in rules:
        if rule.get("id") == div["id"]:
            return True, rule["explanation"], f"id:{rule['rule_id']}"
    for rule in rules:
        match = rule.get("match")
        if not isinstance(match, dict) or not match:
            continue
        if all(div.get(k) == v for k, v in match.items()):
            return True, rule["explanation"], f"class:{rule['rule_id']}"
    return False, "", ""


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
            repo_root: pathlib.Path | None = None,
            gap_log: pathlib.Path | None = None,
            explanations: pathlib.Path | None = None) -> dict[str, Any]:
    """Shadow-vs-reality review since `cutoff`. Deterministic (R10).

    Kinds (CC-8.1(c), S5 2026-10-05): gap-resolver entries are judged
    against the resolver's OWN execution record (autoExecuted), not
    file-level git noise; non-gap sources with a target keep the
    file-level check; entries with neither execution channel nor target
    are not evaluated (untracked_targets). Divergences carry explanation
    state (CC-8.1(b)); unexplained > 0 trips shadow-divergences-explained.
    """
    repo = repo_root or WORKSPACE
    gap_path = (gap_log if gap_log is not None
                else repo / "logs" / "gap-resolution.jsonl")
    expl_path = (explanations if explanations is not None
                 else repo / "state" / "epistemic"
                 / "divergence_explanations.jsonl")
    entries = load(ledger)
    total = len(entries)
    new = [e for e in entries
           if (ts := _parse_ts(e.get("ts"))) is not None and ts >= cutoff]
    blocked = [e for e in new if not e.get("bounds", {}).get("pass", False)]
    rules = load_explanations(expl_path)
    gap_rows = _load_gap_rows(gap_path)
    divergences: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = {}
    aligned = 0
    for entry in new:
        would_run = bool(entry.get("bounds", {}).get("pass", False))
        source = str(entry.get("source", ""))
        target = entry.get("target")
        if source == "gap-resolver":
            truth: bool | None = _lookup_execution(
                str(entry.get("action", "")), str(entry.get("ts", "")),
                gap_rows)
        elif target:
            truth = _git_changed_since(entry["ts"], target, repo)
        else:
            continue  # no execution channel and no target — not evaluable
        if truth is None:
            kind = "unverifiable"
        elif would_run and truth:
            kind = "aligned-executed"
        elif not would_run and not truth:
            kind = "aligned-blocked"
        elif would_run and not truth:
            kind = ("would-run-deferred" if source == "gap-resolver"
                    else "would-run-not-materialized")
        else:  # bounds said no, yet it executed/materialized
            kind = ("blocked-but-executed" if source == "gap-resolver"
                    else "blocked-but-materialized")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if kind.startswith("aligned"):
            aligned += 1
            continue
        div: dict[str, Any] = {
            "id": entry.get("id", "?"),
            "kind": kind,
            "target": target,
            "ts": entry.get("ts", ""),
            "source": source,
        }
        div["explained"], div["explanation"], div["explained_by"] =             _explain(div, rules)
        if not div["explained"] and target:
            # side-by-side context, cost-bounded to unexplained divergences
            div["target_changed_since"] = _git_changed_since(
                entry["ts"], target, repo)
        divergences.append(div)
    unexplained = [d for d in divergences if not d["explained"]]
    return {
        "total": total,
        "new_count": len(new),
        "new": new,
        "blocked_count": len(blocked),
        "blocked_ids": [e.get("id", "?") for e in blocked],
        "divergences": divergences,
        "divergences_explained": len(divergences) - len(unexplained),
        "divergences_unexplained": len(unexplained),
        "kind_counts": kind_counts,
        "aligned_count": aligned,
        "untracked_targets": sum(1 for e in new if not e.get("target")),
    }
