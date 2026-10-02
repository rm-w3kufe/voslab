#!/usr/bin/env python3
"""
vsf-audit-logger.py — B1: S3* audit stream persistence + HTTP API.

Subscribes to vsf.alpha.s3star.audit (NATS), writes every event to a durable
JSONL log, and serves an HTTP API for the supervision review surface (A).

API endpoints (port 9090):
  GET /audit/events          — all events (JSONL stream, paginated via ?limit=)
  GET /audit/summary         — volume/trend/distribution/anomalies
  GET /audit/pending         — pending decisions (escalations not yet resolved)
  GET /health                — liveness

Usage:
  python3 vsf-audit-logger.py              # foreground
  systemctl start vsf-audit-logger.service  # systemd
"""

import asyncio
import datetime
import json
import os
import signal
import sys
from collections import Counter, defaultdict
from pathlib import Path

import nats
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

# ── Configuration ───────────────────────────────────────────────────────────
NATS_URL           = os.environ.get("NATS_URL", "nats://10.10.20.20:4222")
AUDIT_SUBJECT      = "vsf.alpha.s3star.audit"
DECISION_SUBJECT   = "vsf.alpha.s5.decision"
LOG_DIR            = Path(os.environ.get("AUDIT_LOG_DIR", "/var/log/vsf-audit"))
LOG_FILE           = LOG_DIR / "audit_stream.jsonl"
API_PORT           = int(os.environ.get("AUDIT_API_PORT", "9090"))
API_HOST           = os.environ.get("AUDIT_API_HOST", "0.0.0.0")

# In-memory ring buffer for recent events (last 5000)
MAX_RECENT_EVENTS = 5000
recent_events: list[dict] = []
recent_lock = threading.Lock()

# Global NATS connection (set by nats_reader, used by HTTP API to publish decisions)
nats_connection = None
nats_lock = threading.Lock()

# Import decision auth module (B2/B3 signing + verification)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from vsf_decision_auth import verify_decision
    HAS_DECISION_AUTH = True
except ImportError:
    HAS_DECISION_AUTH = False
    print("[audit-logger] WARNING: vsf_decision_auth not available (B2/B3 disabled)", flush=True)


# ── B1: Durable log writer ──────────────────────────────────────────────────
def _ensure_log_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def write_event(ev: dict):
    """Append one event to the durable JSONL log and in-memory ring."""
    line = json.dumps(ev, sort_keys=True, default=str) + "\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    # Ring buffer
    with recent_lock:
        recent_events.append(ev)
        if len(recent_events) > MAX_RECENT_EVENTS:
            recent_events[:] = recent_events[-MAX_RECENT_EVENTS:]


async def nats_reader():
    """Subscribe to the audit stream + decision channel, persist every event."""
    global nats_connection
    print(f"[audit-logger] connecting to NATS at {NATS_URL} ...", flush=True)
    nc = await nats.connect(NATS_URL)
    with nats_lock:
        nats_connection = nc
    print(f"[audit-logger] subscribed to {AUDIT_SUBJECT} + {DECISION_SUBJECT}", flush=True)

    # B1: subscribe to S3* audit stream
    async def on_audit(msg):
        try:
            ev = json.loads(msg.data.decode())
            ev["_nats_subject"] = AUDIT_SUBJECT
            write_event(ev)
        except Exception as e:
            print(f"[audit-logger] parse error (audit): {e}", flush=True)

    # B2/B3: subscribe to supervision decisions (signed verdicts)
    async def on_decision(msg):
        try:
            ev = json.loads(msg.data.decode())
            ev["_nats_subject"] = DECISION_SUBJECT
            # Tag the event type for the pending/resolved tracking
            if "verdict" in ev:
                ev["event_type"] = "supervision_decision"
                ev["action"] = f"DECISION_{ev.get('verdict', 'UNKNOWN')}"
            write_event(ev)
            print(f"[audit-logger] decision: {ev.get('verdict','?')} esc_id={ev.get('escalation_id','?')[:20]}", flush=True)
        except Exception as e:
            print(f"[audit-logger] parse error (decision): {e}", flush=True)

    await nc.subscribe(AUDIT_SUBJECT, cb=on_audit)
    await nc.subscribe(DECISION_SUBJECT, cb=on_decision)

    # Keep running
    while True:
        await asyncio.sleep(3600)


# ── A: Review surface API (HTTP) ──────────────────────────────────────────
def _read_log_lines(limit: int = 100) -> list[dict]:
    """Read the last N events from the JSONL file."""
    events = []
    try:
        with open(LOG_FILE) as f:
            # Tail-like: read all, take last N
            lines = f.readlines()
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return events


def _compute_summary(events: list[dict]) -> dict:
    """Volume, trend, distribution, anomalies over the event list."""
    if not events:
        return {"events_in_window": 0, "volume": {}, "trend": {}, "distribution": {}, "anomalies": []}

    # Volume
    total = len(events)
    by_loop = Counter(ev.get("event_type", "unknown") for ev in events)
    by_action = Counter(ev.get("action", "unknown") for ev in events)
    by_vmid = Counter(str(ev.get("vmid", "unknown")) for ev in events)
    resource_moved = sum(ev.get("grant_cores", 0) or 0 for ev in events) + \
                     sum(ev.get("grant_mem", 0) or 0 for ev in events)

    # Trend: volume per minute (approximate by event_ts clustering)
    timestamps = []
    for ev in events:
        ts = ev.get("ts", "")
        if ts:
            try:
                timestamps.append(datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass

    # Distribution
    escalated = [ev for ev in events if ev.get("escalated")]
    held = [ev for ev in events if ev.get("action") == "HOLD"]

    # Anomalies: chronic pattern — same vmid appeared in >50% of events
    chronic_vmids = []
    for vmid, count in by_vmid.most_common(5):
        if count > total * 0.5 and total > 5:
            chronic_vmids.append(vmid)

    return {
        "events_in_window": total,
        "volume": {
            "total_events": total,
            "by_event_type": dict(by_loop.most_common(10)),
            "by_action": dict(by_action.most_common(10)),
            "by_vmid_top5": dict(by_vmid.most_common(5)),
            "resource_moved_units": resource_moved,
        },
        "trend": {
            "window_start": str(timestamps[0]) if timestamps else None,
            "window_end": str(timestamps[-1]) if timestamps else None,
            "total_minutes": round((timestamps[-1] - timestamps[0]).total_seconds() / 60, 1) if len(timestamps) > 1 else 0,
        },
        "distribution": {
            "escalated_count": len(escalated),
            "held_count": len(held),
            "held_vmids": list(set(str(ev.get("vmid", "?")) for ev in held)),
        },
        "anomalies": {
            "chronically_propped_vmids": chronic_vmids,
            "note": "vmid appearing in >50% of events may indicate a structural problem being masked by autonomous grants"
            if chronic_vmids else "no chronic masking patterns detected",
        },
    }


class AuditAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the audit + supervision API."""

    KNOWN_PATHS = ["/health", "/audit/events", "/audit/summary", "/audit/pending", "/audit/decide"]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        limit = int(params.get("limit", [500])[0])

        if path in ("", "/"):
            self._json_response({"service": "vsf-audit-logger", "paths": self.KNOWN_PATHS})

        elif path == "/health":
            self._json_response({"status": "ok", "log_file": str(LOG_FILE)})

        elif path in ("/audit/events",):
            evts = _read_log_lines(limit)
            self._json_response({"count": len(evts), "events": evts[-min(limit, 100):]})  # cap at 100 for GET

        elif path in ("/audit/summary",):
            evts = _read_log_lines(limit)
            summary = _compute_summary(evts)
            self._json_response(summary)

        elif path in ("/audit/pending",):
            evts = _read_log_lines(limit)
            # Pending = escalated+HOLD events that do NOT have a matching resolution
            escalated = [ev for ev in evts if ev.get("escalated") and ev.get("action") == "HOLD"]
            # Check each escalation for a matching decision (same escalation_id with verdict)
            resolved_ids = set()
            for ev in evts:
                if ev.get("event_type") == "supervision_decision" and ev.get("verdict"):
                    resolved_ids.add(ev.get("escalation_id"))
            pending = [ev for ev in escalated if ev.get("escalation_id") not in resolved_ids]
            self._json_response({
                "count": len(pending),
                "total_escalated": len(escalated),
                "resolved": len(resolved_ids),
                "pending_decisions": pending[-20:],
            })

        else:
            self._json_response({"error": "not_found", "paths": self.KNOWN_PATHS}, status=404)

    def do_POST(self):
        """POST /audit/decide — submit a signed supervision_decision."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path not in ("/audit/decide",):
            self._json_response({"error": "not_found", "paths": self.KNOWN_PATHS}, status=404)
            return

        # Read body
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            self._json_response({"error": "empty body"}, status=400)
            return
        body = self.rfile.read(content_len)

        try:
            decision = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._json_response({"error": f"invalid JSON: {e}"}, status=400)
            return

        # Verify the signature (B3)
        verified = {"valid": False, "reason": "decision auth not available"}
        if HAS_DECISION_AUTH:
            try:
                verified = verify_decision(dict(decision))
            except Exception as e:
                verified = {"valid": False, "reason": f"verify error: {e}"}

        if not verified.get("valid"):
            self._json_response({
                "accepted": False,
                "reason": verified.get("reason", "signature invalid"),
            }, status=403)
            return

        # Publish to NATS decision subject
        published = False
        with nats_lock:
            nc = nats_connection
            if nc is not None and nc.is_connected:
                try:
                    # Create a minimal coroutine to publish
                    import asyncio
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(nc.publish(DECISION_SUBJECT, json.dumps(decision).encode()))
                    loop.close()
                    published = True
                except Exception as e:
                    self._json_response({
                        "accepted": False,
                        "reason": f"publish failed: {e}",
                    }, status=500)
                    return

        # Also write directly to the durable log
        decision["_nats_subject"] = DECISION_SUBJECT
        decision["event_type"] = "supervision_decision"
        decision["action"] = f"DECISION_{decision.get('verdict', 'UNKNOWN')}"
        write_event(decision)

        self._json_response({
            "accepted": True,
            "published": published,
            "escalation_id": decision.get("escalation_id"),
            "verdict": decision.get("verdict"),
        })

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Suppress request logs to stderr (they go to journald)."""
        pass


def run_http_server():
    """Run the HTTP API in a background thread."""
    server = HTTPServer((API_HOST, API_PORT), AuditAPIHandler)
    print(f"[audit-logger] HTTP API on http://{API_HOST}:{API_PORT}", flush=True)
    server.serve_forever()


# ── Main ────────────────────────────────────────────────────────────────────
async def main():
    _ensure_log_dir()
    print(f"[audit-logger] log file: {LOG_FILE}", flush=True)
    print(f"[audit-logger] subjects: AUDIT={AUDIT_SUBJECT} DECISION={DECISION_SUBJECT}", flush=True)
    print(f"[audit-logger] decision auth: {'ENABLED' if HAS_DECISION_AUTH else 'DISABLED'}", flush=True)

    # Start HTTP API thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Start NATS reader
    await nats_reader()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[audit-logger] shutdown", flush=True)
        sys.exit(0)
