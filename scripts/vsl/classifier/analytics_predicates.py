#!/usr/bin/env python3
"""
analytics_predicates.py — VSF custom predicates for Analytics Pattern Classification.

Predicates for pattern_classify.tree.vsm decision tree.
Classifies patterns by severity and type for IR generation.
"""
from __future__ import annotations


def is_high_error_rate(ctx: dict) -> bool:
    """Check if pattern is high error rate."""
    pattern = ctx.get("pattern", {})
    return pattern.get("type") == "high_error_rate"


def is_consecutive_failures(ctx: dict) -> bool:
    """Check if pattern is consecutive failures."""
    pattern = ctx.get("pattern", {})
    return pattern.get("type") == "consecutive_failures"


def is_inactive_instrument(ctx: dict) -> bool:
    """Check if pattern is inactive instrument."""
    pattern = ctx.get("pattern", {})
    return pattern.get("type") == "inactive_instrument"


def is_temporal_correlation(ctx: dict) -> bool:
    """Check if pattern is temporal correlation."""
    pattern = ctx.get("pattern", {})
    return pattern.get("type") == "temporal_correlation"


# Registry for socratic engine
ANALYTICS_PREDICATES = {
    "is_high_error_rate": is_high_error_rate,
    "is_consecutive_failures": is_consecutive_failures,
    "is_inactive_instrument": is_inactive_instrument,
    "is_temporal_correlation": is_temporal_correlation,
}
