"""Intra-artifact consistency layer (proposal layer 2a)."""
from .consistency import (
    ContradictionBlocked,
    blocked_ids,
    ensure_certifiable,
    internal_check,
)

__all__ = ["ContradictionBlocked", "blocked_ids", "ensure_certifiable",
           "internal_check"]
