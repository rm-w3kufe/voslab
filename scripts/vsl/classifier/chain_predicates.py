#!/usr/bin/env python3
"""
chain_predicates.py — VSF custom predicates for Chain Integrity Classifier.

Predicates for chain_classify.tree.vsm decision tree.
Classifies integrity failures by the fork-event taxonomy (AC-M3).
"""
from __future__ import annotations

import hashlib
import json


def compute_event_hash(event: dict) -> str:
    """Compute SHA256 of event with hash field removed (canonical form)."""
    ev = {k: v for k, v in event.items() if k != "hash"}
    canonical = json.dumps(ev, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def is_content_tamper(ctx: dict) -> bool:
    """Check if stored hash ≠ recomputed hash."""
    ev = ctx.get("event", {})
    stored_hash = ctx.get("stored_hash")
    if not stored_hash:
        return False
    recomputed = compute_event_hash(ev)
    return stored_hash != recomputed


def is_diverge_origin(ctx: dict) -> bool:
    """Check if prev_hash doesn't match actual last hash."""
    prev_hash = ctx.get("prev_hash")
    actual_prev = ctx.get("actual_prev")
    
    # No prev_hash → chain segment start (not an error)
    if prev_hash is None or prev_hash == "":
        return False
    
    # First event in file has a prev_hash — can't verify
    if actual_prev is None:
        return True
    
    # Check if it's a clean reset (prev_hash = 0...0)
    if prev_hash == "0" * 64 or prev_hash == "":
        return False
    
    # Fork event: stored prev_hash doesn't match actual last hash
    return prev_hash != actual_prev


def is_resume_wrong(ctx: dict) -> bool:
    """Check if chain restart after reset where first event's prev_hash ≠ last event's hash."""
    prev_hash = ctx.get("prev_hash")
    actual_prev = ctx.get("actual_prev")
    is_chain_start = ctx.get("is_chain_start", False)
    
    # Only applies to chain restarts
    if not is_chain_start:
        return False
    
    # Check if prev_hash matches last event's hash
    if actual_prev is None:
        return False
    
    return prev_hash != actual_prev


def is_epoch_rollback(ctx: dict) -> bool:
    """Check if sequence number decreases."""
    seq = ctx.get("algedonic_seq")
    last_seq = ctx.get("last_algedonic_seq")
    
    if seq is None or last_seq is None:
        return False
    
    try:
        return int(seq) < int(last_seq)
    except (ValueError, TypeError):
        return False


def is_truncated_line(ctx: dict) -> bool:
    """Check if line ends without newline or is partial JSON."""
    return ctx.get("is_truncated", False)


# Registry for socratic engine
CHAIN_PREDICATES = {
    "is_content_tamper": is_content_tamper,
    "is_diverge_origin": is_diverge_origin,
    "is_resume_wrong": is_resume_wrong,
    "is_epoch_rollback": is_epoch_rollback,
    "is_truncated_line": is_truncated_line,
}
