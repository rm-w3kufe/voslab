#!/usr/bin/env python3
"""
VSF BBS Poller — S1 command channel listener
Polls channel=vsf-nucleus on BBS, executes commands, posts results to vsf-results.
Deploy: /root/vsf_bbs_poller.py on n02 bare metal
"""

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BBS_BASE = "http://10.10.20.20:8600"
POLL_CHANNEL = "vsf-nucleus"
RESULT_CHANNEL = "vsf-results"
ALERTS_CHANNEL = "vsf-alerts"
S5_CONSOLE_URL = "http://192.168.0.104:8090"
AUTHOR = "vsf-nucleus-s1"
POLL_INTERVAL = 30
STATE_FILE = "/root/vsf_bbs_poller_state.json"
LOG_DIR = "/root/logs"
NUCLEUS_BIN = "/root/vsf-nucleus"

_running = True


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen_ids": [], "initialized": False}


def save_state(state: dict) -> None:
    # Keep seen_ids bounded at 200 entries
    state["seen_ids"] = state["seen_ids"][-200:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def bbs_get(channel: str, limit: int = 20) -> list:
    params = urllib.parse.urlencode({"channel": channel, "limit": limit})
    url = f"{BBS_BASE}/messages?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def bbs_post(channel: str, body: str) -> None:
    payload = json.dumps({"channel": channel, "author": AUTHOR, "body": body}).encode()
    req = urllib.request.Request(
        f"{BBS_BASE}/messages",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def cmd_ping() -> str:
    return f"PONG | host=n02 | ts={now_iso()}"


def cmd_status() -> str:
    parts = []
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        procs = [
            l for l in result.stdout.splitlines()
            if "vsf-nucleus" in l and "grep" not in l and "poller" not in l
        ]
        parts.append(f"processes={len(procs)}")
    except Exception as e:
        parts.append(f"processes=error({e})")

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        logs = sorted([
            f for f in os.listdir(LOG_DIR)
            if f.endswith(".log") and "bbs_poller" not in f
        ])
        if logs:
            log_path = os.path.join(LOG_DIR, logs[-1])
            with open(log_path) as f:
                lines = f.readlines()
            last = lines[-1].strip() if lines else "(empty)"
            parts.append(f"log={logs[-1]} | last={last[:120]}")
        else:
            parts.append("log=none")
    except Exception as e:
        parts.append(f"log=error({e})")

    parts.append(f"bin={'ok' if os.path.exists(NUCLEUS_BIN) else 'missing'}")
    return "STATUS | " + " | ".join(parts)


def cmd_help() -> str:
    return "COMMANDS: ping | status | help"


def execute(body: str) -> str:
    cmd = body.strip().lower().split()[0] if body.strip() else ""
    if cmd == "ping":
        return cmd_ping()
    elif cmd == "status":
        return cmd_status()
    elif cmd == "help":
        return cmd_help()
    else:
        return f"UNKNOWN: '{body.strip()[:80]}' | try: help"


def forward_to_s5(body: str) -> None:
    """Forward a vsf-alerts message to the S5 Console /alert endpoint."""
    if "[CRITICAL]" in body or "BRIEF-FAILED" in body or "BRIEF-TIMEOUT" in body:
        severity = "critical"
    elif "[WARNING]" in body or "BRIEF-BLOCKED" in body:
        severity = "warning"
    else:
        severity = "info"
    payload = json.dumps({
        "id": "bbs-alert",
        "severity": severity,
        "msg": body[:300],
        "source": "vsf-alerts",
    }).encode()
    req = urllib.request.Request(
        f"{S5_CONSOLE_URL}/alert",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def signal_handler(sig, frame):
    global _running
    _running = False


def main():
    global _running
    os.makedirs(LOG_DIR, exist_ok=True)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    state = load_state()
    seen = set(state["seen_ids"])
    alerts_seen = set(state.get("alerts_seen", []))

    # On first run: mark all existing messages as seen (don't re-execute old commands)
    if not state["initialized"]:
        try:
            existing = bbs_get(POLL_CHANNEL, limit=50)
            for m in existing:
                seen.add(m["message_id"])
            state["seen_ids"] = list(seen)
            state["initialized"] = True
            save_state(state)
            print(f"[{now_iso()}] initialized | baseline={len(existing)} messages marked seen", flush=True)
        except Exception as e:
            print(f"[{now_iso()}] init error: {e}", flush=True)

    if not state.get("alerts_initialized"):
        try:
            existing_alerts = bbs_get(ALERTS_CHANNEL, limit=50)
            for m in existing_alerts:
                alerts_seen.add(m["message_id"])
            state["alerts_seen"] = list(alerts_seen)
            state["alerts_initialized"] = True
            save_state(state)
        except Exception as e:
            print(f"[{now_iso()}] alerts init error: {e}", flush=True)

    print(f"[{now_iso()}] vsf-bbs-poller starting | seen={len(seen)}", flush=True)

    try:
        bbs_post(RESULT_CHANNEL,
            f"vsf-nucleus-s1 poller started | polling={POLL_CHANNEL} | interval={POLL_INTERVAL}s | ts={now_iso()}")
    except Exception as e:
        print(f"[{now_iso()}] startup post failed: {e}", flush=True)

    while _running:
        try:
            messages = bbs_get(POLL_CHANNEL, limit=20)
            new = [m for m in messages if m["message_id"] not in seen]
            for msg in new:
                mid = msg["message_id"]
                body = msg.get("body", "")
                author = msg.get("author", "?")
                print(f"[{now_iso()}] cmd from={author} id={mid} body={body!r}", flush=True)
                try:
                    result = execute(body)
                except Exception as e:
                    result = f"ERROR executing '{body[:40]}': {e}"
                try:
                    bbs_post(RESULT_CHANNEL, result)
                except Exception as e:
                    print(f"[{now_iso()}] post failed: {e}", flush=True)
                seen.add(mid)
                state["seen_ids"] = list(seen)
                save_state(state)
        except Exception as e:
            print(f"[{now_iso()}] poll error: {e}", flush=True)

        try:
            alert_msgs = bbs_get(ALERTS_CHANNEL, limit=20)
            new_alerts = [m for m in alert_msgs if m["message_id"] not in alerts_seen]
            for msg in new_alerts:
                mid = msg["message_id"]
                body = msg.get("body", "")
                try:
                    forward_to_s5(body)
                    print(f"[{now_iso()}] s5 forward id={mid} body={body[:60]!r}", flush=True)
                except Exception as e:
                    print(f"[{now_iso()}] s5 forward failed: {e}", flush=True)
                alerts_seen.add(mid)
                state["alerts_seen"] = list(alerts_seen)[-200:]
                save_state(state)
        except Exception as e:
            print(f"[{now_iso()}] alerts poll error: {e}", flush=True)

        for _ in range(POLL_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    try:
        bbs_post(RESULT_CHANNEL, f"vsf-nucleus-s1 poller stopping | ts={now_iso()}")
    except Exception:
        pass
    print(f"[{now_iso()}] vsf-bbs-poller stopped", flush=True)


if __name__ == "__main__":
    main()
