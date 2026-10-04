#!/usr/bin/env python3
"""
s3_viz_view — view-module #3: S3 resource bargain live view.

Shows pool state (zone, usage), active grants per LXC, and recent grant/restore
history by subscribing to the NATS channel vsf.alpha.s3.resource_grant (where
the s3 allocator publishes).

Stdlib-only: uses raw TCP sockets for NATS (no nats-py dependency).
Connection is established once at module import; events accumulate in a deque.
build_tick() returns the current view from accumulated events.

Deploy: LXC 109, served at /view/s3-viz.
"""
import json
import os
import socket
import threading
from collections import deque
from datetime import datetime, timezone

# ── Constants ────────────────────────────────────────────────────────────────
SCHEMA = "s3-viz-view/0.1"
MODULE_ID = "s3-viz"
SYSTEM_ID = "alpha"
NATS_HOST = os.environ.get("NATS_HOST", "10.10.20.20")
NATS_PORT = int(os.environ.get("NATS_PORT", "4222"))
GRANT_SUBJECT = "vsf.alpha.s3.resource_grant"
POOL_CORES = int(os.environ.get("S3_POOL_CORES", "3"))
POOL_MEM_MB = int(os.environ.get("S3_POOL_MEM_MB", "1536"))
SAFETY_MARGIN = float(os.environ.get("S3_SAFETY_MARGIN", "0.20"))
ZONE_GREEN_MAX = 0.60
ZONE_YELLOW_MAX = 0.80

# ── Global state ─────────────────────────────────────────────────────────────
_events = deque(maxlen=500)
_lock = threading.Lock()
_connected = False
_connection_error = None
_sub_thread = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond:06d}Z"


def _pool_zone(used_cores: int, used_mem: int) -> str:
    """Calculate pool zone from usage. Same logic as s3_resource_alloc.py."""
    eff_c = POOL_CORES * (1.0 - SAFETY_MARGIN)
    eff_m = POOL_MEM_MB * (1.0 - SAFETY_MARGIN)
    usage_c = used_cores / eff_c if eff_c > 0 else 1.0
    usage_m = used_mem / eff_m if eff_m > 0 else 1.0
    usage = max(usage_c, usage_m)
    if usage >= ZONE_YELLOW_MAX:
        return "red"
    if usage >= ZONE_GREEN_MAX:
        return "yellow"
    return "green"


def _build_state() -> dict:
    """Rebuild current pool + per-LXC state from accumulated events."""
    with _lock:
        evts = list(_events)

    # Track per-LXC extra allocations and last event
    lxcs: dict[str, dict] = {}
    pool_cores_used = 0
    pool_mem_used = 0
    history = []

    for evt in evts:
        et = evt.get("event_type", "")
        vmid = evt.get("vmid", "")
        role = evt.get("role", vmid)

        if et == "s3_resource_grant":
            gc = evt.get("grant_cores", 0)
            gm = evt.get("grant_mem_mb", 0)
            if vmid not in lxcs:
                lxcs[vmid] = {"extra_cores": 0, "extra_mem": 0, "status": "baseline"}
            lxcs[vmid]["extra_cores"] += gc
            lxcs[vmid]["extra_mem"] += gm
            lxcs[vmid]["status"] = "granted"
            lxcs[vmid]["last_grant_ts"] = evt.get("ts", "")
            pool_cores_used += gc
            pool_mem_used += gm
            history.append(evt)

        elif et == "s3_resource_restore":
            fc = evt.get("freed_cores", 0)
            fm = evt.get("freed_mem_mb", 0)
            if vmid not in lxcs:
                lxcs[vmid] = {"extra_cores": 0, "extra_mem": 0, "status": "baseline"}
            lxcs[vmid]["extra_cores"] = max(0, lxcs[vmid].get("extra_cores", 0) - fc)
            lxcs[vmid]["extra_mem"] = max(0, lxcs[vmid].get("extra_mem", 0) - fm)
            lxcs[vmid]["status"] = "baseline" if lxcs[vmid]["extra_cores"] == 0 else "granted"
            lxcs[vmid]["last_restore_ts"] = evt.get("ts", "")
            pool_cores_used = max(0, pool_cores_used - fc)
            pool_mem_used = max(0, pool_mem_used - fm)
            history.append(evt)

        elif et == "s3_pool_red_algedonic":
            history.append(evt)

    # Final status strings
    for vmid, lxc in lxcs.items():
        if lxc.get("extra_cores", 0) > 0:
            lxc["status"] = "granted"
        else:
            lxc["status"] = "baseline"

    zone = _pool_zone(pool_cores_used, pool_mem_used)

    # Recent history (last 20)
    recent = history[-20:] if history else []

    return {
        "pool": {
            "total_cores": POOL_CORES,
            "total_mem_mb": POOL_MEM_MB,
            "safety_margin": SAFETY_MARGIN,
            "used_cores": pool_cores_used,
            "used_mem_mb": pool_mem_used,
            "effective_cores": POOL_CORES * (1.0 - SAFETY_MARGIN),
            "effective_mem_mb": POOL_MEM_MB * (1.0 - SAFETY_MARGIN),
            "zone": zone,
            "zone_thresholds": {"green": ZONE_GREEN_MAX, "yellow": ZONE_YELLOW_MAX},
        },
        "grants_active": [
            {
                "vmid": vmid,
                "role": lxc.get("role", vmid),
                "extra_cores": lxc["extra_cores"],
                "extra_mem": lxc["extra_mem"],
                "status": lxc["status"],
            }
            for vmid, lxc in sorted(lxcs.items())
            if lxc.get("extra_cores", 0) > 0 or lxc.get("extra_mem", 0) > 0
        ],
        "lxcs": [
            {
                "vmid": vmid,
                "role": lxc.get("role", vmid),
                "extra_cores": lxc.get("extra_cores", 0),
                "extra_mem": lxc.get("extra_mem", 0),
                "status": lxc.get("status", "unknown"),
            }
            for vmid, lxc in sorted(lxcs.items())
        ],
        "history": [
            {
                "ts": e.get("ts", ""),
                "event_type": e.get("event_type", ""),
                "vmid": e.get("vmid", ""),
                "role": e.get("role", ""),
                "grant_cores": e.get("grant_cores", 0),
                "grant_mem_mb": e.get("grant_mem_mb", 0),
                "stress_depth": e.get("stress_depth"),
                "pool_zone": e.get("pool_zone"),
            }
            for e in recent
        ],
        "stats": {
            "events_total": len(evts),
            "events_window": len(recent),
        },
    }


# ── NATS subscriber (raw TCP, stdlib) ───────────────────────────────────────

def _nats_worker():
    """Background thread: connect to NATS, subscribe to grant channel, collect events."""
    global _connected, _connection_error, _events

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((NATS_HOST, NATS_PORT))

        # Handshake
        sock.sendall(b'CONNECT {"verbose":false,"pedantic":false}\r\n')
        sock.sendall(f'SUB {GRANT_SUBJECT} 1\r\n'.encode())
        sock.sendall(b'PING\r\n')

        _connected = True
        _connection_error = None
    except Exception as e:
        _connected = False
        _connection_error = str(e)
        if sock:
            sock.close()
        return

    # Read loop
    buf = b""
    while _connected:
        try:
            data = sock.recv(65536)
            if not data:
                break
            buf += data
        except socket.timeout:
            # Send periodic PING to keep connection alive
            try:
                sock.sendall(b'PING\r\n')
            except Exception:
                break
            continue
        except Exception:
            break

        while b"\r\n" in buf:
            line, buf = buf.split(b"\r\n", 1)
            if not line:
                continue
            if line == b"PING":
                try:
                    sock.sendall(b"PONG\r\n")
                except Exception:
                    pass
                continue
            if line.startswith(b"MSG "):
                # MSG <subject> <sid> <bytes>\r\n
                parts = line.split(b" ")
                if len(parts) >= 4:
                    try:
                        size = int(parts[3])
                        # Read payload: next `size` bytes + trailing \r\n
                        payload_raw = buf[:size]
                        buf = buf[size:]
                        if buf.startswith(b"\r\n"):
                            buf = buf[2:]
                        evt = json.loads(payload_raw.decode())
                        with _lock:
                            _events.append(evt)
                    except (ValueError, json.JSONDecodeError):
                        pass
                continue
            # INFO, OK, -ERR → ignore

    _connected = False
    if sock:
        sock.close()


# Start subscriber on import
_sub_thread = threading.Thread(target=_nats_worker, daemon=True)
_sub_thread.start()


# ── Public API ───────────────────────────────────────────────────────────────

def build_tick():
    """Build the current S3 resource bargain view tick."""
    state = _build_state()
    view = state

    findings = []
    if not _connected:
        findings.append(f"NATS_DISCONNECTED: {_connection_error or 'no connection'}")

    return {
        "schema": SCHEMA,
        "ts": _now_iso(),
        "system_id": SYSTEM_ID,
        "module_id": MODULE_ID,
        "source": f"nats://{NATS_HOST}:{NATS_PORT}/{GRANT_SUBJECT}",
        "view": view,
        "source_ref": {"nats_subject": GRANT_SUBJECT},
        "certified": _connected,
        "cert_basis": "nats-subscriber-live — connected to grant channel, {} events".format(len(_events)),
        "cert_findings": findings,
    }


if __name__ == "__main__":
    import time
    time.sleep(1)  # let subscriber connect
    print(json.dumps(build_tick(), indent=2))
