#!/usr/bin/env python3
"""
s5_ca_monitor.py — A1c: S5 CA root key expiry monitor.

Monitors the offline S5 CA root key (Ed25519) expiry date.
Publishes algedonic warnings at configurable thresholds.

Ref:
  RULES.md §Calendar — S5 CA root renewal (ITEM_6.4)
  TASK_INDEX A1c — AX-STATE: S5 CA monitor

Exit codes:
  0 = green (OK, >180 days)
  1 = yellow (WARN, 90-180 days)
  2 = orange (ALERT, 30-90 days) → algedonic published
  3 = red (CRITICAL, <30 days) → algedonic published
  9 = expired or config error
"""
import json, os, socket, sys, time
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
S5_CA_CONFIG   = os.environ.get("S5_CA_CONFIG",    "/etc/vsf/s5_ca.json")
NATS_HOST      = os.environ.get("NATS_HOST",        "10.10.20.20")
NATS_PORT      = int(os.environ.get("NATS_PORT",    "4222"))
VSF_ID         = os.environ.get("VSF_ID",           "alpha")
THRESHOLD_YL   = int(os.environ.get("THRESHOLD_YELLOW", "180"))
THRESHOLD_OR   = int(os.environ.get("THRESHOLD_ORANGE", "90"))
THRESHOLD_RD   = int(os.environ.get("THRESHOLD_RED",    "30"))

FINGERPRINT = "(unknown)"
PUB_HEX     = "(unknown)"
EXPIRES_AT  = None
RENEW_BEFORE = None


def emit(msg, level="INFO"):
    """Print a structured log line to stdout (captured by systemd)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[s5-ca-monitor] {ts} [{level}] {msg}", flush=True)


def load_config():
    global FINGERPRINT, PUB_HEX, EXPIRES_AT, RENEW_BEFORE
    if not os.path.exists(S5_CA_CONFIG):
        emit(f"Config not found: {S5_CA_CONFIG}", "ERROR")
        return False
    try:
        with open(S5_CA_CONFIG) as f:
            cfg = json.load(f)
        FINGERPRINT = cfg.get("root_key_fingerprint", FINGERPRINT)
        PUB_HEX     = cfg.get("root_pub_hex", PUB_HEX)
        EXPIRES_AT  = cfg.get("expires_at")
        RENEW_BEFORE = cfg.get("renew_before", "?")
        emit(f"Config loaded: expires_at={EXPIRES_AT} fpr={FINGERPRINT[:16]}…")
        return True
    except (OSError, json.JSONDecodeError) as e:
        emit(f"Cannot read config: {e}", "ERROR")
        return False


def days_remaining(target_str):
    if not target_str:
        return None
    try:
        target = datetime.fromisoformat(target_str.replace("Z", "+00:00"))
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max((target - now).days, -1)
    except (ValueError, TypeError) as e:
        emit(f"Bad date '{target_str}': {e}", "ERROR")
        return None


def publish_algedonic(severity, category, message):
    """Publish algedonic signal to NATS (best-effort, short timeout)."""
    payload = json.dumps({
        "source_id": "s5-ca-monitor",
        "category": category,
        "severity": severity,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    try:
        s = socket.create_connection((NATS_HOST, NATS_PORT), timeout=3)
        s.settimeout(3)
        s.sendall(f"PUB vsf.{VSF_ID}.algedonic {len(payload)}\r\n".encode())
        s.sendall(payload.encode() + b"\r\n")
        s.close()
        emit(f"Algedonic sent: sev={severity} cat={category}")
    except Exception as e:
        emit(f"Algedonic publish failed: {e}", "WARN")


def main():
    emit("S5 CA Monitor starting")
    if not load_config():
        emit("Config error — exiting", "ERROR")
        publish_algedonic(7, "ca_config_error",
            "S5 CA monitor: cannot load /etc/vsf/s5_ca.json")
        return 9

    remaining = days_remaining(EXPIRES_AT)
    if remaining is None:
        emit(f"No valid expiry date in config", "ERROR")
        return 9

    emit(f"Root key expires: {EXPIRES_AT}  days_remaining={remaining}  "
         f"renew_before={RENEW_BEFORE}  fpr={FINGERPRINT[:16]}…")

    # ── Evaluate thresholds ─────────────────────────────────────────────────
    if remaining < 0:
        emit("☠ EXPIRED — S5 CA root key has expired! Renew immediately!", "CRITICAL")
        publish_algedonic(9, "ca_expired",
            f"S5 CA root key EXPIRED. fpr={FINGERPRINT}")
        return 9

    if remaining < THRESHOLD_RD:
        emit(f"🔴 CRITICAL: root key expires in {remaining} days! "
             f"Renew before {RENEW_BEFORE}. Action required.", "CRITICAL")
        publish_algedonic(7, "ca_expiry_critical",
            f"S5 CA root key expires in {remaining}d. fpr={FINGERPRINT}")
        return 3

    if remaining < THRESHOLD_OR:
        emit(f"🟠 ALERT: root key expiry in {remaining} days. "
             f"Prepare renewal before {RENEW_BEFORE}.", "ALERT")
        publish_algedonic(5, "ca_expiry_alert",
            f"S5 CA root key expires in {remaining}d. fpr={FINGERPRINT}")
        return 2

    if remaining < THRESHOLD_YL:
        emit(f"🟡 WARN: root key expiry approaching — {remaining} days until "
             f"{EXPIRES_AT}", "WARN")
        return 1

    emit(f"🟢 OK: {remaining} days until root key expiry", "INFO")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as e:
        emit(f"Unhandled error: {e}", "ERROR")
        rc = 9
    sys.exit(rc)
