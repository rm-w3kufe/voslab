#!/usr/bin/env python3
"""vsf_autoimmune — S5 algedonic immune test harness.

Injects synthetic merkle_break events into the triage ledger to verify the agent
responds correctly. NEVER injects into events.jsonl (Ax_ChainVirginity).

Covenant: covenant_ops.vsm v0.2 §sanctioned_exercises (S5-ratified 2026-07-02).
Five axioms binding this design:
  - Ax_BlindToOrganNotHuman: blind to the organ, never to the record.
  - Ax_ChainVirginity: never inject into the Merkle chain (events.jsonl).
  - Ax_TruthfulClosure: always close injected rows with ack_note identifying them.
  - Ax_BoundedCadence: weekly timer + after each triage deploy; ≤ ~10/month.
  - Ax_HonestMarker: the nonce/marker field must not be learnable by classifiers.

Usage:
  python3 vsf_autoimmune.py          # run full test cycle
  python3 vsf_autoimmune.py --check  # check-only: inspect ledger for synthetic rows

Output: appended to /root/algedonic/exercise_register.jsonl
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
LEDGER_DB = "/root/algedonic/ledger.db"
REGISTER_FILE = "/root/algedonic/exercise_register.jsonl"
SERVICES_MIRROR = "/root/algedonic/services_mirror.json"
AGENT_POLL_S = 60       # vsf-s5-agent poll interval
WAIT_CYCLES = 2          # wait 2× poll for agent to process
WAIT_S = AGENT_POLL_S * WAIT_CYCLES + 10  # +10s grace

# The nonce marker field — a name real merkle_break payloads never carry.
# Blindness audit (quarterly): grep vsf_s5_agent.py for '_x' — classifiers must
# never reference it. Rotate yearly.
MARKER_FIELD = "_x"


# ── Helpers ────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def open_ledger() -> sqlite3.Connection:
    db = sqlite3.connect(LEDGER_DB, check_same_thread=False, timeout=10)
    db.row_factory = sqlite3.Row
    return db


# ── Pre-registration (Ax_BlindToOrganNotHuman) ─────────────────────────────────

def preregister(nonce: str, direction: str, payload: dict) -> dict:
    """Append to exercise_register.jsonl BEFORE injection.
    Returns the register entry for cross-reference.
    """
    payload_sha = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    entry = {
        "nonce": nonce,
        "ts": now_iso(),
        "direction": direction,  # 'must_escalate' | 'must_dismiss'
        "payload_sha256": payload_sha,
    }
    register_path = Path(REGISTER_FILE)
    register_path.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTER_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()
        os.fsync(f.fileno())
    print(f"[autoimmune] registered {nonce} direction={direction}")
    return entry


# ── Injection ──────────────────────────────────────────────────────────────────

def make_must_escalate_payload(nonce: str) -> dict:
    """Create a realistic must_escalate merkle_break payload.
    Appearance: high-index content tamper, sev 10.0, source s3_star.
    Real enough that a classifier cannot distinguish from genuine findings.
    """
    # Use a realistic high event index (NOT < 5) so the early-chain classifier
    # cannot dismiss it.
    event_idx = 4821
    fake_stored = hashlib.sha256(f"stored_{nonce}".encode()).hexdigest()
    fake_recomp = hashlib.sha256(f"recomp_{nonce}".encode()).hexdigest()
    return {
        "ts": now_iso(),
        "audit_target": "chain_integrity",
        "category": "content_tamper",
        "severity": 10.0,
        "finding_class": "content_tamper",
        "detail": (
            f"event #{event_idx}: content tamper: stored hash {fake_stored[:16]}.. "
            f"\u2260 recomputed {fake_recomp[:16]}.. (chain_format_version=Some(2))"
        ),
        "source_event_hash": fake_stored[:40],
        "sample_method": "diverse_verifier",
        "predicate_matched": "hash_recomputation",
        # Nonce buried here — classifiers must not learn to key on this field
        MARKER_FIELD: nonce,
    }


def make_must_dismiss_payload(nonce: str, active_since_ts: str = None) -> dict | None:
    """Create a dismissible merkle_break payload — seam event (#1) after a real restart.
    Uses a finding timestamp close to the nucleus restart so E2 (restart window) passes.
    """
    # Read nucleus active_since from services_mirror to set finding close to restart
    restart_ts = None
    if active_since_ts:
        restart_ts = active_since_ts
    else:
        try:
            import json
            m = json.load(open(SERVICES_MIRROR))
            nuc = m.get("vsf-nucleus-operational") or {}
            restart_ts = nuc.get("active_since")
        except Exception:
            pass
    if not restart_ts:
        print("[autoimmune] no restart_ts found — must_dismiss injected with now_iso()")
        finding_ts = now_iso()
    else:
        # Set finding 3s after restart — well within RESTART_WINDOW_S (300s)
        try:
            from datetime import timedelta
            # Parse systemd-like format "Thu 2026-07-02 06:08:30 UTC"
            rest = restart_ts
            if rest[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
                rest = rest[4:].strip()
            restart_dt = datetime.strptime(rest, "%Y-%m-%d %H:%M:%S %Z")
            finding_dt = restart_dt + timedelta(seconds=3)
            finding_ts = finding_dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
        except Exception:
            print(f"[autoimmune] fallback to now_iso() — restart_ts={restart_ts}")
            finding_ts = now_iso()
    fake_stored = hashlib.sha256(f"dismiss_stored_{nonce}".encode()).hexdigest()
    return {
        "ts": finding_ts,
        "audit_target": "chain_integrity",
        "category": "restart_seam",
        "severity": 9.0,
        "finding_class": "restart_seam",
        "detail": (
            f"event #1: restart seam — prev_hash=null (chain segment start after restart) "
            f"stored hash {fake_stored[:16]}.."
        ),
        "source_event_hash": fake_stored[:40],
        "sample_method": "chain_verify",
        "predicate_matched": "restart_seam",
        MARKER_FIELD: nonce,
    }


def inject_row(db: sqlite3.Connection, payload: dict) -> int:
    """Direct INSERT into algedonic_ledger — NEVER into events.jsonl.
    Returns the row id.
    """
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO algedonic_ledger (ts, source, type, severity, payload, status) "
        "VALUES (?, ?, ?, ?, ?, 'pending_human')",
        (ts, "s3_star", "merkle_break", payload.get("severity", 10.0),
         json.dumps(payload))
    )
    db.commit()
    row_id = cur.lastrowid
    print(f"[autoimmune] injected row #{row_id} ({payload.get('detail','')[:80]}...)")
    return row_id


# ── Evaluation (Ax_TruthfulClosure) ────────────────────────────────────────────

def evaluate(nonce: str, row_id: int, direction: str, db: sqlite3.Connection) -> dict:
    """Wait for agent cycle, then check disposition. Returns outcome dict."""
    print(f"[autoimmune] waiting {WAIT_S}s for agent to process row #{row_id}...")
    time.sleep(WAIT_S)

    row = dict(db.execute("SELECT * FROM algedonic_ledger WHERE id=?", (row_id,)).fetchone())
    status = row["status"]
    agent_note = row.get("agent_note", "")

    if direction == "must_escalate":
        if status == "pending_human":
            outcome = "PASS"
            result_detail = f"correctly pending_human (not auto-handled)"
        elif status == "agent_handled":
            outcome = "FAIL"
            result_detail = f"AGENT AUTO-HANDLED must-escalate synthetic — agent_note={agent_note}"
            # Emit algedonic for the failure
            _emit_failure_alert(nonce, result_detail)
        else:
            outcome = "ERROR"
            result_detail = f"unexpected status={status}"
    elif direction == "must_dismiss":
        if status == "agent_handled":
            outcome = "PASS"
            result_detail = f"correctly agent_handled — note={agent_note}"
        elif status == "pending_human":
            outcome = "NOTE"
            result_detail = "alarm_inflation: agent escalated a dismissible synthetic"
            _emit_advisory(nonce, result_detail)
        else:
            outcome = "ERROR"
            result_detail = f"unexpected status={status}"
    else:
        outcome = "ERROR"
        result_detail = f"unknown direction={direction}"

    # ALWAYS close the row truthfully (Ax_TruthfulClosure)
    ack_ts = now_iso()
    db.execute(
        "UPDATE algedonic_ledger SET status='acked', ack_ts=?, agent_note=?, ack_note=? WHERE id=?",
        (ack_ts,
         agent_note,
         f"autoimmune exercise {nonce} — synthetic, see exercise_register; outcome={outcome}",
         row_id)
    )
    db.commit()

    result = {
        "nonce": nonce,
        "row_id": row_id,
        "direction": direction,
        "outcome": outcome,
        "result_detail": result_detail,
        "agent_note_seen": agent_note,
        "ack_ts": ack_ts,
    }
    return result


def _emit_failure_alert(nonce: str, detail: str):
    """Log to stderr — the autoimmune test runner reports failures loudly.
    In production (when this runs unattended), this feeds into the alert channel.
    """
    msg = f"[autoimmune-FAIL] {detail}"
    print(msg, file=sys.stderr)


def _emit_advisory(nonce: str, detail: str):
    """Log advisory for alarm_inflation (lesser failure)."""
    print(f"[autoimmune-ADVISORY] {detail}")


# ── Register append (result) ───────────────────────────────────────────────────

def append_result(result: dict):
    """Append result to exercise_register.jsonl"""
    entry = {
        "nonce": result["nonce"],
        "outcome": result["outcome"],
        "direction": result["direction"],
        "agent_note_seen": result.get("agent_note_seen", ""),
        "ts": now_iso(),
    }
    with open(REGISTER_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()
        os.fsync(f.fileno())
    print(f"[autoimmune] register append: nonce={result['nonce']} outcome={result['outcome']}")


# ── Check-only ─────────────────────────────────────────────────────────────────

def check_register():
    """Read exercise_register.jsonl and report."""
    path = Path(REGISTER_FILE)
    if not path.exists():
        print("[autoimmune] no exercise_register.jsonl — no exercises run yet")
        return
    with open(REGISTER_FILE) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    if not lines:
        print("[autoimmune] exercise_register.jsonl is empty")
        return
    print(f"[autoimmune] exercise_register: {len(lines)} entries")
    for entry in lines:
        print(f"  nonce={entry.get('nonce','?')[:12]} direction={entry.get('direction','?')} "
              f"outcome={entry.get('outcome','?')}")


# ── Chain virginity check ──────────────────────────────────────────────────────

def check_chain_virginity():
    """Grep events.jsonl for nonce markers — must return 0."""
    import subprocess
    # Check if events.jsonl is accessible (may be on LXC 101)
    result = subprocess.run(
        ["grep", "-c", MARKER_FIELD, "/var/lib/vsf/vsf_nucleus/events.jsonl"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        count = int(result.stdout.strip())
        if count > 0:
            print(f"[autoimmune] ⚠ CHAIN VIRGINITY BREACH: {count} synthetic events in events.jsonl!")
        else:
            print(f"[autoimmune] ✓ chain virginity holds (0 events with {MARKER_FIELD})")
    else:
        print(f"[autoimmune] ? chain check skipped (events.jsonl not accessible)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="VSF autoimmune test harness")
    ap.add_argument("--check", action="store_true", help="check-only: inspect register + chain")
    ap.add_argument("--must-escalate-only", action="store_true",
                    help="run only must_escalate case (for first run against old triage)")
    args = ap.parse_args()

    if args.check:
        check_register()
        check_chain_virginity()
        return

    print(f"[autoimmune] === immune test {now_iso()} ===")
    db = open_ledger()
    failures = []

    # ── Case 1: must_escalate ──────────────────────────────────────────────────
    nonce_e = str(uuid.uuid4())
    payload_e = make_must_escalate_payload(nonce_e)
    preregister(nonce_e, "must_escalate", payload_e)
    row_id_e = inject_row(db, payload_e)
    result_e = evaluate(nonce_e, row_id_e, "must_escalate", db)
    append_result(result_e)
    if result_e["outcome"] == "FAIL":
        failures.append(f"must_escalate: {result_e['result_detail']}")

    # ── Case 2: must_dismiss (skip if --must-escalate-only) ────────────────────
    if not args.must_escalate_only:
        nonce_d = str(uuid.uuid4())
        payload_d = make_must_dismiss_payload(nonce_d)
        if payload_d is not None:
            preregister(nonce_d, "must_dismiss", payload_d)
            row_id_d = inject_row(db, payload_d)
            result_d = evaluate(nonce_d, row_id_d, "must_dismiss", db)
            append_result(result_d)
            if result_d["outcome"] == "FAIL":
                failures.append(f"must_dismiss: {result_d['result_detail']}")

    db.close()

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n[autoimmune] === summary {now_iso()} ===")
    check_register()
    check_chain_virginity()
    if failures:
        print(f"[autoimmune] ❌ {len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print(f"[autoimmune] ✓ all tests passed")


if __name__ == "__main__":
    main()
