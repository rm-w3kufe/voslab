#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""composer — B-phase coverage motor: program enumeration + LOO verify.

Audit 2026-10-16: the 56 fixed dynamics cover 9% of training; the other
91% falls to unverified fallback. The propose→LOO-verify→critic frame
was always right — this module supplies the missing generator: atomic
grid operations (geometry, palette, structure, census) composed as
pairs, every candidate certified by the SAME verify_loo_fraction the
dynamics use. Deterministic (R10): fixed op order, learned params from
trains only, no randomness.

Integration: agent.propose calls composer.candidates(trains, test) and
merges results as producers (order 500). Cost: ~120-180 fns × LOO,
bounded by INVARIANT prefilters (shape ratio, palette size).
"""
from __future__ import annotations

from collections import Counter
from typing import Callable, List, Optional, Tuple

Grid = List[List[int]]
Trains = List[Tuple[Grid, Grid]]

# ─── grid primitives (lists, stdlib only) ───────────────────────────

def shape(g):
    return (len(g), len(g[0]) if g else 0)


def rot90(g):
    R, C = shape(g)
    return [[g[R - 1 - c][r] for c in range(R)] for r in range(C)] if R else g


def flip_h(g):
    return [row[::-1] for row in g]


def flip_v(g):
    return g[::-1]


def transpose(g):
    if not g or not g[0]:
        return g
    return [list(row) for row in zip(*g)]


def anti_transpose(g):
    return transpose(flip_h(g))


def colors(g):
    return {c for row in g for c in row}


def bg_of(trains):
    """Most common corner color across train inputs (background)."""
    cnt = Counter()
    for inp, _out in trains:
        for r in (0, len(inp) - 1):
            for c in (0, len(inp[r]) - 1):
                cnt[inp[r][c]] += 1
    return cnt.most_common(1)[0][0] if cnt else 0


def content_bbox(g, bg):
    rows = [r for r in range(len(g))
            if any(v != bg for v in g[r])]
    if not rows:
        return None
    cols = [c for c in range(len(g[0]))
            if any(g[r][c] != bg for r in rows)]
    if not cols:
        return None
    r0, r1, c0, c1 = rows[0], rows[-1], cols[0], cols[-1]
    return [row[c0:c1 + 1] for row in g[r0:r1 + 1]]


def components_of(g, bg=None):
    """4-connected non-bg components: list of set((r, c))."""
    if bg is None:
        bg = bg_of([(g, g)])
    R, C = shape(g)
    seen = set()
    out = []
    for r0 in range(R):
        for c0 in range(C):
            if g[r0][c0] == bg or (r0, c0) in seen:
                continue
            stack, comp = [(r0, c0)], set()
            seen.add((r0, c0))
            while stack:
                r, c = stack.pop()
                comp.add((r, c))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = r + dr, c + dc
                    if (0 <= nr < R and 0 <= nc < C
                            and (nr, nc) not in seen
                            and g[nr][nc] != bg):
                        seen.add((nr, nc))
                        stack.append((nr, nc))
            out.append(comp)
    return out


# ─── atomic ops: factory(trains) -> fn(trains, grid) -> grid|None ───

def _pure(name, f):
    return (name, lambda trains, _f=f: (lambda _t, g, __f=_f: __f(g)))


ATOMIC = [
    _pure("rot90", rot90),
    _pure("rot180", lambda g: rot90(rot90(g))),
    _pure("rot270", lambda g: rot90(rot90(rot90(g)))),
    _pure("flip_h", flip_h),
    _pure("flip_v", flip_v),
    _pure("transpose", transpose),
    _pure("anti_transpose", anti_transpose),
]

LEARNABLE: List[Tuple[str, Callable[[Trains], Optional[Callable]]]] = []


def _fact_crop(trains):
    """Crop to train-input content bbox (contract: fn(trains, grid))."""
    bg = bg_of(trains)
    for inp, _out in trains:
        if content_bbox(inp, bg) is None:
            return None
    return lambda _t, inp: (content_bbox(inp, bg) or inp)


def _fact_tile_learn(trains):
    """Tile input to match train output shape (constant integer factor)."""
    factors = set()
    for inp, out in trains:
        ir, ic = shape(inp)
        orr, oc = shape(out)
        if ir and ic and orr % ir == 0 and oc % ic == 0:
            factors.add((orr // ir, oc // ic))
        else:
            return None
    if len(factors) != 1:
        return None
    fr, fc = factors.pop()

    def fn(_t, inp):
        R, C = shape(inp)
        return [[inp[r % R][c % C] for c in range(fc * C)]
                for r in range(fr * R)]
    return fn


def _fact_invert_mono(trains):
    """Invert non-bg colors into a consecutive low palette (train-learned)."""
    bg = bg_of(trains)
    seen = set()
    for inp, out in trains:
        seen |= (colors(inp) | colors(out)) - {bg}
    if not seen or len(seen) > 9:
        return None
    order = sorted(seen)
    cmap = {old: i + 1 for i, old in enumerate(order)}

    def fn(_t, inp):
        return [[bg if v == bg else cmap.get(v, v) for v in row]
                for row in inp]
    return fn


def _fact_count_to_color(trains):
    """Per-cell color := count of that cell's color in its row (census)."""

    def fn(_t, inp):
        out = []
        for row in inp:
            cnt = Counter(row)
            out.append([cnt[v] % 10 for v in row])
        return out
    return fn


def _fact_obj_fill(trains):
    """Fill every component with its own modal color (object uniformity)."""
    bg = bg_of(trains)

    def fn(_t, inp):
        g = [row[:] for row in inp]
        for comp in components_of(inp, bg):
            modal = Counter(inp[r][c] for r, c in comp).most_common(1)[0][0]
            for r, c in comp:
                g[r][c] = modal
        return g
    return fn


def _fact_clear_border(trains):
    """Border cells -> background (train-consistent bg)."""
    bg = bg_of(trains)

    def fn(_t, inp):
        R, C = shape(inp)
        g = [row[:] for row in inp]
        for c in range(C):
            g[0][c] = bg
            g[R - 1][c] = bg
        for r in range(R):
            g[r][0] = bg
            g[r][C - 1] = bg
        return g
    return fn


def _fact_color_map(trains):
    """Pointwise color mapping learned from train pairs (consistent only).

    Covers the large 'recolor' family the strict dynamics detectors miss.
    """
    cmap = {}
    for inp, out in trains:
        if shape(inp) != shape(out):
            return None
        for rin, rout in zip(inp, out):
            for a, b in zip(rin, rout):
                if a in cmap and cmap[a] != b:
                    return None
                cmap[a] = b
    if not cmap or len(set(cmap.values())) == len(colors(
            trains[0][1])) and all(k == v for k, v in cmap.items()):
        return None  # identity or empty: no signal
    return lambda _t, g: [[cmap.get(v, v) for v in row] for row in g]


def _fact_sym_h(trains):
    """Complete horizontal symmetry: left half mirrors onto right."""

    def fn(_t, g):
        R, C = shape(g)
        if C < 2:
            return None
        out = [row[:] for row in g]
        for r in range(R):
            for c in range((C + 1) // 2):
                out[r][C - 1 - c] = g[r][c]
        return out
    return fn


def _fact_sym_v(trains):
    """Complete vertical symmetry: top half mirrors onto bottom."""

    def fn(_t, g):
        R, C = shape(g)
        if R < 2:
            return None
        out = [row[:] for row in g]
        for r in range((R + 1) // 2):
            out[R - 1 - r] = g[r][:]
        return out
    return fn


def _fact_quadrant_copy(trains):
    """Tile top-left quadrant across the whole grid."""

    def fn(_t, g):
        R, C = shape(g)
        hr, hc = R // 2, C // 2
        if hr == 0 or hc == 0:
            return None
        q = [row[:hc] for row in g[:hr]]
        return [[q[r % hr][c % hc] for c in range(C)] for r in range(R)]
    return fn


def _fact_objcount_row(trains):
    """Per-cell color := number of objects intersecting that row (mod 10)."""
    bg = bg_of(trains)

    def fn(_t, g):
        comps = components_of(g, bg)
        cnt_rows = Counter()
        for comp in comps:
            for r in {rr for rr, _cc in comp}:
                cnt_rows[r] += 1
        return [[cnt_rows[r] % 10 for _c in g[r]] for r in range(len(g))]
    return fn


LEARNABLE = [
    ("crop_content", _fact_crop),
    ("tile_learn", _fact_tile_learn),
    ("invert_mono", _fact_invert_mono),
    ("count_to_color", _fact_count_to_color),
    ("obj_fill", _fact_obj_fill),
    ("clear_border", _fact_clear_border),
    ("color_map", _fact_color_map),
    ("sym_h", _fact_sym_h),
    ("sym_v", _fact_sym_v),
    ("quadrant_copy", _fact_quadrant_copy),
    ("objcount_row", _fact_objcount_row),
]


# ─── composition + candidates ───────────────────────────────────────

def _shape_preserving(trains):
    """True when every train output matches its input shape exactly."""
    return all(shape(i) == shape(o) for i, o in trains)


def _palette_bound(trains):
    """Palette size of train outputs (census ops capped by this)."""
    out_cols = set()
    for _i, o in trains:
        out_cols |= colors(o)
    return len(out_cols)


def candidates(trains, test):
    """Enumerate composed programs, return verified-friendly list.

    Each item: {name, fn, pred, loo} — pred already applied to test via
    safe semantics (fn may return None). Caller runs verify_loo_fraction.
    Prefilters: pure pairs always (cheap); learnables only when their
    factory resolves; census ops only when train palette > 2 (else a
    constant census cannot express the output).
    """
    import recognizer as R  # local import: keep composer standalone-testable

    built = []  # (name, fn)
    for name, fac in ATOMIC:
        fn = fac(trains)
        if fn is None:
            continue
        built.append((name, fn))
    for name, fac in LEARNABLE:
        try:
            fn = fac(trains)
        except Exception:
            fn = None
        if fn is None:
            continue
        built.append((name, fn))

    # census op is only meaningful when outputs have >2 colors
    palette_out = _palette_bound(trains)

    out = []
    seen = set()

    def emit(name, fn):
        if name in seen:
            return
        pred = R.safe_apply(fn, trains, test)
        if pred is None:
            return
        seen.add(name)
        try:
            loo = R.verify_loo_fraction(fn, trains)
        except Exception:
            loo = 0.0
        out.append({"name": name, "fn": fn, "pred": pred, "loo": loo})

    for name, fn in built:
        emit("c:" + name, fn)

    # pairs: op2 ∘ op1 (skip census-containing pairs unless palette ok)
    census_names = {"count_to_color"}
    for n1, f1 in built:
        for n2, f2 in built:
            if (n1 in census_names or n2 in census_names) and palette_out <= 2:
                continue

            def composed(trains, g, _f1=f1, _f2=f2):
                g1 = _f1(trains, g)
                if g1 is None:
                    return None
                return _f2(trains, g1)
            emit(f"c:{n2}∘{n1}", composed)
    return out
