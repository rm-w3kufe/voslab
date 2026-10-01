"""ARC leaderboard submission harness — LOCAL preparation only (A-5 vía 2).

Builds and validates an ARC submission payload (canonical grid schema):
a JSON object mapping task_id -> grid, where task_id is an 8-char hex
string and grid is a non-empty list of rows of ints 0..9 (1..30 x 1..30).

NOTHING here contacts any external service: this is the cheap local
preparation the backlog allows ("preparacion barata ... cuando S5
ordene"). The actual leaderboard upload / PR requires S5 order (P7:
publishing is last).

NB: the exact upload endpoint and file wrapping must be confirmed
against the official ARC submission guide at execution time — S5-ordered
runbook lives in docs/publishing/track.vsm.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TASK_ID_RE = re.compile(r"^[0-9a-f]{8}$")
MIN_DIM, MAX_DIM = 1, 30
MAX_CELL = 9


def validate_grid(grid: object, where: str = "grid") -> list[str]:
    errors: list[str] = []
    if not isinstance(grid, list) or not grid:
        return [f"{where}: grid must be a non-empty list of rows"]
    if not all(isinstance(r, list) for r in grid):
        return [f"{where}: every row must be a list"]
    height = len(grid)
    width = len(grid[0])
    if not (MIN_DIM <= height <= MAX_DIM and MIN_DIM <= width <= MAX_DIM):
        errors.append(
            f"{where}: dims {height}x{width} outside {MIN_DIM}..{MAX_DIM}")
    for r_i, row in enumerate(grid):
        if len(row) != width:
            errors.append(f"{where}: ragged row {r_i} (len {len(row)} != {width})")
        for c_i, cell in enumerate(row):
            if not isinstance(cell, int) or isinstance(cell, bool):
                errors.append(f"{where}[{r_i}][{c_i}]: cell is not an int")
            elif not (0 <= cell <= MAX_CELL):
                errors.append(
                    f"{where}[{r_i}][{c_i}]: cell {cell} outside 0..{MAX_CELL}")
    return errors


def validate_submission(obj: object) -> list[str]:
    if not isinstance(obj, dict):
        return ["submission: top level must be an object (task_id -> grid)"]
    if not obj:
        return ["submission: empty — at least one task is required"]
    errors: list[str] = []
    for task_id, grid in obj.items():
        if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
            errors.append(f"task id {task_id!r}: expected 8 lowercase hex chars")
            continue
        errors += validate_grid(grid, where=f"task {task_id}")
    return errors


def load_submission(path: Path) -> dict:
    return json.loads(path.read_text())


def build_submission(predictions: dict) -> dict:
    """Validate + normalize (stable key order) a predictions mapping."""
    errors = validate_submission(predictions)
    if errors:
        raise ValueError("; ".join(errors))
    return {k: predictions[k] for k in sorted(predictions)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="arc_submission_harness",
        description="local build/validate of ARC submission JSON (no network)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_val = sub.add_parser("validate", help="validate a submission JSON (rc1)")
    p_val.add_argument("file")
    p_bld = sub.add_parser("build", help="validate + sort + write submission")
    p_bld.add_argument("file", help="predictions JSON (task_id -> grid)")
    p_bld.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)

    src = Path(args.file)
    try:
        data = load_submission(src)
    except FileNotFoundError:
        print(f"ERROR: no such file: {src}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "validate":
        errors = validate_submission(data)
        if errors:
            for e in errors:
                print(f"INVALID: {e}", file=sys.stderr)
            return 1
        print(f"OK: {len(data)} tasks valid")
        return 0

    try:
        built = build_submission(data)
    except ValueError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    Path(args.out).write_text(json.dumps(built, indent=0) + "\n")
    print(f"wrote {args.out}: {len(built)} tasks (keys sorted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
