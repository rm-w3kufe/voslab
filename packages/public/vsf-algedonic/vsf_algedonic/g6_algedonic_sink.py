#!/usr/bin/env python3
"""g6_algedonic_sink.py — first real downstream for the algedonic channel.

Closes G6 of the consolidated plan ("algedonic escalación real, no solo log").
Until now `vsf_algedonic_subscriber.py` persists + prints to stderr; an
operator can read the jsonl but no human-facing alert exists. This sink
turns persisted events into actionable lines an operator inbox can poll
(and, if configured, posts them to an external webhook).

Design (Tier α, deliberately minimal):
  - Tail the algedonic jsonl produced by vsf_algedonic_subscriber.py.
  - For each new line, evaluate severity ≥ threshold (default 1.0).
  - Dedup by (source_id, category, minute) so a storm becomes one line.
  - Append a human-readable record to /alerts/operator_inbox.log.
  - If ALG_WEBHOOK_URL is set, POST the JSON (best-effort, no retries —
    we never block the inbox on a flaky external).

Run as a systemd unit on LXC 104 alongside the subscriber.

Environment:
  ALG_LOG_PATH       jsonl produced by the subscriber  (default /root/algedonic/vsf_algedonic.jsonl)
  ALG_INBOX_PATH     operator-facing log              (default /alerts/operator_inbox.log)
  ALG_SEVERITY_MIN   skip events below this severity  (default 1.0)
  ALG_DEDUP_WINDOW_S dedup key time bucket size       (default 60)
  ALG_WEBHOOK_URL    optional POST target              (default unset → disabled)
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

LOG_PATH = os.environ.get("ALG_LOG_PATH", "/root/algedonic/vsf_algedonic.jsonl")
INBOX_PATH = os.environ.get("ALG_INBOX_PATH", "/alerts/operator_inbox.log")
SEVERITY_MIN = float(os.environ.get("ALG_SEVERITY_MIN", "1.0"))
DEDUP_WINDOW_S = int(os.environ.get("ALG_DEDUP_WINDOW_S", "60"))
WEBHOOK_URL = os.environ.get("ALG_WEBHOOK_URL") or None
POLL_INTERVAL_S = 1.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_inbox() -> None:
    os.makedirs(os.path.dirname(INBOX_PATH), exist_ok=True)


def render_line(record: dict) -> str:
    payload = record.get("payload") or {}
    return (
        f"{now_iso()}  sev={payload.get('severity','?')}  "
        f"src={payload.get('source_id','?')}  cat={payload.get('category','?')}  "
        f"received_at={record.get('received_at','?')}  "
        f"detail={json.dumps(payload, ensure_ascii=False)[:200]}"
    )


def post_webhook(record: dict) -> None:
    """Fire-and-forget POST. Never raises into the main loop."""
    if not WEBHOOK_URL:
        return
    try:
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=json.dumps(record).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3).close()
    except Exception as e:
        print(f"[g6-sink] webhook POST failed: {e!r}", file=sys.stderr, flush=True)


def dedup_key(record: dict, bucket_s: int) -> tuple[str, str, int]:
    """Bucket events into (source_id, category, minute) so a flap is one alert."""
    payload = record.get("payload") or {}
    ts = int(time.time()) // bucket_s
    return (str(payload.get("source_id", "?")), str(payload.get("category", "?")), ts)


def tail(path: str):
    """Generator yielding new lines as they're appended. Reopens on rotation."""
    while True:
        try:
            with open(path, "r") as f:
                f.seek(0, os.SEEK_END)  # start at EOF — we only care about new events
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(POLL_INTERVAL_S)
                        # Detect rotation: file shrank or inode changed
                        try:
                            cur_size = os.fstat(f.fileno()).st_size
                            disk_size = os.stat(path).st_size
                            if disk_size < cur_size:
                                break  # reopen
                        except FileNotFoundError:
                            break
                        continue
                    yield line.rstrip("\n")
        except FileNotFoundError:
            time.sleep(2)


def main() -> int:
    ensure_inbox()
    print(f"[g6-sink] starting — log={LOG_PATH} inbox={INBOX_PATH} sev_min={SEVERITY_MIN} "
          f"dedup_window={DEDUP_WINDOW_S}s webhook={'yes' if WEBHOOK_URL else 'no'}",
          flush=True)

    seen: dict[tuple, float] = {}
    for line in tail(LOG_PATH):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[g6-sink] skip malformed: {e}", file=sys.stderr, flush=True)
            continue

        sev = float((record.get("payload") or {}).get("severity") or 0)
        if sev < SEVERITY_MIN:
            continue

        key = dedup_key(record, DEDUP_WINDOW_S)
        now_t = time.time()
        # Evict expired keys cheaply (bounded mem)
        for k, t in list(seen.items()):
            if now_t - t > DEDUP_WINDOW_S * 4:
                del seen[k]
        if key in seen:
            continue
        seen[key] = now_t

        rendered = render_line(record)
        with open(INBOX_PATH, "a") as inbox:
            inbox.write(rendered + "\n")
        print(f"[g6-sink] inbox <- {rendered[:160]}", flush=True)
        post_webhook(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
