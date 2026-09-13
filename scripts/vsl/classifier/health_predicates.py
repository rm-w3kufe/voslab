#!/usr/bin/env python3
"""
health_predicates.py — VSF custom predicates for Service Health Check.

Predicates for health_check.tree.vsm decision tree.
Classifies health check results for watchdog decisions.
"""
from __future__ import annotations

import socket
import subprocess
import os

# Configuration
NATS_HOST = os.environ.get("NATS_HOST", "10.10.20.20")
NATS_PORT = 4222
DISK_PATH = "/var/lib/vsf-state"
ALERTS_DB_PATH = "/var/lib/vsf-state/s5-alerts.db"
DISK_WARN_PCT = 85
ALERTS_ROW_WARN = 50_000
ALERTS_SIZE_WARN = 500 * 1024 * 1024  # 500 MB


def _pct_exec(lxc: int, cmd: list, timeout: int = 10) -> subprocess.CompletedProcess:
    """Execute command in LXC container."""
    return subprocess.run(
        ["pct", "exec", str(lxc), "--"] + cmd,
        capture_output=True, text=True, timeout=timeout
    )


def service_active(ctx: dict) -> bool:
    """Check if service is active."""
    lxc = ctx.get("lxc", 101)
    svc = ctx.get("service", "vsf-nucleus-operational")
    try:
        r = _pct_exec(lxc, ["systemctl", "is-active", svc])
        return r.stdout.strip() == "active"
    except Exception:
        return False


def nats_reachable(ctx: dict) -> bool:
    """Check if NATS is reachable (TCP connect)."""
    try:
        s = socket.create_connection((NATS_HOST, NATS_PORT), timeout=5)
        s.recv(64)
        s.close()
        return True
    except Exception:
        return False


def nats_authenticated(ctx: dict) -> bool:
    """Check if NATS accepts authenticated connection."""
    nats_token = os.environ.get("VSF_NATS_TOKEN")
    if not nats_token:
        return True  # skipped if not configured
    connect = f'{{"verbose": false, "pedantic": false, "auth_token": "{nats_token}", "name": "watchdog"}}'
    try:
        s = socket.create_connection((NATS_HOST, NATS_PORT), timeout=5)
        s.settimeout(5)
        info = s.recv(4096)
        if not info.startswith(b"INFO"):
            s.close()
            return False
        s.sendall(b"CONNECT " + connect.encode() + b"\r\n")
        s.sendall(b"PING\r\n")
        resp = s.recv(256)
        s.close()
        return b"PONG" in resp
    except Exception:
        return False


def disk_ok(ctx: dict) -> bool:
    """Check if disk usage is below warning threshold."""
    try:
        r = _pct_exec(101, ["df", "--output=pcent", DISK_PATH])
        lines = [l.strip() for l in r.stdout.splitlines()
                 if l.strip() and l.strip() != "Use%"]
        if not lines:
            return True
        pct = int(lines[-1].rstrip("%"))
        return pct < DISK_WARN_PCT
    except Exception:
        return True


def alerts_db_ok(ctx: dict) -> bool:
    """Check if alerts DB is below warning thresholds."""
    code = (
        f"import sqlite3,os; db='{ALERTS_DB_PATH}'; "
        f"sz=os.path.getsize(db) if os.path.exists(db) else -1; "
        f"n=sqlite3.connect(db).execute('SELECT COUNT(*) FROM meta').fetchone()[0] "
        f"if sz>=0 else -1; print(n,sz)"
    )
    try:
        r = _pct_exec(101, ["python3", "-c", code], timeout=15)
        if r.returncode != 0 or not r.stdout.strip():
            return True
        parts = r.stdout.strip().split()
        rows, size = int(parts[0]), int(parts[1])
        return rows <= ALERTS_ROW_WARN and size <= ALERTS_SIZE_WARN
    except Exception:
        return True


# Registry for socratic engine
HEALTH_PREDICATES = {
    "service_active": service_active,
    "nats_reachable": nats_reachable,
    "nats_authenticated": nats_authenticated,
    "disk_ok": disk_ok,
    "alerts_db_ok": alerts_db_ok,
}
