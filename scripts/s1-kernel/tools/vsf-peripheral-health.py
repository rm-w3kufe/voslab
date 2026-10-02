#!/usr/bin/env python3
"""vsf-peripheral-health — continuous end-to-end health probe for peripherals.

PERIPHERAL-HEALTH-CENSUS (2026-07-03): every declared peripheral is probed every
5 minutes (systemd timer). On N consecutive failures → algedonic_ledger INSERT
(sev 8.0, 'peripheral_down'). On recovery → sev 2.0 recovery event.

Pattern: vsf-topology-reconcile (oneshot timer, exits cleanly, state persisted via
state.db). Runs on the n02 host, probes n01 peripherals end-to-end from outside.

Usage:
  # Oneshot (timer):
  /usr/local/bin/vsf-peripheral-health.py

  # Dry-run (no algedonic, verbose):
  /usr/local/bin/vsf-peripheral-health.py --dry-run

Design:
  - Manifest: /usr/local/etc/vsf/peripherals.manifest.json
  - State: state.db table peripheral_health (persists consecutive failures)
  - Timer: vsf-peripheral-health.timer (5min, OnCalendar=*:00/5)
"""

import json, os, socket, ssl, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Config paths
MANIFEST_PATH = "/usr/local/etc/vsf/peripherals.manifest.json"
STATE_DB = "/var/lib/vsf-state/state.db"
DRY_RUN = "--dry-run" in sys.argv

# ---------------------------------------------------------------------------
# Probe functions
# ---------------------------------------------------------------------------

# Sentinel to ensure error is always a string
def _err(s: str) -> str:
    return s if s is not None else ""


def probe_http(host: str, port: int, endpoint: str, expect_status: int,
               expect_body: str = "", timeout: int = 5) -> dict:
    """Probe an HTTP endpoint. Returns {ok, status, body_snippet, error}."""
    url = f"http://{host}:{port}{endpoint}"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "vsf-peripheral-health/0.1")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:4096]
            status = resp.status
            ok = (status == expect_status)
            body_mismatch = False
            if expect_body and ok:
                ok = expect_body.lower() in body.lower()
                if not ok:
                    body_mismatch = True
            error_msg = ""
            if not ok:
                if body_mismatch:
                    error_msg = f"expected status {expect_status} with body containing '{expect_body}', got status {status} but '{expect_body}' not found in first 4096 bytes"
                else:
                    error_msg = f"expected status {expect_status}{' with '+expect_body if expect_body else ''}, got {status}"
            return {
                "ok": ok,
                "status": status,
                "body_snippet": body[:100],
                "error": _err(error_msg)
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "body_snippet": str(e)[:100],
                "error": _err(f"HTTP {e.code}: {e.reason}")}
    except urllib.error.URLError as e:
        return {"ok": False, "status": 0, "body_snippet": "",
                "error": _err(f"connection failed: {e.reason}")}
    except Exception as e:
        return {"ok": False, "status": 0, "body_snippet": "",
                "error": _err(f"unexpected error: {e}")}


def probe_tls_http(host: str, port: int, endpoint: str, expect_status: int,
                   expect_body: str = "", sni: str = "", timeout: int = 5) -> dict:
    """Probe an HTTPS endpoint with TLS. Returns {ok, status, body_snippet, error}."""
    url = f"https://{host}:{port}{endpoint}"
    ctx = ssl.create_default_context()
    if sni:
        ctx.check_hostname = True
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "vsf-peripheral-health/0.1")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:4096]
            status = resp.status
            ok = (status == expect_status)
            body_mismatch = False
            if expect_body and ok:
                ok = expect_body.lower() in body.lower()
                if not ok:
                    body_mismatch = True
            error_msg = ""
            if not ok:
                if body_mismatch:
                    error_msg = f"expected status {expect_status} with body containing '{expect_body}', got status {status} but '{expect_body}' not found in first 4096 bytes"
                else:
                    error_msg = f"expected status {expect_status}{' with '+expect_body if expect_body else ''}, got {status}"
            return {
                "ok": ok,
                "status": status,
                "body_snippet": body[:100],
                "error": _err(error_msg)
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "body_snippet": str(e)[:100],
                "error": _err(f"HTTP {e.code}: {e.reason}")}
    except urllib.error.URLError as e:
        return {"ok": False, "status": 0, "body_snippet": "",
                "error": _err(f"connection failed: {e.reason}")}
    except Exception as e:
        return {"ok": False, "status": 0, "body_snippet": "",
                "error": _err(f"unexpected error: {e}")}


def probe_ssh_port(host: str, port: int, ssh_user: str = "rmw3",
                   timeout: int = 10) -> dict:
    """Probe a port on a remote host via SSH (port check from inside).

    Needed for services behind firewalls. Uses ssh to check port on 127.0.0.1
    from inside the target host. Returns {ok, status, body_snippet, error}."""
    try:
        cmd = ["ssh", f"{ssh_user}@{host}",
               f"timeout {timeout} bash -c 'echo > /dev/tcp/127.0.0.1/{port}'"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        ok = (result.returncode == 0)
        return {
            "ok": ok,
            "status": 0 if ok else result.returncode,
            "body_snippet": "",
            "error": _err("") if ok else f"port {port} not reachable on {host}:{port}"
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": 0, "body_snippet": "",
                "error": _err(f"ssh timeout after {timeout}s")}
    except Exception as e:
        return {"ok": False, "status": 0, "body_snippet": "",
                "error": _err(f"ssh failed: {e}")}


def probe_peripheral(p: dict) -> dict:
    """Run the appropriate probe for a peripheral."""
    probe_type = p.get("probe_type", "http")
    host = p["host"]
    port = p["port"]
    endpoint = p.get("health_endpoint", "/")
    expect = p.get("expect_status", 200)
    expect_body = p.get("expect_body_contains", "")
    timeout = p.get("connect_timeout_s", 5)
    sni = p.get("expected_tls_sni", host)
    ssh_user = p.get("ssh_user", "rmw3")

    if probe_type == "external_only":
        # Dormant service — always reports "not reachable" but no algedonic.
        return {"ok": False, "status": 0, "body_snippet": "",
                "error": _err("external_only — not yet reachable from monitoring host (expected)")}
    if probe_type == "ssh_port":
        return probe_ssh_port(host, port, ssh_user, timeout)
    elif probe_type == "tls_http":
        return probe_tls_http(host, port, endpoint, expect, expect_body, sni, timeout)
    else:
        return probe_http(host, port, endpoint, expect, expect_body, timeout)


# ---------------------------------------------------------------------------
# State DB helpers
# ---------------------------------------------------------------------------

def ensure_state_table():
    """Create peripheral_health table if not exists."""
    if DRY_RUN:
        return
    try:
        subprocess.run(
            ["sqlite3", STATE_DB,
             "CREATE TABLE IF NOT EXISTS peripheral_health ("
             "  peripheral_id TEXT PRIMARY KEY,"
             "  consecutive_failures INTEGER NOT NULL DEFAULT 0,"
             "  last_ok INTEGER NOT NULL DEFAULT 1,"
             "  last_checked_ts TEXT,"
             "  last_error TEXT"
             ")"],
            capture_output=True, timeout=10, check=True
        )
    except Exception as e:
        print(f"[peripheral-health] WARN: could not init state table: {e}", file=sys.stderr)


def read_state(pid: str) -> dict:
    """Read peripheral health state from DB."""
    if DRY_RUN:
        return {"consecutive_failures": 0, "last_ok": 1}
    try:
        result = subprocess.run(
            ["sqlite3", STATE_DB,
             f"SELECT consecutive_failures, last_ok FROM peripheral_health WHERE peripheral_id='{pid}'"],
            capture_output=True, text=True, timeout=10
        )
        line = result.stdout.strip()
        if line:
            parts = line.split("|")
            return {"consecutive_failures": int(parts[0]), "last_ok": int(parts[1])}
    except Exception:
        pass
    return {"consecutive_failures": 0, "last_ok": 1}


def write_state(pid: str, consec: int, ok: int, error: str = ""):
    """Upsert peripheral health state."""
    if DRY_RUN:
        return
    ts = datetime.now(timezone.utc).isoformat()
    error_esc = error.replace("'", "''")
    try:
        subprocess.run(
            ["sqlite3", STATE_DB,
             f"INSERT OR REPLACE INTO peripheral_health "
             f"(peripheral_id, consecutive_failures, last_ok, last_checked_ts, last_error) "
             f"VALUES ('{pid}', {consec}, {ok}, '{ts}', '{error_esc}')"],
            capture_output=True, timeout=10, check=True
        )
    except Exception as e:
        print(f"[peripheral-health] WARN: state write failed: {e}", file=sys.stderr)


def emit_algedonic(peripheral_id: str, severity: float, message: str, detail: dict):
    """Publish an algedonic signal via NATS (q17.phase_3 migration).

    Previously wrote to the orphan algedonic_ledger table in state.db
    (ledger_B — ONE writer, NO reader). Now publishes via NATS like every
    other emitter, so findings land in ledger_A (LXC 104) and get triaged,
    deduped, and surfaced by the same path as everything else.

    Per feedback_no_proxy_consolidation: one channel, not two.
    """
    if DRY_RUN:
        print(f"  [algedonic] would emit: sev={severity} id={peripheral_id} msg={message}")
        return
    ts = datetime.now(timezone.utc).isoformat()
    # Determine category: peripheral_down for failures, peripheral_recovered for recoveries
    is_recovery = severity <= 3.0
    category = "peripheral_recovered" if is_recovery else "peripheral_down"
    payload_data = {
        "ts": ts,
        "source_id": "vsf-peripheral-health",
        "category": category,
        "severity": severity,
        "signal": 1,
        "peripheral_id": peripheral_id,
        "message": message,
        **detail,
    }
    payload = json.dumps(payload_data)
    subject = f"vsf.alpha.algedonic.{category}"

    # Load NATS token (same pattern as vsf-state-populate)
    nats_token = os.environ.get("NATS_TOKEN", "")
    if not nats_token:
        creds_path = "/etc/vsf/nats-creds.env"
        if os.path.exists(creds_path):
            with open(creds_path) as f:
                for line in f:
                    if line.startswith("NATS_TOKEN="):
                        nats_token = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not nats_token:
        print("[peripheral-health] WARN: NATS_TOKEN unset — algedonic NOT published", file=sys.stderr)
        return

    # Publish via NATS (socket-based, same pattern as populate.sh)
    import socket as _socket
    try:
        s = _socket.create_connection(("10.10.20.20", 4222), timeout=5)
        s.settimeout(5)
        s.recv(4096)  # INFO
        s.sendall(b'CONNECT {"verbose":false,"auth_token":"' + nats_token.encode() + b'"}\r\n')
        body = payload.encode()
        s.sendall(b"PUB " + subject.encode() + b" " + str(len(body)).encode() + b"\r\n" + body + b"\r\n")
        s.sendall(b"PING\r\n")
        r = s.recv(4096)
        s.close()
        if b"-ERR" in r:
            print(f"[peripheral-health] NATS refused: {r[:120].decode(errors='replace')}", file=sys.stderr)
        else:
            print(f"  [algedonic] published: {category} sev={severity} id={peripheral_id}", flush=True)
    except Exception as e:
        print(f"[peripheral-health] WARN: NATS publish failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # Load manifest
    if not os.path.exists(MANIFEST_PATH):
        print(f"[peripheral-health] manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 1
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    defaults = manifest.get("probe_defaults", {})
    fail_threshold = defaults.get("fail_threshold", 3)
    recovery_threshold = defaults.get("recovery_threshold", 2)
    peripherals = manifest.get("peripherals", [])

    if not peripherals:
        print("[peripheral-health] no peripherals declared in manifest", file=sys.stderr)
        return 0

    # Ensure state table exists
    ensure_state_table()

    ts_banner = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[peripheral-health] probe cycle {ts_banner}")
    print(f"  peripherals: {len(peripherals)}")

    any_failure = False

    for p in peripherals:
        pid = p["id"]
        label = p.get("label", pid)
        state = read_state(pid)
        consec = state["consecutive_failures"]
        was_ok = state["last_ok"]

        # Per-peripheral algedonic gate (e.g. dormant peripherals should not alarm)
        algedonic_enabled = p.get("algedonic_on_failure", True)

        # Probe
        result = probe_peripheral(p)
        now_ok = result["ok"]

        if now_ok:
            if was_ok:
                # Still healthy
                consec = 0
            else:
                # Recovering
                consec = max(0, consec - 1)
                if consec <= recovery_threshold:
                    print(f"  \u2713 {label} — RECOVERED (consec={consec})")
                    emit_algedonic(pid, 2.0, f"{label} recovered",
                                   {"error": result.get("error", ""), "consecutive_failures": consec})
                    consec = 0
        else:
            consec += 1
            error = result.get("error", "unknown error")
            print(f"  \u2717 {label} — FAIL ({error}) consec={consec}/{fail_threshold}")

            if consec >= fail_threshold and was_ok:
                # First crossing of threshold → emit HIGH algedonic
                if algedonic_enabled:
                    print(f"  \u26D4 {label} — ALGEDONIC HIGH (sev=8.0) after {consec} consecutive failures")
                    emit_algedonic(pid, 8.0, f"{label} DOWN — {error}",
                                   {"consecutive_failures": consec, "probe_result": result})
                else:
                    print(f"  \u26AA {label} — algedonic suppressed (dormant/peripheral)")
                any_failure = True
            elif consec >= fail_threshold and not was_ok:
                # Sustained: re-emit every 3 additional failures
                if consec % 3 == 0 and algedonic_enabled:
                    emit_algedonic(pid, 6.0, f"{label} still DOWN ({consec} failures) — {error}",
                                   {"consecutive_failures": consec, "probe_result": result})
                any_failure = True

        # Persist state
        write_state(pid, consec, 1 if now_ok else 0, str(result.get("error", "")))

        status_char = "\u2713" if now_ok else "\u2717"
        status_tag = "RECOVERED" if (now_ok and not was_ok) else (
            "DOWN" if not now_ok else "OK"
        )
        detail = result.get("body_snippet", "")[:60]
        print(f"  {status_char} {label:20s} \u2192 {status_tag:9s}  {detail}")

    print(f"[peripheral-health] cycle complete{' — WITH FAILURES' if any_failure else ' — all OK'}")
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
