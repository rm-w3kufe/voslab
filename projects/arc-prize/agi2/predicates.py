#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_vsm_harness.vsm
"""predicates.py — socratic-engine lite for the ViArc-2 kernel.

Port of the deterministic predicate core of packages/public/socratic-engine:
evaluates candidate SCORING as declarative trees (data) instead of
hardcoded weight expressions. stdlib-only, R10-deterministic.

Tree grammar:
    leaf            -> predicate name (see PREDICATES)
    {"and": [..]}   -> all true
    {"or":  [..]}   -> any true
    {"not": tree}   -> negation
    {"leaf": name}  -> explicit leaf
    {"w": tree, "weight": x}  -> weighted contribution (float score)

SCORING_TREE converts a candidate context into the score previously
hardcoded in agent.py (0.5*loo + 0.3*agreement + 0.2*prior) — now the
weights live here as data S5 can amend without touching agent code.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

# ── Deterministic leaf predicates (ctx: dict of candidate facts) ────────

def _loo_ge_half(ctx: Dict[str, Any]) -> bool:
    return float(ctx.get("loo_frac", 0.0) or 0.0) >= 0.5


def _loo_positive(ctx: Dict[str, Any]) -> bool:
    return float(ctx.get("loo_frac", 0.0) or 0.0) > 0.0


def _agreement_strong(ctx: Dict[str, Any]) -> bool:
    return float(ctx.get("agreement", 0.0) or 0.0) >= 0.3


def _prior_known(ctx: Dict[str, Any]) -> bool:
    return float(ctx.get("prior", 0.0) or 0.0) >= 0.03


def _is_rsi_tool(ctx: Dict[str, Any]) -> bool:
    return str(ctx.get("dynamic", "")).startswith("rsi:")


PREDICATES: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    "loo_ge_half": _loo_ge_half,
    "loo_positive": _loo_positive,
    "agreement_strong": _agreement_strong,
    "prior_known": _prior_known,
    "is_rsi_tool": _is_rsi_tool,
}


def evaluate(tree: Any, ctx: Dict[str, Any]) -> bool:
    """Evaluate a boolean tree against ctx. Unknown leaf -> False."""
    if isinstance(tree, str):
        fn = PREDICATES.get(tree)
        return bool(fn(ctx)) if fn else False
    if isinstance(tree, dict):
        if "and" in tree:
            return all(evaluate(t, ctx) for t in tree["and"])
        if "or" in tree:
            return any(evaluate(t, ctx) for t in tree["or"])
        if "not" in tree:
            return not evaluate(tree["not"], ctx)
        if "leaf" in tree:
            return evaluate(tree["leaf"], ctx)
    return False


def weight(tree: Any) -> float:
    return float(tree.get("weight", 0.0)) if isinstance(tree, dict) \
        and "weight" in tree else 0.0


# ── Scoring terms (amendable by S5; replaces hardcoded W_* in agent) ───
# Linear weighted sum — exact parity with the proven M1 formula
# (0.5*loo + 0.3*agreement + 0.2*prior). Boolean trees above are for
# DECISIONS (certify eligibility, tool gates), not the continuous score.

SCORING_TERMS = [
    {"weight": 0.5, "field": "loo_frac",
     "note": "verify fraction — the certify-first core (was W_VERIFIES)"},
    {"weight": 0.3, "field": "agreement",
     "note": "producer consensus share (was W_AGREE)"},
    {"weight": 0.2, "field": "prior",
     "note": "empirical per-dynamic p@1 prior (was W_PRIOR)"},
]

# Declarative decision trees (I1 for candidates; I1 for RSI tools)
CERTIFY_TREE = {"leaf": "loo_ge_half"}
TOOL_CERTIFY_TREE = {"and": [{"leaf": "loo_ge_half"}]}


def score(ctx: Dict[str, Any]) -> float:
    """Weighted candidate score from SCORING_TERMS (deterministic, linear).

    ctx must carry: loo_frac, agreement, prior (all float-normalized).
    """
    return round(sum(t["weight"] * float(ctx.get(t["field"], 0.0) or 0.0)
                     for t in SCORING_TERMS), 4)


def certified(ctx: Dict[str, Any]) -> bool:
    """I1 decision: candidate may lead iff LOO >= threshold."""
    return evaluate(CERTIFY_TREE, ctx)


if __name__ == "__main__":  # pragma: no cover
    demo = {"loo_frac": 1.0, "agreement": 0.6, "prior": 0.1, "dynamic": "tiling"}
    print("demo score:", score(demo), "| verify-tree:",
          evaluate({"leaf": "loo_ge_half"}, demo))
