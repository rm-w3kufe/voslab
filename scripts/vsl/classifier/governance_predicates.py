#!/usr/bin/env python3
"""
governance_predicates.py — VSF custom predicates for S5 Governance.

Predicates for s5_governance.tree.vsm decision tree.
Classifies algedonic events for governance decisions.
"""
from __future__ import annotations

import json


def is_cert_test(ctx: dict) -> bool:
    """Check if event is certification/test artifact."""
    row = ctx.get("row", {})
    source = (row.get("source") or "").lower()
    payload = ctx.get("payload", {})
    reason = (payload.get("reason") or "").lower()
    return "cert" in source or "test" in source or "cert" in reason or "item16" in reason


def is_cycle_summary(ctx: dict) -> bool:
    """Check if event is S3* cycle summary (informational)."""
    row = ctx.get("row", {})
    return row.get("type") == "cycle_summary" and float(row.get("severity", 0)) == 0.0


def is_drift_alert(ctx: dict) -> bool:
    """Check if event is drift_alert."""
    row = ctx.get("row", {})
    return row.get("type") == "drift_alert"


def is_merkle_break(ctx: dict) -> bool:
    """Check if event is merkle_break."""
    row = ctx.get("row", {})
    return row.get("type") == "merkle_break"


def has_evidence(ctx: dict) -> bool:
    """Check if merkle_break has sufficient evidence (E1+E2+E3)."""
    row = ctx.get("row", {})
    payload = ctx.get("payload", {})
    
    # E1: writer is a declared component
    writer = payload.get("writer", "")
    declared_components = {"vsf-nucleus", "vsf-motor2", "vsf-s5-algedonic", "vsf-s3-phidown-actuator"}
    e1 = writer in declared_components
    
    # E2: real restart occurred within RESTART_WINDOW_S
    restart_ts = payload.get("restart_ts")
    finding_ts = row.get("ts")
    e2 = restart_ts is not None and finding_ts is not None
    
    # E3: seam signature (prev_hash=null, early event index)
    prev_hash = payload.get("prev_hash")
    event_idx = payload.get("event_idx", 999)
    e3 = prev_hash is None and event_idx < 10
    
    return e1 and e2 and e3


def is_covenant_halt_test(ctx: dict) -> bool:
    """Check if event is covenant_halt test/inject."""
    row = ctx.get("row", {})
    payload = ctx.get("payload", {})
    source = (row.get("source") or "").lower()
    reason = (payload.get("reason") or "").lower()
    return row.get("type") == "covenant_halt" and ("test" in source or "inject" in source or "test" in reason)


# Registry for socratic engine
GOVERNANCE_PREDICATES = {
    "is_cert_test": is_cert_test,
    "is_cycle_summary": is_cycle_summary,
    "is_drift_alert": is_drift_alert,
    "is_merkle_break": is_merkle_break,
    "has_evidence": has_evidence,
    "is_covenant_halt_test": is_covenant_halt_test,
}
