"""arc_dsl.py — grid operation DSL for ARC program synthesis (phase 1).

Design: TOTAL functions (never raise, never crash). An op that cannot
apply returns the input unchanged — the GA needs safe composition, and
fitness (exact match on train pairs) sorts it out. Grids are lists of
lists of ints 0-9. Programs are lists of (op_name, params) steps.

v1 op set (~12, deliberately small so random search has a chance):
  geometric: rot90, rot180, rot270, flip_h, flip_v, transpose
  color:     recolor(a, b)
  move:      shift(dx, dy) with background fill (color 0), same size
  other:     invert (9-v), identity
"""
from __future__ import annotations

from typing import Any


def _check(grid) -> bool:
    return (isinstance(grid, list) and bool(grid)
            and all(isinstance(r, list) and r for r in grid))


def _size(grid):
    return len(grid), len(grid[0])


def rot90(grid):
    if not _check(grid):
        return grid
    h, w = _size(grid)
    return [[grid[h - 1 - r][c] for r in range(h)] for c in range(w)]


def rot180(grid):
    if not _check(grid):
        return grid
    return [row[::-1] for row in grid[::-1]]


def rot270(grid):
    if not _check(grid):
        return grid
    h, w = _size(grid)
    return [[grid[r][w - 1 - c] for r in range(h)] for c in range(w)]


def flip_h(grid):
    if not _check(grid):
        return grid
    return [row[::-1] for row in grid]


def flip_v(grid):
    if not _check(grid):
        return grid
    return grid[::-1]


def transpose(grid):
    if not _check(grid):
        return grid
    h, w = _size(grid)
    return [[grid[r][c] for r in range(h)] for c in range(w)]


def recolor(grid, a=1, b=2):
    if not _check(grid):
        return grid
    try:
        a, b = int(a) % 10, int(b) % 10
    except (TypeError, ValueError):
        return grid
    return [[b if v == a else v for v in row] for row in grid]


def shift(grid, dx=0, dy=0, bg=0):
    """Shift by (dx rows, dy cols), fill vacated cells with bg, same size."""
    if not _check(grid):
        return grid
    try:
        dx, dy, bg = int(dx), int(dy), int(bg) % 10
    except (TypeError, ValueError):
        return grid
    h, w = _size(grid)
    out = [[bg] * w for _ in range(h)]
    for r in range(h):
        for c in range(w):
            nr, nc = r + dx, c + dy
            if 0 <= nr < h and 0 <= nc < w:
                out[nr][nc] = grid[r][c]
    return out


def invert(grid):
    if not _check(grid):
        return grid
    try:
        return [[9 - int(v) for v in row] for row in grid]
    except (TypeError, ValueError):
        return grid


def identity(grid):
    return grid


OPS = {
    "rot90": (rot90, 0),
    "rot180": (rot180, 0),
    "rot270": (rot270, 0),
    "flip_h": (flip_h, 0),
    "flip_v": (flip_v, 0),
    "transpose": (transpose, 0),
    "recolor": (recolor, 2),
    "shift": (shift, 2),
    "invert": (invert, 0),
    "identity": (identity, 0),
}

OP_NAMES = sorted(OPS)


def apply(program, grid):
    """Run a program: list of (op_name, [params]). Unknown ops are skipped
    (total: never raises on bad steps, only on non-list grid input which
    callers guarantee)."""
    out = grid
    for step in program:
        try:
            name = step[0]
            params = step[1] if len(step) > 1 else []
            fn, _arity = OPS[name]
            out = fn(out, *params)
        except Exception:
            continue
    return out


def program_to_str(program) -> str:
    parts = []
    for step in program:
        name = step[0]
        params = step[1] if len(step) > 1 else []
        parts.append(name if not params else f"{name}{tuple(params)}")
    return " -> ".join(parts) if parts else "identity"


def _components(grid, bg=0):
    """4-connected components of non-bg cells. Returns list of cell-sets."""
    if not _check(grid):
        return []
    h, w = _size(grid)
    seen = [[False] * w for _ in range(h)]
    comps = []
    for r in range(h):
        for c in range(w):
            if seen[r][c] or grid[r][c] == bg:
                continue
            stack, cells = [(r, c)], []
            seen[r][c] = True
            while stack:
                cr, cc = stack.pop()
                cells.append((cr, cc))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = cr + dr, cc + dc
                    if (0 <= nr < h and 0 <= nc < w and not seen[nr][nc]
                            and grid[nr][nc] != bg):
                        seen[nr][nc] = True
                        stack.append((nr, nc))
            comps.append(cells)
    return comps


def keep_color(grid, c=1):
    """Zero out every cell except color c."""
    if not _check(grid):
        return grid
    try:
        c = int(c) % 10
    except (TypeError, ValueError):
        return grid
    return [[v if v == c else 0 for v in row] for row in grid]


def crop_content(grid, bg=0):
    """Crop to bounding box of non-bg cells (identity if empty/full)."""
    if not _check(grid):
        return grid
    try:
        bg = int(bg) % 10
    except (TypeError, ValueError):
        return grid
    rows = [r for r, row in enumerate(grid)
            if any(v != bg for v in row)]
    cols = [c for c in range(len(grid[0]))
            if any(grid[r][c] != bg for r in range(len(grid)))]
    if not rows or not cols:
        return grid
    return [[grid[r][c] for c in range(min(cols), max(cols) + 1)]
            for r in range(min(rows), max(rows) + 1)]


def fill_enclosed(grid, bg=0):
    """Fill bg-regions fully enclosed by a single color with that color."""
    if not _check(grid):
        return grid
    try:
        bg = int(bg) % 10
    except (TypeError, ValueError):
        return grid
    h, w = _size(grid)
    # bg cells reachable from the border are NOT enclosed
    open_bg = [[False] * w for _ in range(h)]
    stack = [(r, c) for r in range(h) for c in (0, w - 1)
             if grid[r][c] == bg]
    stack += [(c, c2) for c2 in range(w) for c in (0, h - 1)
              if grid[c][c2] == bg]
    while stack:
        cr, cc = stack.pop()
        if open_bg[cr][cc]:
            continue
        open_bg[cr][cc] = True
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = cr + dr, cc + dc
            if (0 <= nr < h and 0 <= nc < w and not open_bg[nr][nc]
                    and grid[nr][nc] == bg):
                stack.append((nr, nc))
    out = [row[:] for row in grid]
    for r in range(h):
        for c in range(w):
            if grid[r][c] == bg and not open_bg[r][c]:
                neigh = {grid[nr][nc]
                         for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         for nr, nc in [(r + dr, c + dc)]
                         if 0 <= nr < h and 0 <= nc < w
                         and grid[nr][nc] != bg}
                if len(neigh) == 1:
                    out[r][c] = neigh.pop()
    return out


def symmetrize_h(grid):
    """Mirror left half onto right half (vertical axis symmetry)."""
    if not _check(grid):
        return grid
    h, w = _size(grid)
    out = [row[:] for row in grid]
    for r in range(h):
        for c in range(w // 2, w):
            out[r][c] = grid[r][w - 1 - c]
    return out


def tile2x2(grid):
    """Repeat grid into 2x2 blocks."""
    if not _check(grid):
        return grid
    return [row + row for row in grid] + \
        [row + row for row in grid]


OPS.update({
    "keep_color": (keep_color, 1),
    "crop_content": (crop_content, 0),
    "fill_enclosed": (fill_enclosed, 0),
    "symmetrize_h": (symmetrize_h, 0),
    "tile2x2": (tile2x2, 0),
})
OP_NAMES[:] = sorted(OPS)
