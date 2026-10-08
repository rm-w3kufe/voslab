#!/usr/bin/env python3
"""vsf-s5-ledger — ITEM_16: S5 algedonic canal al humano.

Runs on LXC 104 (s5-policy). Subscribes to algedonic events from all sources
via NATS, writes to algedonic_ledger (state.db), applies autopilot_rules when
matched, and exposes a simple query interface for the TUI and onboard.sh.

Beer: "The algedonic channel bypasses the chain of command to reach S5/the human
directly. It is the signal that cannot be ignored."

Algedonic sources:
  vsf.alpha.algedonic.>          — nucleus + general algedonic bus
  vsf.alpha.s5.covenant_halt     — covenant halt events
  vsf.alpha.s3_star.audit.>      — S3* audit findings

State.db (on n02 host): /var/lib/vsf-state/state.db (accessed via SSH or mount)
Local mirror (LXC 104): /root/algedonic/ledger.db (SQLite replica for fast reads)
"""
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

NATS_HOST = os.environ.get("NATS_HOST", "10.10.20.20")
NATS_PORT = int(os.environ.get("NATS_PORT", "4222"))
VSF_ID    = os.environ.get("VSF_ID", "alpha")

# Local ledger DB (replica on LXC 104 for fast TUI reads)
LEDGER_DB = os.environ.get("LEDGER_DB", "/root/algedonic/ledger.db")
# Canonical state.db path (on n02 host, accessible via SSH from LXC 104).
# 2026-10-08 (A4-OPS-01): default fue 10.10.20.1 — filtrado por PVEFW-HOST-IN
# desde 104 (sin RETURN :22 para 10.10.20.104) → timeout silencioso. Ruta
# aprobada S5: 192.168.0.168 (eth0, PVEFW ya acepta 192.168.0.0/24:22) + key.
STATE_DB_HOST = os.environ.get("STATE_DB_HOST", "192.168.0.168")
STATE_DB_PATH = os.environ.get("STATE_DB_PATH", "/var/lib/vsf-state/state.db")

RECONNECT_DELAY_S = 5

# NATS subjects to subscribe
SUBJECTS = [
    (f"vsf.{VSF_ID}.algedonic.>",         "1"),
    (f"vsf.{VSF_ID}.s5.covenant_halt",    "2"),
    (f"vsf.{VSF_ID}.s3_star.audit.>",     "3"),
]

# Severity heuristics by event type
SEVERITY_MAP = {
    "covenant_halt":       8.0,
    "semantic_divergence": 7.0,
    "emit_silence":        6.0,
    "invariant_breach":    5.0,
    "drift_alert":         3.0,
    "signal_escalated":    4.0,
    "algedonic":           5.0,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


# ── Local ledger DB ───────────────────────────────────────────────────────────

def open_ledger() -> sqlite3.Connection:
    Path(LEDGER_DB).parent.mkdir(parents=True, exist_ok=True)
    # timeout=30: busy collisions with vsf-s5-agent (10s) must WAIT, not fail —
    # a failed commit left a hot journal + open txn (never rolled back) that
    # locked out ALL readers for hours (2026-10-08 incident).
    db = sqlite3.connect(LEDGER_DB, check_same_thread=False, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS algedonic_ledger (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ts             TEXT NOT NULL,
            source         TEXT NOT NULL,
            type           TEXT NOT NULL,
            severity       REAL NOT NULL,
            payload        TEXT NOT NULL,
            action_auto    TEXT,
            action_human   TEXT,
            status         TEXT NOT NULL DEFAULT 'pending_human',
            ack_ts         TEXT,
            ack_note       TEXT,
            autopilot_rule INTEGER
        );
        CREATE TABLE IF NOT EXISTS autopilot_rules (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            name                   TEXT NOT NULL UNIQUE,
            description            TEXT NOT NULL,
            condition_type         TEXT NOT NULL,
            condition_severity_max REAL NOT NULL,
            condition_extra        TEXT,
            auto_action            TEXT NOT NULL,
            requires_ack_after     INTEGER NOT NULL DEFAULT 1,
            active                 INTEGER NOT NULL DEFAULT 1,
            created_at             TEXT NOT NULL,
            created_by             TEXT NOT NULL DEFAULT 'rmw3'
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_status ON algedonic_ledger(status);
        CREATE INDEX IF NOT EXISTS idx_ledger_ts     ON algedonic_ledger(ts);
        CREATE INDEX IF NOT EXISTS idx_ledger_type   ON algedonic_ledger(type);
    """)
    db.commit()
    return db


def sync_rules_from_canonical(db: sqlite3.Connection) -> None:
    """Pull autopilot_rules from canonical state.db on n02 host via SSH sqlite3."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=accept-new",
             f"root@{STATE_DB_HOST}",
             f"sqlite3 {STATE_DB_PATH} 'SELECT id,name,description,condition_type,"
             f"condition_severity_max,condition_extra,auto_action,requires_ack_after,"
             f"active,created_at,created_by FROM autopilot_rules WHERE active=1;'"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            # R9: rc≠0 era un return silencioso (la deuda .1:22 pasaba invisible).
            print(f"[ledger] rule sync ssh rc={result.returncode}: "
                  f"{(result.stderr or '').strip()[:160]} (using cached rules)",
                  flush=True)
            return
        db.execute("DELETE FROM autopilot_rules")
        for line in result.stdout.strip().splitlines():
            parts = line.split("|")
            if len(parts) < 11:
                continue
            db.execute("""
                INSERT OR REPLACE INTO autopilot_rules
                    (id,name,description,condition_type,condition_severity_max,
                     condition_extra,auto_action,requires_ack_after,active,created_at,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, parts)
        db.commit()
        print(f"[ledger] autopilot_rules synced from canonical state.db", flush=True)
    except Exception as e:
        db.rollback()   # DELETE/INSERTs may have executed before the failure
        print(f"[ledger] rule sync failed: {e} (using cached rules)", flush=True)


# ── Autopilot dispatch ────────────────────────────────────────────────────────

def classify_event(subject: str, payload: dict) -> tuple[str, str, float]:
    """Returns (event_type, source, severity)."""
    # Explicit fields win, most specific first. `category` is what the host
    # reconciler (vsf-state-populate) emits; it was not consulted before, so
    # its signals had to be inferred from the subject.
    etype = payload.get("event_type") or payload.get("category") or ""
    if not etype:
        # Infer from subject
        parts = subject.split(".")
        etype = parts[-1] if parts else "unknown"

    # Normalize known types — match on `etype` ONLY.
    # This loop also tested `key in subject`, which was unconditionally true:
    # every subject on this channel is `vsf.<id>.algedonic.<category>` and
    # "algedonic" is itself a SEVERITY_MAP key, so the first pass flattened
    # EVERY unmapped category to a generic "algedonic". Categories that happened
    # to be in the map (semantic_divergence…) survived by luck; sha_divergence
    # and file_missing did not, which is why triage could not tell an
    # undeployed-component alert from any other algedonic signal. 2026-07-24.
    for key in SEVERITY_MAP:
        if key in etype:
            etype = key
            break

    source = (payload.get("system_id")
              or payload.get("source_id")     # emitted by vsf-state-populate
              or payload.get("source")
              or (subject.split(".")[2] if len(subject.split(".")) > 2 else "unknown"))
    severity = payload.get("severity", SEVERITY_MAP.get(etype, 5.0))
    if isinstance(severity, str):
        try:
            severity = float(severity)
        except Exception:
            severity = 5.0
    return etype, source, float(severity)


def find_rule(db: sqlite3.Connection, etype: str, severity: float, payload: dict):
    """Find the first applicable autopilot rule. Returns row or None."""
    rows = db.execute(
        "SELECT * FROM autopilot_rules WHERE active=1 AND condition_type=? AND condition_severity_max>=? ORDER BY condition_severity_max ASC",
        (etype, severity)
    ).fetchall()
    for row in rows:
        extra = row["condition_extra"]
        if extra:
            try:
                conds = json.loads(extra)
                # Check stasis_cos_min if present
                if "stasis_cos_min" in conds:
                    sc = payload.get("metrics", {}).get("kernel", {}).get("stasis_cos", 0.0)
                    if sc < conds["stasis_cos_min"]:
                        continue
            except Exception:
                pass
        return row
    return None


def execute_autopilot(action: dict, entry_id: int) -> str:
    """Execute autopilot action. Returns description of what was done."""
    atype = action.get("type", "log_only")

    if atype == "log_only":
        return "log_only"

    if atype == "restart_service":
        lxc     = action.get("lxc", 101)
        service = action.get("service", "vsf-nucleus-operational")
        try:
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                 "root@10.10.20.1",
                 f"pct exec {lxc} -- systemctl restart {service}"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return f"restarted {service} on LXC {lxc}"
            else:
                return f"restart failed: {result.stderr[:200]}"
        except Exception as e:
            return f"restart exception: {e}"

    return f"unknown_action:{atype}"


# ── q17.phase_1 — fingerprint identity fields per category ──────────────────
# Per docs/rubric/q17.phase_0_report.vsm §0.4. EXCLUDE drift fields.
# cycle_summary is SKIPPED (q18 owns heartbeat type per spec).
# Event types not listed here (merkle_break, covenant_halt, etc.) insert always.
FINGERPRINT_IDENTITY_FIELDS = {
    "sha_divergence":           ["lxc", "component"],
    "semantic_divergence":      ["audit_target"],
    "emit_count_divergence":    ["audit_target"],
    "env_temp_divergence":      ["audit_target"],
    "env_load_divergence":      ["audit_target"],
    "lvm_data_percent_warning":  ["lv"],
    "lvm_data_percent_critical": ["lv"],
}

# Event types that always insert a fresh row (no fingerprint dedup).
ALWAYS_INSERT_EVENTS = {
    "merkle_break", "covenant_halt", "emit_silence", "emit_stale",
    "drift_alert", "s4_anomaly",
    "peripheral_down", "peripheral_recovered",  # q17.phase_3 migration
}

# ── q17.phase_2 — emitter → condition types for cycle_manifest auto-close ────
# When an emitter publishes a cycle_manifest, the ledger uses its condition_set
# to determine which previously-pending condition fingerprints have cleared.
# This mapping tells the ledger which condition types belong to each emitter.
# See docs/spec/condition_vs_event.spec.vsm §phase_2
EMITTER_CONDITION_TYPES = {
    "vsf-state-populate": ["sha_divergence"],
    "vsf-storage-probe":  ["lvm_data_percent_warning", "lvm_data_percent_critical"],
    "unknown": [],  # future emitters add here
}


def handle_cycle_manifest(db: sqlite3.Connection, payload: dict, source: str) -> None:
    """Process a cycle_manifest: auto-close conditions absent from the manifest.

    Per docs/spec/condition_vs_event.spec.vsm §phase_2 correct_design:
      close(fingerprint) REQUIRES ALL of:
        (i)   manifest ts newer than the row's ts,
        (ii)  fingerprint absent from that manifest's condition_set,
        (iii) manifest evaluated_count > 0.
    """
    emitter = payload.get("emitter", source)
    evaluated_count = payload.get("evaluated_count", 0)
    manifest_ts = payload.get("ts", now_iso())

    if evaluated_count == 0:
        print(
            f"[ledger] manifest from {emitter}: evaluated_count=0 — "
            f"empty sweep proves nothing, skipping auto-close",
            flush=True
        )
        return

    # Which condition types does this emitter produce?
    condition_types = EMITTER_CONDITION_TYPES.get(
        emitter,
        EMITTER_CONDITION_TYPES.get("unknown", [])
    )
    if not condition_types:
        print(
            f"[ledger] manifest from {emitter}: no known condition types, "
            f"skipping auto-close",
            flush=True
        )
        return

    closed_set = set(payload.get("condition_set", []))
    if not closed_set:
        print(
            f"[ledger] manifest from {emitter}: empty condition_set "
            f"(evaluated_count={evaluated_count}) — all conditions cleared",
            flush=True
        )

    placeholders = ",".join("?" * len(condition_types))
    rows = db.execute(
        f"SELECT id, type, fingerprint, ts, dup_count FROM algedonic_ledger "
        f"WHERE status='pending_human' AND fingerprint IS NOT NULL "
        f"AND type IN ({placeholders})",
        list(condition_types)
    ).fetchall()

    closed_count = 0
    for row in rows:
        if row["ts"] >= manifest_ts:
            # Row is newer than the manifest — not eligible (may have been
            # emitted by a concurrent cycle after the manifest was generated)
            continue
        if row["fingerprint"] in closed_set:
            # Still diverging according to the manifest — keep pending
            continue

        # All three conditions satisfied: auto-close
        evidence = json.dumps({
            "manifest_ts": manifest_ts,
            "evaluated_count": evaluated_count,
            "probe": emitter,
            "observed": "absent from live sweep",
            "auto_closed_at": now_iso(),
        })
        db.execute(
            "UPDATE algedonic_ledger SET status='auto_resolved', "
            "evidence_json=? WHERE id=?",
            (evidence, row["id"])
        )
        db.commit()
        closed_count += 1
        print(
            f"[ledger] AUTO-RESOLVED id={row['id']} type={row['type']} "
            f"fp={row['fingerprint'][:16]} dup={row['dup_count']} "
            f"— cleared per manifest from {emitter}",
            flush=True
        )

    print(
        f"[ledger] manifest processed: emitter={emitter} "
        f"evaluated={evaluated_count} closed={closed_count} "
        f"still_open={len(rows) - closed_count}",
        flush=True
    )


def compute_fingerprint(etype: str, payload: dict) -> str | None:
    """Compute a deterministic fingerprint from identity_fields per category.

    Returns None for event types that always insert fresh rows (no dedup).
    The fingerprint is a SHA256 of 'category|identity1|identity2|...'
    where identityN are extracted from the payload using per-category identity_fields.
    """
    if etype in ALWAYS_INSERT_EVENTS or etype == "cycle_summary":
        return None
    fields = FINGERPRINT_IDENTITY_FIELDS.get(etype)
    if not fields:
        # Unknown type — no dedup
        return None
    parts = [etype]
    for f in fields:
        val = payload.get(f, "")
        parts.append(str(val))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def dispatch(db: sqlite3.Connection, subject: str, payload: dict) -> None:
    """Core dispatch: classify → compute fingerprint → write/upsert ledger → apply autopilot.

    q17.phase_1 (2026-07-26): condition-class events are fingerprinted by
    per-category identity_fields. When a fingerprint already exists with status
    'pending_human', increment dup_count instead of inserting a new row.
    Cycle_summary is skipped (q18 owns heartbeat dedup).
    Always-insert events (merkle_break, covenant_halt, etc.) bypass dedup.

    q17.phase_2 (2026-07-26): cycle_manifest events intercepted before normal
    path — used to auto-close conditions absent from the manifest's condition_set.
    """
    etype, source, severity = classify_event(subject, payload)
    ts = payload.get("ts", now_iso())

    # q17.phase_2: cycle_manifest is consumed, not stored as a ledger row
    if etype == "cycle_manifest":
        handle_cycle_manifest(db, payload, source)
        return

    # ── Fingerprint computation ──────────────────────────────────────────────
    fp = compute_fingerprint(etype, payload)
    entry_id = None

    if fp is not None:
        # Check if a pending row with this fingerprint already exists
        existing = db.execute(
            "SELECT id, dup_count FROM algedonic_ledger "
            "WHERE fingerprint=? AND status='pending_human' "
            "ORDER BY id ASC LIMIT 1",
            (fp,)
        ).fetchone()
        if existing is not None:
            # Condition re-emitted — increment dup_count, don't insert new row
            entry_id = existing["id"]
            db.execute(
                "UPDATE algedonic_ledger SET dup_count=dup_count+1, "
                "ts=?, payload=? WHERE id=?",
                (ts, json.dumps(payload), entry_id)
            )
            db.commit()
            print(
                f"[ledger] UPDATED id={entry_id} type={etype} "
                f"dup_count={existing['dup_count'] + 1} — condition re-emitted",
                flush=True
            )
            # Still try autopilot (rule may apply to re-emission)
            rule = find_rule(db, etype, severity, payload)
            if rule:
                try:
                    action = json.loads(rule["auto_action"])
                    result_desc = execute_autopilot(action, entry_id)
                    db.execute(
                        "UPDATE algedonic_ledger SET status='auto_handled', "
                        "action_auto=?, autopilot_rule=? WHERE id=?",
                        (result_desc, rule["id"], entry_id)
                    )
                    db.commit()
                    print(
                        f"[ledger] UPDATED+AUTO id={entry_id} type={etype} sev={severity:.1f} "
                        f"rule='{rule['name']}' action={result_desc}",
                        flush=True
                    )
                except Exception as e:
                    db.rollback()   # UPDATE may have executed before commit failed
                    print(f"[ledger] autopilot error for id={entry_id}: {e}", flush=True)
            return

    # ── Insert new row ───────────────────────────────────────────────────────
    payload_json = json.dumps(payload)
    cur = db.execute(
        "INSERT INTO algedonic_ledger "
        "(ts,source,type,severity,payload,status,fingerprint,dup_count,first_ts) "
        "VALUES (?,?,?,?,?,'pending_human',?,1,?)",
        (ts, source, etype, severity, payload_json, fp, ts)
    )
    entry_id = cur.lastrowid
    db.commit()

    # Try autopilot
    rule = find_rule(db, etype, severity, payload)
    if rule:
        action = json.loads(rule["auto_action"])
        result_desc = execute_autopilot(action, entry_id)
        new_status = "auto_handled"
        db.execute(
            "UPDATE algedonic_ledger SET status=?, action_auto=?, autopilot_rule=? WHERE id=?",
            (new_status, result_desc, rule["id"], entry_id)
        )
        db.commit()
        print(
            f"[ledger] AUTO id={entry_id} type={etype} sev={severity:.1f} "
            f"rule='{rule['name']}' action={result_desc}",
            flush=True
        )
        # If requires_ack_after, keep a pending_ack marker in ack_note
        if rule["requires_ack_after"]:
            db.execute(
                "UPDATE algedonic_ledger SET ack_note='[autopilot: ack retroactivo pendiente]' WHERE id=?",
                (entry_id,)
            )
            db.commit()
    else:
        print(
            f"[ledger] PENDING id={entry_id} type={etype} sev={severity:.1f} "
            f"source={source} — no autopilot rule, waiting human",
            flush=True
        )


# ── NATS plumbing ─────────────────────────────────────────────────────────────

def nats_parse_msg(data: bytes, offset: int):
    crlf = data.find(b"\r\n", offset)
    if crlf < 0:
        return None, None, None, offset
    header = data[offset:crlf].decode(errors="replace")
    parts  = header.split()
    if not header.startswith("MSG") or len(parts) < 4:
        return None, None, None, crlf + 2
    subj       = parts[1]
    try:
        size   = int(parts[-1])
    except Exception:
        return None, None, None, crlf + 2
    body_start = crlf + 2
    body_end   = body_start + size
    if len(data) < body_end + 2:
        return None, None, None, offset   # incomplete
    return subj, data[body_start:body_end], header, body_end + 2


def run_once(db: sqlite3.Connection) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(15)
    s.connect((NATS_HOST, NATS_PORT))
    s.recv(4096)   # INFO
    with open('/etc/vsf/nats.token') as _f:
        _token = _f.read().strip()
    s.sendall(b'CONNECT {"verbose":false,"auth_token":"' + _token.encode() + b'","name":"vsf-s5-ledger"}\r\n')
    for subj, sid in SUBJECTS:
        s.sendall(f"SUB {subj} {sid}\r\n".encode())
    s.settimeout(120)
    print(f"[ledger] connected {NATS_HOST}:{NATS_PORT} — subscribed {len(SUBJECTS)} subjects", flush=True)

    # Sync rules from canonical at connect
    sync_rules_from_canonical(db)
    last_rule_sync = time.time()
    last_ping      = time.time()
    buf = b""

    while True:
        try:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("NATS closed")
            buf += chunk
        except socket.timeout:
            if time.time() - last_ping > 30:
                s.sendall(b"PING\r\n")
                last_ping = time.time()
            # Re-sync rules every 5 minutes
            if time.time() - last_rule_sync > 300:
                sync_rules_from_canonical(db)
                last_rule_sync = time.time()
            continue

        i = 0
        while i < len(buf):
            if buf[i:i+4] == b"PING":
                end = buf.find(b"\r\n", i)
                if end < 0:
                    break
                s.sendall(b"PONG\r\n")
                last_ping = time.time()
                i = end + 2
                continue
            if buf[i:i+4] in (b"PONG", b"+OK\r"):
                end = buf.find(b"\r\n", i)
                if end < 0:
                    break
                i = end + 2
                continue
            if buf[i:i+3] == b"MSG":
                subj, body, _, next_i = nats_parse_msg(buf, i)
                if subj is None:
                    break
                try:
                    payload = json.loads(body.decode()) if body else {}
                except Exception:
                    payload = {"raw": body.decode(errors="replace")[:500]}
                dispatch(db, subj, payload)
                i = next_i
                continue
            end = buf.find(b"\r\n", i)
            if end < 0:
                break
            i = end + 2
        buf = buf[i:]


def main():
    print(f"[ledger] ITEM_16 S5 algedonic ledger starting ({NATS_HOST}:{NATS_PORT})", flush=True)
    db = open_ledger()
    while True:
        try:
            run_once(db)
        except Exception as e:
            # ROLLBACK CRITICAL: a failed commit (busy vs agent) leaves a hot
            # journal + open txn that blocks every reader until process restart
            # (2026-10-08 incident: 16.5h of locked pain channel).
            db.rollback()
            print(f"[ledger] error: {e} — reconnect in {RECONNECT_DELAY_S}s", flush=True)
            time.sleep(RECONNECT_DELAY_S)


if __name__ == "__main__":
    main()
