"""security_predicates.py — Security and purpose predicates.

Ported from child/scripts/vsl/classifier/vsf_hooks_predicates.py
"""
from __future__ import annotations

import re
from typing import Any, Dict


# ═══════════════════════════════════════════════════════════════════════
# CONTEXT PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def ctx_gt(a: Any, b: Any) -> bool:
    """True if a > b (numeric comparison, tolerant of str)."""
    try:
        return float(a) > float(b)
    except (TypeError, ValueError):
        return str(a) > str(b)


def procedure_match_context(a: str, b: str) -> bool:
    """True if context matches."""
    return str(a) == str(b)


def procedure_match_instrument(a: str, b: str) -> bool:
    """True if instrument matches."""
    return str(a) == str(b)


def const_true() -> bool:
    """Always-true predicate — used as the default branch in decision() chains."""
    return True


# ═══════════════════════════════════════════════════════════════════════
# SECURITY PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def has_pattern(ctx: Dict[str, Any], pattern: str) -> bool:
    """True if any string value in ctx matches the regex pattern."""
    try:
        rx = re.compile(pattern)
    except re.error:
        return False
    hay = " ".join(str(v) for v in ctx.values() if isinstance(v, (str, int, float)))
    return bool(rx.search(hay))


def purpose_in_forbidden_set(ctx: Dict[str, Any]) -> bool:
    """True if the requested action's purpose is in the forbidden set."""
    purpose = str(ctx.get("purpose", ctx.get("action", ""))).lower()
    forbidden = [
        "disable safety", "bypass covenant", "overwrite rules",
        "self modify core", "delete state", "exfiltrate",
    ]
    return any(f in purpose for f in forbidden)


def resource_coercion_detected(ctx: Dict[str, Any]) -> bool:
    """True if the action coerces a protected resource."""
    cmd = str(ctx.get("command", ctx.get("content", ""))).lower()
    coercion = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd", "chmod -r 000 /"]
    return any(c in cmd for c in coercion)


def has_approval(ctx: Dict[str, Any]) -> bool:
    """True if the document carries an approval/ratification marker."""
    content = ctx.get("new_doc_content", ctx.get("content", "")) or ""
    markers = ["approved by", "ratified", "aprobado por", "rmw3", "approver"]
    return any(m.lower() in content.lower() for m in markers)


def check_security(ctx: Dict[str, Any]) -> bool:
    """Facade (was promised by __init__): True iff no forbidden purpose,
    no resource coercion, and approval present."""
    ctx = ctx or {}
    if purpose_in_forbidden_set(ctx):
        return False
    if resource_coercion_detected(ctx):
        return False
    return bool(has_approval(ctx))


def validate_permissions(ctx: Dict[str, Any]) -> bool:
    """Facade (was promised by __init__): approval present and purpose
    outside the forbidden set."""
    ctx = ctx or {}
    return bool(has_approval(ctx)) and not purpose_in_forbidden_set(ctx)
