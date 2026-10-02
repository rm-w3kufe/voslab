#!/usr/bin/env python3
"""
supervision_view.py — opsroom view-module for SUPERVISION-LAYER (Part A).

Lives on LXC 109 (/root/view_host/). Fetches the review surface from the
audit-logger HTTP API (LXC 101, port 9090) and projects it as a module tick.

The review surface answers the STRATEGIC question:
  "Is the autonomous regulation aligned with the ENDS I intend, or drifting?"

TICK shape:
  ts, source, module_id, tick = { volume, trend, distribution, anomalies,
  pending_decisions, certified }

Integration: add to MODULES dict in host.py.
"""

import json
import os
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── Configuration ───────────────────────────────────────────────────────────
AUDIT_API_URL = os.environ.get("AUDIT_API_URL", "http://10.10.20.10:9090")
EVENTS_LIMIT  = int(os.environ.get("AUDIT_EVENTS_LIMIT", "500"))


def _fetch(endpoint: str) -> dict | None:
    """Fetch JSON from the audit-logger API. Returns None on failure."""
    url = f"{AUDIT_API_URL}{endpoint}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as e:
        return None


def _percentile(events: list[dict], key: str, pct: float = 0.95) -> float:
    """Approximate percentile for a numeric field in events."""
    vals = sorted([ev.get(key, 0) or 0 for ev in events if isinstance(ev.get(key), (int, float))])
    if not vals:
        return 0.0
    idx = min(int(len(vals) * pct), len(vals) - 1)
    return vals[idx]


def build_tick() -> dict:
    """Build the supervision review-surface tick."""
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Fetch summary from audit-logger
    summary = _fetch(f"/audit/summary?limit={EVENTS_LIMIT}")
    pending = _fetch(f"/audit/pending?limit={EVENTS_LIMIT}")
    raw_events = _fetch(f"/audit/events?limit={EVENTS_LIMIT}")

    # Default structure if audit-logger is unreachable
    if summary is None:
        return {
            "ts": ts,
            "source": "supervision_view",
            "module_id": "supervision",
            "tick": {
                "status": "unavailable",
                "audit_api": AUDIT_API_URL,
                "note": "audit-logger unreachable — check LXC 101 service",
            },
            "certified": False,
        }

    # Extract events for deeper analysis
    events = []
    if raw_events and "events" in raw_events:
        events = raw_events["events"]

    # ── Volume ──
    volume = summary.get("volume", {})

    # ── Trend over time (last N events grouped by hour) ──
    hourly: dict[str, int] = {}
    for ev in events:
        ts_str = ev.get("ts", "")
        if ts_str:
            try:
                hour_key = ts_str[:13] + ":00:00Z"  # group by hour
                hourly[hour_key] = hourly.get(hour_key, 0) + 1
            except Exception:
                pass

    trend = {
        **summary.get("trend", {}),
        "hourly_volume": dict(sorted(hourly.items())),
    }

    # ── Distribution by loop and S1 ──
    distribution = summary.get("distribution", {})
    by_event_type = volume.get("by_event_type", {})
    by_action = volume.get("by_action", {})
    by_vmid = volume.get("by_vmid_top5", {})

    # ── Anomalies ──
    anomalies = summary.get("anomalies", {})
    # Add additional anomaly detection: rapid succession of same event type
    if len(events) >= 5:
        # Check if >80% of recent events are the same type
        recent_types = [ev.get("event_type", "?") for ev in events[-10:]]
        if recent_types:
            most_common = max(set(recent_types), key=recent_types.count)
            pct_same = recent_types.count(most_common) / len(recent_types)
            if pct_same >= 0.8:
                if "patterns" not in anomalies:
                    anomalies["patterns"] = []
                anomalies["patterns"].append(
                    f"repetitive: {most_common} appears in {pct_same:.0%} of last {len(recent_types)} events"
                )

    # ── Pending decisions ──
    pending_decisions = []
    if pending and "pending_decisions" in pending:
        pending_decisions = pending["pending_decisions"]

    # ─── BUILD the tick ───
    tick = {
        "status": "ok",
        "events_window": summary.get("events_in_window", 0),
        "volume": volume,
        "trend": trend,
        "distribution": {
            **distribution,
            "by_event_type": by_event_type,
            "by_action": by_action,
            "by_vmid": by_vmid,
        },
        "anomalies": anomalies,
        "pending_decisions": {
            "count": len(pending_decisions),
            "list": pending_decisions[-10:],
        },
        "audit_api_ts": ts,
    }

    return {
        "ts": ts,
        "source": "supervision_view",
        "module_id": "supervision",
        "tick": tick,
        "certified": True,
        # The data comes from the audit-logger which reads the persisted JSONL;
        # certification level: data is as-received (not independently verified).
        "cert_note": "review-surface data from audit-logger API (LXC 101:9090)",
    }


# ── CLI test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tick = build_tick()
    print(json.dumps(tick, indent=2, default=str))
