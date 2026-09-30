"""Tolerant loading of state/rsi/tree_traces.jsonl (runtime artifact).

Rows have different ages (pre-F1 rows lack home/context; pre-F3 rows lack
node text/question) — loading never fails on old shapes, and skips are
COUNTED, never silent (denominator rule).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def traces_path() -> Path:
    """Default JSONL location; VOSLAB_PATH re-read at runtime (same
    convention as TreeTraceLogger — tests redirect with the env var)."""
    root = os.environ.get("VOSLAB_PATH")
    if root:
        return Path(root) / "state" / "rsi" / "tree_traces.jsonl"
    from vos_kernel.epistemic import repo_root
    return repo_root() / "state" / "rsi" / "tree_traces.jsonl"


def load_traces(path: Path | str | None = None) -> tuple[list[dict], int]:
    """(traces, skipped) — skipped counts malformed/empty lines."""
    p = Path(path) if path is not None else traces_path()
    if not p.exists():
        return [], 0
    traces: list[dict] = []
    skipped = 0
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(rec, dict):
            traces.append(rec)
        else:
            skipped += 1
    return traces, skipped


def family(tree_shape: str | None) -> str:
    """'claim_gate(AND(...))' -> 'claim_gate'; 'type_prefix' stays."""
    return str(tree_shape or "?").split("(", 1)[0].strip()
