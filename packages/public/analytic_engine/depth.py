"""depth_estimator — estimate required analysis levels + tools for a document.

Deterministic-first (R10): pure regex feature counting + fixed thresholds.
No randomness, no time-dependence, no LLM. The estimate says WHICH levels
(L1-L5, analytic_engine/levels.py) a given artifact requires and WHAT tools
each level needs — so the pipeline runs the depth the document demands
instead of a hand-picked level.

Levels (canon: analytic_engine/levels.py):
  L1 claim extraction + routing      -> claim_ingest
  L2 theorem parsing                 -> l2_parser
  L3 symbolic verification           -> sympy (+ z3 when inequalities present)
  L4 theory-experiment correlation   -> results_join (paper_data/results.vsm)
  L5 cross-source reasoning          -> ledger_correlate

Usage:
    from analytic_engine.depth import estimate
    est = estimate(text, related_sources=3)
    est["levels"], est["tools"], est["evidence"], est["verdict"]
"""

from __future__ import annotations

import re
from typing import Any

# ── feature patterns (deterministic) ──────────────────────────────────────────

_PATTERNS: dict[str, str] = {
    "theorem_envs": r"\\begin\{(theorem|lemma|corollary|proposition|definition|remark)\}",
    "equation_envs": r"\\begin\{equation\}|\\label\{eq:",
    "math_symbols": (
        r"\\frac|\\int|\\le\b|\\ge\b|\\forall|\\exists|\\cdot|\\Omega|"
        r"\\lambda|\\sigma|\\theta|\\langle|\\lVert|\$\$"
    ),
    "quant_claims": (
        r"\b\d+(?:\.\d+)?\s?(?:%|s\b|ms\b|ticks|samples|ppm)|"
        r"\b(always|never|zero|none|all|siempre|nunca|todos)\b"
    ),
    "experiment_ids": r"\bEXP-[A-Za-z0-9-]+|\bN\s*=\s*\d+|\bp\s*[<>≤≥=]\s*0?\.\d",
    "measure_tokens": (
        r"\bmedian\b|\bmean\b|measured|confidence|std|variance|"
        r"\bσ\b|\bλ\b|empirical"
    ),
    "external_refs": r"\\cite\{|\\ref\{|\\eqref\{|\bsee\s+(?:Sec|§|section)\b|\.vsm\b|\.pdf\b",
    "numbered_sections": r"\\section\*\{\s*\d+\.",
    "vsm_blocks": r"^\s*(?:design|rule|phase|task)\s*\(",
    "inequality_symbols": r"\\le\b|\\ge\b|≤|≥|\\forall|convex|bounded",
}

# ── thresholds (calibrated 2026-10-09 on main.tex / fierro / carta /
#    claim_ingest_proposal.vsm / addendum.tex — see NB03) ─────────────────────
MATH_SYMBOLS_MIN = 30      # L3 raw math volume
MATH_DENSITY_MIN = 1.0     # L3 symbols per kB (real docs: 1.61/5.22 vs 0.00)

_LEVEL_TOOLS: dict[str, str] = {
    "L1": "claim_ingest",
    "L2": "l2_parser",
    "L3": "sympy",
    "L4": "results_join",
    "L5": "ledger_correlate",
}


def features(text: str) -> dict[str, int]:
    """Count deterministic signals in the text."""
    out = {
        name: len(re.findall(pat, text, re.I | re.MULTILINE))
        for name, pat in _PATTERNS.items()
    }
    out["math_density"] = round(out["math_symbols"] / max(len(text) / 1000, 0.1), 2)
    return out


def estimate(
    text: str,
    *,
    name: str = "",
    related_sources: int = 1,
) -> dict[str, Any]:
    """Estimate required analysis levels + tools for a document.

    Args:
        text: document text (extracted)
        name: optional document name (for the verdict string)
        related_sources: how many sibling artifacts exist for cross-source
            analysis (1 = standalone, >1 = part of a document set)

    Returns:
        {levels, tools, evidence, verdict, related_sources}
    """
    f = features(text)
    levels: list[str] = []

    # L1 — any extractable claim signal (empirical or declarative)
    if f["quant_claims"] > 0 or f["vsm_blocks"] > 0:
        levels.append("L1")

    # L2 — theorem/equation structure, VSM blocks, or numbered answer sections
    if (
        f["theorem_envs"] > 0
        or f["equation_envs"] > 0
        or f["vsm_blocks"] > 0
        or f["numbered_sections"] > 0
    ):
        levels.append("L2")

    # L3 — symbolic verification: real math volume at real density
    if (
        f["equation_envs"] > 0 or f["math_symbols"] >= MATH_SYMBOLS_MIN
    ) and f["math_density"] >= MATH_DENSITY_MIN:
        levels.append("L3")

    # L4 — theory-experiment: experiment ids AND measurement vocabulary
    if f["experiment_ids"] > 0 and f["measure_tokens"] > 0:
        levels.append("L4")

    # L5 — cross-source: explicit references or a multi-document set
    if f["external_refs"] > 0 or related_sources > 1:
        levels.append("L5")

    tools = [_LEVEL_TOOLS[lv] for lv in levels]
    if "L3" in levels and f["inequality_symbols"] > 0:
        tools.append("z3")

    label = f" ({name})" if name else ""
    if levels:
        verdict = (
            f"full stack L1-L5 required{label}" if len(levels) == 5
            else f"required depth: {', '.join(levels)}{label}"
        )
    else:
        verdict = f"no analyzable structure detected{label}"

    span = (
        f"{levels[0]}-{levels[-1]}" if len(levels) > 1
        else levels[0] if levels else ""
    )
    return {
        "levels": levels,
        "tools": tools,
        "evidence": f,
        "verdict": verdict,
        "span": span,
        "related_sources": related_sources,
    }
