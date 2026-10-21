#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/monitoring_runners.vsm
# route: monitoring_runners.vsm §flota/§helpers — registro canonico de la familia monitoring (T7-F2; entry_point = unit systemd o invocacion manual)
# verify: sin test unitario (deuda T7); invocacion manual/ad-hoc
"""vsf-log-feedback.py — Real-time log anomaly detection for kernel action loop.

Reads recent agent_plugin.jsonl entries, detects:
- High error rate (failures in last N calls)
- Loop detection (identical tool+action repeated)
- Unacked algedonic alerts

Returns JSON with warnings for injection into tool output.

Task: LOG-FEEDBACK-LOOP (2026-10-12)
Design: docs/audit/log_connectivity_audit_2026_10_12.vsm
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone

# ── Config ──
WINDOW_SECS = 120          # lookback window
MIN_CALLS_FOR_RATE = 10    # min calls before rate is meaningful
ERROR_RATE_WARN = 15.0     # percent
ERROR_RATE_CRIT = 30.0     # percent
LOOP_MIN_REPEAT = 5        # identical (tool,action) pairs to flag
LOOP_WINDOW_SECS = 60      # loop detection window


def parse_ts(ts_str: str) -> float:
    """Parse ISO timestamp to epoch seconds."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


def read_recent(log_path: Path, window_secs: int) -> list[dict]:
    """Read entries from agent_plugin.jsonl within the time window."""
    if not log_path.exists():
        return []

    cutoff = time.time() - window_secs
    entries = []

    try:
        with open(log_path, "r") as f:
            # Read last 500 lines efficiently
            lines = f.readlines()[-500:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = parse_ts(rec.get("ts", ""))
                if ts >= cutoff:
                    entries.append(rec)
            except json.JSONDecodeError:
                continue
    except OSError:
        return []

    return entries


def detect_error_rate(entries: list[dict]) -> dict | None:
    """Detect high error rate in recent entries."""
    tool_calls = [
        e for e in entries
        if e.get("event_type") in ("tool.execute.after", "tool.execute.before")
    ]

    if len(tool_calls) < MIN_CALLS_FOR_RATE:
        return None

    errors = [
        e for e in tool_calls
        if e.get("level") in ("error", "warning")
        or "error" in str(e.get("detail", "")).lower()
    ]

    rate = (len(errors) / len(tool_calls)) * 100

    if rate >= ERROR_RATE_CRIT:
        return {
            "severity": "CRIT",
            "rate": round(rate, 1),
            "total": len(tool_calls),
            "errors": len(errors),
            "message": f"HIGH ERROR RATE: {rate:.1f}% ({len(errors)}/{len(tool_calls)} calls)"
        }
    elif rate >= ERROR_RATE_WARN:
        return {
            "severity": "WARN",
            "rate": round(rate, 1),
            "total": len(tool_calls),
            "errors": len(errors),
            "message": f"Elevated error rate: {rate:.1f}% ({len(errors)}/{len(tool_calls)} calls)"
        }
    return None


def detect_loop(entries: list[dict]) -> dict | None:
    """Detect repeated identical tool+action pairs (loop detection)."""
    cutoff = time.time() - LOOP_WINDOW_SECS

    recent = [
        e for e in entries
        if e.get("event_type") == "tool.execute.before"
        and parse_ts(e.get("ts", "")) >= cutoff
    ]

    if len(recent) < LOOP_MIN_REPEAT:
        return None

    # Count identical (tool, action) pairs
    pairs = Counter()
    for e in recent:
        tool = e.get("action", "").split(":")[0].strip() if ":" in e.get("action", "") else e.get("action", "")
        pairs[tool] += 1

    for tool, count in pairs.most_common(3):
        if count >= LOOP_MIN_REPEAT:
            return {
                "severity": "CRIT",
                "tool": tool,
                "count": count,
                "window": LOOP_WINDOW_SECS,
                "message": f"LOOP DETECTED: '{tool}' called {count}x in {LOOP_WINDOW_SECS}s"
            }
    return None


def check_unacked_alerts(repo_root: Path) -> dict | None:
    """Check for unacked algedonic alerts."""
    alerts_file = repo_root / "state" / "rsi" / "alerts.jsonl"
    if not alerts_file.exists():
        return None

    try:
        with open(alerts_file, "r") as f:
            lines = f.readlines()[-20:]
        unacked = 0
        for line in lines:
            try:
                rec = json.loads(line)
                if not rec.get("acked", False):
                    unacked += 1
            except json.JSONDecodeError:
                continue
        if unacked > 0:
            return {
                "severity": "INFO",
                "unacked": unacked,
                "message": f"{unacked} unacked algedonic alerts"
            }
    except OSError:
        pass
    return None


def main():
    repo_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    log_path = repo_root / "logs" / "agent_plugin.jsonl"

    entries = read_recent(log_path, WINDOW_SECS)

    warnings = []

    # Error rate check
    er = detect_error_rate(entries)
    if er:
        warnings.append(er)

    # Loop detection
    lp = detect_loop(entries)
    if lp:
        warnings.append(lp)

    # Unacked alerts
    al = check_unacked_alerts(repo_root)
    if al:
        warnings.append(al)

    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "entries_analyzed": len(entries),
        "warnings": warnings,
        "has_critical": any(w["severity"] == "CRIT" for w in warnings),
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
