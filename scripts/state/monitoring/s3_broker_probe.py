#!/usr/bin/env python3
"""s3_broker_probe.py — S3* emission audit: wire truth vs log claims (G2).
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Epistemic problem (s3star_audit emission tier): Merkle proves the LOCAL log
is self-consistent, not that the nucleus EMITTED anything — a captured
nucleus writes a consistent log while emitting zero. The broker (LXC 106)
holds the one count the nucleus does not control.

Method — witness subscriber (not connz scraping): this probe subscribes to
vsf.alpha.vsf-nucleus.up.kernel_tick itself for OBSERVE_SECS and counts what
the broker actually delivers, then compares against nucleus-claimed ticks in
the same window from events.jsonl (RO bind-mount /mnt/telemetry, same source
kpi reads). A witness measures exactly "what the broker delivered", which for
a healthy broker equals received. Per-subject scraping of broker internals
would couple to monitoring-API shapes; a first-class subscriber cannot drift
that way. The witness channel is proven per-run (PING round-trip post-SUB):
an unproven witness never accuses the nucleus (witness_degraded, never
emit_silence on a broken self).

Findings (s3star_audit emission tier, severities verbatim):
  emit_silence           log advances, witness received 0 ............ sev 7
  emit_count_divergence  |witness-claimed|/claimed > 0.25, >=2 windows  sev 6
  emit_stale             witness newest older than log newest by margin  sev 7
  witness_degraded       the witness channel itself failed ............ sev 4
Persistence (>25% over >=2 consecutive windows) absorbs clock skew and
short-window noise by design — a single divergent window only arms.

No findings when the log itself is quiet: log-silence belongs to kpi
(no_kernel_ticks), never double-reported here.

Deterministic (R10): no random. Sporadic-ness is not needed here — every
window is fully observed; the surprise is in WHAT the wire shows, and the
nucleus cannot predict a 60s observation window it never sees declared.

Runs on LXC 107 (broker + telemetry reach). Cron:
    */10 * * * * flock -n /var/lock/vsf_broker_probe.lock python3 /root/vsf-scripts/s3_broker_probe.py >> /var/log/vsf-broker-probe.log 2>&1
Deploy ships shared/vsf_algedonic_pub.py alongside (canonical publisher).
"""
import json
import os
import re
import socket
import sqlite3
import sys
from datetime import datetime, timezone

EVENTS_PATH = os.environ.get("VSF_EVENTS_PATH", "/mnt/telemetry/events.jsonl")
PROBE_DB    = os.environ.get("VSF_BROKER_PROBE_DB",
                             "/var/lib/vsf/s3_star/broker_probe.db")
NATS_HOST   = os.environ.get("NATS_HOST", "10.10.20.20")
NATS_PORT   = int(os.environ.get("NATS_PORT", "4222"))
VSF_ID      = os.environ.get("VSF_ID", "alpha")
# Wire truth (verified live: wildcard census sees traffic HERE, none on the
# dash variant): production emits underscore vsf_nucleus while the Rust unit
# test pins dash vsf-nucleus (test constructs both sides — passes trivially
# while production diverges). Subscribe to what flows; override via env.
# Naming debt recorded: unify system_id spelling test-vs-prod (Rust side).
SUBJECT     = os.environ.get("VSF_KERNEL_TICK_SUBJECT",
                             f"vsf.{VSF_ID}.vsf_nucleus.up.kernel_tick")

OBSERVE_SECS  = int(os.environ.get("VSF_BROKER_PROBE_OBSERVE", "60"))
LOG_GRACE_SECS = 5
DIVERGE_RATIO = 0.25
STALE_MARGIN_SECS = 180

_SEVERITY = {
    "emit_silence": 7,
    "emit_count_divergence": 6,
    "emit_stale": 7,
    "witness_degraded": 4,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def read_log_window(path, start_ts, end_ts):
    """Kernel_tick events in [start, end] from the local tail: (count, max_tick, latest_ts)."""
    count, max_tick, latest = 0, None, None
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 512 * 1024))
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return count, max_tick, latest
    for line in raw.splitlines()[1:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event_type") != "kernel_tick":
            continue
        ts = _parse_ts(e.get("timestamp") or e.get("ts") or "")
        if ts is None or not (start_ts <= ts <= end_ts):
            continue
        count += 1
        tick = ((e.get("metrics", {}) or {}).get("kernel", {}) or {}).get("tick")
        if isinstance(tick, int) and (max_tick is None or tick > max_tick):
            max_tick = tick
        ets = e.get("timestamp") or e.get("ts") or ""
        if ets > (latest or ""):
            latest = ets
    return count, max_tick, latest


def _load_token():
    tok = os.environ.get("NATS_TOKEN", "")
    if tok:
        return tok
    try:
        with open("/etc/vsf/nats-creds.env", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("NATS_TOKEN="):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val:
                        return val
    except OSError:
        pass
    return None


def observe_wire(subject, observe_secs, token, host, port):
    """Subscribe and count delivered kernel_tick MSGs.

    Returns (proven, received, newest_ts): proven is False unless the full
    handshake (INFO/CONNECT/PING-PONG/SUB/PING-PONG) completed — an unproven
    witness accuses nobody.
    """
    received, newest = 0, ""
    try:
        sock = socket.create_connection((host, port), timeout=8)
        sock.settimeout(max(observe_secs + 10, 15))
        data = sock.recv(4096)
        if b"INFO" not in data:
            sock.close()
            return False, 0, ""
        sock.sendall(b'CONNECT {"verbose":false,"auth_token":"'
                     + token.encode() + b'"}\r\n')
        sock.sendall(b"PING\r\n")
        if b"PONG" not in sock.recv(4096):
            sock.close()
            return False, 0, ""
        sock.sendall(b"SUB " + subject.encode() + b" 1\r\n")
        sock.sendall(b"PING\r\n")
        if b"PONG" not in sock.recv(4096):
            sock.close()
            return False, 0, ""
        buf = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    if line.startswith(b"MSG"):
                        parts = line.split(b" ")
                        try:
                            nbytes = int(parts[-1])
                        except (ValueError, IndexError):
                            continue
                        while len(buf) < nbytes + 2:
                            more = sock.recv(65536)
                            if not more:
                                break
                            buf += more
                        payload, buf = buf[:nbytes], buf[nbytes + 2:]
                        received += 1
                        try:
                            ev = json.loads(payload.decode())
                            ets = ev.get("timestamp") or ev.get("ts") or ""
                            if ets > newest:
                                newest = ets
                        except ValueError:
                            pass
        except socket.timeout:
            pass
        sock.close()
        return True, received, newest
    except Exception as exc:
        print(f"broker_probe: witness channel failed: {exc}", file=sys.stderr)
        return False, 0, ""


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_poll TEXT NOT NULL, kind TEXT NOT NULL,
        detail TEXT NOT NULL, ref TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS poll_state (
        key TEXT PRIMARY KEY, value TEXT)""")
    return conn


def _load_pub_helper():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "shared"),
                 "/root/vsf-scripts/shared",
                 "/usr/local/lib/vsf"):
        mod = os.path.join(cand, "vsf_algedonic_pub.py")
        if os.path.isfile(mod):
            d = os.path.normpath(cand)
            if d not in sys.path:
                sys.path.insert(0, d)
            try:
                import vsf_algedonic_pub as _m
                return _m
            except Exception as exc:
                print(f"broker_probe: publisher import failed ({mod}): {exc}",
                      file=sys.stderr)
                return None
    return None


def run(events_path=EVENTS_PATH, db_path=PROBE_DB, publish=None,
        observe=None, observe_secs=OBSERVE_SECS):
    """One audit window. observe injects (proven, received, newest) for tests."""
    from datetime import timedelta
    ts_poll = now_iso()
    t0 = datetime.now(timezone.utc).replace(tzinfo=None)
    exceptions = []

    if observe is None:
        token = _load_token()
        if not token:
            exceptions.append(("witness_degraded",
                               "no NATS token available — witness cannot prove itself",
                               "broker witness"))
            proven, received, newest = False, 0, ""
        else:
            proven, received, newest = observe_wire(
                SUBJECT, observe_secs, token, NATS_HOST, NATS_PORT)
    else:
        proven, received, newest = observe

    # Read the log for the SAME interval just observed (plus a small grace
    # for mount/write lag). The old order — snapshot the log window BEFORE
    # observing — compared a past log against a future wire and manufactured
    # emit_silence on every slow-ticking system (caught on first live run).
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = t0 - timedelta(seconds=LOG_GRACE_SECS)
    log_count, _, log_latest = read_log_window(events_path, start, now)

    if not proven:
        if not any(k == "witness_degraded" for k, _, _ in exceptions):
            exceptions.append(("witness_degraded",
                               "witness channel unproven — accuses nobody",
                               "broker witness"))
    elif log_count > 0 and received == 0:
        exceptions.append(("emit_silence",
                           f"log claims {log_count} ticks in window, "
                           f"broker delivered 0",
                           "wire vs log"))
    elif log_count > 0:
        ratio = abs(received - log_count) / max(log_count, 1)
        if ratio > DIVERGE_RATIO:
            exceptions.append(("emit_count_pending",
                               f"witness={received} log={log_count} "
                               f"ratio={ratio:.2f} (needs 2nd window)",
                               "wire vs log"))
    if proven and received > 0 and log_latest and newest:
        try:
            skew = (datetime.strptime(log_latest[:19], "%Y-%m-%dT%H:%M:%S")
                    - datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S")
                    ).total_seconds()
            if skew > STALE_MARGIN_SECS:
                exceptions.append(("emit_stale",
                                   f"log newest {log_latest} ahead of wire "
                                   f"newest {newest} by {skew:.0f}s",
                                   "wire vs log"))
        except ValueError:
            pass

    conn = connect(db_path)
    emitted = []
    now_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    for kind, detail, ref in exceptions:
        emit_kind = kind
        if kind == "emit_count_pending":
            row = conn.execute(
                "SELECT value FROM poll_state WHERE key='diverge_armed'").fetchone()
            if row:
                emit_kind = "emit_count_divergence"
                conn.execute("DELETE FROM poll_state WHERE key='diverge_armed'")
            else:
                conn.execute("INSERT INTO poll_state(key,value) VALUES"
                             "('diverge_armed',?) ON CONFLICT(key) DO UPDATE "
                             "SET value=excluded.value", (ts_poll,))
                conn.commit()
                print(f"PENDING (arming, needs 2nd window) [{kind}] {detail}")
                continue
        else:
            conn.execute("DELETE FROM poll_state WHERE key='diverge_armed'")
        conn.execute("INSERT INTO exceptions (ts_poll, kind, detail, ref) "
                     "VALUES (?,?,?,?)", (ts_poll, emit_kind, detail, ref))
        emitted.append(emit_kind)
        print(f"EXCEPTION [{emit_kind}] {detail} ({ref})")
        sev = {"emit_silence": 7, "emit_count_divergence": 6,
               "emit_stale": 7, "witness_degraded": 4}.get(emit_kind, 5)
        rate_key = f"algedonic_pub_{emit_kind}_{now_hour}"
        if not conn.execute("SELECT 1 FROM poll_state WHERE key=?",
                            (rate_key,)).fetchone():
            conn.execute("INSERT INTO poll_state(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO NOTHING", (rate_key, ts_poll))
            if publish is not None:
                try:
                    ok = publish(category=emit_kind, severity=sev,
                                 source_id="s3-broker-probe", detail=detail)
                    print(f"broker_probe: algedonic [{emit_kind}] delivered={ok}")
                except Exception as exc:
                    print(f"broker_probe: publish failed [{emit_kind}]: {exc}",
                          file=sys.stderr)
    conn.commit()
    conn.close()
    if not emitted and not exceptions:
        print("broker_probe: nominal — wire matches log")
    return 1 if emitted else 0


def main() -> int:
    helper = _load_pub_helper()
    if helper is None:
        print("broker_probe: canonical publisher unavailable (ship shared/"
              "vsf_algedonic_pub.py alongside this script) — findings go "
              "to stdout/cron log ONLY this run", file=sys.stderr)
    rc = run(publish=(helper.publish if helper else None))
    return rc


if __name__ == "__main__":
    sys.exit(main())
