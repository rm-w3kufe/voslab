#!/usr/bin/env python3
"""vsf-s5-agent — L2 algedonic reviewer (TRIAGE-EVIDENCE-RULE).

Runs on LXC 104 (s5-policy). Polls pending_human events every POLL_S seconds,
runs deterministic classifiers, and either:
  - Marks agent_handled (known pattern, within policy) + writes agent_note brief
  - Keeps pending_human + writes agent_note recommendation (genuine escalation)

R12 (Hard rule, state.db + RULES.md):
  Automated triage may close an algedonic signal only by attaching
  machine-checkable evidence (probe + observed value). Narrative-only
  dismissal is prohibited; classifiers that attempt it are auto-escalated.

Beer: the human sees only what no classifier could resolve. Everything else
arrives as a digest — "N handled, 0 escalations" = nothing to do.

Phase 1: deterministic classifiers (no LLM).
Phase 2: Qwen query for unrecognised patterns before escalation.
"""
import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

LEDGER_DB = "/root/algedonic/ledger.db"
POLL_S    = 60
SERVICES_MIRROR = "/root/algedonic/services_mirror.json"

# How many seconds back we consider for "recent restart correlation"
RESTART_WINDOW_S = 300  # 5 min — a restart within 5 min of the finding is "recent"


# ── Evidence (R12) ─────────────────────────────────────────────────────────────

@dataclass
class Evidence:
    question: str      # what was checked, human-readable
    probe: str         # the query/command actually executed
    observed: str      # the raw observed value(s), stringified
    supports: bool     # True if this observation supports the decision


@dataclass
class Decision:
    action: str                     # 'handle' | 'escalate'
    brief: str                      # one-line for digest / operator note
    evidence: list[Evidence] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def ts_to_epoch(ts: str) -> float:
    """Parse various timestamp formats to epoch float.
    
    Handles:
      - ISO 8601:  2026-07-02T06:08:30+00:00  (with or without Z)
      - systemd:   Thu 2026-07-02 06:08:30 UTC
    """
    ts = ts.strip()
    # Try ISO 8601 first
    ts_iso = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_iso).timestamp()
    except Exception:
        pass
    # Try systemd format: "Day Mon DD HH:MM:SS YYYY TZ" e.g. "Thu 2026-07-02 06:08:30 UTC"
    try:
        # Remove day prefix: "Thu " 
        rest = ts
        if rest[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            rest = rest[4:].strip()
        # rest is now "2026-07-02 06:08:30 UTC"
        # datetime.fromisoformat with space separator works in Python 3.11+
        rest_iso = rest.replace(" UTC", "+00:00").replace(" +0000", "+00:00")
        return datetime.fromisoformat(rest_iso).timestamp()
    except Exception:
        return 0.0


# ── Services mirror reader ─────────────────────────────────────────────────────

def read_services_mirror() -> dict:
    """Read the services_mirror.json pushed by vsf-state-populate.
    Returns {name: {"active_since": str, "lxc": int}}.
    Returns empty dict if file absent or unreadable.
    """
    try:
        with open(SERVICES_MIRROR) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ── Classifiers ──────────────────────────────────────────────────────────────
# Each is a function (row: dict, db: Connection) -> Optional[Decision]
# First match wins. Return None to try next classifier.

def _payload(row: dict) -> dict:
    try:
        return json.loads(row["payload"])
    except Exception:
        return {}


def _clf_cert_test(row: dict, db: sqlite3.Connection) -> Optional[Decision]:
    """Certification/test inject events (source or reason contains 'test'/'cert')."""
    source = (row["source"] or "").lower()
    reason = (_payload(row).get("reason") or "").lower()
    if "cert" in source or "test" in source or "cert" in reason or "item16" in reason:
        return Decision("handle", f"certification/test artifact from source='{row['source']}'")
    return None


def _clf_cycle_summary(row: dict, db: sqlite3.Connection) -> Optional[Decision]:
    """S3* cycle_summary — purely informational (sev=0)."""
    if row["type"] == "cycle_summary" and float(row["severity"]) == 0.0:
        p = _payload(row)
        findings = p.get("findings_emitted", "?")
        return Decision("handle", f"S3* audit cycle summary — findings_emitted={findings} (informational)")
    return None


def _clf_drift_alert(row: dict, db: sqlite3.Connection) -> Optional[Decision]:
    """drift_alert — already captured by autopilot; if it slipped through, handle."""
    if row["type"] == "drift_alert":
        sev = float(row["severity"])
        p   = _payload(row)
        cos = p.get("metrics", {}).get("kernel", {}).get("stasis_cos") or p.get("stasis_cos")
        cos_str = f"stasis_cos={cos:.4f}" if cos is not None else ""
        return Decision("handle", f"drift_alert sev={sev:.1f} {cos_str} — within monitoring range, no action")
    return None


def _clf_merkle_break_evidence(row: dict, db: sqlite3.Connection) -> Optional[Decision]:
    """merkle_break triage with evidence (R12). Replaces _clf_merkle_break_early.

    Three evidence checks required before handle:
      E1: writer is a declared component (not foreign)
      E2: real restart occurred within RESTART_WINDOW_S of the finding
      E3: seam signature (prev_hash=null, early event index)
    Only close if ALL three support the decision.
    """
    if row["type"] != "merkle_break":
        return None
    detail = _payload(row).get("detail", "")
    ev = []

    # E1: extract system_id / writer from payload detail
    #    "event #N: content tamper: stored hash ... ≠ recomputed ... (chain_format_version=Some(2))"
    #    or "event #N: restart seam — prev_hash=null ..."
    # The system_id is NOT in the payload directly; we check source.
    # If source is a declared writer (s3_star, diverse_verifier), it's not foreign.
    source = (row.get("source") or "").lower()
    declared_writers = {"s3_star", "diverse_verifier", "vsf_nucleus"}
    is_declared = source in declared_writers
    ev.append(Evidence(
        question="Is the offending writer a declared one?",
        probe=f"source='{source}' in {sorted(declared_writers)}",
        observed=f"source={source}, declared={is_declared}",
        supports=is_declared,
    ))

    # E2: real restart near the finding?
    #      Read services_mirror.json for vsf-nucleus-operational on LXC 101
    #      Use payload.ts (event timestamp) not row.ts (insertion timestamp)
    finding_ts = _payload(row).get("ts", row.get("ts", ""))
    finding_epoch = ts_to_epoch(finding_ts)
    restart_close = False
    restart_detail = "no mirror or finding ts unavailable"

    if finding_epoch > 0:
        mirror = read_services_mirror()
        nucleus_svc = mirror.get("vsf-nucleus-operational") or mirror.get("vsf_nucleus_operational", {})
        active_since_str = nucleus_svc.get("active_since", "")
        if active_since_str:
            active_since_epoch = ts_to_epoch(active_since_str)
            if active_since_epoch > 0:
                age = finding_epoch - active_since_epoch
                restart_close = 0 <= age <= RESTART_WINDOW_S
                restart_detail = f"finding_ts={finding_ts}, active_since={active_since_str}, age={age:.0f}s, within_window={restart_close}"
    ev.append(Evidence(
        question="Real restart within RESTART_WINDOW_S of the finding?",
        probe=f"services_mirror vsf-nucleus-operational active_since; finding.ts - active_since <= {RESTART_WINDOW_S}s",
        observed=restart_detail,
        supports=restart_close,
    ))

    # E3: seam signature?
    #      Check for prev_hash=null wording or early event index
    seam_detail = ""
    m = re.search(r"event #(\d+)", detail)
    event_idx = int(m.group(1)) if m else None
    is_early = event_idx is not None and event_idx < 5
    has_null_prev = "prev_hash=null" in detail.lower()
    is_seam = is_early or has_null_prev
    seam_detail = f"event_idx={event_idx}, prev_hash=null={has_null_prev}, is_seam={is_seam}"
    ev.append(Evidence(
        question="Seam signature? (prev_hash=null or early event index < 5)",
        probe=f"detail regex match for 'event #N' and 'prev_hash=null'",
        observed=seam_detail,
        supports=is_seam,
    ))

    # E4: deploy-window inhibition (phase inhibition)
    # If last_deploy_ts is available in the mirror and the finding is within
    # ±10min of a deploy, this is almost certainly a deploy seam.
    DEPLOY_WINDOW_S = 600
    deploy_close = False
    deploy_detail = "no deploy tracking in mirror"
    if finding_epoch > 0:
        mirror = read_services_mirror()
        # Check for deploy_tracking object or last_deploy_ts per component
        # (populate.sh needs to push deploy_tracking — placeholder for now)
        deploy_info = mirror.get("deploy_tracking", {})
        if isinstance(deploy_info, dict):
            for comp_name, comp_info in deploy_info.items():
                if isinstance(comp_info, dict):
                    ldt = comp_info.get("last_deploy_ts")
                    if ldt:
                        ldt_epoch = ts_to_epoch(ldt)
                        if ldt_epoch > 0:
                            delta = abs(finding_epoch - ldt_epoch)
                            if delta <= DEPLOY_WINDOW_S:
                                deploy_close = True
                                deploy_detail = f"deploy_window: {comp_name} deployed at {ldt}, delta={delta:.0f}s"
                                break
    ev.append(Evidence(
        question="Deploy window (±10min of a declared deploy)?",
        probe="services_mirror deploy_tracking last_deploy_ts per component",
        observed=deploy_detail,
        supports=deploy_close,
    ))

    # DECIDE: close only if ALL evidence items support
    all_support = all(e.supports for e in ev)
    if all_support:
        return Decision(
            "handle",
            f"merkle_break evidence-based close: declared writer={is_declared}, "
            f"restart_close={restart_close}, seam={is_seam} — "
            f"deploy/restart artifact within window",
            evidence=ev,
        )
    else:
        # Escalate with evidence attached
        fail_items = [f"{e.question[:40]}: supports={e.supports}" for e in ev if not e.supports]
        return Decision(
            "escalate",
            f"merkle_break evidence FAIL: {'; '.join(fail_items)} — "
            f"escalated with {len(ev)} evidence items attached",
            evidence=ev,
        )


def _clf_semantic_divergence_tolerance(row: dict, db: sqlite3.Connection) -> Optional[Decision]:
    """semantic_divergence with diff < 0.05 — floating-point tolerance between builds."""
    if row["type"] != "semantic_divergence":
        return None
    detail = _payload(row).get("detail", "")
    m = re.search(r"diff=([\d.]+)", detail)
    if m:
        diff = float(m.group(1))
        if diff < 0.05:
            claimed = re.search(r"claimed=([\d.]+)", detail)
            recomp  = re.search(r"recomputed stasis_cos=([\d.]+)", detail)
            claimed_v = float(claimed.group(1)) if claimed else "?"
            recomp_v  = float(recomp.group(1))  if recomp  else "?"
            return Decision(
                "handle",
                f"semantic_divergence diff={diff:.4f} < 0.05 tolerance — "
                f"float precision between builds (claimed={claimed_v}, recomp={recomp_v}); "
                f"monitor trend; consider adjusting ε if recurring"
            )
    return None


def _clf_covenant_halt_test(row: dict, db: sqlite3.Connection) -> Optional[Decision]:
    """covenant_halt from a test source — already resolved."""
    if row["type"] != "covenant_halt":
        return None
    source = (row["source"] or "").lower()
    reason = (_payload(row).get("reason") or "").lower()
    if "test" in source or "cert" in source or "inject" in reason:
        return Decision("handle", f"covenant_halt: test/inject from '{row['source']}' — resolved")
    return None


# Escalation advisories for unmatched events
ESCALATION_ADVISORY = {
    "covenant_halt":       "REAL halt signal — verify nucleus state, review S5 covenant conditions",
    "merkle_break":        "chain integrity breach at high event index — inspect events.jsonl",
    "semantic_divergence": "large stasis_cos divergence (diff ≥ 0.05) — possible state_vector corruption",
    "emit_silence":        "nucleus stopped emitting — check vsf-nucleus-operational on LXC 101",
    "invariant_breach":    "hard invariant violated — review nucleus metrics immediately",
    "signal_escalated":    "persistent signal escalated by S3 — check stasis trend",
}

# ALG-DEDUP-PROCEDURE: attached procedures (ECAM-style checklists)
# An alert that is escalated gets its procedure attached as agent_note.
PROCEDURES = {
    "merkle_break": [
        "1. payload.detail → offending event index + system_id; declared writer?",
        "2. restart within ±10min? (services_mirror.json active_since — see triage_evidence spec)",
        "3. run diverse verifier on the tail (scripts/audit/verify_chain_diverse.py report)",
        "4. all clean → tamper suspected: DO NOT ack; notify rmw3; freeze triage of this fp",
    ],
    "semantic_divergence": [
        "1. verify vsf-nucleus-operational is running (systemctl is-active)",
        "2. check build parity: running binary sha vs state.db sha vs manifest sha",
        "3. if diff < 0.05: float precision between builds — update ε threshold",
        "4. if diff ≥ 0.05: possible state_vector corruption — run full audit",
    ],
    "emit_silence": [
        "1. check vsf-nucleus-operational on LXC 101: is-active or dead?",
        "2. check NATS broker on LXC 106: is nats-server responding?",
        "3. check broker_in_msgs vs nucleus_event_count in latest payload",
        "4. if nucleus alive and broker alive: restart broker-probe on LXC 107",
    ],
    "covenant_halt": [
        "1. verify nucleus state: is vsf-nucleus-operational active on LXC 101?",
        "2. review S5 covenant conditions (covenant_state.json)",
        "3. if test/cert: mark as handled with note",
        "4. if real: DO NOT ACK — requires human decision to restore autonomy",
    ],
    "invariant_breach": [
        "1. identify which invariant was violated (VAR-1 / TRUST-1 / ALG-1)",
        "2. check nucleus metrics: stasis_cos, trust, D_eff trend",
        "3. if single event: monitor for recurrence in next 2 cycles",
        "4. if persistent: escalate — possible kernel bug or hardware issue",
    ],
    "emit_count_divergence": [
        "1. compare broker_in_msgs vs nucleus_event_count delta",
        "2. check for dropped NATS messages (nats-server -s)",
        "3. if gap growing: restart NATS-subscriber on LXC 101",
    ],
}


def procedure_text(event_type: str) -> str:
    """Return the ordered checklist for an event type, or empty string."""
    steps = PROCEDURES.get(event_type)
    if not steps:
        return ""
    return "\n" + "=" * 40 + "\nPROCEDURE:\n" + "\n".join(steps) + "\n" + "=" * 40

CLASSIFIERS = [
    _clf_cert_test,
    _clf_cycle_summary,
    _clf_drift_alert,
    _clf_merkle_break_evidence,   # ← replaces _clf_merkle_break_early (TRIAGE-EVIDENCE-RULE)
    _clf_semantic_divergence_tolerance,
    _clf_covenant_halt_test,
]


def classify(row: dict, db: sqlite3.Connection) -> Decision:
    for clf in CLASSIFIERS:
        result = clf(row, db)
        if result is not None:
            return result
    advisory = ESCALATION_ADVISORY.get(row["type"], "unknown pattern — manual review required")
    return Decision("escalate", advisory)


# ── Main review loop (EVIDENCE-RULE enforcement) ───────────────────────────────

def open_db() -> sqlite3.Connection:
    db = sqlite3.connect(LEDGER_DB, check_same_thread=False, timeout=10)
    db.row_factory = sqlite3.Row
    # Add columns if missing (idempotent migrations)
    for col in ["agent_note", "evidence_json"]:
        try:
            db.execute(f"ALTER TABLE algedonic_ledger ADD COLUMN {col} TEXT")
            db.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    return db


def review_pending(db: sqlite3.Connection) -> tuple[int, int]:
    """Review all pending_human events. Returns (handled, escalated) counts.

    R12 ENFORCEMENT: a 'handle' decision without evidence is auto-escalated.
    This catches any classifier that attempts narrative-only closure.
    """
    rows = db.execute(
        "SELECT * FROM algedonic_ledger WHERE status='pending_human' ORDER BY id ASC"
    ).fetchall()

    handled = escalated = 0
    for row in rows:
        row = dict(row)
        decision = classify(row, db)
        ts = now_iso()

        # R12: handle without evidence → auto-escalate
        if decision.action == "handle":
            if not decision.evidence or not all(e.observed for e in decision.evidence):
                # EVIDENCE-RULE triggered: override to escalate
                orig_brief = decision.brief
                decision = Decision(
                    "escalate",
                    f"EVIDENCE-RULE: classifier attempted narrative-only closure — "
                    f"auto-escalated. Original brief: {orig_brief}",
                )

        if decision.action == "handle":
            db.execute(
                "UPDATE algedonic_ledger SET status='agent_handled', ack_ts=?, agent_note=?, evidence_json=? WHERE id=?",
                (ts, decision.brief,
                 json.dumps([{"question": e.question, "probe": e.probe,
                               "observed": e.observed, "supports": e.supports}
                              for e in decision.evidence]) if decision.evidence else None,
                 row["id"])
            )
            handled += 1
        else:
            # ALG-DEDUP-PROCEDURE: attach checklist to agent_note
            brief_with_procedure = decision.brief + procedure_text(row["type"])
            db.execute(
                "UPDATE algedonic_ledger SET agent_note=?, evidence_json=? WHERE id=? AND agent_note IS NULL",
                (brief_with_procedure,
                 json.dumps([{"question": e.question, "probe": e.probe,
                               "observed": e.observed, "supports": e.supports}
                              for e in decision.evidence]) if decision.evidence else None,
                 row["id"])
            )
            escalated += 1
        db.commit()

    if rows:
        print(f"[agent] reviewed {len(rows)} pending → handled={handled} escalated={escalated}")
    return handled, escalated


def main() -> None:
    print(f"[agent] vsf-s5-agent starting (TRIAGE-EVIDENCE-RULE active) — poll every {POLL_S}s")
    db = open_db()
    while True:
        try:
            review_pending(db)
        except Exception as e:
            db.rollback()   # never leave an open txn (blocks ledger writers/readers)
            print(f"[agent] review error: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
