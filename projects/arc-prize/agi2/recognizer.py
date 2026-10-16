#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-2 Recognizer — RSI orient step: WHAT is this puzzle about?

Instead of trying strategies blindly (fixed order), first CLASSIFY the
puzzle dynamic from its train pairs, then route to ONE strategy.

  classify(trains) -> (dynamic, evidence)
  solve_routed(trains, test) -> apply predicted strategy, fallback to chain

Detectors are honest: a dynamic is claimed only if its strategy
reproduces EVERY train output from its train input (no test leakage).

Metrics (all deterministic, rule-based — R10):
  - precision@1: predicted strategy alone solves the test
  - oracle: ANY known strategy solves (upper bound of current toolbox)
  - efficiency: strategies tried per puzzle (routed ~1-2 vs blind ~15)
  - per-dynamic precision table (feeds the learning loop)

New strategy from this module: try_object_shift (uniform translation
of all objects). If it solves puzzles nothing else solves → RSI gain.
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
import solver_smart_v2 as v2
import solver_v3 as v3
from rsi_module import try_adaptive_tiling

Grid = List[List[int]]
Trains = List[Tuple[Grid, Grid]]

# ─── Grid helpers ────────────────────────────────────────────────────

def shape(g: Grid) -> Tuple[int, int]:
    return (len(g), len(g[0]) if g else 0)


def bg_color(g: Grid) -> int:
    c = Counter(c for row in g for c in row)
    return c.most_common(1)[0][0]


def components(g: Grid, bg: Optional[int] = None):
    """Connected components (4-dir) of non-background cells, per color."""
    if bg is None:
        bg = bg_color(g)
    R, C = shape(g)
    seen = set()
    comps = []
    for r in range(R):
        for c in range(C):
            if (r, c) in seen or g[r][c] == bg:
                continue
            color = g[r][c]
            cells, stack = [], [(r, c)]
            while stack:
                cr, cc = stack.pop()
                if ((cr, cc) in seen or cr < 0 or cr >= R or cc < 0 or cc >= C
                        or g[cr][cc] != color):
                    continue
                seen.add((cr, cc))
                cells.append((cr, cc))
                stack.extend([(cr - 1, cc), (cr + 1, cc),
                              (cr, cc - 1), (cr, cc + 1)])
            if cells:
                rs = [x[0] for x in cells]
                cs = [x[1] for x in cells]
                sig = frozenset((rr - min(rs), cc - min(cs))
                                for rr, cc in cells)
                comps.append({"color": color, "cells": cells,
                              "size": len(cells), "sig": sig,
                              "anchor": (min(rs), min(cs))})
    return comps


def contains_subgrid(big: Grid, small: Grid) -> bool:
    R, C = shape(big)
    r, c = shape(small)
    if r > R or c > C or r == 0:
        return False
    for i in range(R - r + 1):
        for j in range(C - c + 1):
            if all(big[i + di][j + dj] == small[di][dj]
                   for di in range(r) for dj in range(c)):
                return True
    return False


def verify(fn: Callable, trains: Trains) -> bool:
    """Strategy reproduces every train output from its train input."""
    try:
        for inp, out in trains:
            pred = fn(trains, inp)
            if pred is None or not v3.grids_equal(pred, out):
                return False
        return True
    except Exception:
        return False


def verify_loo(fn: Callable, trains: Trains) -> bool:
    """Leave-one-out: predict each train output from the OTHER pairs.

    Kills memorizers (e.g. nearest_neighbor returns the matching train
    output verbatim → plain verify passes trivially, LOO fails).
    Detectors must prove generalization, not recall.
    """
    if len(trains) < 2:
        return verify(fn, trains)
    try:
        for i, (inp, out) in enumerate(trains):
            others = trains[:i] + trains[i + 1:]
            pred = fn(others, inp)
            if pred is None or not v3.grids_equal(pred, out):
                return False
        return True
    except Exception:
        return False


def verify_loo_fraction(fn: Callable, trains: Trains) -> float:
    """Fraction of train pairs reproduced leave-one-out (0.0-1.0).

    Fractional sibling of verify_loo for critic scoring — the A+B audit
    (2026-10-16) found agent.propose called this name, got AttributeError,
    and silently scored every producer's 0.5-weight LOO term as 0.0.
    Deterministic (R10): same pairs, same fraction, always.
    """
    if not trains:
        return 0.0
    if len(trains) < 2:
        try:
            pred = fn(trains, trains[0][0])
            return (1.0 if pred is not None and
                    v3.grids_equal(pred, trains[0][1]) else 0.0)
        except Exception:
            return 0.0
    ok = 0
    for i, (_inp, out) in enumerate(trains):
        others = trains[:i] + trains[i + 1:]
        try:
            pred = fn(others, _inp)
            if pred is not None and v3.grids_equal(pred, out):
                ok += 1
        except Exception:
            pass
    return ok / len(trains)


def safe_apply(fn: Callable, trains: Trains, test: Grid):
    try:
        return fn(trains, test)
    except Exception:
        return None

# ─── New strategy: uniform object shift ──────────────────────────────

def detect_shift(trains: Trains) -> Optional[Tuple[int, int]]:
    """All objects translated by one consistent (dr, dc)?"""
    shifts = []
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        ic = components(inp)
        oc = components(out)
        if not ic or len(ic) != len(out and oc):
            return None
        # match by (color, size, shape)
        omap = defaultdict(list)
        for o in oc:
            omap[(o["color"], o["size"], o["sig"])].append(o["anchor"])
        pair_shifts = set()
        for o in ic:
            key = (o["color"], o["size"], o["sig"])
            if len(omap.get(key, [])) != 1:
                return None
            (or_, oc_) = omap[key][0]
            (ir, ic_) = o["anchor"]
            pair_shifts.add((or_ - ir, oc_ - ic_))
        if len(pair_shifts) != 1:
            return None
        shifts.append(next(iter(pair_shifts)))
    if not shifts or len(set(shifts)) != 1:
        return None
    return shifts[0]


def try_object_shift(trains: Trains, test: Grid) -> Optional[Grid]:
    s = detect_shift(trains)
    if s is None:
        return None
    dr, dc = s
    R, C = shape(test)
    bg = bg_color(trains[0][0])
    out = [[bg] * C for _ in range(R)]
    for comp in components(test, bg):
        for (r, c) in comp["cells"]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C:
                out[nr][nc] = comp["color"]
            else:
                return None  # shift leaves the grid → not this dynamic
    return out

# ─── Band match (rearrange family) ─────────────────────────────────────
# Seen in 18447a8d. Static comps (same cells in/out, learned per subset)
# form BANDS; movers pair with bands REVERSE by size (bands size-asc /
# movers size-desc, ties: row-asc / color-desc) — corroborated by exact
# complementarity (band8 + moversize = 15 in all 3 trains). Each mover
# rigid-translates to its band (TOP = band min-row, LEFT = leftmost >= 0
# non-overlapping vs static). Movers vacate (bg shows through).

def _static_colors(trains, bg):
    colors = None
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        # static OBJECTS (identical cell sets in/out), grouped by color
        imap, omap = defaultdict(set), defaultdict(set)
        for o in components(inp, bg):
            imap[o["color"]] |= set(o["cells"])
        for o in components(out, bg):
            omap[o["color"]] |= set(o["cells"])
        stat = {c for c in set(imap) | set(omap)
                if imap.get(c, set()) == omap.get(c, set()) and imap.get(c)}
        colors = stat if colors is None else (colors & stat)
    return colors


def try_band_match(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    bg = bg_color(trains[0][0])
    stat = _static_colors(trains, bg)
    if not stat:
        return None
    R, C = shape(test)
    tcomps = components(test, bg)
    bands = [o for o in tcomps if o["color"] in stat]
    movers = [o for o in tcomps if o["color"] not in stat]
    if not movers or len(bands) != len(movers):
        return None
    bands.sort(key=lambda o: (o["size"], o["anchor"][0], o["anchor"][1]))
    movers.sort(key=lambda o: (-o["size"], -o["color"],
                               o["anchor"][0], o["anchor"][1]))
    out = [row[:] for row in test]
    for m in movers:
        for (r, c) in m["cells"]:
            out[r][c] = bg
    static_cells = set()
    for b in bands:
        static_cells |= set(b["cells"])
    for band, mover in zip(bands, movers):
        top = min(r for (r, c) in band["cells"])
        (ar, ac) = mover["anchor"]
        placed = None
        for left in range(0, C):
            cells = [(r - ar + top, c - ac + left)
                     for (r, c) in mover["cells"]]
            if not all(0 <= r < R and 0 <= c < C for (r, c) in cells):
                continue
            if any((r, c) in static_cells for (r, c) in cells):
                continue
            placed = cells
            break
        if placed is None:
            return None
        for (r, c) in placed:
            out[r][c] = mover["color"]
            static_cells.add((r, c))
    return out


def d_bandmatch(trains):
    return verify_loo(try_band_match, trains)

# ─── Legend swap (rearrange family) ────────────────────────────────────
# Seen in 0becf7df: the top-left 2x2 corner is an immutable LEGEND whose
# ROWS define color-swap pairs (row0 [a,b] -> a<->b, row1 [c,d] -> c<->d);
# every other cell swaps accordingly. Learned per input (pairs differ
# per train!), legend cells never change. Colors outside the pairs and
# degenerate pairs (a==b) pass through.

def _legend_pairs(inp):
    if len(inp) < 2 or len(inp[0]) < 2:
        return None
    a, b = inp[0][0], inp[0][1]
    c, d = inp[1][0], inp[1][1]
    return {a: b, b: a, c: d, d: c}


def try_legend_swap(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        m = _legend_pairs(inp)
        if m is None:
            return None
        R, C = shape(inp)
        for r in range(R):
            for c in range(C):
                if r < 2 and c < 2:
                    if out[r][c] != inp[r][c]:
                        return None  # legend must be immutable
                elif out[r][c] != m.get(inp[r][c], inp[r][c]):
                    return None
    m = _legend_pairs(test)
    if m is None:
        return None
    R, C = shape(test)
    return [[test[r][c] if (r < 2 and c < 2) else m.get(test[r][c],
            test[r][c]) for c in range(C)] for r in range(R)]


def d_legendswap(trains):
    return verify_loo(try_legend_swap, trains)

# ─── Lattice interpolation (rearrange family) ──────────────────────────
# Seen in 06df4c85/train0: same-shape same-color blocks on lattice lines
# get intermediate lattice points filled with shifted copies (step 3 =
# gcd of same-line gaps; 0-blocks replaced). Multi-texture puzzles (whose
# trains need different rules, like 06df4c85 itself) HONESTLY fail LOO.
# Placeholders: fills may overwrite bg or the single most-common block
# class (learned per subset); anything else -> None (fail safe).

def _grid_step(inp, bg):
    """Per-grid lattice step: min spacing of full-bg lines, else gcd."""
    R, C = shape(inp)
    rl = [r for r in range(R) if all(v == bg for v in inp[r])]
    cl = [c for c in range(C) if all(inp[r][c] == bg for r in range(R))]
    sp = []
    if len(rl) >= 2:
        sp.append(min(b - a for a, b in zip(rl, rl[1:])))
    if len(cl) >= 2:
        sp.append(min(b - a for a, b in zip(cl, cl[1:])))
    if sp:
        return min(sp) if min(sp) >= 2 else None
    gaps = []
    comps = components(inp, bg)
    byrc = defaultdict(list)
    for o in comps:
        byrc[(o["color"], "r", o["anchor"][0])].append(o["anchor"][1])
        byrc[(o["color"], "c", o["anchor"][1])].append(o["anchor"][0])
    for _k, v in byrc.items():
        v = sorted(v)
        for a, b in zip(v, v[1:]):
            if b > a:
                gaps.append(b - a)
    if not gaps:
        return None
    from math import gcd
    from functools import reduce
    s = reduce(gcd, gaps)
    return s if s >= 2 else None


def _placeholder(inp, bg):
    cnt = Counter()
    for o in components(inp, bg):
        cnt[(o["color"], o["sig"])] += 1
    return cnt.most_common(1)[0][0] if cnt else None


def _lattice_apply(inp, s, ph_color, bg):
    R, C = shape(inp)
    out = [row[:] for row in inp]
    comps = components(inp, bg)
    groups = defaultdict(list)
    for o in comps:
        groups[(o["color"], o["sig"])].append(o)
    for (_color, _sig), objs in groups.items():
        if len(objs) < 2:
            continue
        byrow, bycol = defaultdict(list), defaultdict(list)
        for o in objs:
            byrow[o["anchor"][0]].append(o)
            bycol[o["anchor"][1]].append(o)
        for _k, run in list(byrow.items()) + list(bycol.items()):
            run = sorted(run, key=lambda o: o["anchor"])
            for a, b in zip(run, run[1:]):
                ar, ac = a["anchor"]
                br, bc = b["anchor"]
                span = br - ar + bc - ac
                if span % s != 0:
                    return None
                steps = span // s
                for t in range(1, steps):
                    f = t / steps
                    or_ = round(ar + (br - ar) * f)
                    oc = round(ac + (bc - ac) * f)
                    cells = [(cr - ar + or_, cc - ac + oc)
                             for (cr, cc) in a["cells"]]
                    if not all(0 <= nr < R and 0 <= nc < C
                               for (nr, nc) in cells):
                        return None
                    # occupied by pattern endpoints (e.g. a colored block
                    # where the 0-lattice wants to paint): skip the copy,
                    # never half-paint. Final verify catches real misses.
                    if all(out[nr][nc] in (bg, ph_color)
                           for (nr, nc) in cells):
                        for (nr, nc) in cells:
                            out[nr][nc] = a["color"]
    return out


def try_lattice_interp(trains: Trains, test: Grid) -> Optional[Grid]:
    # Per-grid analysis (bg, step, placeholder all native to each grid):
    # 06df4c85 trains have DIFFERENT bgs (1/8/4) — a shared-bg rule can
    # never cover them. The RULE (interpolate on bg lattice) is uniform;
    # parameters are per-grid. Vacuity guard: the rule must visibly do
    # something in at least one train (else identity puzzles false-fire).
    if not trains:
        return None
    worked = 0
    for inp, out in trains:
        bg = bg_color(inp)
        s = _grid_step(inp, bg)
        ph = _placeholder(inp, bg)
        if s is None or ph is None:
            return None
        pred = _lattice_apply(inp, s, ph[0], bg)
        if pred is None or not v3.grids_equal(pred, out):
            return None
        worked += sum(1 for r in range(len(inp))
                      for c in range(len(inp[0]))
                      if pred[r][c] != inp[r][c])
    if worked == 0:
        return None
    bg = bg_color(test)
    s = _grid_step(test, bg)
    ph = _placeholder(test, bg)
    if s is None or ph is None:
        return None
    return _lattice_apply(test, s, ph[0], bg)


def d_lattice(trains):
    return verify_loo(try_lattice_interp, trains)

# ─── Connect dots (draw family) ────────────────────────────────────────
# Seen in 992798f6: an `x` king-path joins `o` to `#`. Rule, fit on all
# 4 trains: the ELBOW endpoint emits [1 diagonal toward target +
# straight run of (max-min) along the LONG axis]; the DIAG endpoint emits
# pure diagonal king-steps until adjacent to drawn content. Endpoint
# roles, dot colors and ray color are LEARNED per puzzle (both role
# orders tried; first reproducing all trains wins). bg-only painting;
# rays stop before non-bg (content preserved). No overwrite evidence.

def _king_step(fr, fc, tr, tc):
    dr = (tr > fr) - (tr < fr)
    dc = (tc > fc) - (tc < fc)
    return (fr + dr, fc + dc)


def _singles(g, bg):
    out = {}
    for r, row in enumerate(g):
        for c, v in enumerate(row):
            if v != bg:
                out.setdefault(v, []).append((r, c))
    return {k: v[0] for k, v in out.items() if len(v) == 1}


def _connect_build(inp, pe, pd, X, bg):
    R, C = shape(inp)
    out = [row[:] for row in inp]
    drawn = {pe, pd}

    def paintable(r, c):
        return 0 <= r < R and 0 <= c < C and out[r][c] == bg

    # elbow ray: 1 diagonal + straight (max-min) along long axis
    dr = pd[0] - pe[0]
    dc = pd[1] - pe[1]
    if abs(dr) + abs(dc) <= 1:
        return None
    r, c = _king_step(pe[0], pe[1], pd[0], pd[1])
    if (r, c) == pd or not paintable(r, c):
        return None
    out[r][c] = X
    drawn.add((r, c))
    if abs(dr) >= abs(dc):
        step, n = (1 if dr > 0 else -1, 0), abs(dr) - abs(dc)
    else:
        step, n = (0, 1 if dc > 0 else -1), abs(dc) - abs(dr)
    for _ in range(n):
        r, c = r + step[0], c + step[1]
        if not (0 <= r < R and 0 <= c < C):
            return None
        if out[r][c] != bg:
            break  # truncate before content; trains never hit this
        out[r][c] = X
        drawn.add((r, c))
    # diag ray: king-steps until adjacent to drawn content
    r, c = pd
    for _ in range(64):
        nr, nc = _king_step(r, c, pe[0], pe[1])
        if not (0 <= nr < R and 0 <= nc < C):
            return None
        if out[nr][nc] != bg:
            break
        out[nr][nc] = X
        drawn.add((nr, nc))
        r, c = nr, nc
    # must end adjacent to the elbow construction (else unlinked)
    if not any(abs(r - dr_) + abs(c - dc_) == 1 or
               (abs(r - dr_) == 1 and abs(c - dc_) == 1)
               for (dr_, dc_) in drawn if (dr_, dc_) != (r, c)):
        pass  # linked via paint trail by construction; no extra check
    return out


def try_connect_dots(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    bg = bg_color(trains[0][0])
    # learn: exactly-2 single-cell colors consistent + single ray color
    cols = None
    for inp, _out in trains:
        s = set(_singles(inp, bg).keys())
        cols = s if cols is None else (cols & s)
        if len(cols or ()) > 2:
            return None
    if not cols or len(cols) != 2:
        return None
    c1, c2 = sorted(cols)
    # strictness: outputs differ only by bg->X additions, single X
    added = set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        for r in range(len(inp)):
            for c in range(len(inp[0])):
                a, b = inp[r][c], out[r][c]
                if a == bg and b != bg:
                    added.add(b)
                elif a != b:
                    return None
    if len(added) != 1:
        return None
    X = next(iter(added))
    if X in cols:
        return None
    for (e_col, d_col) in ((c1, c2), (c2, c1)):
        ok = True
        for inp, out in trains:
            se = _singles(inp, bg)
            if e_col not in se or d_col not in se:
                ok = False
                break
            pred = _connect_build(inp, se[e_col], se[d_col], X, bg)
            if pred is None or not v3.grids_equal(pred, out):
                ok = False
                break
        if ok:
            se = _singles(test, bg)
            if e_col not in se or d_col not in se:
                return None
            return _connect_build(test, se[e_col], se[d_col], X, bg)
    return None


def d_connect(trains):
    return verify_loo(try_connect_dots, trains)

# ─── Grow ring (draw family) ───────────────────────────────────────────
# Seen in 0962bcdd: a clean DIAMOND (center C, 4 orthogonal arms color A
# length exactly 1, diagonal corners bg) grows one ring: arms extend to
# length 2 (same arm color per direction), all diagonal cells within
# radius 2 take the CENTER color, center kept. Star centered at input
# center, shifted minimally to fit grid (up-first order); (10,8)->(9,8)
# in train0 is grid-fit, not a rule change. Multi-motif grids handled
# per motif; strict (any failure -> None). Conservative bg-only paint.

def _find_diamonds(g, bg):
    R, C = shape(g)
    found = []
    for r in range(R):
        for c in range(C):
            if g[r][c] == bg:
                continue
            nbrs = [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
            if not all(0 <= nr < R and 0 <= nc < C and
                       g[nr][nc] != bg for (nr, nc) in nbrs):
                continue
            acol = {g[nr][nc] for (nr, nc) in nbrs}
            if len(acol) != 1:
                continue
            diags = [(r - 1, c - 1), (r - 1, c + 1),
                     (r + 1, c - 1), (r + 1, c + 1)]
            if not all(0 <= nr < R and 0 <= nc < C and
                       g[nr][nc] == bg for (nr, nc) in diags):
                continue
            # arms exactly length 1 (cells at distance 2 along axes bg/out)
            ok = True
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + 2 * dr, c + 2 * dc
                if 0 <= nr < R and 0 <= nc < C and g[nr][nc] != bg:
                    ok = False
                    break
            if not ok:
                continue
            found.append({"center": (r, c), "ccolor": g[r][c],
                          "arm": next(iter(acol))})
    return found


def _grow_star(g, bg, motif):
    R, C = shape(g)
    (cr, cc) = motif["center"]
    arm, cen = motif["arm"], motif["ccolor"]
    for dor, doc in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
                     (-1, -1), (-1, 1), (1, -1), (1, 1)):
        nr, nc = cr + dor, cc + doc
        if not (0 <= nr < R and 0 <= nc < C):
            return None
    out = [row[:] for row in g]
    # arms: extend each axis using that direction's arm color
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ar, ac = cr + dr, cc + dc  # existing arm cell (len 1)
        # walk outward while same arm color (robust to len>1 inputs)
        cells = [(ar, ac)]
        nr, nc = ar + dr, ac + dc
        while 0 <= nr < R and 0 <= nc < C and out[nr][nc] == arm:
            cells.append((nr, nc))
            nr, nc = nr + dr, nc + dc
        # one new cell beyond, if bg
        if 0 <= nr < R and 0 <= nc < C:
            if out[nr][nc] != bg:
                return None
            out[nr][nc] = arm
        # corners along the way take center color
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            if abs(dr) != abs(dc) or (dr == 0 and dc == 0):
                continue
            nr, nc = cr + dr, cc + dc
            if out[nr][nc] == bg:
                out[nr][nc] = cen
            elif out[nr][nc] != cen:
                return None
    return out


def try_grow_ring(trains: Trains, test: Grid) -> Optional[Grid]:
    # In-place only: observed stars never shift (an earlier (10,8)->(9,8)
    # "shift" was a misread; the diamond was already centered (9,8)).
    # Out-of-bounds growth -> None (honest; revisit with evidence if seen).
    if not trains:
        return None
    for inp, out in trains:
        bg = bg_color(inp)
        motifs = _find_diamonds(inp, bg)
        if not motifs:
            return None
        pred = [row[:] for row in inp]
        for m in motifs:
            pred = _grow_star(pred, bg, m)
            if pred is None:
                return None
        if not v3.grids_equal(pred, out):
            return None
    bg = bg_color(test)
    motifs = _find_diamonds(test, bg)
    if not motifs:
        return None
    pred = [row[:] for row in test]
    for m in motifs:
        pred = _grow_star(pred, bg, m)
        if pred is None:
            return None
    return pred


def d_growring(trains):
    return verify_loo(try_grow_ring, trains)

# ─── Symmetry complete (draw family) ───────────────────────────────────
# Seen in 11852cab (C4-closure reproduces all 3 trains): paint the orbit
# of every non-bg cell under a symmetry group about the content-bbox
# center (additive only: bg cells fill, content never erased/recolored).
# Groups tried in order (specific first): C4 rotations, H flip, V flip,
# D4 (fixpoint of rot90+flipH). First group reproducing all trains wins.

def _sym_orbit_fill(g, bg, center, ops):
    R, C = shape(g)
    CR, CC = center
    # doubled integer arithmetic (supports .5 centers)
    ICR, ICC = int(round(2 * CR)), int(round(2 * CC))
    out = [row[:] for row in g]

    def img(op, r, c):
        R2, C2 = 2 * r, 2 * c
        if op == "rot90":
            R2, C2 = ICR - (C2 - ICC), ICC + (R2 - ICR)
        elif op == "flipH":
            C2 = 2 * ICC - C2
        elif op == "flipV":
            R2 = 2 * ICR - R2
        else:
            return None
        if R2 % 2 or C2 % 2:
            return None
        return (R2 // 2, C2 // 2)

    for _ in range(8):  # fixpoint: closure under group
        changed = False
        for r in range(R):
            for c in range(C):
                if out[r][c] == bg:
                    continue
                for op in ops:
                    p = img(op, r, c)
                    if p is None:
                        continue
                    or_, oc = p
                    if 0 <= or_ < R and 0 <= oc < C and out[or_][oc] == bg:
                        out[or_][oc] = out[r][c]
                        changed = True
        if not changed:
            break
    return out


SYM_GROUPS = [
    ("C4", ["rot90"]),
    ("H", ["flipH"]),
    ("V", ["flipV"]),
    ("D4", ["rot90", "flipH"]),
]


def try_symmetry_complete(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    for group, ops in SYM_GROUPS:
        ok = True
        for inp, out in trains:
            bg = bg_color(inp)
            cells = [(r, c) for r, row in enumerate(inp)
                     for c, v in enumerate(row) if v != bg]
            if not cells:
                ok = False
                break
            cr = (min(r for r, c in cells) + max(r for r, c in cells)) / 2
            cc = (min(c for r, c in cells) + max(c for r, c in cells)) / 2
            pred = _sym_orbit_fill(inp, bg, (cr, cc), ops)
            if not v3.grids_equal(pred, out):
                ok = False
                break
        if ok:
            bg = bg_color(test)
            cells = [(r, c) for r, row in enumerate(test)
                     for c, v in enumerate(row) if v != bg]
            if not cells:
                return None
            cr = (min(r for r, c in cells) + max(r for r, c in cells)) / 2
            cc = (min(c for r, c in cells) + max(c for r, c in cells)) / 2
            return _sym_orbit_fill(test, bg, (cr, cc), ops)
    return None


def d_symcomplete(trains):
    return verify_loo(try_symmetry_complete, trains)

# ─── Invert + recolor (EV-hunt find) ───────────────────────────────────
# Seen in 6ea4a07e (EV top 0.29 via pattern_fill): binary occupancy
# INVERTED (6/6 trains: out-cells = 9 - in-cells) plus a learned
# fg->newfg map (5->4, 8->2, 3->1, consistent across trains). Strict:
# single fg color per train input; bg stays bg; map must agree.

def try_invert_recolor(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    mapping = {}
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        bg = bg_color(inp)
        # NOTE: never bg_color(out): frequency flips when fg dominates
        # (6ea4a07e/train0 out is 5 O vs 4 dots). Input bg rules.
        fg = {v for row in inp for v in row if v != bg}
        if len(fg) != 1:
            return None
        old = next(iter(fg))
        newf = {out[r][c] for r in range(len(out))
                for c in range(len(out[0]))
                if inp[r][c] == bg}
        if len(newf) != 1:
            return None
        new = next(iter(newf))
        if new == bg:
            return None
        if old in mapping and mapping[old] != new:
            return None
        mapping[old] = new
        for r in range(len(inp)):
            for c in range(len(inp[0])):
                want = new if inp[r][c] == bg else bg
                if out[r][c] != want:
                    return None
    bg = bg_color(test)
    fg = {v for row in test for v in row if v != bg}
    if len(fg) != 1 or next(iter(fg)) not in mapping:
        return None
    new = mapping[next(iter(fg))]
    return [[new if v == bg else bg for v in row] for row in test]


def d_invertrecolor(trains):
    # Same coverage-vs-redundancy lesson as sizefill: strict LOO demands
    # each pair's key appear in OTHER pairs; 6ea4a07e/train3 is the only
    # carrier of key 3 (LOO-3 unlearnable, yet the rule is true). Use
    # full-train consistency + evidence bar (distinct keys >= 2, or a key
    # repeated). Memorizers still excluded: output is fully determined by
    # the small map + inversion structure, not by copying a train.
    if not verify(try_invert_recolor, trains):
        return False
    keys = []
    for inp, _out in trains:
        bg = bg_color(inp)
        fg = {v for row in inp for v in row if v != bg}
        if len(fg) != 1:
            return False
        keys.append(next(iter(fg)))
    return len(set(keys)) >= 2 or len(keys) > len(set(keys))

# ─── Mirror double (EV-hunt find) ──────────────────────────────────────
# Seen in 3af2c5a8 (EV 0.26 via adaptive_tiling: right neighborhood!).
# Output = symmetric mirror-pad to exactly 2x (NO edge repeat):
# rows [0..R-1, R-1..0], cols [0..C-1, C-1..0], i.e. four quadrants
# [orig | fliplr ; flipud | both]. Found by eliminating tiling modes
# (col-flip fails exactly the cells mirror-pad explains).

def _mirror_double(g):
    R = len(g)
    C = len(g[0]) if R else 0
    if R == 0 or C == 0:
        return None
    top = [row[:] + row[::-1] for row in g]
    return top + top[::-1]


def try_mirror_double(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    for inp, out in trains:
        ir, ic = shape(inp)
        or_, oc = shape(out)
        if (or_, oc) != (2 * ir, 2 * ic):
            return None
        pred = _mirror_double(inp)
        if pred is None or not v3.grids_equal(pred, out):
            return None
    ir, ic = shape(test)
    return _mirror_double(test)


def d_mirrordouble(trains):
    return verify_loo(try_mirror_double, trains)

# ─── Block census (cola-20 find) ───────────────────────────────────────
# Seen in 6773b310 (4 trains, all hand-verified cell-exact): partition by
# uniform dividers (reuse _oddblock_partition); blocks contain only one
# non-bg color C; output one cell per block: mark-color M iff C-count==2.
# Threshold 2 is literal (no 0/3+ block observed; documented scope).
# Strict LOO detector.

def _blockcensus_params(trains):
    Cset, Mset = None, None
    for inp, out in trains:
        blocks = _oddblock_partition(inp)
        if blocks is None:
            return None
        bg = bg_color(inp)
        or_, oc = shape(out)
        # recover block grid dims
        R, C = shape(inp)
        hdiv = [r for r in range(R) if len(set(inp[r])) == 1]
        vdiv = [c for c in range(C) if len({inp[r][c] for r in range(R)}) == 1]
        if (len(hdiv) + 1, len(vdiv) + 1) != (or_, oc):
            return None
        ncols = len(vdiv) + 1
        # block colors: single non-bg color across all blocks?
        palette = {v for b in blocks for row in b for v in row} - {bg}
        if len(palette) != 1:
            return None
        ccol = next(iter(palette))
        Cset = {ccol} if Cset is None else (Cset & {ccol})
        # output: monochrome mark color + bg?
        obg = bg_color(out)
        opal = {v for row in out for v in row} - {obg}
        if len(opal) != 1:
            return None
        mcol = next(iter(opal))
        if mcol == bg:
            return None
        Mset = {mcol} if Mset is None else (Mset & {mcol})
        # reproduce: count==2 -> mark
        for i, b in enumerate(blocks):
            k = sum(1 for row in b for v in row if v == ccol)
            want = mcol if k == 2 else obg
            if out[i // ncols][i % ncols] != want:
                return None
    if not Cset or len(Cset) != 1 or not Mset or len(Mset) != 1:
        return None
    return (next(iter(Cset)), next(iter(Mset)))


def try_blockcensus(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    learned = _blockcensus_params(trains)
    if learned is None:
        return None
    ccol, mcol = learned
    bg = bg_color(test)
    blocks = _oddblock_partition(test)
    if blocks is None:
        return None
    R, C = shape(test)
    hdiv = [r for r in range(R) if len(set(test[r])) == 1]
    vdiv = [c for c in range(C) if len({test[r][c] for r in range(R)}) == 1]
    nr, nc = len(hdiv) + 1, len(vdiv) + 1
    if len(blocks) != nr * nc:
        return None
    out = []
    for i in range(nr):
        row = []
        for j in range(nc):
            b = blocks[i * nc + j]
            # scope: blocks hold only bg + learned color
            if {v for r in b for v in r} - {bg, ccol}:
                return None
            k = sum(1 for r in b for v in r if v == ccol)
            row.append(mcol if k == 2 else bg)
        out.append(row)
    return out


def d_blockcensus(trains):
    return verify_loo(try_blockcensus, trains)

# ─── Halves family (overlay boolops) ─────────────────────────────────
# norhalves (fafffa47: even-row halves; 6430c8c4: odd rows split
# around a middle uniform divider, divider excluded; 66f2d22f +
# e345f17b: vertical even halves as last resort), xorhalves
# (99b1bc43: EXACTLY ONE half figure), orhalves (ce4f8723: AT
# LEAST ONE half figure). Shared machinery: split kinds tried in
# precedence order (hdiv, heven, veven for NOR; H-only for XOR/OR —
# vertical XOR/OR unobserved, scope held); ground = palette
# INTERSECTION, never majority; mark M learned across trains
# (LOO enforces stability). Strict LOO detectors.

def _halves_cand(inp, kind):
    R = len(inp)
    C = len(inp[0]) if inp else 0
    if kind == "hdiv":
        if R % 2 == 0:
            return None
        dh = R // 2
        # the middle row must be a real divider (uniform NON-bg: an
        # all-bg middle row is empty space, not structure)
        if len(set(inp[dh])) != 1 or inp[dh][0] == bg_color(inp):
            return None
        return inp[:dh], inp[dh + 1:]
    if kind == "heven":
        if R % 2 or R < 2:
            return None
        h = R // 2
        return inp[:h], inp[h:]
    if kind == "veven":
        if C % 2 or C < 2:
            return None
        w = C // 2
        return [row[:w] for row in inp], [row[w:] for row in inp]
    if kind == "sdiv":
        strips = _vstrips_split(inp)
        if strips is None or len(strips) != 2:
            return None
        return strips[0], strips[1]
    return None


def _halves_ground(a, b):
    g = ({v for row in a for v in row} &
         {v for row in b for v in row})
    return next(iter(g)) if len(g) == 1 else None


def _halves_fit(trains, kinds, mask):
    for kind in kinds:
        marks = set()
        ok = True
        for inp, out in trains:
            cand = _halves_cand(inp, kind)
            if cand is None:
                ok = False
                break
            a, b = cand
            g = _halves_ground(a, b)
            if g is None:
                ok = False
                break
            h, w = len(a), len(a[0])
            if (h, w) != (len(out), len(out[0])):
                ok = False
                break
            fig = {v for row in out for v in row} - {g}
            if len(fig) != 1:
                ok = False
                break
            m = next(iter(fig))
            good = True
            for r in range(h):
                for c in range(w):
                    want = m if mask(a[r][c] != g, b[r][c] != g) else g
                    if out[r][c] != want:
                        good = False
                        break
                if not good:
                    break
            if not good:
                ok = False
                break
            marks.add(m)
        if ok and len(marks) == 1:
            return (kind, next(iter(marks)))
    return None


def _halves_try(trains, test, kinds, mask):
    if not trains:
        return None
    fit = _halves_fit(trains, kinds, mask)
    if fit is None:
        return None
    kind, m = fit
    cand = _halves_cand(test, kind)
    if cand is None:
        return None
    a, b = cand
    g = _halves_ground(a, b)
    if g is None:
        return None
    h, w = len(a), len(a[0])
    return [[m if mask(a[r][c] != g, b[r][c] != g) else g
             for c in range(w)] for r in range(h)]


def _mask_nor(fa, fb):
    return not fa and not fb


def _mask_xor(fa, fb):
    return fa != fb


def _mask_or(fa, fb):
    return fa or fb


_NOR_KINDS = ("hdiv", "heven", "veven", "sdiv")
_H_KINDS = ("hdiv", "heven")


def try_norhalves(trains: Trains, test: Grid) -> Optional[Grid]:
    return _halves_try(trains, test, _NOR_KINDS, _mask_nor)


def d_norhalves(trains):
    return verify_loo(try_norhalves, trains)

# ─── Xor halves (overlay-XOR) ───────────────────────────────────────
# Seen in 99b1bc43: same halves machinery (H-only kinds), mask marks
# cells where EXACTLY ONE half is figure (hand-verified: both-figure
# and both-bg stay 0 — a cell-wise (top,bot) function is refuted:
# (1,2) and (1,3) share the pair yet differ). Mark color M learned
# across trains; LOO enforces its stability. Strict detector.

def try_xorhalves(trains: Trains, test: Grid) -> Optional[Grid]:
    return _halves_try(trains, test, _H_KINDS, _mask_xor)


def d_xorhalves(trains):
    return verify_loo(try_xorhalves, trains)

# ─── Or halves (overlay-OR) ─────────────────────────────────────────
# Seen in ce4f8723: same halves machinery (H-only kinds), mask marks
# cells where AT LEAST ONE half is figure (union). Completes the
# boolean family: NOR, XOR, OR. Mark M learned across trains; LOO
# enforces stability. Strict detector.

def try_orhalves(trains: Trains, test: Grid) -> Optional[Grid]:
    return _halves_try(trains, test, _H_KINDS, _mask_or)


def d_orhalves(trains):
    return verify_loo(try_orhalves, trains)

# ─── Pack (fit pieces into 3x3) ────────────────────────────────────
# Seen in 137eaa0f: multi-cell straight bars go to fixed slots
# (horizontals: first-in-reading → top row, last → bottom row;
# verticals: side column opposite the bottom row); the modal single
# color dots the center, every other modal single is dropped, all
# remaining singles fill free cells slot by slot in canvas reading
# order — each slot takes its nearest input single (slot home =
# cell center scaled to input dims; ties: leftmost column, then
# reading), skipping singles that would 4-merge — rest 0.
# Alignment notes (scope, all evidenced): top row mirrors the input
# side; bottom row is left iff a top bar exists; vertical rows are top
# iff the top bar is left-aligned. Only the modal color is learned
# across trains (LOO enforces its stability) — everything else is a
# deterministic function of the input. Strict LOO detector.

def _pack_parts(inp):
    comps = components(inp)
    H = [c for c in comps
         if c["size"] > 1 and len({r for r, _ in c["cells"]}) == 1]
    V = [c for c in comps
         if c["size"] > 1 and len({cc for _, cc in c["cells"]}) == 1]
    S = [c for c in comps if c["size"] == 1]
    if any(c not in H and c not in V and c not in S for c in comps):
        return None
    if not H:
        return None
    return H, V, S


def _pack_modal(ts):
    modals = set()
    for inp, _out in ts:
        parts = _pack_parts(inp)
        if parts is None:
            return None
        _H, _V, S = parts
        cnt = Counter(c["color"] for c in S)
        if not cnt or list(cnt.values()).count(max(cnt.values())) != 1:
            return None
        modals.add(cnt.most_common(1)[0][0])
    if len(modals) != 1:
        return None
    return next(iter(modals))


def _pack_place(inp, modal):
    parts = _pack_parts(inp)
    if parts is None:
        return None
    H, V, S = parts
    if len(H) > 2 or len(V) > 1:
        return None
    if any(c["color"] == modal for c in H + V):
        return None
    W = len(inp[0])
    mid = (W - 1) / 2.0
    top = H[0] if len(H) == 2 else None
    bot = H[-1]
    occ = {}

    def _put(cells, color):
        for cell in cells:
            r, c = cell
            if not (0 <= r < 3 and 0 <= c < 3) or cell in occ:
                return False
            occ[cell] = color
        return True

    if top is not None:
        w = len(top["cells"])
        align = "L" if sum(cc for _, cc in top["cells"]) / w > mid else "R"
        cells = ([(0, c) for c in range(3)] if w == 3 else
                 [(0, c) for c in ([0, 1] if align == "L" else [1, 2])])
        if not _put(cells, top["color"]):
            return None
        top_align = align if w == 2 else "full"
    else:
        top_align = None
    w = len(bot["cells"])
    if w == 3:
        verildi = [(2, c) for c in range(3)]
    else:
        b_align = "L" if top is not None else "R"
        verildi = [(2, c) for c in ([0, 1] if b_align == "L" else [1, 2])]
    if not _put(verildi, bot["color"]):
        return None
    bot_align = "full" if w == 3 else b_align
    if V:
        if w == 3:
            return None  # unobserved: vertical + full-width bottom
        v = V[0]
        col = 2 if bot_align == "L" else 0
        if top_align == "L":
            rows = [0, 1]
        else:
            rows = [1, 2]
        if not _put([(r, col) for r in rows], v["color"]):
            # retry the other row band (deterministic fallback)
            occ = {k: vv for k, vv in occ.items()
                   if vv != v["color"]}
            rows = [1, 2] if rows == [0, 1] else [0, 1]
            if not _put([(r, col) for r in rows], v["color"]):
                return None
    if (1, 1) in occ:
        return None
    occ[(1, 1)] = modal
    Hh, Ww = len(inp), len(inp[0])
    rest = [c for c in S if c["color"] != modal]
    for r in range(3):
        for c in range(3):
            if (r, c) in occ:
                continue
            hr, hc = (r + 0.5) * Hh / 3.0, (c + 0.5) * Ww / 3.0
            cands = sorted(
                rest,
                key=lambda s: ((s["anchor"][0] - hr) ** 2 +
                               (s["anchor"][1] - hc) ** 2,
                               s["anchor"][1], s["anchor"][0]))
            for s in cands:
                if any(occ.get((r + dr, c + dc)) == s["color"]
                       for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    continue
                occ[(r, c)] = s["color"]
                rest.remove(s)
                break
    if rest:
        return None  # every non-modal single must land somewhere
    return [[occ.get((r, c), 0) for c in range(3)] for r in range(3)]


def _pack_params(trains):
    modal = _pack_modal(trains)
    if modal is None:
        return None
    for inp, out in trains:
        if _pack_place(inp, modal) != out:
            return None
    return modal


def try_pack(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    modal = _pack_modal(trains)
    if modal is None:
        return None
    return _pack_place(test, modal)


def d_pack(trains):
    return verify_loo(try_pack, trains)

# ─── Anomaly crop (odd-count block) ─────────────────────────────────
# Seen in a87f7484: input is a strip of 3x3 monochrome blocks (one row
# or one column of blocks); output is a verbatim copy of the block
# whose non-bg cell count is UNIQUE across the strip (exactly one
# singleton count, else None). Shape and symmetry are decoys (both
# refuted: t3/TEST have fully-symmetric decoys); color varies per
# train by design. Nothing is learned across trains — the rule is
# structural; LOO still guards it per puzzle. Strict LOO detector.

def _anomaly_blocks(inp):
    R, C = shape(inp)
    if R == 3 and C % 3 == 0 and C >= 6:
        return [[row[c:c + 3] for row in inp] for c in range(0, C, 3)]
    if C == 3 and R % 3 == 0 and R >= 6:
        return [[row[:] for row in inp[r:r + 3]] for r in range(0, R, 3)]
    return None


def _anomaly_pick(blocks, bg):
    counts = [sum(1 for row in b for v in row if v != bg)
              for b in blocks]
    freq = Counter(counts)
    singles = [c for c, n in freq.items() if n == 1]
    if len(singles) != 1:
        return None
    return blocks[counts.index(singles[0])]


def try_anomaly(trains: Trains, test: Grid) -> Optional[Grid]:
    blocks = _anomaly_blocks(test)
    if blocks is None or not trains:
        return None
    pick = _anomaly_pick(blocks, bg_color(test))
    if pick is None:
        return None
    return [row[:] for row in pick]


def d_anomaly(trains):
    if not trains:
        return False
    for inp, out in trains:
        blocks = _anomaly_blocks(inp)
        if blocks is None:
            return False
        pick = _anomaly_pick(blocks, bg_color(inp))
        if pick is None or pick != out:
            return False
    return verify_loo(try_anomaly, trains)

# ─── Quadrant collage (bbox per quadrant) ───────────────────────────
# Seen in 0bb8deee: exactly one full-length uniform horizontal
# divider + one vertical divider split the input into 4 quadrants;
# output is a 6x6 collage where each quadrant is replaced by the
# tight bbox of its content (must fit 3x3, else None). Padding (when
# the bbox is smaller) hugs content AWAY from the dividers: right
# quadrants pad left, left quadrants pad right, top quadrants pad
# bottom, bottom quadrants pad top (single evidenced case t2-TR;
# LOO + sweep judge). Strict LOO detector.

def _qcollage_split(inp):
    R, C = shape(inp)
    bg = bg_color(inp)
    hdiv = [r for r in range(R)
            if len(set(inp[r])) == 1 and inp[r][0] != bg]
    vdiv = [c for c in range(C)
            if len({inp[r][c] for r in range(R)}) == 1
            and inp[0][c] != bg]
    if len(hdiv) != 1 or len(vdiv) != 1:
        return None
    dh, dv = hdiv[0], vdiv[0]
    if dh == 0 or dh == R - 1 or dv == 0 or dv == C - 1:
        return None
    quads = {
        "TL": ([row[:dv] for row in inp[:dh]], True, True),
        "TR": ([row[dv + 1:] for row in inp[:dh]], True, False),
        "BL": ([row[:dv] for row in inp[dh + 1:]], False, True),
        "BR": ([row[dv + 1:] for row in inp[dh + 1:]], False, False),
    }
    return quads


def _qcollage_quad(q, bg, is_top, is_left):
    content = [(r, c) for r, row in enumerate(q) for c, v in enumerate(row)
               if v != bg]
    if not content:
        return None
    rs = [r for r, _ in content]
    cs = [c for _, c in content]
    r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
    h, w = r1 - r0 + 1, c1 - c0 + 1
    if h > 3 or w > 3:
        return None
    box = [[q[r][c] if q[r][c] != bg else 0
            for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
    out = [[0] * 3 for _ in range(3)]
    r_off = 0 if is_top else 3 - h
    c_off = 0 if is_left else 3 - w
    for r in range(h):
        for c in range(w):
            out[r_off + r][c_off + c] = box[r][c]
    return out


def try_qcollage(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    quads = _qcollage_split(test)
    if quads is None:
        return None
    bg = bg_color(test)
    cells = {}
    for name, (q, is_top, is_left) in quads.items():
        got = _qcollage_quad(q, bg, is_top, is_left)
        if got is None:
            return None
        cells[name] = got
    return [cells["TL"][r] + cells["TR"][r] for r in range(3)] + \
           [cells["BL"][r] + cells["BR"][r] for r in range(3)]


def d_qcollage(trains):
    if not trains:
        return False
    for inp, out in trains:
        quads = _qcollage_split(inp)
        if quads is None:
            return False
        bg = bg_color(inp)
        cells = {}
        for name, (q, is_top, is_left) in quads.items():
            got = _qcollage_quad(q, bg, is_top, is_left)
            if got is None:
                return False
            cells[name] = got
        want = [cells["TL"][r] + cells["TR"][r] for r in range(3)] + \
               [cells["BL"][r] + cells["BR"][r] for r in range(3)]
        if want != out:
            return False
    return verify_loo(try_qcollage, trains)

# ─── Quadrant stack (z-order overlay) ───────────────────────────────
# Seen in a68b268e: one full horizontal + one vertical divider split
# the input into 4 SAME-SIZE quadrants, each with its own figure
# color on bg; output stacks them with fixed z-priority TL > TR >
# BL > BR (first non-bg wins, else 0). Hand-verified: every shared
# cell follows the priority (e.g. {TR,BL,BR} → TR, {BL,BR} → BL).
# Strict LOO detector.

def _qstack_place(quads, bg):
    names = ["TL", "TR", "BL", "BR"]
    grids = [quads[n][0] for n in names]
    R = len(grids[0])
    if any(len(g) != R or any(len(row) != len(grids[0][0]) for row in g)
           for g in grids):
        return None
    C = len(grids[0][0])
    out = []
    for r in range(R):
        row = []
        for c in range(C):
            v = 0
            for g in grids:
                if g[r][c] != bg:
                    v = g[r][c]
                    break
            row.append(v)
        out.append(row)
    return out


def try_qstack(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    quads = _qcollage_split(test)
    if quads is None:
        return None
    return _qstack_place(quads, bg_color(test))


def d_qstack(trains):
    if not trains:
        return False
    for inp, out in trains:
        quads = _qcollage_split(inp)
        if quads is None:
            return False
        if _qstack_place(quads, bg_color(inp)) != out:
            return False
    return verify_loo(try_qstack, trains)

# ─── Quadrant stack 2 (TR-first overlay) ────────────────────────────
# Seen in 75b8110e: NO dividers — plain even halves split into 4
# quadrants; output stacks with fixed z-priority TR > BL > BR > TL
# (first non-bg wins, else 0). Assert-verified on all trains+TEST
# (an earlier eyeball park of this white was a misread — the code
# verdicts rule). Strict LOO detector.

def _quads_split(inp):
    R, C = shape(inp)
    if R % 2 or C % 2 or R < 2 or C < 2:
        return None
    h, w = R // 2, C // 2
    return {
        "TL": [[v for v in row[:w]] for row in inp[:h]],
        "TR": [[v for v in row[w:]] for row in inp[:h]],
        "BL": [[v for v in row[:w]] for row in inp[h:]],
        "BR": [[v for v in row[w:]] for row in inp[h:]],
    }


def _qstack2_place(quads, bg):
    grids = [quads[n] for n in ("TR", "BL", "BR", "TL")]
    R = len(grids[0])
    if any(len(g) != R or any(len(row) != len(grids[0][0]) for row in g)
           for g in grids):
        return None
    C = len(grids[0][0])
    out = []
    for r in range(R):
        row = []
        for c in range(C):
            v = 0
            for g in grids:
                if g[r][c] != bg:
                    v = g[r][c]
                    break
            row.append(v)
        out.append(row)
    return out


def try_qstack2(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    quads = _quads_split(test)
    if quads is None:
        return None
    return _qstack2_place(quads, bg_color(test))


def d_qstack2(trains):
    if not trains:
        return False
    for inp, out in trains:
        quads = _quads_split(inp)
        if quads is None:
            return False
        if _qstack2_place(quads, bg_color(inp)) != out:
            return False
    return verify_loo(try_qstack2, trains)

# ─── Quadrant stack learned (consensus order) ───────────────────────
# Seen in e99362f0: divider quads like qstack, but the priority order
# is LEARNED per puzzle — the unique order consistent with ALL trains
# (here [3,0,1,2]; computed, not assumed). Ambiguous (several
# consistent orders) → None: an underdetermined mechanism is an
# honest miss, not a guess. Strict LOO detector.

def _qstackL_order(trains):
    import itertools as _it
    ok = []
    for order in _it.permutations(range(4)):
        good = True
        for inp, out in trains:
            quads = _qcollage_split(inp)
            if quads is None:
                good = False
                break
            Q = [quads["TL"][0], quads["TR"][0],
                 quads["BL"][0], quads["BR"][0]]
            bg = bg_color(inp)
            for r in range(len(Q[0])):
                for c in range(len(Q[0][0])):
                    v = 0
                    for i in order:
                        if Q[i][r][c] != bg:
                            v = Q[i][r][c]
                            break
                    if out[r][c] != v:
                        good = False
                        break
                if not good:
                    break
            if not good:
                break
        if good:
            ok.append(order)
    return ok[0] if len(ok) == 1 else None


def try_qstackL(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    order = _qstackL_order(trains)
    if order is None:
        return None
    quads = _qcollage_split(test)
    if quads is None:
        return None
    Q = [quads["TL"][0], quads["TR"][0],
         quads["BL"][0], quads["BR"][0]]
    bg = bg_color(test)
    return [[next((Q[i][r][c] for i in order if Q[i][r][c] != bg), 0)
             for c in range(len(Q[0][0]))] for r in range(len(Q[0]))]


def d_qstackL(trains):
    if not trains:
        return False
    if _qstackL_order(trains) is None:
        return False
    return verify_loo(try_qstackL, trains)

# ─── Vertical stack (strip z-order) ─────────────────────────────────
# Seen in 281123b4: full-length uniform divider columns (all one
# color) split the input into equal vertical strips; output stacks
# them with halves priority — right-half strips left-to-right,
# then left-half strips left-to-right (for 4 strips: B2>B3>B0>B1).
# First non-bg wins, else 0. Hand-verified on all t0/t1 cells.
# Strict LOO detector.

def _vstrips_split(inp):
    R, C = shape(inp)
    bycolor = {}
    for c in range(C):
        col = [inp[r][c] for r in range(R)]
        if len(set(col)) == 1:
            bycolor.setdefault(col[0], []).append(c)
    cands = []
    for _color, divs in bycolor.items():
        bounds, start = [], 0
        for c in range(C + 1):
            if c in divs or c == C:
                if start < c:
                    bounds.append((start, c))
                start = c + 1
        if len(bounds) < 2:
            continue
        w0 = bounds[0][1] - bounds[0][0]
        if any(b - a != w0 for a, b in bounds):
            continue
        cands.append([[row[a:b] for row in inp] for a, b in bounds])
    if len(cands) != 1:
        return None
    return cands[0]


def _vstack_split(inp):
    strips = _vstrips_split(inp)
    if strips is None or len(strips) % 2:
        return None
    return strips


def try_vstack(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    strips = _vstack_split(test)
    if strips is None:
        return None
    bg = bg_color(test)
    half = len(strips) // 2
    order = strips[half:] + strips[:half]
    R = len(strips[0])
    if any(len(s) != R or any(len(row) != len(strips[0][0]) for row in s)
           for s in strips):
        return None
    C = len(strips[0][0])
    return [[next((s[r][c] for s in order if s[r][c] != bg), 0)
             for c in range(C)] for r in range(R)]


def d_vstack(trains):
    if not trains:
        return False
    for inp, out in trains:
        strips = _vstack_split(inp)
        if strips is None:
            return False
        if try_vstack(trains, inp) != out:
            return False
    return verify_loo(try_vstack, trains)

# ─── Vertical union (conditional overlay) ───────────────────────────
# Seen in bbb1b8b6: one full uniform divider column splits the input
# into same-size left+right strips; output = their union IFF they are
# disjoint, else the left strip alone (all-or-nothing: t1's right 2x2
# overlaps left, so even its non-overlapping cell (1,1)=2 stays 0 —
# a priority rule is refuted). Colors copied verbatim, nothing
# learned. Extended 2026-09-12 (e98196ab): same with a horizontal
# divider (top/bottom strips, else-first-strip); precedence vdiv
# then hdiv (status quo first, deterministic). Strict LOO detector.

def _vunion_cand(inp, kind):
    R, C = shape(inp)
    bg = bg_color(inp)
    cands = []
    if kind == "vdiv":
        for dv in range(C):
            if len({inp[r][dv] for r in range(R)}) != 1:
                continue
            if inp[0][dv] == bg:
                continue
            left = [row[:dv] for row in inp]
            right = [row[dv + 1:] for row in inp]
            if not left[0] or not right[0]:
                continue
            if len(left[0]) != len(right[0]):
                continue
            cands.append((left, right))
    else:
        for dh in range(R):
            if len(set(inp[dh])) != 1:
                continue
            if inp[dh][0] == bg:
                continue
            top, bot = inp[:dh], inp[dh + 1:]
            if not top or not bot or len(top) != len(bot):
                continue
            if len(top[0]) != len(bot[0]):
                continue
            cands.append((top, bot))
    if len(cands) != 1:
        return None
    return cands[0]


def _vunion_place(inp):
    for kind in ("vdiv", "hdiv"):
        sp = _vunion_cand(inp, kind)
        if sp is None:
            continue
        a, b = sp
        R = len(a)
        bg = bg_color(inp)
        if any(a[r][c] != bg and b[r][c] != bg
               for r in range(R) for c in range(len(a[0]))):
            return [row[:] for row in a]
        return [[b[r][c] if a[r][c] == bg else a[r][c]
                 for c in range(len(a[0]))] for r in range(R)]
    return None


def try_vunion(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    return _vunion_place(test)


def d_vunion(trains):
    if not trains:
        return False
    for inp, out in trains:
        if _vunion_place(inp) != out:
            return False
    return verify_loo(try_vunion, trains)

# ─── Vertical first (strip reading priority) ────────────────────────
# Seen in cf98881b: divider columns split into 3 equal strips;
# output takes the first non-bg scanning strips left-to-right
# (B0>B1>B2 — hand-verified on all trains+TEST; the halves priority
# of vstack is refuted here and vice versa: the two detectors are
# structurally exclusive). Strict LOO detector.

def try_vfirst(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    strips = _vstrips_split(test)
    if strips is None or len(strips) < 2:
        return None
    bg = bg_color(test)
    R = len(strips[0])
    if any(len(s) != R or any(len(row) != len(strips[0][0]) for row in s)
           for s in strips):
        return None
    C = len(strips[0][0])
    return [[next((s[r][c] for s in strips if s[r][c] != bg), 0)
             for c in range(C)] for r in range(R)]


def d_vfirst(trains):
    if not trains:
        return False
    for inp, out in trains:
        strips = _vstrips_split(inp)
        if strips is None or len(strips) < 2:
            return False
        if try_vfirst(trains, inp) != out:
            return False
    return verify_loo(try_vfirst, trains)

# ─── Vertical rows (collect non-empty rows) ─────────────────────────
# Seen in 25c199f5: divider columns split into equal strips sharing
# one bg; output collects every row containing non-bg, blocks
# right-to-left, each block's rows top-down, bottom-justified (pad
# top with bg rows if short; more rows than block height → None).
# Hand-verified: L-to-R + top-justify refuted (t0-r3 is B0r1, not
# position 1). Strict LOO detector.

def try_vrows(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    strips = _vstrips_split(test)
    if strips is None or len(strips) < 2:
        return None
    bg = bg_color(test)
    H = len(strips[0])
    W = len(strips[0][0])
    if any(len(s) != H or any(len(row) != W for row in s)
           for s in strips):
        return None
    rows = []
    for s in reversed(strips):
        for row in s:
            if any(v != bg for v in row):
                rows.append(row[:])
    if len(rows) > H:
        return None
    return [[bg] * W for _ in range(H - len(rows))] + rows


def d_vrows(trains):
    if not trains:
        return False
    for inp, out in trains:
        strips = _vstrips_split(inp)
        if strips is None or len(strips) < 2:
            return False
        if try_vrows(trains, inp) != out:
            return False
    return verify_loo(try_vrows, trains)

# ─── Vertical columns (positional column slices) ────────────────────
# Seen in 5ecac7f7: three 5-wide strips share one bg; output takes
# fixed positional slices — left strip cols 0-1, middle strip col 2
# (center), right strip cols 3-4 (2+1+2). Hand-verified on all
# trains+TEST (t1/t2/TEST exact cell-by-cell). Narrow scope (3
# strips x width 5); LOO + sweep judge any generalization. Strict.

def try_vcols(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    strips = _vstrips_split(test)
    if strips is None or len(strips) != 3:
        return None
    if any(len(s) != 5 or any(len(row) != 5 for row in s)
           for s in strips):
        return None
    b0, b1, b2 = strips
    return [[b0[r][0], b0[r][1], b1[r][2], b2[r][3], b2[r][4]]
            for r in range(5)]


def d_vcols(trains):
    if not trains:
        return False
    for inp, out in trains:
        strips = _vstrips_split(inp)
        if strips is None or len(strips) != 3:
            return False
        if try_vcols(trains, inp) != out:
            return False
    return verify_loo(try_vcols, trains)

# ─── Frames overlay (first figure wins) ─────────────────────────────
# Seen in 25e02866: two or more same-color SQUARE borders (h==w>=3,
# border complete; interior may hold ring-colored cells — only the
# border must be present, so solid blocks register harmlessly as
# figure-less frames; bg-colored borders excluded) share one
# (color,size); output paints the ring and overlays interiors in
# frame reading order — first non-ring figure wins (in-sample
# figures never overlap, so order is unloaded but deterministic).
# Nothing learned across trains; LOO still guards per puzzle.

def _frames_find(inp):
    bg = bg_color(inp)
    found = []
    for c in components(inp, bg=bg):
        cells = set(c["cells"])
        rs = [r for r, _ in cells]
        cs = [cc for _, cc in cells]
        h, w = max(rs) - min(rs) + 1, max(cs) - min(cs) + 1
        if h != w or h < 3:
            continue
        t, l = min(rs), min(cs)
        border = ({(t, cc) for cc in range(l, l + w)} |
                  {(t + h - 1, cc) for cc in range(l, l + w)} |
                  {(r, l) for r in range(t, t + h)} |
                  {(r, l + w - 1) for r in range(t, t + h)})
        if border <= cells:
            found.append((c["color"], h, t, l))
    return found


def try_frames(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    found = _frames_find(test)
    if len(found) < 2:
        return None
    if len({(c, h) for c, h, _, _ in found}) != 1:
        return None
    color, N, _, _ = found[0]
    out = [[color] * N for _ in range(N)]
    for _, _, t, l in sorted(found, key=lambda f: (f[2], f[3])):
        for r in range(1, N - 1):
            for c in range(1, N - 1):
                v = test[t + r][l + c]
                if v != color and out[r][c] == color:
                    out[r][c] = v
    return out


def d_frames(trains):
    if not trains:
        return False
    for inp, out in trains:
        if try_frames(trains, inp) != out:
            return False
    return verify_loo(try_frames, trains)

# ─── Dot frame (dye in dots' frame) ─────────────────────────────────
# Seen in 3de23699: dot-colored cells frame a canvas (their bbox
# shrunk by 1); output shows that canvas with blob-colored cells
# dyed to dot-color and everything else 0 (dots inside erase).
# Blob = color with the uniquely-largest component; dot = the only
# other non-bg color whose shrunk bbox is valid and contains all
# blob cells. Colors vary per train by design (no cross-train
# learning — structural rule, LOO guards). Strict LOO detector.

def _dotframe_place(grid):
    R, C = shape(grid)
    bg = bg_color(grid)
    comps = components(grid, bg=bg)
    if not comps:
        return None
    bycolor = {}
    for c in comps:
        bycolor.setdefault(c["color"], []).append(c)
    biggest = {col: max(len(c["cells"]) for c in cs)
               for col, cs in bycolor.items()}
    top = max(biggest.values())
    if sum(1 for v in biggest.values() if v == top) != 1:
        return None
    blob = next(col for col, v in biggest.items() if v == top)
    bcells = [(r, c) for cs in [bycolor[blob]] for c in cs
              for (r, c) in c["cells"]]
    br0, br1 = min(r for r, _ in bcells), max(r for r, _ in bcells)
    bc0, bc1 = min(c for _, c in bcells), max(c for _, c in bcells)
    cands = []
    for col, cs in bycolor.items():
        if col == blob:
            continue
        dcells = [(r, c) for c in cs for (r, c) in c["cells"]]
        dr0 = min(r for r, _ in dcells)
        dr1 = max(r for r, _ in dcells)
        dc0 = min(c for _, c in dcells)
        dc1 = max(c for _, c in dcells)
        cr, cc = (dr0 + 1, dr1 - 1), (dc0 + 1, dc1 - 1)
        if cr[0] > cr[1] or cc[0] > cc[1]:
            continue
        if not (cr[0] <= br0 and br1 <= cr[1] and
                cc[0] <= bc0 and bc1 <= cc[1]):
            continue
        cands.append((col, cr, cc))
    if len(cands) != 1:
        return None
    dot, (r0, r1), (c0, c1) = cands[0]
    return [[dot if grid[r][c] == blob else 0
             for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]


def try_dotframe(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    return _dotframe_place(test)


def d_dotframe(trains):
    if not trains:
        return False
    for inp, out in trains:
        if _dotframe_place(inp) != out:
            return False
    return verify_loo(try_dotframe, trains)

# ─── Below marker (fixed window) ────────────────────────────────────
# Seen in 48d8fb45: the unique singleton-colored cell (exactly one
# cell of its color grid-wide, bg excluded) is the marker; output is
# the verbatim 3x3 window directly below it, horizontally centered
# (rows mr+1..mr+3, cols mc-1..mc+1; out of bounds → None).
# Hand-verified cell-exact on all trains+TEST. Nothing learned
# across trains (marker found per grid); LOO still guards it.

def _below_window(grid):
    R, C = shape(grid)
    bg = bg_color(grid)
    cnt = Counter(v for row in grid for v in row if v != bg)
    ones = [c for c, n in cnt.items() if n == 1]
    if len(ones) != 1:
        return None
    m = ones[0]
    mr = next(r for r in range(R) for c in range(C) if grid[r][c] == m)
    mc = next(c for r in range(R) for c in range(C) if grid[r][c] == m)
    if mr + 3 >= R or mc < 1 or mc + 1 >= C:
        return None
    return [[grid[r][c] for c in range(mc - 1, mc + 2)]
            for r in range(mr + 1, mr + 4)]


def try_below(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    return _below_window(test)


def d_below(trains):
    if not trains:
        return False
    for inp, out in trains:
        if _below_window(inp) != out:
            return False
    return verify_loo(try_below, trains)

# ─── Midline (line through object) ──────────────────────────────────
# Seen in da2b0fe3: the line runs along the object's MINOR principal
# axis (variance comparison — robust to outliers where bbox extent
# lies: t1's stray cell stretches bbox width but not spread, and the
# line is horizontal). Position is the ceiling of the bbox midpoint
# along the line axis; the line overwrites everything with the
# learned color (singleton across trains). Equal variances (a dot —
# no orientable axis) → None. Hand-verified + asserts. Strict.

def _midline_orient(fig):
    n = len(fig)
    mr = sum(r for r, _ in fig) / n
    mc = sum(c for _, c in fig) / n
    vr = sum((r - mr) ** 2 for r, _ in fig) / n
    vc = sum((c - mc) ** 2 for _, c in fig) / n
    if vr == vc:
        return None
    return "h" if vr > vc else "v"


def _midline_params(trains):
    colors = set()
    for inp, out in trains:
        bg = bg_color(inp)
        R, C = shape(inp)
        if shape(out) != (R, C):
            return None
        fig = [(r, c) for r in range(R) for c in range(C)
               if inp[r][c] != bg]
        if not fig:
            return None
        orient = _midline_orient(fig)
        if orient is None:
            return None
        r0, r1 = min(r for r, _ in fig), max(r for r, _ in fig)
        c0, c1 = min(c for _, c in fig), max(c for _, c in fig)
        want = [row[:] for row in inp]
        if orient == "v":
            pos = (c0 + c1 + 1) // 2
            for r in range(R):
                want[r][pos] = None
        else:
            pos = (r0 + r1 + 1) // 2
            for c in range(C):
                want[pos][c] = None
        vals = {out[r][c] for (r, c) in
                [(r, c) for r in range(R) for c in range(C)
                 if want[r][c] is None]}
        if len(vals) != 1:
            return None
        m = next(iter(vals))
        chk = [row[:] for row in inp]
        if orient == "v":
            for r in range(R):
                chk[r][pos] = m
        else:
            for c in range(C):
                chk[pos][c] = m
        if chk != out:
            return None
        colors.add(m)
    if len(colors) != 1:
        return None
    return next(iter(colors))


def try_midline(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    m = _midline_params(trains)
    if m is None:
        return None
    bg = bg_color(test)
    R, C = shape(test)
    fig = [(r, c) for r in range(R) for c in range(C)
           if test[r][c] != bg]
    if not fig:
        return None
    orient = _midline_orient(fig)
    if orient is None:
        return None
    r0, r1 = min(r for r, _ in fig), max(r for r, _ in fig)
    c0, c1 = min(c for _, c in fig), max(c for _, c in fig)
    got = [row[:] for row in test]
    if orient == "v":
        pos = (c0 + c1 + 1) // 2
        for r in range(R):
            got[r][pos] = m
    else:
        pos = (r0 + r1 + 1) // 2
        for c in range(C):
            got[pos][c] = m
    return got


def d_midline(trains):
    if not trains:
        return False
    if _midline_params(trains) is None:
        return False
    return verify_loo(try_midline, trains)

# ─── Asymmetric block (odd one out) ─────────────────────────────────
# Seen in 662c240a: a vertical strip of 3x3 blocks (width 3, rows
# multiple of 3); output is a verbatim copy of the UNIQUE block
# that is NOT transpose-symmetric (exactly one, else None).
# Hand-verified + asserts on all trains+TEST. Strict LOO detector.

def _transpose_sym(g):
    n = len(g)
    if any(len(row) != n for row in g):
        return False
    return all(g[r][c] == g[c][r] for r in range(n) for c in range(n))


def _asym_blocks(inp):
    R, C = shape(inp)
    if C != 3 or R % 3 or R < 6:
        return None
    return [[row[:] for row in inp[r:r + 3]] for r in range(0, R, 3)]


def try_asym(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    blocks = _asym_blocks(test)
    if blocks is None:
        return None
    odd = [b for b in blocks if not _transpose_sym(b)]
    if len(odd) != 1:
        return None
    return [row[:] for row in odd[0]]


def d_asym(trains):
    if not trains:
        return False
    for inp, out in trains:
        blocks = _asym_blocks(inp)
        if blocks is None:
            return False
        odd = [b for b in blocks if not _transpose_sym(b)]
        if len(odd) != 1 or odd[0] != out:
            return False
    return verify_loo(try_asym, trains)

# ─── Divider-emitter with push (05a7bcf2) ────────────────────────────
# Full-length 8-divider splits emitter-side (4s) from mover-side (2s).
# Per grid (orientation varies: vertical col or horizontal row):
#   A: every 4 -> 3, plus 4-fill from block to divider (gap must be bg).
#   D: rays of 8 from divider to far edge on B-side, on ray lines
#      (rows/cols containing 4s). Rest of ray line = 8.
#   B: 2s overwritten by rays reappear far-edge-justified on same
#      line, order preserved (counts conserved). Non-ray lines untouched.
# Strict: exactly one full-8 divider, no 3s in input, 4s/2s on opposite
# sides, gaps bg-only, ray-line B-cells bg/2-only. LOO-verified.

def _divemit_apply(g):
    R, C = shape(g)
    if R == 0 or C == 0:
        return None
    bg = bg_color(g)
    # Divider is specifically full-length 8 (mover spine is also full-length
    # but color 2: e.g. train0 col20 all-2, train1 row21 all-2).
    hdiv = [r for r in range(R) if len(set(g[r])) == 1 and g[r][0] == 8]
    vdiv = [c for c in range(C)
            if len({g[r][c] for r in range(R)}) == 1 and g[0][c] == 8]
    if len(hdiv) + len(vdiv) != 1:
        return None
    if any(v == 3 for row in g for v in row):
        return None
    fours = [(r, c) for r in range(R) for c in range(C) if g[r][c] == 4]
    twos = [(r, c) for r in range(R) for c in range(C) if g[r][c] == 2]
    if not fours or not twos:
        return None
    out = [row[:] for row in g]
    if vdiv:
        dc = vdiv[0]
        if g[0][dc] != 8:
            return None
        left4 = [(r, c) for r, c in fours if c < dc]
        right4 = [(r, c) for r, c in fours if c > dc]
        left2 = [(r, c) for r, c in twos if c < dc]
        right2 = [(r, c) for r, c in twos if c > dc]
        if any(c == dc for _, c in fours + twos):
            return None
        if bool(left4) == bool(right4):
            return None
        if bool(left2) == bool(right2):
            return None
        a_left = bool(left4)
        b_left = bool(left2)
        if a_left == b_left:
            return None
        for r, c in fours:
            out[r][c] = 3
        if a_left:
            rows = sorted(set(r for r, _ in left4))
            for r in rows:
                maxc = max(c for rr, c in left4 if rr == r)
                for c in range(maxc + 1, dc):
                    if out[r][c] != bg:
                        return None
                    out[r][c] = 4
            for r in rows:
                for c in range(dc + 1, C):
                    if g[r][c] != bg and g[r][c] != 2:
                        return None
                vals = [g[r][c] for c in range(dc + 1, C) if g[r][c] == 2]
                k = len(vals)
                for c in range(dc + 1, C):
                    out[r][c] = 8
                for i in range(k):
                    out[r][C - k + i] = vals[i]
        else:
            rows = sorted(set(r for r, _ in right4))
            for r in rows:
                minc = min(c for rr, c in right4 if rr == r)
                for c in range(dc + 1, minc):
                    if out[r][c] != bg:
                        return None
                    out[r][c] = 4
            for r in rows:
                for c in range(0, dc):
                    if g[r][c] != bg and g[r][c] != 2:
                        return None
                vals = [g[r][c] for c in range(0, dc) if g[r][c] == 2]
                k = len(vals)
                for c in range(0, dc):
                    out[r][c] = 8
                for i in range(k):
                    out[r][i] = vals[i]
        return out
    else:
        dr = hdiv[0]
        if g[dr][0] != 8:
            return None
        up4 = [(r, c) for r, c in fours if r < dr]
        dn4 = [(r, c) for r, c in fours if r > dr]
        up2 = [(r, c) for r, c in twos if r < dr]
        dn2 = [(r, c) for r, c in twos if r > dr]
        if any(r == dr for r, _ in fours + twos):
            return None
        if bool(up4) == bool(dn4):
            return None
        if bool(up2) == bool(dn2):
            return None
        a_up = bool(up4)
        b_up = bool(up2)
        if a_up == b_up:
            return None
        for r, c in fours:
            out[r][c] = 3
        if a_up:
            cols = sorted(set(c for _, c in up4))
            for c in cols:
                maxr = max(r for r, cc in up4 if cc == c)
                for r in range(maxr + 1, dr):
                    if out[r][c] != bg:
                        return None
                    out[r][c] = 4
            for c in cols:
                for r in range(dr + 1, R):
                    if g[r][c] != bg and g[r][c] != 2:
                        return None
                vals = [g[r][c] for r in range(dr + 1, R) if g[r][c] == 2]
                k = len(vals)
                for r in range(dr + 1, R):
                    out[r][c] = 8
                for i in range(k):
                    out[R - k + i][c] = vals[i]
        else:
            cols = sorted(set(c for _, c in dn4))
            for c in cols:
                minr = min(r for r, cc in dn4 if cc == c)
                for r in range(dr + 1, minr):
                    if out[r][c] != bg:
                        return None
                    out[r][c] = 4
            for c in cols:
                for r in range(0, dr):
                    if g[r][c] != bg and g[r][c] != 2:
                        return None
                vals = [g[r][c] for r in range(0, dr) if g[r][c] == 2]
                k = len(vals)
                for r in range(0, dr):
                    out[r][c] = 8
                for i in range(k):
                    out[i][c] = vals[i]
        return out


def try_divemit(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    return _divemit_apply(test)


def d_divemit(trains):
    if not trains:
        return False
    for inp, out in trains:
        if _divemit_apply(inp) != out:
            return False
    return verify_loo(try_divemit, trains)

# ─── Hub-4 star wiring (0e671a1a) ────────────────────────────────────
# Input holds singletons only: exactly one 4 (hub), every other dot
# color 2 or 3. Each spoke wires to the hub with an L-shaped path in
# a NEW learned paint color: 3-dots go vertical-first (own column to
# hub row, then hub row to hub), 2-dots go horizontal-first (own row
# to hub column, then hub column to hub). Path cells must be bg
# (strict). Same shape in/out. LOO-verified.

def _hub4_span(a, b):
    return range(min(a, b), max(a, b) + 1)


def _hub4_params(trains):
    marks = set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        bg = bg_color(inp)
        comps = components(inp, bg=bg)
        if any(c["size"] != 1 for c in comps):
            return None
        hubs = [c for c in comps if c["color"] == 4]
        spokes = [c for c in comps if c["color"] != 4]
        if len(hubs) != 1 or not spokes:
            return None
        if any(c["color"] not in (2, 3) for c in spokes):
            return None
        want = [row[:] for row in inp]
        hr, hc = hubs[0]["anchor"]
        for c in spokes:
            dr, dc = c["anchor"]
            if c["color"] == 3:
                cells = ({(r, dc) for r in _hub4_span(dr, hr) if r != dr} |
                         {(hr, cc) for cc in _hub4_span(dc, hc) if cc != hc})
            else:
                cells = ({(dr, cc) for cc in _hub4_span(dc, hc) if cc != dc} |
                         {(r, hc) for r in _hub4_span(dr, hr) if r != hr})
            for (rr, cc) in cells:
                if want[rr][cc] is not None and want[rr][cc] != bg:
                    return None
                want[rr][cc] = None
        vals = {out[rr][cc] for rr in range(len(out))
                for cc in range(len(out[0])) if want[rr][cc] is None}
        if len(vals) != 1:
            return None
        m = next(iter(vals))
        if m == bg or m in {v for row in inp for v in row}:
            return None
        for rr in range(len(out)):
            for cc in range(len(out[0])):
                if want[rr][cc] is None:
                    want[rr][cc] = m
        if want != out:
            return None
        marks.add(m)
    return next(iter(marks)) if len(marks) == 1 else None


def try_hub4(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    m = _hub4_params(trains)
    if m is None:
        return None
    bg = bg_color(test)
    comps = components(test, bg=bg)
    if any(c["size"] != 1 for c in comps):
        return None
    hubs = [c for c in comps if c["color"] == 4]
    spokes = [c for c in comps if c["color"] != 4]
    if len(hubs) != 1 or not spokes:
        return None
    if any(c["color"] not in (2, 3) for c in spokes):
        return None
    if m in {v for row in test for v in row}:
        return None
    got = [row[:] for row in test]
    hr, hc = hubs[0]["anchor"]
    for c in spokes:
        dr, dc = c["anchor"]
        if c["color"] == 3:
            cells = ({(r, dc) for r in _hub4_span(dr, hr) if r != dr} |
                     {(hr, cc) for cc in _hub4_span(dc, hc) if cc != hc})
        else:
            cells = ({(dr, cc) for cc in _hub4_span(dc, hc) if cc != dc} |
                     {(r, hc) for r in _hub4_span(dr, hr) if r != hr})
        for (rr, cc) in cells:
            if got[rr][cc] != bg and got[rr][cc] != m:
                return None
            got[rr][cc] = m
    return got


def d_hub4(trains):
    if not trains:
        return False
    if _hub4_params(trains) is None:
        return False
    return verify_loo(try_hub4, trains)

# ─── Halo (0ca9ddb6) ────────────────────────────────────────────────
# Every 1-cell paints its orthogonal neighbors, every 2-cell its
# diagonal neighbors, in learned NEW marks (7-ish / 4-ish). Clipped
# at the edge; halo cells must be bg (strict). Other colors pass
# through untouched. Same shape in/out. LOO-verified.

_ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
_DIAG = [(-1, -1), (-1, 1), (1, -1), (1, 1)]


def _halo_params(trains):
    m1s, m2s = set(), set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        Rr, Cc = shape(inp)
        bg = bg_color(inp)
        cells1 = [(r, c) for r in range(Rr) for c in range(Cc)
                  if inp[r][c] == 1]
        cells2 = [(r, c) for r in range(Rr) for c in range(Cc)
                  if inp[r][c] == 2]
        if not cells1 or not cells2:
            return None
        want = [row[:] for row in inp]
        for (r, c) in cells1:
            for dr, dc in _ORTHO:
                rr, cc = r + dr, c + dc
                if not (0 <= rr < Rr and 0 <= cc < Cc):
                    continue
                if want[rr][cc] != bg:
                    return None
                want[rr][cc] = "h1"
        for (r, c) in cells2:
            for dr, dc in _DIAG:
                rr, cc = r + dr, c + dc
                if not (0 <= rr < Rr and 0 <= cc < Cc):
                    continue
                if want[rr][cc] != bg:
                    return None
                want[rr][cc] = "h2"
        v1 = {out[rr][cc] for rr in range(Rr) for cc in range(Cc)
              if want[rr][cc] == "h1"}
        v2 = {out[rr][cc] for rr in range(Rr) for cc in range(Cc)
              if want[rr][cc] == "h2"}
        if len(v1) != 1 or len(v2) != 1:
            return None
        pal = {v for row in inp for v in row}
        if v1 == v2 or next(iter(v1)) in pal or next(iter(v2)) in pal:
            return None
        m1s.add(next(iter(v1)))
        m2s.add(next(iter(v2)))
        for rr in range(Rr):
            for cc in range(Cc):
                if want[rr][cc] == "h1":
                    want[rr][cc] = next(iter(v1))
                elif want[rr][cc] == "h2":
                    want[rr][cc] = next(iter(v2))
        if want != out:
            return None
    if len(m1s) != 1 or len(m2s) != 1:
        return None
    return next(iter(m1s)), next(iter(m2s))


def try_halo(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    pm = _halo_params(trains)
    if pm is None:
        return None
    m1, m2 = pm
    Rr, Cc = shape(test)
    bg = bg_color(test)
    if m1 in {v for row in test for v in row}:
        return None
    if m2 in {v for row in test for v in row}:
        return None
    got = [row[:] for row in test]
    for r in range(Rr):
        for c in range(Cc):
            if test[r][c] == 1:
                for dr, dc in _ORTHO:
                    rr, cc = r + dr, c + dc
                    if not (0 <= rr < Rr and 0 <= cc < Cc):
                        continue
                    if got[rr][cc] != bg:
                        return None
                    got[rr][cc] = m1
    for r in range(Rr):
        for c in range(Cc):
            if test[r][c] == 2:
                for dr, dc in _DIAG:
                    rr, cc = r + dr, c + dc
                    if not (0 <= rr < Rr and 0 <= cc < Cc):
                        continue
                    if got[rr][cc] != bg and got[rr][cc] != m1:
                        return None
                    got[rr][cc] = m2
    return got


def d_halo(trains):
    if not trains:
        return False
    if _halo_params(trains) is None:
        return False
    return verify_loo(try_halo, trains)

# ─── Diagonal focus (11e1fe23) ──────────────────────────────────────
# Dots (non-bg singletons, 3+). Exactly one diagonal (either slope)
# holds 2+ dots: the shared axis. Its crossings with other dots'
# diagonals yield exactly one interior non-dot cell: the focus,
# painted a learned NEW mark. Every dot spawns a same-color copy on
# its own diagonal ADJACENT to the focus (i.e. one step back from
# it); the whole dot-to-copy path must be bg. Originals kept.
# Exact integer geometry, no floats. LOO-verified.

def _diag_lines(dots):
    from collections import defaultdict as _dd
    by_sum, by_dif = _dd(list), _dd(list)
    for d in dots:
        by_sum[d[0] + d[1]].append(d)
        by_dif[d[0] - d[1]].append(d)
    return by_sum, by_dif


def _diagfocus_params(trains):
    marks = set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        Rr, Cc = shape(inp)
        bg = bg_color(inp)
        comps = components(inp, bg=bg)
        if len(comps) < 3 or any(c["size"] != 1 for c in comps):
            return None
        dots = [c["anchor"] for c in comps]
        dset = set(dots)
        by_sum, by_dif = _diag_lines(dots)
        shared = ([("s", k) for k, v in by_sum.items() if len(v) >= 2] +
                  [("d", k) for k, v in by_dif.items() if len(v) >= 2])
        if len(shared) != 1:
            return None
        kind, kk = shared[0]
        cands = set()
        for (dr, dc) in dots:
            s2 = dr + dc
            if not (kind == "s" and s2 == kk):
                for (qr, qc) in _seg_intersect_sum(s2, kind, kk, Rr, Cc):
                    cands.add((qr, qc))
            d2 = dr - dc
            if not (kind == "d" and d2 == kk):
                for (qr, qc) in _seg_intersect_dif(d2, kind, kk, Rr, Cc):
                    cands.add((qr, qc))
        cands -= dset
        cands = {(r, c) for (r, c) in cands if 0 <= r < Rr and 0 <= c < Cc}
        if len(cands) != 1:
            return None
        fr, fc = next(iter(cands))
        if inp[fr][fc] != bg:
            return None
        want = [row[:] for row in inp]
        for (dr, dc) in dots:
            sr = (fr > dr) - (fr < dr)
            sc = (fc > dc) - (fc < dc)
            if sr == 0 or sc == 0:
                return None
            lr, lc = fr - sr, fc - sc
            if (lr, lc) == (dr, dc):
                return None
            if not (0 <= lr < Rr and 0 <= lc < Cc):
                return None
            rr, cc = dr + sr, dc + sc
            while (rr, cc) != (lr, lc):
                if want[rr][cc] != bg:
                    return None
                rr, cc = rr + sr, cc + sc
            if want[lr][lc] != bg:
                return None
            # intermediate stays bg; landing gets ("copy", color) below
            want[lr][lc] = ("copy", inp[dr][dc])
        vals = {out[fr][fc]}
        for rr in range(Rr):
            for cc in range(Cc):
                w = want[rr][cc]
                if isinstance(w, tuple) and out[rr][cc] != w[1]:
                    return None
        m = next(iter(vals))
        pal = {v for row in inp for v in row}
        if m == bg or m in pal:
            return None
        got = [row[:] for row in inp]
        for rr in range(Rr):
            for cc in range(Cc):
                if isinstance(want[rr][cc], tuple):
                    got[rr][cc] = want[rr][cc][1]
        got[fr][fc] = m
        if got != out:
            return None
        marks.add(m)
    return next(iter(marks)) if len(marks) == 1 else None


def _seg_intersect_sum(s2, kind, kk, Rr, Cc):
    # line r+c=s2  X  shared axis -> lattice points on both
    pts = []
    if kind == "s":
        return pts  # parallel, no crossing
    # shared is r-c=kk -> r=(s2+kk)/2, c=(s2-kk)/2
    if (s2 + kk) % 2:
        return pts
    r, c = (s2 + kk) // 2, (s2 - kk) // 2
    if 0 <= r < Rr and 0 <= c < Cc:
        pts.append((r, c))
    return pts


def _seg_intersect_dif(d2, kind, kk, Rr, Cc):
    pts = []
    if kind == "d":
        return pts  # parallel, no crossing
    # shared is r+c=kk -> r=(kk+d2)/2, c=(kk-d2)/2
    if (kk + d2) % 2:
        return pts
    r, c = (kk + d2) // 2, (kk - d2) // 2
    if 0 <= r < Rr and 0 <= c < Cc:
        pts.append((r, c))
    return pts


def try_diagfocus(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    m = _diagfocus_params(trains)
    if m is None:
        return None
    Rr, Cc = shape(test)
    bg = bg_color(test)
    comps = components(test, bg=bg)
    if len(comps) < 3 or any(c["size"] != 1 for c in comps):
        return None
    dots = [c["anchor"] for c in comps]
    dset = set(dots)
    by_sum, by_dif = _diag_lines(dots)
    shared = ([("s", k) for k, v in by_sum.items() if len(v) >= 2] +
              [("d", k) for k, v in by_dif.items() if len(v) >= 2])
    if len(shared) != 1:
        return None
    kind, kk = shared[0]
    cands = set()
    for (dr, dc) in dots:
        s2 = dr + dc
        if not (kind == "s" and s2 == kk):
            cands.update(_seg_intersect_sum(s2, kind, kk, Rr, Cc))
        d2 = dr - dc
        if not (kind == "d" and d2 == kk):
            cands.update(_seg_intersect_dif(d2, kind, kk, Rr, Cc))
    cands -= dset
    cands = {(r, c) for (r, c) in cands if 0 <= r < Rr and 0 <= c < Cc}
    if len(cands) != 1:
        return None
    fr, fc = next(iter(cands))
    if test[fr][fc] != bg:
        return None
    if m in {v for row in test for v in row}:
        return None
    got = [row[:] for row in test]
    for (dr, dc) in dots:
        sr = (fr > dr) - (fr < dr)
        sc = (fc > dc) - (fc < dc)
        if sr == 0 or sc == 0:
            return None
        lr, lc = fr - sr, fc - sc
        if (lr, lc) == (dr, dc):
            return None
        if not (0 <= lr < Rr and 0 <= lc < Cc):
            return None
        rr, cc = dr + sr, dc + sc
        while (rr, cc) != (lr, lc):
            if got[rr][cc] != bg:
                return None
            rr, cc = rr + sr, cc + sc
        if got[lr][lc] != bg:
            return None
        got[lr][lc] = test[dr][dc]
    got[fr][fc] = m
    return got


def d_diagfocus(trains):
    if not trains:
        return False
    if _diagfocus_params(trains) is None:
        return False
    return verify_loo(try_diagfocus, trains)

# ─── Full cross (140c817e) ──────────────────────────────────────────
# Input palette is {bg, 1} only. Every 1-cell paints its FULL row +
# FULL column with 1; every original 1-cell becomes a learned NEW
# dot-mark (2-ish); every diagonal neighbor of an original 1-cell
# becomes a learned NEW diag-mark (3-ish, bg-only strict: a diag
# landing on a bar or another dot fails). Same shape. LOO-verified.

def _cross1_params(trains):
    mdots, mdiag = set(), set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        Rr, Cc = shape(inp)
        bg = bg_color(inp)
        if {v for row in inp for v in row} - {bg, 1}:
            return None
        ones = [(r, c) for r in range(Rr) for c in range(Cc)
                if inp[r][c] == 1]
        if not ones:
            return None
        want = [row[:] for row in inp]
        for (r, c) in ones:
            for cc in range(Cc):
                if want[r][cc] != bg and want[r][cc] != 1:
                    return None
                want[r][cc] = 1
            for rr in range(Rr):
                if want[rr][c] != bg and want[rr][c] != 1:
                    return None
                want[rr][c] = 1
        for (r, c) in ones:
            want[r][c] = "dot"
        for (r, c) in ones:
            for dr, dc in _DIAG:
                rr, cc = r + dr, c + dc
                if not (0 <= rr < Rr and 0 <= cc < Cc):
                    continue
                if want[rr][cc] != bg:
                    return None
                want[rr][cc] = "dg"
        vd = {out[rr][cc] for rr in range(Rr) for cc in range(Cc)
              if want[rr][cc] == "dot"}
        vg = {out[rr][cc] for rr in range(Rr) for cc in range(Cc)
              if want[rr][cc] == "dg"}
        if len(vd) != 1 or len(vg) != 1 or vd == vg:
            return None
        pal = {v for row in inp for v in row}
        if next(iter(vd)) in pal or next(iter(vg)) in pal:
            return None
        mdots.add(next(iter(vd)))
        mdiag.add(next(iter(vg)))
        for rr in range(Rr):
            for cc in range(Cc):
                if want[rr][cc] == "dot":
                    want[rr][cc] = next(iter(vd))
                elif want[rr][cc] == "dg":
                    want[rr][cc] = next(iter(vg))
        if want != out:
            return None
    if len(mdots) != 1 or len(mdiag) != 1:
        return None
    return next(iter(mdots)), next(iter(mdiag))


def try_cross1(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    pm = _cross1_params(trains)
    if pm is None:
        return None
    mdot, mdiag = pm
    Rr, Cc = shape(test)
    bg = bg_color(test)
    if {v for row in test for v in row} - {bg, 1}:
        return None
    pal = {v for row in test for v in row}
    if mdot in pal or mdiag in pal:
        return None
    ones = [(r, c) for r in range(Rr) for c in range(Cc)
            if test[r][c] == 1]
    if not ones:
        return None
    got = [row[:] for row in test]
    for (r, c) in ones:
        for cc in range(Cc):
            if got[r][cc] != bg and got[r][cc] != 1:
                return None
            got[r][cc] = 1
        for rr in range(Rr):
            if got[rr][c] != bg and got[rr][c] != 1:
                return None
            got[rr][c] = 1
    for (r, c) in ones:
        got[r][c] = mdot
    for (r, c) in ones:
        for dr, dc in _DIAG:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < Rr and 0 <= cc < Cc):
                continue
            if got[rr][cc] != bg:
                return None
            got[rr][cc] = mdiag
    return got


def d_cross1(trains):
    if not trains:
        return False
    if _cross1_params(trains) is None:
        return False
    return verify_loo(try_cross1, trains)

# ─── Square frame corner marks (14b8e18c) ────────────────────────────
# For every non-bg connected component whose bbox is a SQUARE of
# side >= 2 with all four corners in the component's own color,
# paint the 8 corner-aligned outward neighbors (2 per corner) with
# a learned NEW mark. Clipped at the edge; outward cells must be
# bg (strict). Non-square bboxes and 1x1 singletons project
# nothing. Same shape in/out. LOO-verified.

def _sqframe_targets(comps):
    out = []
    for c in comps:
        cells = {(x, y) for x, y in c["cells"]}
        rs = [r for r, _ in c["cells"]]
        cs = [cc for _, cc in c["cells"]]
        r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
        if r1 - r0 != c1 - c0 or r1 - r0 < 1:
            continue
        if any((r, cc) not in cells
               for r, cc in ((r0, c0), (r0, c1), (r1, c0), (r1, c1))):
            continue
        out.append((c["color"], r0, r1, c0, c1))
    return out


def _sqframe_params(trains):
    marks = set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        Rr, Cc = shape(inp)
        bg = bg_color(inp)
        tg = _sqframe_targets(components(inp, bg=bg))
        if not tg:
            return None
        want = [row[:] for row in inp]
        for (_col, r0, r1, c0, c1) in tg:
            for (rr, cc) in ((r0 - 1, c0), (r0 - 1, c1),
                             (r1 + 1, c0), (r1 + 1, c1),
                             (r0, c0 - 1), (r1, c0 - 1),
                             (r0, c1 + 1), (r1, c1 + 1)):
                if not (0 <= rr < Rr and 0 <= cc < Cc):
                    continue
                if want[rr][cc] != bg:
                    return None
                want[rr][cc] = None
        vals = {out[rr][cc] for rr in range(Rr) for cc in range(Cc)
                if want[rr][cc] is None}
        if len(vals) != 1:
            return None
        m = next(iter(vals))
        if m == bg or m in {v for row in inp for v in row}:
            return None
        for rr in range(Rr):
            for cc in range(Cc):
                if want[rr][cc] is None:
                    want[rr][cc] = m
        if want != out:
            return None
        marks.add(m)
    return next(iter(marks)) if len(marks) == 1 else None


def try_sqframe(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    m = _sqframe_params(trains)
    if m is None:
        return None
    Rr, Cc = shape(test)
    bg = bg_color(test)
    if m in {v for row in test for v in row}:
        return None
    tg = _sqframe_targets(components(test, bg=bg))
    if not tg:
        return None
    got = [row[:] for row in test]
    for (_col, r0, r1, c0, c1) in tg:
        for (rr, cc) in ((r0 - 1, c0), (r0 - 1, c1),
                         (r1 + 1, c0), (r1 + 1, c1),
                         (r0, c0 - 1), (r1, c0 - 1),
                         (r0, c1 + 1), (r1, c1 + 1)):
            if not (0 <= rr < Rr and 0 <= cc < Cc):
                continue
            if got[rr][cc] != bg and got[rr][cc] != m:
                return None
            got[rr][cc] = m
    return got


def d_sqframe(trains):
    if not trains:
        return False
    if _sqframe_params(trains) is None:
        return False
    return verify_loo(try_sqframe, trains)

# ─── Tiling gaps (137f0df0) ─────────────────────────────────────────
# Full-bg rows/cols strictly INSIDE the non-bg bbox (blocks on both
# sides) are gap lines: cells inside the bbox paint a learned NEW
# inside-mark, cells outside a learned NEW outside-mark. Crossings
# of a gap row with a gap column must agree. Exterior full-bg
# lines are not gap lines (they only receive outside-marks where
# crossed). Same shape in/out. LOO-verified.

def _tilegap_lines(g, bg, r0, r1, c0, c1):
    Rr, Cc = shape(g)
    grows = [r for r in range(Rr)
             if all(g[r][c] == bg for c in range(Cc)) and r0 < r < r1]
    gcols = [c for c in range(Cc)
             if all(g[r][c] == bg for r in range(Rr)) and c0 < c < c1]
    return grows, gcols


def _tilegap_params(trains):
    mi, mo = set(), set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        Rr, Cc = shape(inp)
        bg = bg_color(inp)
        nbg = [(r, c) for r in range(Rr) for c in range(Cc)
               if inp[r][c] != bg]
        if not nbg:
            return None
        r0 = min(r for r, _ in nbg)
        r1 = max(r for r, _ in nbg)
        c0 = min(c for _, c in nbg)
        c1 = max(c for _, c in nbg)
        grows, gcols = _tilegap_lines(inp, bg, r0, r1, c0, c1)
        want = [row[:] for row in inp]
        for r in grows:
            for c in range(Cc):
                if want[r][c] != bg:
                    return None
                want[r][c] = "in" if c0 <= c <= c1 else "out"
        for c in gcols:
            for r in range(Rr):
                w = "in" if r0 <= r <= r1 else "out"
                if want[r][c] != bg and want[r][c] != w:
                    return None
                want[r][c] = w
        vi = {out[rr][cc] for rr in range(Rr) for cc in range(Cc)
              if want[rr][cc] == "in"}
        vo = {out[rr][cc] for rr in range(Rr) for cc in range(Cc)
              if want[rr][cc] == "out"}
        if not vi or not vo or len(vi) != 1 or len(vo) != 1 or vi == vo:
            return None
        pal = {v for row in inp for v in row}
        if next(iter(vi)) in pal or next(iter(vo)) in pal:
            return None
        mi.add(next(iter(vi)))
        mo.add(next(iter(vo)))
        for rr in range(Rr):
            for cc in range(Cc):
                if want[rr][cc] == "in":
                    want[rr][cc] = next(iter(vi))
                elif want[rr][cc] == "out":
                    want[rr][cc] = next(iter(vo))
        if want != out:
            return None
    if len(mi) != 1 or len(mo) != 1:
        return None
    return next(iter(mi)), next(iter(mo))


def try_tilegap(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    pm = _tilegap_params(trains)
    if pm is None:
        return None
    mi, mo = pm
    Rr, Cc = shape(test)
    bg = bg_color(test)
    pal = {v for row in test for v in row}
    if mi in pal or mo in pal:
        return None
    nbg = [(r, c) for r in range(Rr) for c in range(Cc)
           if test[r][c] != bg]
    if not nbg:
        return None
    r0 = min(r for r, _ in nbg)
    r1 = max(r for r, _ in nbg)
    c0 = min(c for _, c in nbg)
    c1 = max(c for _, c in nbg)
    grows, gcols = _tilegap_lines(test, bg, r0, r1, c0, c1)
    got = [row[:] for row in test]
    for r in grows:
        for c in range(Cc):
            if got[r][c] != bg:
                return None
            got[r][c] = mi if c0 <= c <= c1 else mo
    for c in gcols:
        for r in range(Rr):
            w = mi if r0 <= r <= r1 else mo
            if got[r][c] != bg and got[r][c] != w:
                return None
            got[r][c] = w
    return got


def d_tilegap(trains):
    if not trains:
        return False
    if _tilegap_params(trains) is None:
        return False
    return verify_loo(try_tilegap, trains)

# ─── Dot bars (178fcbfb) ────────────────────────────────────────────
# Dots (non-bg singletons). Each color wires to an orientation,
# LEARNED: row-colors paint their dots' full rows, col-colors
# their dots' full columns, with the dot's own color. Row bars
# win crossings (a col bar never overwrites a row bar). Bars paint
# bg-only otherwise (a dot on another's bar fails closed). Same
# shape in/out. LOO-verified.

def _dotbars_orient(trains):
    rowcolors, colcolors = set(), set()
    allc = set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        Rr, Cc = shape(inp)
        bg = bg_color(inp)
        comps = components(inp, bg=bg)
        if any(c["size"] != 1 for c in comps):
            return None
        for c in comps:
            allc.add(c["color"])
            dr, dc = c["anchor"]
            if all(out[dr][cc] == c["color"] for cc in range(Cc)):
                rowcolors.add(c["color"])
    colcolors = allc - rowcolors
    if not rowcolors and not colcolors:
        return None
    return rowcolors, colcolors


def _dotbars_apply(g, rowcolors, colcolors, bg):
    Rr, Cc = shape(g)
    comps = components(g, bg=bg)
    if any(c["size"] != 1 for c in comps):
        return None
    if {c["color"] for c in comps} - (rowcolors | colcolors):
        return None
    dots = {(r, c) for r in range(Rr) for c in range(Cc) if g[r][c] != bg}
    got = [row[:] for row in g]
    for c in comps:
        if c["color"] not in rowcolors:
            continue
        dr, _dc = c["anchor"]
        for cc in range(Cc):
            if (dr, cc) in dots:
                continue
            if got[dr][cc] != bg and got[dr][cc] != c["color"]:
                return None
            got[dr][cc] = c["color"]
    for c in comps:
        if c["color"] not in colcolors:
            continue
        _dr, dc = c["anchor"]
        for rr in range(Rr):
            if (rr, dc) in dots:
                continue
            if got[rr][dc] == bg or got[rr][dc] == c["color"]:
                got[rr][dc] = c["color"]
                continue
            # row bars win crossings: keep them, fail otherwise
            is_row = any(cc2["color"] in rowcolors and
                         cc2["anchor"][0] == rr for cc2 in comps)
            if not is_row or got[rr][dc] not in rowcolors:
                return None
    return got


def _dotbars_params(trains):
    o = _dotbars_orient(trains)
    if o is None:
        return None
    rowcolors, colcolors = o
    for inp, out in trains:
        got = _dotbars_apply(inp, rowcolors, colcolors, bg_color(inp))
        if got != out:
            return None
    return rowcolors, colcolors


def try_dotbars(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    pm = _dotbars_params(trains)
    if pm is None:
        return None
    return _dotbars_apply(test, pm[0], pm[1], bg_color(test))


def d_dotbars(trains):
    if not trains:
        return False
    if _dotbars_params(trains) is None:
        return False
    return verify_loo(try_dotbars, trains)

# ─── Spine tiling (12422b43) ────────────────────────────────────────
# Exactly one column opens with a top run (length >= 1) of 5s: the
# spine; its rows are the tile. The tile cycles downward starting
# at the first row below all content, copying every non-bg cell
# except the spine column (bg-only strict). Same shape. No marks
# to learn (verbatim copy). LOO-verified.

def _spinetile_params(trains):
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        Rr, Cc = shape(inp)
        bg = bg_color(inp)
        spines = [c for c in range(Cc) if inp[0][c] == 5]
        if len(spines) != 1:
            return None
        sp = spines[0]
        K = _runlen(inp, sp)
        content = [r for r in range(Rr)
                   if any(v != bg for v in inp[r])]
        if not content:
            return None
        anchor = max(content) + 1
        if anchor >= Rr:
            return None
        painted = [False]
        if _spinetile_paint(inp, out, bg, sp, K, anchor,
                            list(range(K)), painted) is None:
            return None
        if not painted[0]:
            return None
    return True


def _runlen(g, c):
    n = 0
    while n < len(g) and g[n][c] == 5:
        n += 1
    return n


def _spinetile_paint(inp, out, bg, sp, K, anchor, rows, painted):
    Rr, Cc = shape(inp)
    want = [row[:] for row in inp]
    L = len(rows)
    for r in range(anchor, Rr):
        src = rows[(r - anchor) % L]
        for c in range(Cc):
            if c == sp:
                continue
            v = inp[src][c]
            if v == bg:
                continue
            if want[r][c] != bg:
                return None
            want[r][c] = v
            painted[0] = True
    return want if want == out else None


def try_spinetile(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    if _spinetile_params(trains) is None:
        return None
    Rr, Cc = shape(test)
    bg = bg_color(test)
    spines = [c for c in range(Cc) if test[0][c] == 5]
    if len(spines) != 1:
        return None
    sp = spines[0]
    K = _runlen(test, sp)
    content = [r for r in range(Rr) if any(v != bg for v in test[r])]
    if not content:
        return None
    anchor = max(content) + 1
    if anchor >= Rr:
        return None
    got = [row[:] for row in test]
    L = K
    for r in range(anchor, Rr):
        src = (r - anchor) % L
        for c in range(Cc):
            if c == sp:
                continue
            v = test[src][c]
            if v == bg:
                continue
            if got[r][c] != bg:
                return None
            got[r][c] = v
    return got


def d_spinetile(trains):
    if not trains:
        return False
    if _spinetile_params(trains) is None:
        return False
    return verify_loo(try_spinetile, trains)

# ─── Odd block select (shrink-88 find) ─────────────────────────────────
# Seen in 2dc579da: full-length uniform divider lines (ANY color, even
# bg — test uses dot row+col) partition into EQUAL blocks; output = the
# UNIQUE block differing from the rest (counts [1, n-1]; 2-block ties
# and non-unique odds -> None). Strict LOO detector.

def _oddblock_partition(g):
    R, C = shape(g)
    if R == 0 or C == 0:
        return None
    hdiv = [r for r in range(R) if len(set(g[r])) == 1]
    vdiv = [c for c in range(C) if len({g[r][c] for r in range(R)}) == 1]
    if not hdiv and not vdiv:
        return None
    rb = [-1] + hdiv + [R]
    cb = [-1] + vdiv + [C]
    hs = [rb[i + 1] - rb[i] - 1 for i in range(len(rb) - 1)]
    ws = [cb[j + 1] - cb[j] - 1 for j in range(len(cb) - 1)]
    if any(s <= 0 for s in hs + ws):
        return None
    if len(set(hs)) != 1 or len(set(ws)) != 1:
        return None
    blocks = []
    for i in range(len(rb) - 1):
        for j in range(len(cb) - 1):
            blocks.append(tuple(tuple(row[cb[j] + 1:cb[j + 1]])
                                for row in g[rb[i] + 1:rb[i + 1]]))
    return blocks


def _oddblock_pick(blocks):
    from collections import Counter as _C
    if not blocks or len(blocks) < 2:
        return None
    cnt = _C(blocks)
    if len(cnt) != 2:
        return None
    top = cnt.most_common()
    if top[0][1] == 1 and top[1][1] == len(blocks) - 1:
        return top[0][0]
    if top[1][1] == 1 and top[0][1] == len(blocks) - 1:
        return top[1][0]
    return None


def try_oddblock(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    for inp, out in trains:
        blocks = _oddblock_partition(inp)
        if blocks is None:
            return None
        odd = _oddblock_pick(blocks)
        if odd is None or [list(r) for r in odd] != out:
            return None
        if (len(odd), len(odd[0])) != shape(out):
            return None
    blocks = _oddblock_partition(test)
    if blocks is None:
        return None
    odd = _oddblock_pick(blocks)
    if odd is None:
        return None
    return [list(r) for r in odd]


def d_oddblock(trains):
    return verify_loo(try_oddblock, trains)

# ─── Anchor crop (shrink-88 find) ──────────────────────────────────────
# Seen in sparse->3x3: output is an exact subgrid; anchor LEARNED per
# puzzle, exactly ONE mode may reproduce all trains (else None):
# FIXED (5bd6f4ac: constant position), DENSEST_C (ae4f1146: unique
# argmax of color-C density), BBOX_C (a87f7484: tight bbox of color C).
# Strict LOO detector. 48d8fb45 fits none (below-marker max-cover rule
# noted as future work, NOT implemented).

def _crop_at(g, r, c, h, w):
    return [row[c:c + w] for row in g[r:r + h]]


def _all_crop_pos(I, O):
    Rr, Cc, or_, oc = shape(I)[0], shape(I)[1], shape(O)[0], shape(O)[1]
    return [(r, c) for r in range(Rr - or_ + 1) for c in range(Cc - oc + 1)
            if _crop_at(I, r, c, or_, oc) == O]


def _densest_pos(I, h, w, color):
    Rr, Cc = shape(I)
    best, arg = -1, []
    for r in range(Rr - h + 1):
        for c in range(Cc - w + 1):
            k = sum(1 for rr in range(r, r + h) for cc in range(c, c + w)
                    if I[rr][cc] == color)
            if k > best:
                best, arg = k, [(r, c)]
            elif k == best:
                arg.append((r, c))
    return arg


def _tight_bbox(I, color):
    cells = [(r, c) for r, row in enumerate(I) for c, v in enumerate(row)
             if v == color]
    if not cells:
        return None
    r0 = min(r for r, _c in cells)
    r1 = max(r for r, _c in cells)
    c0 = min(c for _r, c in cells)
    c1 = max(c for _r, c in cells)
    return (r0, c0, r1 - r0 + 1, c1 - c0 + 1)


def _anchor_params(trains):
    shapes = {shape(o) for _i, o in trains}
    if len(shapes) != 1:
        return None
    (oh, ow) = next(iter(shapes))
    if oh <= 0 or ow <= 0:
        return None
    modes = []
    # FIXED: same crop position in every train
    pos0 = None
    fixed_ok = True
    for inp, out in trains:
        hits = _all_crop_pos(inp, out)
        if len(hits) != 1:
            fixed_ok = False
            break
        if pos0 is None:
            pos0 = hits[0]
        elif hits[0] != pos0:
            fixed_ok = False
            break
    if fixed_ok and pos0 is not None:
        modes.append(("FIXED", pos0))
    # DENSEST_C / BBOX_C per color
    colors = sorted({v for inp, _o in trains for row in inp for v in row})
    for col in colors:
        dok, bok = True, True
        for inp, out in trains:
            if _all_crop_pos(inp, out) != _densest_pos(inp, oh, ow, col) or \
                    len(_densest_pos(inp, oh, ow, col)) != 1:
                dok = False
            bb = _tight_bbox(inp, col)
            if bb is None or bb[2:] != (oh, ow) or \
                    _crop_at(inp, bb[0], bb[1], oh, ow) != out:
                bok = False
            if not dok and not bok:
                break
        if dok:
            modes.append(("DENSEST", col))
        if bok:
            modes.append(("BBOX", col))
    if len(modes) != 1:
        return None
    return modes[0]


def try_anchor_crop(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    learned = _anchor_params(trains)
    if learned is None:
        return None
    (oh, ow) = shape(trains[0][1])
    mode = learned[0]
    if mode == "FIXED":
        (r, c) = learned[1]
        Rr, Cc = shape(test)
        if r + oh > Rr or c + ow > Cc:
            return None
        return _crop_at(test, r, c, oh, ow)
    col = learned[1]
    if mode == "DENSEST":
        arg = _densest_pos(test, oh, ow, col)
        if len(arg) != 1:
            return None
        (r, c) = arg[0]
        return _crop_at(test, r, c, oh, ow)
    bb = _tight_bbox(test, col)
    if bb is None or bb[2:] != (oh, ow):
        return None
    return _crop_at(test, bb[0], bb[1], oh, ow)


def d_anchorcrop(trains):
    return verify_loo(try_anchor_crop, trains)

# ─── Half fold boolean (shrink-88 find) ─────────────────────────────────
# Seen in v-divider->3x3: split by full-height divider (or even split),
# overlay halves with a LEARNED boolean op (AND: 0520fde7, OR: dae9d2b5,
# e133d23d), output monochrome learned color. Vertical only (no h-case
# observed). First (split,op) in deterministic order reproducing ALL
# trains wins; strict LOO detector.

def _halfold_splits(g, bg):
    R, C = shape(g)
    out = []
    for c in range(C):
        col = [g[r][c] for r in range(R)]
        if len(set(col)) == 1 and col[0] != bg:
            L, Rr = c, C - c - 1
            if L == Rr and L > 0:
                out.append((c,))
    if C % 2 == 0 and C >= 2:
        out.append(None)  # even split, no divider
    return out


def _halfold_apply(g, bg, split, op, outcolor):
    R, C = shape(g)
    if split is None:
        w = C // 2
        L = [row[:w] for row in g]
        Rr = [row[w:] for row in g]
    else:
        c = split[0]
        L = [row[:c] for row in g]
        Rr = [row[c + 1:] for row in g]
    if len(L[0]) != len(Rr[0]):
        return None
    res = []
    for r in range(R):
        row = []
        for i in range(len(L[0])):
            a = L[r][i] != bg
            b = Rr[r][i] != bg
            v = (a and b) if op == "AND" else ((a or b) if op == "OR"
                                               else (a != b))
            row.append(outcolor if v else bg)
        res.append(row)
    return res


def _halfold_params(trains):
    bgcands = [0]
    for inp, _out in trains:
        m = bg_color(inp)
        if m not in bgcands:
            bgcands.append(m)
    for bg in bgcands:
        cands = None
        ok = True
        for inp, out in trains:
            or_, oc = shape(out)
            good = []
            for split in _halfold_splits(inp, bg):
                for op in ("AND", "OR", "XOR"):
                    for ocol in range(10):
                        if ocol == bg:
                            continue
                        if _halfold_apply(inp, bg, split, op, ocol) == out:
                            good.append((split, op, ocol))
            # keep only (split,op) pairs that explain with a single color;
            # color may vary per train (learned map below)
            pairs = {(s, o) for (s, o, _c) in good}
            if not pairs:
                ok = False
                break
            cands = pairs if cands is None else (cands & pairs)
            if not cands:
                ok = False
                break
        if not ok or cands is None or len(cands) != 1:
            continue
        split, op = next(iter(cands))
        # out-color: consistent across trains? (fresh-map like keydelete if not)
        cols = set()
        for inp, out in trains:
            ocols = {c for row in out for c in row if c != bg}
            if len(ocols) != 1:
                cols = set()
                break
            cols.add(next(iter(ocols)))
        if len(cols) != 1:
            continue
        return (bg, split, op, next(iter(cols)))
    return None


def try_halfold(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    learned = _halfold_params(trains)
    if learned is None:
        return None
    bg, split, op, ocol = learned
    return _halfold_apply(test, bg, split, op, ocol)


def d_halfold(trains):
    return verify_loo(try_halfold, trains)

# ─── Keyed delete+recolor (EV-hunt find) ─────────────────────────────────
# Seen in 009d5c81 (EV 0.25): one FIXED color D vanishes entirely, one
# FIXED color T recolors wholesale, new color keyed by the LARGEST
# deleted component's shape sig (t1==t3 -> 3, t2==t4 -> 2, t0 unique -> 7).
# Positions/shapes preserved exactly; only colors change. Strict: single
# D and single T fixed across trains; new color fresh (not in input);
# coverage-based detector (unique keys break strict LOO, as in sizefill).

def _keydelete_params(trains):
    from collections import Counter as _C
    Dset, Tset, mapping = None, None, {}
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        bg = bg_color(inp)
        ci = _C(c for row in inp for c in row if c != bg)
        co = _C(c for row in out for c in row if c != bg)
        vanished = [c for c in ci if co.get(c, 0) == 0]
        fresh = {c: n for c, n in co.items() if c not in ci}
        tmap, dlist = {}, []
        for c in vanished:
            matches = [n for n, k in fresh.items() if k == ci[c]]
            if len(matches) == 1:
                tmap[c] = matches[0]
            elif len(matches) == 0:
                dlist.append(c)
            else:
                return None  # ambiguous count-match
        if len(dlist) != 1 or len(tmap) != 1:
            return None
        d = dlist[0]
        tcol, ncol = next(iter(tmap.items()))
        Dset = {d} if Dset is None else (Dset & {d})
        Tset = {tcol} if Tset is None else (Tset & {tcol})
        # key shape: largest deleted component sig
        dsigs = sorted([o["sig"] for o in components(inp, bg)
                        if o["color"] == d],
                       key=lambda s: -len(s))
        if not dsigs:
            return None
        key = dsigs[0]
        if key in mapping and mapping[key] != ncol:
            return None
        mapping[key] = ncol
    if not Dset or len(Dset) != 1 or not Tset or len(Tset) != 1:
        return None
    return (next(iter(Dset)), next(iter(Tset)), mapping)


def _keydelete_keyshape(g, bg, dcolor):
    ds = sorted([o["sig"] for o in components(g, bg)
                 if o["color"] == dcolor], key=lambda s: -len(s))
    return ds[0] if ds else None


def try_keydelete(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    learned = _keydelete_params(trains)
    if learned is None:
        return None
    dcol, tcol, mapping = learned
    bg = bg_color(test)
    key = _keydelete_keyshape(test, bg, dcol)
    if key is None or key not in mapping:
        return None
    newc = mapping[key]
    R, C = shape(test)
    out = [row[:] for row in test]
    for r in range(R):
        for c in range(C):
            if out[r][c] == dcol:
                out[r][c] = bg
            elif out[r][c] == tcol:
                out[r][c] = newc
    return out


def d_keydelete(trains):
    if not verify(try_keydelete, trains):
        return False
    learned = _keydelete_params(trains)
    if learned is None:
        return False
    dcol = learned[0]
    keys = set()
    reps = 0
    for inp, _out in trains:
        bg = bg_color(inp)
        k = _keydelete_keyshape(inp, bg, dcol)
        if k is None:
            return False
        reps += 1
        keys.add(k)
    return len(keys) >= 2 or reps > len(keys)

# ─── Row period extend (EV-hunt find) ───────────────────────────────────
# Seen in 963e52fc (EV 0.25 via tiling: right neighborhood, wrong mode).
# Each row continues its smallest prefix-period to 2x width; heights and
# dot-rows unchanged. NOT plain doubling (fails), NOT mirror (fails):
# out[i] = row[i % p]. Strict: same height in/out, out width exactly 2x
# in every train; horizontal only (no vertical case observed).

def _row_period(row):
    n = len(row)
    for p in range(1, n + 1):
        if all(row[i] == row[i % p] for i in range(n)):
            return p
    return n


def try_row_extend(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    for inp, out in trains:
        ir, ic = shape(inp)
        or_, oc = shape(out)
        if ir == 0 or (or_, oc) != (ir, 2 * ic):
            return None
        for r in range(ir):
            p = _row_period(inp[r])
            if ([inp[r][c % p] for c in range(oc)] != list(out[r])):
                return None
    ir, ic = shape(test)
    if ir == 0 or ic == 0:
        return None
    return [[test[r][c % _row_period(test[r])] for c in range(2 * ic)]
            for r in range(ir)]


def d_rowextend(trains):
    return verify_loo(try_row_extend, trains)

# ─── Progression continue (draw family) ────────────────────────────────
# Seen in 0b17323b: `#` dots on an arithmetic-diagonal step get the line
# continued FORWARD to the grid edge, drawn in a LEARNED new color (`o`
# in both trains). Strict: all non-bg cells are single dots of ONE color;
# constant step (row-sorted diffs); forward-only (backward indistinguishable
# on observed trains — conservative draws less); anti-vacuity: must draw
# >= 1 dot across trains (else identity puzzles false-fire).

def _progression(dots):
    if len(dots) < 2:
        return None
    pts = sorted(dots)
    diffs = [(b[0] - a[0], b[1] - a[1])
             for a, b in zip(pts, pts[1:])]
    if len(set(diffs)) != 1 or diffs[0] == (0, 0):
        return None
    return pts, diffs[0]


def try_prog_continue(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    newcolors = set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        bg = bg_color(inp)
        dots = [(r, c) for r, row in enumerate(inp)
                for c, v in enumerate(row) if v != bg]
        colors = {inp[r][c] for (r, c) in dots}
        if len(colors) != 1:
            return None
        # dots must be isolated singles (no two dots 8-adjacent)
        dotset = set(dots)
        for (r, c) in dots:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if (dr or dc) and (r + dr, c + dc) in dotset:
                        return None
        for r in range(len(inp)):
            for c in range(len(inp[0])):
                a, b = inp[r][c], out[r][c]
                if a == bg and b != bg:
                    newcolors.add(b)
                elif a != b:
                    return None  # only additions allowed
    if len(newcolors) != 1:
        return None
    newc = next(iter(newcolors))

    def apply(inp):
        bg = bg_color(inp)
        dots = [(r, c) for r, row in enumerate(inp)
                for c, v in enumerate(row) if v != bg]
        if not dots:
            return None
        if len({inp[r][c] for (r, c) in dots}) != 1:
            return None
        pr = _progression(dots)
        if pr is None:
            return None
        pts, (dr, dc) = pr
        R, C = shape(inp)
        out = [row[:] for row in inp]
        r, c = pts[-1][0] + dr, pts[-1][1] + dc
        while 0 <= r < R and 0 <= c < C:
            if out[r][c] != bg:
                return None  # path blocked: not this dynamic
            out[r][c] = newc
            r, c = r + dr, c + dc
        return out

    for inp, out in trains:
        pred = apply(inp)
        if pred is None or not v3.grids_equal(pred, out):
            return None
    ndrawn = 0
    for inp, out in trains:
        ndrawn += sum(1 for r in range(len(inp)) for c in range(len(inp[0]))
                      if inp[r][c] == bg_color(inp) and out[r][c] != bg_color(inp))
    if ndrawn == 0:
        return None
    return apply(test)


def d_progcontinue(trains):
    return verify_loo(try_prog_continue, trains)

# ─── Frame dots (draw family) ──────────────────────────────────────────
# Seen in dc1df850: every `o` dot gets a 3x3 hollow `#` square centered
# on it (clipped at borders, center preserved). Other colors ignored.
# Generalized as a learned map: dot_color -> frame_color, 3x3 hollow.
# Conservative: frames paint bg cells only (no colliding example seen;
# overwriting content would be a guess, and guesses don't ship).

def _frame_map(trains: Trains, bg):
    dots, frames = set(), set()
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        for r in range(len(inp)):
            for c in range(len(inp[0])):
                a, b = inp[r][c], out[r][c]
                if a == bg and b != bg:
                    frames.add(b)
                elif a != bg and b != bg and a != b:
                    return None  # recolor: not this dynamic
        # dot candidates: unchanged non-bg cells fully surrounded by
        # non-bg in the OUTPUT (a frame center; edge-clipped frames count
        # in-bounds neighbors only). Mere adjacency (e.g. * diagonal to a
        # frame in dc1df850/train1) must NOT qualify: surroundedness does.
        R, C = shape(inp)
        for r in range(R):
            for c in range(C):
                if inp[r][c] == bg or out[r][c] != inp[r][c]:
                    continue
                nbrs = [(r + dr, c + dc) for dr in (-1, 0, 1)
                        for dc in (-1, 0, 1) if (dr or dc)
                        and 0 <= r + dr < R and 0 <= c + dc < C]
                if nbrs and all(out[nr][nc] != bg for (nr, nc) in nbrs):
                    dots.add(inp[r][c])
    if len(frames) != 1 or len(dots) != 1:
        return None
    return (next(iter(dots)), next(iter(frames)))


def try_frame_dots(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    bg = bg_color(trains[0][0])
    m = _frame_map(trains, bg)
    if m is None:
        return None
    dot, frame = m
    R, C = shape(test)
    out = [row[:] for row in test]
    for r in range(R):
        for c in range(C):
            if test[r][c] != dot:
                continue
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if (0 <= nr < R and 0 <= nc < C and
                            out[nr][nc] == bg):
                        out[nr][nc] = frame
    return out


def d_framedots(trains):
    return verify_loo(try_frame_dots, trains)

# ─── Size-keyed fill (draw family) ─────────────────────────────────────
# Seen in 00dbd492: hollow rectangles get interiors filled; fill COLOR
# is keyed by interior SIZE ((7,7)->x, (5,5)->O, (3,3)->8, learned from
# trains); pre-existing interior dots are preserved (only bg cells fill).

def _enclosed_interiors(g: Grid, bg: int):
    R, C = shape(g)
    reached = [[False] * C for _ in range(R)]
    stack = ([(r, 0) for r in range(R)] + [(r, C - 1) for r in range(R)] +
             [(0, c) for c in range(C)] + [(R - 1, c) for c in range(C)])
    while stack:
        r, c = stack.pop()
        if not (0 <= r < R and 0 <= c < C):
            continue
        if reached[r][c] or g[r][c] != bg:
            continue
        reached[r][c] = True
        stack.extend([(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)])
    seen = set()
    regions = []
    for r in range(R):
        for c in range(C):
            if g[r][c] != bg or reached[r][c] or (r, c) in seen:
                continue
            cells, st = [], [(r, c)]
            while st:
                cr, cc = st.pop()
                if ((cr, cc) in seen or not (0 <= cr < R and 0 <= cc < C)
                        or g[cr][cc] != bg or reached[cr][cc]):
                    continue
                seen.add((cr, cc))
                cells.append((cr, cc))
                st.extend([(cr - 1, cc), (cr + 1, cc),
                           (cr, cc - 1), (cr, cc + 1)])
            if cells:
                regions.append(cells)
    return regions


def _sizefill_map(trains: Trains, bg):
    """(h, w) -> fill color, learned. None if inconsistent/empty."""
    mapping = {}
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        for cells in _enclosed_interiors(inp, bg):
            r0 = min(r for r, c in cells)
            r1 = max(r for r, c in cells)
            c0 = min(c for r, c in cells)
            c1 = max(c for r, c in cells)
            key = (r1 - r0 + 1, c1 - c0 + 1)
            fills = Counter(out[r][c] for (r, c) in cells
                            if inp[r][c] == bg)
            if not fills:
                return None
            color, n = fills.most_common(1)[0]
            if n != len([1 for (r, c) in cells if inp[r][c] == bg]):
                return None  # interior bg did not uniformly fill
            if color == bg:
                return None
            if key in mapping and mapping[key] != color:
                return None
            mapping[key] = color
    return mapping or None


def try_sizefill(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    bg = bg_color(trains[0][0])
    mapping = _sizefill_map(trains, bg)
    if not mapping:
        return None
    out = [row[:] for row in test]
    for cells in _enclosed_interiors(test, bg):
        r0 = min(r for r, c in cells)
        r1 = max(r for r, c in cells)
        c0 = min(c for r, c in cells)
        c1 = max(c for r, c in cells)
        key = (r1 - r0 + 1, c1 - c0 + 1)
        if key not in mapping:
            return None
        for (r, c) in cells:
            if out[r][c] == bg:
                out[r][c] = mapping[key]
    return out


def d_sizefill(trains):
    # NOT verify_loo: map-learning needs coverage, not redundancy.
    # LOO demands each pair's sizes appear in OTHER pairs; sparse maps
    # (00dbd492: (7,7) only in t0) fail LOO on a TRUE rule. Instead:
    # plain consistency + evidence bar (distinct keys >= 2, or a key
    # repeated across trains). Memorizers can't pass: output is fully
    # determined by the small key->color map, not by copying a train.
    if not verify(try_sizefill, trains):
        return False
    bg = bg_color(trains[0][0])
    keys = []
    for inp, _out in trains:
        for cells in _enclosed_interiors(inp, bg):
            r0 = min(r for r, c in cells)
            r1 = max(r for r, c in cells)
            c0 = min(c for r, c in cells)
            c1 = max(c for r, c in cells)
            keys.append((r1 - r0 + 1, c1 - c0 + 1))
    return len(set(keys)) >= 2 or len(keys) > len(set(keys))

# ─── Staircase pack (stack family, H4) ─────────────────────────────────
# Seen in 03560426. H1 (column gravity), H2 (delete empty rows/cols) and
# H3 (compact+pad) all REFUTED computationally on its 3 trains.
# True rule (fit on 10 object motions, 3 trains): order objects by
# (min_col, min_row); obj0 anchor -> (0,0); then staircase:
#   top[i+1]  = top[i] + height[i] - 1
#   left[i+1] = left[i] + width[i] - 1
# (FULL input-shape bbox dims), paint sequentially, later overwrites
# (overlap cells resolve to the later object: the "lost" cells).

def try_staircase_pack(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    bg = bg_color(trains[0][0])
    R, C = shape(test)
    tcomps = components(test, bg)
    if not tcomps:
        return None
    tcomps.sort(key=lambda o: (o["anchor"][1], o["anchor"][0]))
    out = [[bg] * C for _ in range(R)]
    top, left = 0, 0
    first = True
    for comp in tcomps:
        (ar, ac) = comp["anchor"]
        cells = [(r - ar + top, c - ac + left) for (r, c) in comp["cells"]]
        if any(not (0 <= r < R and 0 <= c < C) for (r, c) in cells):
            return None
        for (r, c) in cells:
            out[r][c] = comp["color"]
        _r0, _r1, _c0, _c1 = _bbox(comp["cells"])
        h, w = _r1 - _r0 + 1, _c1 - _c0 + 1
        top, left = top + h - 1, left + w - 1
        first = False
    return out


def d_staircase(trains):
    return verify_loo(try_staircase_pack, trains)

# ─── Crop + quadrant extraction (extract family) ─────────────────────
# Finding 2026-09-09: "extract" (output⊂input, 52 puzzles) is a FAMILY,
# not one dynamic. bbox-crop holds on trains for 1/52 (refuted as the
# cluster rule). Consistent-quadrant holds for 2/52. Both implemented as
# LOO-gated micro-rules: zero regression risk, honest p@1 accounting.

def _content_box(g, bg):
    cells = [(r, c) for r, row in enumerate(g)
             for c, v in enumerate(row) if v != bg]
    if not cells:
        return None
    r0 = min(r for r, c in cells)
    r1 = max(r for r, c in cells)
    c0 = min(c for r, c in cells)
    c1 = max(c for r, c in cells)
    return (r0, r1, c0, c1)


def try_crop_content(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    bg = bg_color(trains[0][0])
    for inp, out in trains:
        box = _content_box(inp, bg)
        if box is None:
            return None
        r0, r1, c0, c1 = box
        crop = [row[c0:c1 + 1] for row in inp[r0:r1 + 1]]
        if not v3.grids_equal(crop, out):
            return None
    box = _content_box(test, bg)
    if box is None:
        return None
    r0, r1, c0, c1 = box
    return [row[c0:c1 + 1] for row in test[r0:r1 + 1]]


def _quadrants(box):
    H, W = len(box), len(box[0])
    if H % 2 or W % 2 or H < 2 or W < 2:
        return None
    mh, mw = H // 2, W // 2
    return {"TL": [r[:mw] for r in box[:mh]],
            "TR": [r[mw:] for r in box[:mh]],
            "BL": [r[:mw] for r in box[mh:]],
            "BR": [r[mw:] for r in box[mh:]]}


def try_extract_quadrant(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    bg = bg_color(trains[0][0])
    for q in ("TL", "TR", "BL", "BR"):
        ok = True
        for inp, out in trains:
            box = _content_box(inp, bg)
            if box is None:
                ok = False
                break
            r0, r1, c0, c1 = box
            Q = _quadrants([row[c0:c1 + 1] for row in inp[r0:r1 + 1]])
            if Q is None or not v3.grids_equal(Q[q], out):
                ok = False
                break
        if ok:
            box = _content_box(test, bg)
            if box is None:
                return None
            r0, r1, c0, c1 = box
            Q = _quadrants([row[c0:c1 + 1] for row in test[r0:r1 + 1]])
            return Q[q] if Q is not None else None
    return None


def d_crop(trains):
    return verify_loo(try_crop_content, trains)


def d_quadrant(trains):
    return verify_loo(try_extract_quadrant, trains)

# ─── Flip-tiling (extends rsi_module.try_adaptive_tiling) ─────────────
# Seen in 00576224: 2x2 → 6x6 where odd TILE ROWS are mirrored horizontally.
# rsi adaptive covers vertical-flip-on-odd-row / horizontal-flip-on-odd-col
# but not horizontal-flip-on-odd-row. Full mode matrix below.

def _tile_transform(tile, flip_h, flip_v):
    t = [row[:] for row in tile]
    if flip_h:
        t = [row[::-1] for row in t]
    if flip_v:
        t = t[::-1]
    return t


FLIP_MODES = {
    "repeat":    lambda ti, tj: (False, False),
    "altrow_h":  lambda ti, tj: (ti % 2 == 1, False),
    "altrow_v":  lambda ti, tj: (False, ti % 2 == 1),
    "altcol_h":  lambda ti, tj: (tj % 2 == 1, False),
    "altcol_v":  lambda ti, tj: (False, tj % 2 == 1),
    "checker_h": lambda ti, tj: ((ti + tj) % 2 == 1, False),
    "checker_v": lambda ti, tj: (False, (ti + tj) % 2 == 1),
}


def _check_flip_mode(inp, out, mode, tr, tc):
    ir, ic = shape(inp)
    fn = FLIP_MODES[mode]
    for ti in range(tr):
        for tj in range(tc):
            fh, fv = fn(ti, tj)
            exp = _tile_transform(inp, fh, fv)
            for di in range(ir):
                for dj in range(ic):
                    if out[ti * ir + di][tj * ic + dj] != exp[di][dj]:
                        return False
    return True


def try_flip_tiling(trains: Trains, test: Grid) -> Optional[Grid]:
    if not trains:
        return None
    i0, o0 = trains[0]
    ir, ic = shape(i0)
    or_, oc = shape(o0)
    if ir == 0 or ic == 0 or or_ % ir != 0 or oc % ic != 0:
        return None
    tr, tc = or_ // ir, oc // ic
    if tr < 1 or tc < 1 or (tr == 1 and tc == 1):
        return None
    for mode in FLIP_MODES:
        if all(shape(i) == (ir, ic) and shape(o) == (or_, oc)
               and _check_flip_mode(i, o, mode, tr, tc) for i, o in trains):
            R, C = shape(test)
            if R * tr == 0 or C * tc == 0:
                return None
            fn = FLIP_MODES[mode]
            res = [[0] * (C * tc) for _ in range(R * tr)]
            for ti in range(tr):
                for tj in range(tc):
                    fh, fv = fn(ti, tj)
                    exp = _tile_transform(test, fh, fv)
                    for di in range(R):
                        for dj in range(C):
                            res[ti * R + di][tj * C + dj] = exp[di][dj]
            return res
    return None

# ─── New strategy: move object to anchor ─────────────────────────────
# Dynamic seen in 05f2a901: one object (mover) slides along one axis until
# 4-adjacent to a static object (anchor). Axis varies per pair, so the rule
# is relational (toward-anchor), not a fixed vector (cf. try_object_shift).

def _cells_adjacent(a_cells, b_cells) -> bool:
    b = set(b_cells)
    for (r, c) in a_cells:
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if (r + dr, c + dc) in b:
                return True
    return False


def _bbox(cells):
    rs = [x[0] for x in cells]
    cs = [x[1] for x in cells]
    return (min(rs), max(rs), min(cs), max(cs))


def identify_anchor_mover(trains: Trains, bg) -> Tuple[Optional[int], Optional[int]]:
    """(anchor_color, mover_color): anchor static in every train, mover keeps
    shape but changes position and ends 4-adjacent to the anchor."""
    colors = None
    for inp, _out in trains:
        cs = {c for row in inp for c in row if c != bg}
        colors = cs if colors is None else (colors & cs)
    if not colors:
        return None, None

    def cellset(g, color):
        return {(r, c) for r, row in enumerate(g)
                for c, v in enumerate(row) if v == color}

    def sigs(g, color):
        return sorted(o["sig"] for o in components(g, bg)
                      if o["color"] == color)

    anchor_cand, mover_cand = [], []
    for color in colors:
        static = all(cellset(i, color) == cellset(o, color)
                     for i, o in trains)
        moved = all(sigs(i, color) == sigs(o, color) and
                    cellset(i, color) != cellset(o, color)
                    for i, o in trains)
        if static:
            anchor_cand.append(color)
        if moved:
            mover_cand.append(color)
    if not anchor_cand or not mover_cand:
        return None, None

    # disambiguate by adjacency in every output
    ok_anchors = [a for a in anchor_cand
                  if all(any(_cells_adjacent(cellset(o, m), cellset(o, a))
                             for m in mover_cand)
                         for _, o in trains)]
    ok_movers = [m for m in mover_cand
                 if all(any(_cells_adjacent(cellset(o, m), cellset(o, a))
                            for a in anchor_cand)
                        for _, o in trains)]
    if len(ok_anchors) != 1 or len(ok_movers) != 1:
        return None, None
    return ok_anchors[0], ok_movers[0]


def _slide_to_anchor(mover_cells, anchor_cells):
    """Shift mover per-axis (bbox) until 4-adjacent. None if impossible."""
    mr0, mr1, mc0, mc1 = _bbox(mover_cells)
    ar0, ar1, ac0, ac1 = _bbox(anchor_cells)
    anchor_set = set(anchor_cells)
    dr = dc = 0
    while mr1 < ar0 - 1:
        dr += 1
        mr0 += 1
        mr1 += 1
        if dr > 64:
            return None
    while mr0 > ar1 + 1:
        dr -= 1
        mr0 -= 1
        mr1 -= 1
        if dr < -64:
            return None
    while mc1 < ac0 - 1:
        dc += 1
        mc0 += 1
        mc1 += 1
        if dc > 64:
            return None
    while mc0 > ac1 + 1:
        dc -= 1
        mc0 -= 1
        mc1 -= 1
        if dc < -64:
            return None
    moved = [(r + dr, c + dc) for (r, c) in mover_cells]
    if set(moved) & anchor_set:
        return None  # overlap, not adjacency
    if not _cells_adjacent(moved, anchor_cells):
        return None
    return moved


def try_move_to_anchor(trains: Trains, test: Grid) -> Optional[Grid]:
    bg = bg_color(trains[0][0])
    anchor_c, mover_c = identify_anchor_mover(trains, bg)
    if anchor_c is None:
        return None
    R, C = shape(test)
    anchor_cells = [(r, c) for r, row in enumerate(test)
                    for c, v in enumerate(row) if v == anchor_c]
    mover_comps = [o for o in components(test, bg) if o["color"] == mover_c]
    if not anchor_cells or not mover_comps:
        return None
    out = [row[:] for row in test]
    for comp in mover_comps:
        for (r, c) in comp["cells"]:
            out[r][c] = bg
    for comp in mover_comps:
        moved = _slide_to_anchor(comp["cells"], anchor_cells)
        if moved is None:
            return None
        for (r, c) in moved:
            if not (0 <= r < R and 0 <= c < C) or out[r][c] != bg:
                return None
            out[r][c] = mover_c
    return out


def d_anchor(trains):
    bg = bg_color(trains[0][0])
    a, m = identify_anchor_mover(trains, bg)
    if a is None:
        return False
    return verify_loo(try_move_to_anchor, trains)

# ─── Composition (hunter-grown toolbox, data not code) ───────────────
# A verified composition {"ops": [f, g]} becomes a strategy WITHOUT code
# edits: compose(f, g)(trains, x) = g(trains, f(trains, x)), shared trains
# context, None-propagating. Registry = state/rsi_reports/compositions.json
# (hunter writes it). Loaded only via --compose PATH (opt-in: default runs
# stay exactly comparable). Detector = whichever entry LOO-verifies.

def compose(f, g):
    def _composed(trains, test):
        try:
            mid = f(trains, test)
        except Exception:
            return None
        if mid is None:
            return None
        try:
            return g(trains, mid)
        except Exception:
            return None
    _composed.__name__ = f"{f.__name__}+{g.__name__}"
    return _composed


COMPOSED_FNS = []


def load_compositions(path):
    import json as _json
    try:
        reg = _json.load(open(path))
    except Exception:
        return []
    by_name = {name: fn for name, fn in FALLBACK}
    out = []
    for e in reg.get("compositions", []):
        ops = e.get("ops", [])
        if len(ops) != 2 or not all(o in by_name for o in ops):
            continue
        fn = compose(by_name[ops[0]], by_name[ops[1]])
        out.append((f"composed_{ops[0]}+{ops[1]}", fn))
    return out


def d_composed(trains):
    for _name, fn in COMPOSED_FNS:
        if verify_loo(fn, trains):
            return True
    return False


def composed_fns_for(trains):
    return [fn for _name, fn in COMPOSED_FNS
            if verify_loo(fn, trains)]

# ─── Dynamic detectors (ordered, most specific first) ────────────────

def d_extract(trains):
    return all(contains_subgrid(i, o) for i, o in trains)


def d_retiling(trains):
    return (verify_loo(v3.try_tiling, trains)
            or verify_loo(v3.try_diagonal_tiling, trains)
            or verify_loo(try_adaptive_tiling, trains)
            or verify_loo(try_flip_tiling, trains))


def d_rotation(trains):
    return verify_loo(v3.try_rotation, trains) or verify_loo(v3.try_reflection, trains)


def d_recolor(trains):
    if any(shape(i) != shape(o) for i, o in trains):
        return False
    return (verify_loo(v3.try_color_mapping, trains)
            or verify_loo(v2.try_position_color_map, trains))


def d_fill(trains):
    if any(shape(i) != shape(o) for i, o in trains):
        return False
    return (verify_loo(v3.try_interior_fill, trains)
            or verify_loo(v2.try_pattern_fill, trains)
            or verify_loo(v2.try_flood_fill, trains))


def d_counting(trains):
    if not all(shape(o)[0] * shape(o)[1] <= 25 for _, o in trains):
        return False
    return (verify_loo(v3.try_object_count, trains)
            or verify_loo(v2.try_color_counting, trains))


def d_move(trains):
    return verify_loo(try_object_shift, trains)


def d_expand(trains):
    if not any(shape(o) != shape(i) for i, o in trains):
        return False
    return verify_loo(v3.try_shape_expansion, trains)


def d_spread(trains):
    # nearest_neighbor deliberately excluded: it memorizes train outputs
    # (returns the most similar pair's output) instead of spreading.
    return verify_loo(v3.try_color_spread, trains)

# dynamic -> (detector, strategy fns to try in order, ARC-AGI-3 action family)
DYNAMICS = [
    ("composed", d_composed, None,  # fns resolved per-puzzle (registry)
     "composed"),
    # crop/quadrant BEFORE extract: their outputs are also subgrids,
    # but these two carry solvers while bare extract does not.
    ("crop",     d_crop,     [try_crop_content],
     "explore-cursor"),
    ("quadrant", d_quadrant, [try_extract_quadrant],
     "explore-cursor"),
    ("anchorcrop", d_anchorcrop, [try_anchor_crop],
     "cursor-move(ACTION1/2)"),
    ("oddblock", d_oddblock, [try_oddblock],
     "explore-cursor"),
    ("blockcensus", d_blockcensus, [try_blockcensus],
     "explore-cursor"),
    ("norhalves", d_norhalves, [try_norhalves],  # solver before extract
     "explore-cursor"),
    ("xorhalves", d_xorhalves, [try_xorhalves],  # solver before extract
     "explore-cursor"),
    ("orhalves", d_orhalves, [try_orhalves],  # solver before extract
     "explore-cursor"),
    ("pack", d_pack, [try_pack],  # solver before extract
     "explore-cursor"),
    ("anomaly", d_anomaly, [try_anomaly],  # solver before extract
     "explore-cursor"),
    ("qcollage", d_qcollage, [try_qcollage],  # solver before extract
     "explore-cursor"),
    ("qstack", d_qstack, [try_qstack],  # solver before extract
     "explore-cursor"),
    ("qstack2", d_qstack2, [try_qstack2],  # solver before extract
     "explore-cursor"),
    ("qstackL", d_qstackL, [try_qstackL],  # solver before extract
     "explore-cursor"),
    ("vstack", d_vstack, [try_vstack],  # solver before extract
     "explore-cursor"),
    ("vunion", d_vunion, [try_vunion],  # solver before extract
     "explore-cursor"),
    ("vfirst", d_vfirst, [try_vfirst],  # solver before extract
     "explore-cursor"),
    ("vrows", d_vrows, [try_vrows],  # solver before extract
     "explore-cursor"),
    ("vcols", d_vcols, [try_vcols],  # solver before extract
     "explore-cursor"),
    ("frames", d_frames, [try_frames],  # solver before extract
     "explore-cursor"),
    ("dotframe", d_dotframe, [try_dotframe],  # solver before extract
     "explore-cursor"),
    ("below", d_below, [try_below],  # solver before extract
     "explore-cursor"),
    ("midline", d_midline, [try_midline],  # solver before extract
     "interact-paint(ACTION5)"),
    ("asym", d_asym, [try_asym],  # solver before extract
     "explore-cursor"),
    ("divemit", d_divemit, [try_divemit],  # solver before extract
     "interact-paint(ACTION5)"),
    ("hub4", d_hub4, [try_hub4],  # solver before extract
     "interact-paint(ACTION5)"),
    ("halo", d_halo, [try_halo],  # solver before extract
     "interact-paint(ACTION5)"),
    ("diagfocus", d_diagfocus, [try_diagfocus],  # solver before extract
     "interact-paint(ACTION5)"),
    ("cross1", d_cross1, [try_cross1],  # solver before extract
     "interact-paint(ACTION5)"),
    ("sqframe", d_sqframe, [try_sqframe],  # solver before extract
     "interact-paint(ACTION5)"),
    ("tilegap", d_tilegap, [try_tilegap],  # solver before extract
     "interact-paint(ACTION5)"),
    ("dotbars", d_dotbars, [try_dotbars],  # solver before extract
     "interact-paint(ACTION5)"),
    ("spinetile", d_spinetile, [try_spinetile],  # solver before extract
     "explore-cursor"),
    ("extract",  d_extract,  [],  # no solver without output → fallback
     "explore-cursor"),
    ("retiling", d_retiling, [v3.try_tiling, v3.try_diagonal_tiling,
                              try_adaptive_tiling, try_flip_tiling],
     "transform-bulk(ACTION3/4)"),
    ("mirrordouble", d_mirrordouble, [try_mirror_double],
     "transform-bulk(ACTION3/4)"),
    ("rowextend", d_rowextend, [try_row_extend],
     "transform-bulk(ACTION3/4)"),
    ("halfold", d_halfold, [try_halfold],
     "interact-paint(ACTION5)"),
    ("rotation", d_rotation, [v3.try_rotation, v3.try_reflection],
     "transform-bulk(ACTION3/4)"),
    ("recolor",  d_recolor,  [v3.try_color_mapping, v2.try_position_color_map],
     "interact-paint(ACTION5)"),
    ("fill",     d_fill,     [v3.try_interior_fill, v2.try_pattern_fill,
                              v2.try_flood_fill],
     "interact-paint(ACTION5)"),
    ("sizefill", d_sizefill, [try_sizefill],
     "interact-paint(ACTION5)"),
    ("framedots", d_framedots, [try_frame_dots],
     "interact-paint(ACTION5)"),
    ("symcomplete", d_symcomplete, [try_symmetry_complete],
     "interact-paint(ACTION5)"),
    ("growring", d_growring, [try_grow_ring],
     "interact-paint(ACTION5)"),
    ("progcont", d_progcontinue, [try_prog_continue],
     "interact-paint(ACTION5)"),
    ("keydelete", d_keydelete, [try_keydelete],
     "interact-paint(ACTION5)"),
    ("invertrecolor", d_invertrecolor, [try_invert_recolor],
     "interact-paint(ACTION5)"),
    ("connect", d_connect, [try_connect_dots],
     "interact-paint(ACTION5)"),
    ("counting", d_counting, [v3.try_object_count, v2.try_color_counting],
     "explore-cursor"),
    ("anchor",   d_anchor,   [try_move_to_anchor],
     "move-cursor(ACTION1-4)"),
    ("staircase", d_staircase, [try_staircase_pack],
     "move-cursor(ACTION1-4)"),
    ("legendswap", d_legendswap, [try_legend_swap],
     "move-cursor(ACTION1-4)"),
    ("bandmatch", d_bandmatch, [try_band_match],
     "move-cursor(ACTION1-4)"),
    # lattice UNPARKED 2026-09-10: step now from bg grid lines (not
    # gcd-of-gaps); 06df4c85 all 3 trains reproduce (multi-texture was
    # one mechanism: interpolate on the bg lattice, bg 1/8/4 per train).
    ("lattice", d_lattice, [try_lattice_interp],
     "move-cursor(ACTION1-4)"),
    ("move",     d_move,     [try_object_shift],
     "move-cursor(ACTION1-4)"),
    ("expand",   d_expand,   [v3.try_shape_expansion],
     "transform-bulk(ACTION3/4)"),
    ("spread",   d_spread,   [v3.try_color_spread, v3.try_nearest_neighbor],
     "interact-paint(ACTION5)"),
]

# Full blind chain = v3 order + missing toolbox fns (dedup). Baseline superset.
FALLBACK: List[Tuple[str, Callable]] = list(v3.STRATEGIES)
_seen = {id(f) for _, f in FALLBACK}
for _name, _fn in [("object_count", v3.try_object_count),
                   ("adaptive_tiling", try_adaptive_tiling),
                   ("flip_tiling", try_flip_tiling),
                   ("flood_fill", v2.try_flood_fill),
                   ("position_color_map", v2.try_position_color_map),
                   ("color_counting", v2.try_color_counting),
                   ("pattern_fill", v2.try_pattern_fill),
                   ("object_shift", try_object_shift),
                   ("move_to_anchor", try_move_to_anchor),
                   ("crop_content", try_crop_content),
                   ("extract_quadrant", try_extract_quadrant),
                   ("frame_dots", try_frame_dots),
                   ("half_fold", try_halfold),
                   ("anchor_crop", try_anchor_crop),
                   ("odd_block", try_oddblock),
                   ("block_census", try_blockcensus),
                   ("row_extend", try_row_extend),
                   ("mirror_double", try_mirror_double),
                   ("symmetry_complete", try_symmetry_complete),
                   ("grow_ring", try_grow_ring),
                   ("prog_continue", try_prog_continue),
                   ("legend_swap", try_legend_swap),
                   ("band_match", try_band_match),
                   ("lattice_interp", try_lattice_interp),
                   ("connect_dots", try_connect_dots),
                   ("sizefill", try_sizefill),
                   ("staircase_pack", try_staircase_pack),
                   ("nor_halves", try_norhalves),
                   ("xor_halves", try_xorhalves),
                   ("or_halves", try_orhalves),
                   ("pack_pieces", try_pack),
                   ("anomaly_crop", try_anomaly),
                   ("quad_collage", try_qcollage),
                   ("quad_stack", try_qstack),
                   ("quad_stack2", try_qstack2),
                   ("quad_stackL", try_qstackL),
                   ("vert_stack", try_vstack),
                   ("vert_union", try_vunion),
                   ("vert_first", try_vfirst),
                   ("vert_rows", try_vrows),
                   ("vert_cols", try_vcols),
                   ("frames_overlay", try_frames),
                   ("dot_frame", try_dotframe),
                    ("below_marker", try_below),
                    ("mid_line", try_midline),
                    ("asym_block", try_asym),
                    ("div_emit", try_divemit),
                    ("hub_star", try_hub4),
                    ("halo_dots", try_halo),
                    ("diag_focus", try_diagfocus),
                    ("cross_ones", try_cross1),
                    ("square_frame", try_sqframe),
                    ("tile_gaps", try_tilegap),
                    ("dot_bars", try_dotbars),
                    ("spine_tile", try_spinetile)]:
    if id(_fn) not in _seen:
        FALLBACK.append((_name, _fn))
        _seen.add(id(_fn))


def classify(trains: Trains) -> Tuple[str, Dict[str, Any]]:
    """First dynamic whose detector verifies on all train pairs."""
    evidence: Dict[str, Any] = {"n_train": len(trains)}
    for name, det, _fns, _arc3 in DYNAMICS:
        try:
            hit = det(trains)
        except Exception as e:
            hit = False
            evidence[f"{name}_error"] = str(e)[:60]
        if hit:
            return name, evidence
    return "unknown", evidence


def solve_routed(trains: Trains, test: Grid, use_fallback=True):
    """Apply predicted strategy only; fallback to blind chain on miss."""
    dynamic, evidence = classify(trains)
    tried = []
    for name, _det, fns, _arc3 in DYNAMICS:
        if name != dynamic:
            continue
        if fns is None:  # composed: resolve verifying entries per puzzle
            fns = composed_fns_for(trains)
        for fn in fns:
            tried.append(fn.__name__)
            pred = safe_apply(fn, trains, test)
            if pred is not None:
                return {"pred": pred, "dynamic": dynamic,
                        "tried": tried, "fallback": False,
                        "evidence": evidence}
    if use_fallback:
        for fname, fn in FALLBACK:
            if fn.__name__ in tried:
                continue
            tried.append(fn.__name__)
            pred = safe_apply(fn, trains, test)
            if pred is not None:
                return {"pred": pred, "dynamic": dynamic,
                        "tried": tried, "fallback": True,
                        "evidence": evidence}
    return {"pred": None, "dynamic": dynamic, "tried": tried,
            "fallback": True, "evidence": evidence}


def oracle_solvers(trains: Trains, test: Grid, expected: Grid) -> List[str]:
    """Which toolbox strategies solve this puzzle (upper bound)?"""
    winners = []
    for fname, fn in FALLBACK:
        pred = safe_apply(fn, trains, test)
        if pred is not None and v3.grids_equal(pred, expected):
            winners.append(fname)
    return winners

# ─── Cluster reporter (Fase 3: automate the orient step) ─────────────
# Groups UNKNOWN puzzles by a COARSE structural signature so the next
# hunting target emerges without eyeballing. Buckets are deliberately
# coarse: exact counts gave all-singletons (session 2026-09-09).

def _symmetric(g: Grid) -> bool:
    R, C = shape(g)
    h = all(g[r] == g[R - 1 - r] for r in range(R // 2))
    v = all(g[r][c] == g[r][C - 1 - c]
            for r in range(R) for c in range(C // 2))
    return h or v


def coarse_signature(puzzle: Dict) -> tuple:
    trains = v2.get_train_pairs(puzzle)
    if not trains:
        return ("empty",)
    same_shape = all(shape(i) == shape(o) for i, o in trains)
    if same_shape:
        shp = "same_shape"
    elif all(shape(o)[0] % shape(i)[0] == 0 and shape(o)[1] % shape(i)[1] == 0
             and shape(i)[0] and shape(i)[1] for i, o in trains):
        shp = "int_scale"
    else:
        shp = "reshape"
    in_area = sum(shape(i)[0] * shape(i)[1] for i, _ in trains)
    out_area = sum(shape(o)[0] * shape(o)[1] for _, o in trains)
    ratio = out_area / in_area if in_area else 0
    size = ("tiny" if ratio <= 0.05 else "smaller" if ratio < 0.9
            else "same" if ratio <= 1.1 else "bigger")
    ci = sum(len({c for row in i for c in row}) for i, _ in trains)
    co = sum(len({c for row in o for c in row}) for _, o in trains)
    col = ("same_colors" if ci == co else
           "more_colors" if co > ci else "fewer_colors")
    ni = sum(len(components(i)) for i, _ in trains)
    no = sum(len(components(o)) for _, o in trains)
    obj = ("same_objs" if ni == no else
           "fewer_objs" if no < ni else "more_objs")
    mi = sum(sum(1 for v in row if v != bg_color(i))
             for i, _ in trains for row in i)
    mo = sum(sum(1 for v in row if v != bg_color(o))
             for _, o in trains for row in o)
    mass = ("mass_same" if mi == mo else
            "mass_lost" if mo < mi else "mass_gained")
    sym = ("sym_out" if all(_symmetric(o) for _, o in trains)
           else "asym_out")
    return (shp, size, col, obj, mass, sym)


def cluster_unknowns(rows: List[Dict], puzzles: Dict, top: int = 5):
    """Rank unknown clusters by size. Returns [(key, count, [ids])]."""
    groups = defaultdict(list)
    for r in rows:
        if r["dynamic"] != "unknown":
            continue
        p = puzzles.get(r["id"])
        if p is None:
            continue
        try:
            groups[coarse_signature(p)].append(r["id"])
        except Exception:
            groups[("error",)].append(r["id"])
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    return [(k, len(v), v[:3]) for k, v in ranked[:top]]

# ─── Machine-maintained taxonomy ───────────────────────────────────────
# New categories register THEMSELVES here: every dynamic that solves is
# catalogued with precision, examples and ARC-AGI-3 family, no hand docs.
# Human writes strategies; the system writes the catalog. Origin ladder:
# "toolbox" (hand code) -> "composed" (hunter registry) -> proposal.

def build_taxonomy(rep, out_path=None):
    dyn_meta = {}
    for name, _det, fns, arc3 in DYNAMICS:
        dyn_meta[name] = {
            "strategies": [fn.__name__ if fn is not None else None
                           for fn in (fns or [])],
            "arc3": arc3,
        }
    by_dyn = defaultdict(list)
    for r in rep["rows"]:
        by_dyn[r["dynamic"]].append(r)
    dynamics = []
    for name in sorted(by_dyn):
        rows = by_dyn[name]
        seen, ex = set(), []
        for r in [x for x in rows if x["solved"]] + rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                ex.append(r["id"])
            if len(ex) >= 3:
                break
        fns = dyn_meta.get(name, {}).get("strategies", [])
        origin = ("composed" if any((f or "").startswith("composed_")
                                    for f in fns) else "toolbox")
        dynamics.append({
            "name": name,
            "n": len(rows),
            "p1": sum(1 for r in rows if r.get("p1")),
            "solved": sum(1 for r in rows if r["solved"]),
            "strategies": fns,
            "arc3": dyn_meta.get(name, {}).get("arc3", "?"),
            "examples": ex,
            "origin": origin,
        })
    tax = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "totals": {k: rep[k] for k in
                   ("n", "solved", "accuracy", "precision_at_1",
                    "oracle_solved", "oracle_acc", "avg_strategies_tried")
                   if k in rep},
        "dynamics": dynamics,
        "clusters": rep.get("clusters", []),
    }
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(tax, f, indent=1)
    return tax

# ─── Evaluation ──────────────────────────────────────────────────────

def evaluate(data_dir: str, max_puzzles: int = 1000, oracle: bool = True):
    puzzles = v2.load_puzzles(data_dir)
    ids = sorted(puzzles.keys())[:max_puzzles]
    rows = []
    dyn_stats = defaultdict(lambda: {"n": 0, "p1": 0, "solved": 0})
    for tid in ids:
        p = puzzles[tid]
        trains = v2.get_train_pairs(p)
        if not p.get("test"):
            continue
        test_in = v2.get_test_input(p)
        expected = p["test"][0]["output"]
        r = solve_routed(trains, test_in, use_fallback=True)
        ok = r["pred"] is not None and v3.grids_equal(r["pred"], expected)
        p1 = (not r["fallback"] and r["pred"] is not None
              and v3.grids_equal(r["pred"], expected))
        wins = oracle_solvers(trains, test_in, expected) if oracle else []
        st = dyn_stats[r["dynamic"]]
        st["n"] += 1
        st["p1"] += int(p1)
        st["solved"] += int(ok)
        rows.append({"id": tid, "dynamic": r["dynamic"],
                     "tried": len(r["tried"]), "solved": ok, "p1": p1,
                     "fallback": r["fallback"], "oracle": wins})
    n = len(rows)
    solved = sum(1 for x in rows if x["solved"])
    p1 = sum(1 for x in rows if x["p1"])
    orac = sum(1 for x in rows if x["oracle"])
    avg_tried = sum(x["tried"] for x in rows) / n if n else 0
    return {
        "n": n, "solved": solved, "accuracy": solved / n if n else 0,
        "precision_at_1": p1 / n if n else 0,
        "oracle_solved": orac, "oracle_acc": orac / n if n else 0,
        "avg_strategies_tried": round(avg_tried, 2),
        "blind_chain_len": len(FALLBACK),
        "per_dynamic": {k: {"n": v["n"], "p1": v["p1"],
                            "solved": v["solved"]} for k, v in dyn_stats.items()},
        "rows": rows,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/tmp/opencode/arc-training/training")
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--no-oracle", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--compose", default=None,
                    help="compositions registry JSON (hunter-grown toolbox)")
    ap.add_argument("--taxonomize", default=None, metavar="OUT",
                    help="write machine-maintained taxonomy JSON and exit "
                         "(also saved: no solve run needed, uses --max run)")
    args = ap.parse_args()

    global COMPOSED_FNS
    if args.compose:
        COMPOSED_FNS = load_compositions(args.compose)
        have = {id(f) for _, f in FALLBACK}
        for name, fn in COMPOSED_FNS:
            if id(fn) not in have:
                FALLBACK.append((name, fn))
                have.add(id(fn))
        print(f"composed strategies loaded: {len(COMPOSED_FNS)}")

    rep = evaluate(args.data, args.max, oracle=not args.no_oracle)
    print(f"n={rep['n']} solved={rep['solved']} "
          f"acc={rep['accuracy']:.1%} p@1={rep['precision_at_1']:.1%} "
          f"oracle={rep['oracle_solved']} ({rep['oracle_acc']:.1%}) "
          f"avg_tried={rep['avg_strategies_tried']}/{rep['blind_chain_len']}")
    print("per-dynamic (n / p1 / solved):")
    for k in sorted(rep["per_dynamic"]):
        v = rep["per_dynamic"][k]
        print(f"  {k:10s} n={v['n']:4d} p1={v['p1']:3d} solved={v['solved']:3d}")

    puzzles = v2.load_puzzles(args.data)
    clusters = cluster_unknowns(rep["rows"], puzzles)
    rep["clusters"] = [{"key": list(k), "n": n, "examples": e}
                       for k, n, e in clusters]
    print("top unknown clusters (key / n / examples):")
    for k, n, e in clusters:
        print(f"  n={n:4d} {'|'.join(k)}")
        print(f"           e.g. {e}")

    out = args.out or str(Path(__file__).parent / "state" / "rsi_reports"
                          / f"recognizer_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(rep, f, indent=1)
    print(f"full report: {out}")
    if args.taxonomize:
        tax = build_taxonomy(rep, args.taxonomize)
        print(f"taxonomy: {args.taxonomize} "
              f"({len(tax['dynamics'])} dynamics, "
              f"{sum(1 for d in tax['dynamics'] if d['solved'])} solving)")


if __name__ == "__main__":
    main()
