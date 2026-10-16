#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""T2 template search: parameterized mechanism families x unknowns.

Every candidate is a strict LOO-verified (detector, strategy) pair —
no per-puzzle fitting beyond a learned mark color (same contract as
the hand-built detectors). Hits still need sweep + hand-verify +
full-1000 before any close (T2 proposes, gates dispose).

    python3 arc-agi3/template_search.py --selftest   # known puzzles
    python3 arc-agi3/template_search.py --data data/training [--out h.json]
    python3 arc-agi3/template_search.py --dossier 3  # mechanical
            profile of top-3 unknown-cluster examples (hunt loop T2v2)
    python3 arc-agi3/template_search.py --dividers [--cluster 2]
            # divider-emitter parametric family (generalized divemit:
            # divider color x emitter x recolor x mover), LOO-verified,
            # optionally restricted to top-K cluster examples.
"""
import argparse
import glob
import itertools
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import recognizer as R  # noqa: E402
import solver_smart_v2 as v2  # noqa: E402
import solver_v3 as v3  # noqa: E402


def shape(g):
    return (len(g), len(g[0])) if g else (0, 0)


# ─── splits: input -> list of parts (grids) or None ─────────────────
def sp_halves_h_even(inp):
    Rr = len(inp)
    if Rr % 2:
        return None
    h = Rr // 2
    return [inp[:h], inp[h:]]


def sp_halves_h_div(inp):
    Rr = len(inp)
    if Rr % 2 == 0:
        return None
    dh = Rr // 2
    if len(set(inp[dh])) != 1 or inp[dh][0] == R.bg_color(inp):
        return None
    return [inp[:dh], inp[dh + 1:]]


def sp_halves_v_even(inp):
    Rr, Cc = shape(inp)
    if Cc % 2:
        return None
    w = Cc // 2
    return [[row[:w] for row in inp], [row[w:] for row in inp]]


def sp_strips(inp):
    s = R._vstrips_split(inp)
    return s if s and len(s) >= 2 else None


def sp_quads_plain(inp):
    q = R._quads_split(inp)
    if q is None:
        return None
    return [q["TL"], q["TR"], q["BL"], q["BR"]]


def sp_quads_div(inp):
    q = R._qcollage_split(inp)
    if q is None:
        return None
    return [q["TL"][0], q["TR"][0], q["BL"][0], q["BR"][0]]


SPLITS = {
    "halvesH-even": sp_halves_h_even,
    "halvesH-div": sp_halves_h_div,
    "halvesV-even": sp_halves_v_even,
    "strips": sp_strips,
    "quads-plain": sp_quads_plain,
    "quads-div": sp_quads_div,
}


def _ground(top, bot):
    g = ({v for row in top for v in row} &
         {v for row in bot for v in row})
    return next(iter(g)) if len(g) == 1 else None


def _dims_ok(parts, out):
    return (len(parts[0]) == len(out) and
            len(parts[0][0]) == len(out[0]) and
            all(shape(p) == shape(parts[0]) for p in parts))


# ─── boolops on 2 parts (learned mark, like norhalves) ──────────────
def _boolop_params(trains, split, op):
    marks = set()
    for inp, out in trains:
        parts = split(inp)
        if parts is None or len(parts) != 2:
            return None
        a, b = parts
        g = _ground(a, b)
        if g is None or not _dims_ok(parts, out):
            return None
        h, w = shape(a)
        fig = {v for row in out for v in row} - {g}
        if len(fig) != 1:
            return None
        m = next(iter(fig))
        for r in range(h):
            for c in range(w):
                fa, fb = (a[r][c] != g), (b[r][c] != g)
                want = m if op(fa, fb) else g
                if out[r][c] != want:
                    return None
        marks.add(m)
    return next(iter(marks)) if len(marks) == 1 else None


def _make_boolop(split, op, name):
    def try_fn(trains, test):
        if not trains:
            return None
        m = _boolop_params(trains, split, op)
        if m is None:
            return None
        parts = split(test)
        if parts is None or len(parts) != 2:
            return None
        a, b = parts
        g = _ground(a, b)
        if g is None:
            return None
        h, w = shape(a)
        return [[m if op(a[r][c] != g, b[r][c] != g) else g
                 for c in range(w)] for r in range(h)]
    try_fn.__name__ = name
    return try_fn


# ─── priorities (first non-bg, no learning) ─────────────────────────
def _prio_params(trains, split, order):
    for inp, out in trains:
        parts = split(inp)
        if parts is None or len(parts) != len(order):
            return None
        if not _dims_ok(parts, out):
            return None
        bg = R.bg_color(inp)
        h, w = shape(parts[0])
        for r in range(h):
            for c in range(w):
                v = 0
                for i in order:
                    if parts[i][r][c] != bg:
                        v = parts[i][r][c]
                        break
                if out[r][c] != v:
                    return None
    return True


def _make_prio(split, order, name):
    def try_fn(trains, test):
        if not trains:
            return None
        if _prio_params(trains, split, order) is None:
            return None
        parts = split(test)
        if parts is None or len(parts) != len(order):
            return None
        bg = R.bg_color(test)
        h, w = shape(parts[0])
        return [[next((parts[i][r][c] for i in order
                       if parts[i][r][c] != bg), 0)
                 for c in range(w)] for r in range(h)]
    try_fn.__name__ = name
    return try_fn


# ─── shapes around singletons (LOCAL family) ────────────────────────
# Anchor = size-1 components grouped by color (cap 3 colors, else skip).
# Shapes = EMPTY + all non-empty subsets of PLUS1/X1 arms (15+15).
# Assignment anchor-color -> shape searched per puzzle; painted color
# learned singleton per shape across trains. Clipped at grid edge.
# Overlap with different colors -> fail. Colors must match across
# trains/folds/test (strict). Strict LOO (exact full-grid repro).
PLUS1 = [(-1, 0), (1, 0), (0, -1), (0, 1)]
X1 = [(-1, -1), (-1, 1), (1, -1), (1, 1)]


def _all_subsets(cells):
    return [[cells[i] for i in range(len(cells)) if mask >> i & 1]
            for mask in range(1, 1 << len(cells))]


_SHAPE_CELLS = ({"EMPTY": []} |
                {f"P{i}": s for i, s in enumerate(_all_subsets(PLUS1))} |
                {f"X{i}": s for i, s in enumerate(_all_subsets(X1))})
_SHAPE_NAMES = sorted(_SHAPE_CELLS)


def _shape_anchors(inp, bg):
    comps = R.components(inp, bg=bg)
    bycolor = {}
    for c in comps:
        if c["size"] != 1:
            continue
        bycolor.setdefault(c["color"], []).append(c["anchor"])
    if not bycolor or len(bycolor) > 3:
        return None
    return bycolor


def _make_shapes_try(assign):
    def try_fn(trains, test):
        if not trains:
            return None
        paint = {}
        for inp, out in trains:
            bg = R.bg_color(inp)
            bycolor = _shape_anchors(inp, bg)
            if bycolor is None or set(bycolor) != set(assign):
                return None
            if shape(inp) != shape(out):
                return None
            Rr, Cc = shape(inp)
            for color, cells in bycolor.items():
                for (r, c) in cells:
                    for dr, dc in _SHAPE_CELLS[assign[color]]:
                        rr, cc = r + dr, c + dc
                        if not (0 <= rr < Rr and 0 <= cc < Cc):
                            continue
                        if out[rr][cc] == bg or out[rr][cc] == inp[rr][cc]:
                            continue
                        s = assign[color]
                        if s in paint and paint[s] != out[rr][cc]:
                            return None
                        paint[s] = out[rr][cc]
        bg = R.bg_color(test)
        bycolor = _shape_anchors(test, bg)
        if bycolor is None or set(bycolor) != set(assign):
            return None
        Rr, Cc = shape(test)
        got = [row[:] for row in test]
        for color, cells in bycolor.items():
            s = assign[color]
            if s not in paint:
                return None
            for (r, c) in cells:
                for dr, dc in _SHAPE_CELLS[s]:
                    rr, cc = r + dr, c + dc
                    if not (0 <= rr < Rr and 0 <= cc < Cc):
                        continue
                    if got[rr][cc] != bg and got[rr][cc] != paint[s]:
                        return None
                    got[rr][cc] = paint[s]
        return got
    try_fn.__name__ = "t_shapes"
    return try_fn


def search_shapes(pid, puzzles):
    p = puzzles[pid]
    t = v2.get_train_pairs(p)
    bg0 = R.bg_color(t[0][0])
    bycolor0 = _shape_anchors(t[0][0], bg0)
    if bycolor0 is None:
        return []
    colors = sorted(bycolor0)
    hits = []
    for combo in itertools.product(_SHAPE_NAMES, repeat=len(colors)):
        assign = dict(zip(colors, combo))
        fn = _make_shapes_try(assign)
        try:
            if not R.verify_loo(fn, t):
                continue
            pred = fn(t, v2.get_test_input(p))
        except Exception:
            continue
        if pred is not None and v3.grids_equal(
                pred, p["test"][0]["output"]):
            hits.append(assign)
    return hits




# ─── divider-emitter parametric family (T2v2, generalizes divemit) ───
# Same mechanism as recognizer._divemit_apply, colors parameterized:
# D = divider/ray, E = emitter, N = recolor of emitter originals
# (usually a NEW color), M = mover (far-edge-justified, order kept).
# Implemented by color-remap onto the verified engine fn (D->8,
# E->4, M->2, back: 8->D, 4->E, 3->N, 2->M): zero engine risk,
# strictness inherited (exactly one full-D line, E/M opposite
# sides, gaps bg-only). Orientation is per-grid, so mixed puzzles
# like 05a7bcf2 verify. LOO decides, as always.

def _make_divemit_try(D, E, N, M, name):
    fwd = {D: 8, E: 4, M: 2}
    bwd = {8: D, 4: E, 3: N, 2: M}

    def try_fn(trains, test):
        if not trains:
            return None
        for g in [i for i, _ in trains] + [test]:
            bg = R.bg_color(g)
            if bg in (D, E, M):
                return None
            pal = {v for row in g for v in row}
            if N in pal or not {D, E, M} <= pal:
                return None
            if pal - {bg, D, E, M}:
                return None
        mapped = [[fwd.get(v, v) for v in row] for row in test]
        got = R._divemit_apply(mapped)
        if got is None:
            return None
        return [[bwd.get(v, v) for v in row] for row in got]
    try_fn.__name__ = name
    return try_fn


def _full_line_colors(g):
    Rr, Cc = shape(g)
    out = set()
    for r in range(Rr):
        if len(set(g[r])) == 1:
            out.add(g[r][0])
    for c in range(Cc):
        col = {g[r][c] for r in range(Rr)}
        if len(col) == 1:
            out.add(next(iter(col)))
    return out


def search_dividers(pid, puzzles):
    p = puzzles[pid]
    t = v2.get_train_pairs(p)
    if not t:
        return []
    test = v2.get_test_input(p)
    exp = p["test"][0]["output"]
    d_cands = set.intersection(*[_full_line_colors(i) for i, _ in t])
    d_cands = {d for d in d_cands
               if all(d != R.bg_color(i) for i, _ in t)}
    pals = [{v for row in i for v in row} - {R.bg_color(i)} for i, _ in t]
    common = set.intersection(*pals)
    testpal = {v for row in test for v in row}
    trainpal = set().union(*[{v for row in i for v in row} for i, _ in t])
    hits = []
    for D in sorted(d_cands):
        others = sorted(common - {D})
        for E in others:
            for M in others:
                if M == E:
                    continue
                for N in range(10):
                    if N in trainpal or N in testpal:
                        continue
                    if N in (D, E, M):
                        continue
                    fn = _make_divemit_try(
                        D, E, N, M, f"t_divemit_{D}{E}{N}{M}")
                    try:
                        if not R.verify_loo(fn, t):
                            continue
                        pred = fn(t, test)
                    except Exception:
                        continue
                    if pred is not None and v3.grids_equal(pred, exp):
                        hits.append((D, E, N, M))
    return hits


def selftest_dividers():
    puzzles = v2.load_puzzles("data/training")
    hits = search_dividers("05a7bcf2", puzzles)
    ok = (8, 4, 3, 2) in hits
    print(f"05a7bcf2 divider-family: hits={hits} want=(8,4,3,2) -> {ok}")
    return ok


# ─── hunt dossier (T2v2): mechanical profile, no hypothesis ─────────
# Ranks unknown clusters exactly like recognizer.cluster_unknowns and
# prints a compact per-example profile (dims, palettes, dividers,
# components, mass). Feeds T3 analysis; writes nothing.

def _profile(pid, p):
    t = v2.get_train_pairs(p)
    lines = [f"--- {pid} ntrain={len(t)}"]
    for k, (inp, out) in enumerate(t):
        bg = R.bg_color(inp)
        pi = sorted({v for row in inp for v in row})
        po = sorted({v for row in out for v in row})
        new = sorted(set(po) - set(pi))
        lost = sorted(set(pi) - set(po))
        dl = sorted((f"R{r}:{inp[r][0]}" for r in range(len(inp))
                     if len(set(inp[r])) == 1))
        dc = sorted((f"C{c}:{inp[0][c]}" for c in range(len(inp[0]))
                     if len({inp[r][c] for r in range(len(inp))}) == 1))
        ci = len(R.components(inp, bg=bg))
        co = len(R.components(out, bg=R.bg_color(out)))
        mi = sum(1 for row in inp for v in row if v != bg)
        mo = sum(1 for row in out for v in row
                 if v != R.bg_color(out))
        lines.append(
            f"  t{k} {len(inp)}x{len(inp[0])}->{len(out)}x{len(out[0])}"
            f" bg={bg} pal{pi}->{po} new={new} lost={lost}"
            f" fulllines={dl + dc} comp{ci}->{co} mass{mi}->{mo}")
    ti = v2.get_test_input(p)
    bg = R.bg_color(ti)
    dl = sorted((f"R{r}:{ti[r][0]}" for r in range(len(ti))
                 if len(set(ti[r])) == 1))
    dc = sorted((f"C{c}:{ti[0][c]}" for c in range(len(ti[0]))
                 if len({ti[r][c] for r in range(len(ti))}) == 1))
    lines.append(
        f"  TEST {len(ti)}x{len(ti[0])} bg={bg}"
        f" pal={sorted({v for row in ti for v in row})}"
        f" fulllines={dl + dc} comp={len(R.components(ti, bg=bg))}")
    return "\n".join(lines)


def dossier(report_path, data, top=3, per=4):
    rep = json.load(open(report_path))
    puzzles = v2.load_puzzles(data)
    groups = {}
    for r in rep["rows"]:
        if r["dynamic"] != "unknown":
            continue
        p = puzzles.get(r["id"])
        if p is None:
            continue
        groups.setdefault(R.coarse_signature(p), []).append(r["id"])
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top]
    for key, ids in ranked:
        print(f"=== n={len(ids)} {'|'.join(key)} ===")
        for pid in ids[:per]:
            print(_profile(pid, puzzles[pid]))


# Orientation adapts per input (like the anomaly detector): a row of
# 3x3 blocks, else a column of 3x3 blocks, else None.
def _crop_blocks(inp, bh=3, bw=3):
    Rr, Cc = shape(inp)
    if Rr == bh and Cc % bw == 0 and Cc >= 2 * bw:
        return [[row[c:c + bw] for row in inp]
                for c in range(0, Cc, bw)]
    if Cc == bw and Rr % bh == 0 and Rr >= 2 * bh:
        return [[row[:] for row in inp[r:r + bh]]
                for r in range(0, Rr, bh)]
    return None


def _block_key(b, bg, kind):
    if kind == "count":
        return sum(1 for row in b for v in row if v != bg)
    if kind == "size":
        return (len(b), len(b[0]))
    if kind == "shape":
        pts = {(r, c) for r, row in enumerate(b)
               for c, v in enumerate(row) if v != bg}
        return (len(pts), tuple(sorted(pts)))
    if kind == "colors":
        return tuple(sorted({v for row in b for v in row if v != bg}))
    return None


def _crop_params(trains, bh, bw, kind):
    for inp, out in trains:
        blocks = _crop_blocks(inp, bh, bw)
        if not blocks:
            return None
        bg = R.bg_color(inp)
        keys = [_block_key(b, bg, kind) for b in blocks]
        freq = Counter(keys)
        singles = [k for k, n in freq.items() if n == 1]
        if len(singles) != 1:
            return None
        if blocks[keys.index(singles[0])] != out:
            return None
    return True


def _make_crop(bh, bw, kind, name):
    def try_fn(trains, test):
        if not trains:
            return None
        if _crop_params(trains, bh, bw, kind) is None:
            return None
        blocks = _crop_blocks(test, bh, bw)
        bg = R.bg_color(test)
        keys = [_block_key(b, bg, kind) for b in blocks]
        freq = Counter(keys)
        singles = [k for k, n in freq.items() if n == 1]
        if len(singles) != 1:
            return None
        return [row[:] for row in blocks[keys.index(singles[0])]]
    try_fn.__name__ = name
    return try_fn


def build_configs():
    cfgs = []
    ops = {"NOR": lambda a, b: not a and not b,
           "XOR": lambda a, b: a != b,
           "OR": lambda a, b: a or b,
           "AND": lambda a, b: a and b}
    for sname, sfn in SPLITS.items():
        for oname, op in ops.items():
            cfgs.append((f"{sname}+{oname}",
                         _make_boolop(sfn, op, f"t_{sname}_{oname}")))
        for N in (2, 3, 4):
            for order in itertools.permutations(range(N)):
                oname = "".join(map(str, order))
                cfgs.append((f"{sname}~{oname}",
                             _make_prio(sfn, order,
                                        f"t_{sname}_{oname}")))
    for kind in ("count", "size", "shape", "colors"):
        cfgs.append((f"crop3x3:{kind}",
                     _make_crop(3, 3, kind, f"t_crop3x3_{kind}")))
    return cfgs


def evaluate_config(try_fn, trains):
    try:
        ok = R.verify_loo(try_fn, trains)
    except Exception:
        return False
    return bool(ok)


def selftest():
    cases = {
        "fafffa47": {"halvesH-even+NOR"},
        "94f9d214": {"halvesH-even+NOR"},
        "6430c8c4": {"halvesH-div+NOR"},
        "99b1bc43": {"halvesH-div+XOR"},
        "ce4f8723": {"halvesH-div+OR"},
        "a87f7484": {"crop3x3:count"},
        "a68b268e": {"quads-div~0123"},
        "75b8110e": {"quads-plain~1230"},
    }
    cfgs = dict(build_configs())
    print(f"configs: {len(cfgs)}")
    puzzles = v2.load_puzzles("data/training")
    fails = []
    for pid, want in cases.items():
        t = v2.get_train_pairs(puzzles[pid])
        hits = sorted(n for n, f in cfgs.items() if evaluate_config(f, t))
        ok = bool(want & set(hits))
        extra = sorted(set(hits) - want)
        print(f"{pid}: want⊆hits={ok} hits={hits}"
              f"{' EXTRA:' + str(extra) if extra else ''}")
        if not ok:
            fails.append(pid)
    # scope-check: pack debe dar cero (fuera de scope T2v1)
    t = v2.get_train_pairs(puzzles["137eaa0f"])
    hits = sorted(n for n, f in cfgs.items() if evaluate_config(f, t))
    print(f"137eaa0f (scope): hits={hits or 'NINGUNO (bien)'}")
    return fails


def run_dividers(rep, puzzles, a):
    import time
    unsolved = _target_ids(rep, puzzles, a.cluster, a.examples)
    print(f"divider-family over {len(unsolved)} puzzles")
    hits, t0 = {}, time.time()
    for i, pid in enumerate(unsolved):
        try:
            h = search_dividers(pid, puzzles)
        except Exception as e:
            print(f"EXC {pid}: {str(e)[:80]}")
            continue
        if h:
            hits[pid] = h
            print(f"HIT {pid}: {h}")
        if (i + 1) % 25 == 0:
            dt = time.time() - t0
            print(f"  {i + 1}/{len(unsolved)} ... {len(hits)} con hits"
                  f" ({dt:.0f}s)")
    dt = time.time() - t0
    print(f"hits: {len(hits)}/{len(unsolved)} ({dt:.0f}s)")
    for pid in sorted(hits):
        print(f"  {pid}: {hits[pid]}")
    if a.out:
        json.dump(hits, open(a.out, "w"))
        print(f"hits -> {a.out}")
    return 0


def _target_ids(rep, puzzles, cluster, examples):
    unsolved = [r["id"] for r in rep["rows"] if not r["solved"]]
    if not cluster:
        return sorted(unsolved)
    groups = {}
    for pid in unsolved:
        p = puzzles.get(pid)
        if p is None:
            continue
        groups.setdefault(R.coarse_signature(p), []).append(pid)
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:cluster]
    out = []
    for key, ids in ranked:
        print(f"cluster n={len(ids)} {'|'.join(key)}")
        out.extend(sorted(ids)[:examples] if examples else sorted(ids))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/training")
    ap.add_argument("--report", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dossier", type=int, default=0, metavar="K",
                    help="print mechanical profile of top-K unknown "
                         "clusters (default 4 examples each) and exit")
    ap.add_argument("--per", type=int, default=4)
    ap.add_argument("--dividers", action="store_true",
                    help="run divider-emitter parametric family instead "
                         "of the static configs")
    ap.add_argument("--cluster", type=int, default=0, metavar="K",
                    help="restrict hunt to top-K unknown clusters")
    ap.add_argument("--examples", type=int, default=0, metavar="E",
                    help="with --cluster, cap examples per cluster "
                         "(default: all)")
    a = ap.parse_args()
    if a.selftest:
        fails = selftest()
        if not selftest_dividers():
            fails.append("05a7bcf2-dividers")
        print("SELFTEST:", "PASS" if not fails else f"FAIL {fails}")
        return 0 if not fails else 1
    if a.report is None:
        cands = sorted(glob.glob("arc-agi3/state/rsi_reports/"
                                 "recognizer_*.json"))
        a.report = cands[-1]
    if a.dossier:
        dossier(a.report, a.data, top=a.dossier, per=a.per)
        return 0
    rep = json.load(open(a.report))
    puzzles = v2.load_puzzles(a.data)
    if a.dividers:
        return run_dividers(rep, puzzles, a)
    unsolved = _target_ids(rep, puzzles, a.cluster, a.examples)
    cfgs = build_configs()
    print(f"configs: {len(cfgs)}, unsolved: {len(unsolved)}")
    hits = {}
    for i, pid in enumerate(sorted(unsolved)):
        p = puzzles.get(pid)
        if p is None:
            continue
        t = v2.get_train_pairs(p)
        for name, fn in cfgs:
            if evaluate_config(fn, t):
                test = v2.get_test_input(p)
                try:
                    pred = fn(t, test)
                except Exception:
                    continue
                if pred is not None and v3.grids_equal(
                        pred, p["test"][0]["output"]):
                    hits.setdefault(name, []).append(pid)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(unsolved)} ... "
                  f"{sum(len(v) for v in hits.values())} hits")
    print(f"configs con hits: {len(hits)}")
    for name in sorted(hits):
        print(f"  {name}: {len(hits[name])} {hits[name][:8]}")
    if a.out:
        json.dump(hits, open(a.out, "w"))
        print(f"hits -> {a.out}")


if __name__ == "__main__":
    main()
