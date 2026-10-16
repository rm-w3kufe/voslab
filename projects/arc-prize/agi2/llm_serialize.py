#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""llm_serialize — grid <-> text for LLM prompting (M1 harness).

Format (community grid-serialization style): every grid is rows of
digit characters (colors 0-9), one row per line. The prompt shows all
train pairs as Input/Output blocks and asks for the test output grid
ONLY. Deterministic (R10): pure string transforms, no randomness.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

Grid = List[List[int]]
Trains = List[Tuple[Grid, Grid]]


def grid_to_text(g: Grid) -> str:
    return "\n".join("".join(str(int(v)) for v in row) for row in g)


def grid_from_text(text: str) -> Optional[Grid]:
    """Parse the FIRST valid grid block from LLM text (robust)."""
    rows: List[List[int]] = []
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        if not line:
            if rows:
                break
            continue
        # accept only pure digit rows (optionally space/comma separated)
        cleaned = line.replace(" ", "").replace(",", "")
        if cleaned.isdigit() and len(cleaned) <= 64:
            rows.append([int(ch) for ch in cleaned])
            continue
        if rows:
            break
    if not rows:
        return None
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        return None
    return rows


def build_prompt(trains: Trains, test: Grid) -> str:
    parts = ["Solve this abstract reasoning task. The test OUTPUT grid "
             "follows the same rules as the train examples.",
             "Output ONLY the test output grid: one row per line, digits "
             "0-9, no explanation, no markdown."]
    for i, (inp, out) in enumerate(trains, 1):
        parts.append(f"Train example {i} input:\n{grid_to_text(inp)}")
        parts.append(f"Train example {i} output:\n{grid_to_text(out)}")
    parts.append(f"Test input:\n{grid_to_text(test)}")
    parts.append("Test output:")
    return "\n\n".join(parts)


def sanity_shape(pred: Grid, trains: Trains, max_factor: int = 4) -> bool:
    """Reject absurd shapes: at most max_factor x the largest train out."""
    if not pred:
        return False
    pr, pc = len(pred), len(pred[0])
    if pr < 1 or pc < 1 or pr > 64 or pc > 64:
        return False
    max_r = max(len(o) for _i, o in trains)
    max_c = max(len(o[0]) for _i, o in trains)
    return pr <= max_r * max_factor and pc <= max_c * max_factor


SYSTEM = ("You are an expert at the ARC abstract reasoning benchmark. "
          "You output ONLY grids as rows of digit characters.")
