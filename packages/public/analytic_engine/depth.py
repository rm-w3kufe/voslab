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
    from analytic_engine.depth import estimate, persist_depth
    est = estimate(text, related_sources=3)
    est["levels"], est["tools"], est["evidence"], est["verdict"]

    # per-document sidecar (DEPTH-v1, parallel to .claims.vsm sidecars)
    sc = persist_depth(text, name="main.tex")
    sc["depth_path"], sc["depth_status"]  # written | unchanged
"""

from __future__ import annotations

import json
import re
from pathlib import Path
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


# ── DEPTH-v1 sidecar (parallel to claim_ingest .claims.vsm, F1 conventions) ──
# One <stem>.depth.vsm per document in state/epistemic/sidecars/: what the
# document REQUIRES (levels + tools + evidence), next to what it SAYS
# (<stem>.claims.vsm). Same idempotency contract: body-compare ignoring the
# timestamped ⟦ header, so repeated persists never dirty the tree (gate 5).

def _repo_root() -> Path:
    from vos_kernel.epistemic import repo_root
    return repo_root()


def _name_for(source_name: str) -> str:
    from claim_ingest.ledger import ledger_name_for
    return ledger_name_for(source_name)


def render_depth(name: str, est: dict[str, Any]) -> str:
    """DEPTH-v1 document: levels + tools + evidence + verdict."""
    from vos_kernel.utils.vsm_kernel import new_doc
    parts = [
        "// depth_estimator — required analysis levels + tools "
        "(R10, NB03; docs/plans/claim_ingest_proposal.vsm companion)",
        "levels = " + json.dumps(est["levels"], ensure_ascii=False),
        "tools = " + json.dumps(est["tools"], ensure_ascii=False),
        "evidence = " + json.dumps(est["evidence"], ensure_ascii=False),
        "verdict = " + json.dumps(est["verdict"], ensure_ascii=False),
        "span = " + json.dumps(est["span"], ensure_ascii=False),
        "related_sources = " + str(est["related_sources"]),
    ]
    body = "\n".join(parts) + "\n"
    return new_doc(_name_for(name), "DEPTH-v1", body, status="active")


def depth_body(text: str) -> str:
    """Sidecar content without ⟦ header/footer lines (timestamp-only diffs)."""
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("⟦"))


def write_depth(path: Path | str, name: str, est: dict[str, Any], *,
                if_changed: bool = False) -> Path:
    """Write the depth sidecar; refuses paths outside the vOSlab workspace
    and pre-validates VSM content before disk (same guards as write_ledger)."""
    from vos_kernel.utils.vsm_kernel import validate_vsm_content
    path = Path(path).resolve()
    root = _repo_root().resolve()
    if path != root and root not in path.parents:
        raise PermissionError(
            f"depth path outside workspace: {path} (root {root})")
    content = render_depth(name, est)
    if if_changed and path.exists():
        if depth_body(path.read_text(encoding="utf-8")) == \
                depth_body(content):
            return path
    v = validate_vsm_content(content)
    if not v["valid"]:
        raise ValueError(f"depth VSM invalid: {v['errors']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def persist_depth(
    text: str,
    *,
    name: str,
    related_sources: int = 1,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Estimate + write the per-document DEPTH-v1 sidecar (idempotent).

    Returns {estimate, depth_path, depth_status: "written" | "unchanged"}.
    Default path: state/epistemic/sidecars/<stem>.depth.vsm.
    """
    est = estimate(text, name=name, related_sources=related_sources)
    if path is None:
        path = (
            _repo_root() / "state" / "epistemic" / "sidecars"
            / f"{_name_for(name)}.depth.vsm"
        )
    p = Path(path)
    before = p.read_bytes() if p.exists() else None
    write_depth(p, name, est, if_changed=True)
    after = p.read_bytes() if p.exists() else None
    return {
        "estimate": est,
        "depth_path": str(p),
        "depth_status": "written" if before != after else "unchanged",
    }
