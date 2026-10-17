#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Inference-time agent v1: perceive -> propose -> critic -> decide.

The offline agent S5 asked for: understands the presented puzzle and
decides, alone, with no internet. Deterministic (R10: no random, no
wall-clock branching — caps are fixed counts), stdlib-only.

- perceive: classify() dynamic + palette stats (orientation only).
- propose: EVERY LOO-verifying dynamic's strategies (not just the
  first hit) + fallback chain -> candidates with provenance.
  Grids deduped; agreement counted across producers.
- critic (NO ground truth available): score =
  0.5 * loo_frac + 0.3 * agreement + 0.2 * prior, where loo_frac
  = fraction of train pairs verified via LOO (0.0-1.0, more signal
  than binary), agreement = share of VERIFYING producers emitting
  this exact grid (fallback noise that never verifies cannot boost),
  prior = per-dynamic training p@1 (PRIORS below, era-93 snapshot).
  Tie-break: DYNAMICS order, then fn order (stable, deterministic;
  reproduces legacy routed-first among full ties).
- decide: attempt_1 = argmax; attempt_2 = best DISTINCT grid
  (fixes blind second-attempt p@2=+0 with a ranked runner-up).
- trace: full candidate table + score parts in meta. Accountability:
  every prediction explains itself (dynamic, producers, scores).

PRIORS regen (era-93 taxonomy; rerun when taxonomy moves):
  python3 -c "import json;t=json.load(open('knowledge/arc_taxonomy.json'));print({d['name']:round(d['p1']/d['n'],4) for d in t['dynamics']})"
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import recognizer as R  # noqa: E402

# RSI bridge: load RSI-generated strategies if available
try:
    import rsi_bridge as RSI  # noqa: E402
except Exception:
    RSI = None

# Socratic-lite: declarative scoring (weights as data, parity with M1)
try:
    import predicates as P  # noqa: E402
except Exception:
    P = None

# Priors: empirical p@1 per dynamic over the full ARC training benchmark
# (n>=3). Regen after any taxonomy/bench move:
#   python3 /tmp/opencode/bench_agi2.py 1000   # writes per_dynamic
#   (copy {d: p1/n for n>=3} below)
# A2 (2026-10-16 audit): the era-93 snapshot had n=1..2 per dynamic
# (p1=1.0 trivially, e.g. 1/1) — pure noise. Only dynamics with a real
# training history get a prior now.
PRIORS = {
    'halfold': 0.67,      # 4/6
    'norhalves': 0.86,    # 6/7
    'orhalves': 1.0,      # 3/3
    'recolor': 1.0,       # 3/3
    'retiling': 1.0,      # 11/11
    'rotation': 1.0,      # 3/3
    'sizefill': 1.0,      # 3/3
}

W_VERIFIES, W_AGREE, W_PRIOR = 0.5, 0.3, 0.2


def grid_key(g):
    return tuple(tuple(r) for r in g)


def propose(trains, test):
    """All candidate predictions with provenance.

    Returns list of dicts: {grid, key, producers=[(order, fn, dynamic,
    verifies)], verifies, agreement, prior, score}. Sorted best-first.
    """
    order_of = {name: i for i, (name, _d, _f, _a) in enumerate(R.DYNAMICS)}
    groups = {}

    def add(order, dynamic, fn, pred, verifies, fn_idx=0):
        if pred is None:
            return
        try:
            key = grid_key(pred)
        except Exception:
            return
        prod = (order, fn_idx, fn.__name__, dynamic, verifies)
        g = groups.get(key)
        if g is None:
            groups[key] = {"grid": pred, "key": key, "producers": [prod]}
        else:
            g["producers"].append(prod)

    routed_ids = set()
    for name, det, fns, _arc3 in R.DYNAMICS:
        try:
            hit = det(trains)
        except Exception:
            continue
        if not hit:
            continue
        fns_r = R.composed_fns_for(trains) if fns is None else fns
        for fi, fn in enumerate(fns_r or []):
            routed_ids.add(id(fn))
            try:
                pred = R.safe_apply(fn, trains, test)
            except Exception:
                continue
            if pred is None:
                continue
            try:
                loo_f = R.verify_loo_fraction(fn, trains)
            except Exception:
                loo_f = 0.0
            add(order_of.get(name, 999), name, fn, pred, loo_f,
                fi)
    # B (2026-10-16 A+B): composer — program enumeration certified by
    # the same LOO verify. Sits between fixed dynamics and blind
    # fallback so verified compositions outrank unverified guesses.
    try:
        import composer as C
        for cc in C.candidates(trains, test):
            add(500, "composer:" + cc["name"], cc["fn"], cc["pred"],
                cc["loo"], 0)
    except Exception:
        pass

    for fbi, (fname, fn) in enumerate(R.FALLBACK):
        if id(fn) in routed_ids:
            continue
        try:
            pred = R.safe_apply(fn, trains, test)
        except Exception:
            continue
        if pred is None:
            continue
        try:
            loo_f = R.verify_loo_fraction(fn, trains)
        except Exception:
            loo_f = 0.0
        add(1000 + fbi, "fallback:" + fname, fn, pred, loo_f, 0)

    # RSI-generated strategies: merge as additional candidates
    if RSI is not None:
        try:
            rsi_cands = RSI.rsi_propose(trains, test)
            for rc in rsi_cands:
                add(2000, rc["dynamic"], type("RSIFn", (), {
                    "__name__": rc["fn_name"]
                })(), rc["grid"], rc["loo_frac"], 0)
        except Exception:
            pass

    cands = []
    total_loo = sum(p[4] for g in groups.values() for p in g["producers"])
    for g in groups.values():
        prods = sorted(g["producers"])
        loo_max = max(p[4] for p in prods)
        grid_loo = sum(p[4] for p in prods)
        agreement = (grid_loo / total_loo) if total_loo else 0.0
        prior = max(PRIORS.get(p[3].split(":")[-1], 0.0) for p in prods)
        if P is not None:
            score = P.score({"loo_frac": loo_max, "agreement": agreement,
                             "prior": prior})
        else:
            score = (W_VERIFIES * loo_max + W_AGREE * agreement
                     + W_PRIOR * prior)
        cands.append({"grid": g["grid"], "key": g["key"],
                      "producers": prods, "verifies": loo_max,
                      "agreement": round(agreement, 4), "prior": prior,
                      "score": round(score, 4)})
    cands.sort(key=lambda c: (-c["score"],
                              min(p[0] for p in c["producers"]),
                              min(p[1] for p in c["producers"])))
    return cands


def decide(trains, test):
    """(attempt_1, attempt_2, meta with trace). attempt_2 may be None."""
    cands = propose(trains, test)
    trace = [{"rank": i + 1,
              "dynamic": c["producers"][0][3],
              "fn": c["producers"][0][2],
              "score": c["score"],
              "loo_frac": c["verifies"],
              "agreement": c["agreement"],
              "prior": c["prior"],
              "n_producers": len(c["producers"])} for i, c in enumerate(cands)]
    if not cands:
        dyn, _ev = R.classify(trains)
        return None, None, {"dynamic": dyn, "fallback": True,
                            "trace": trace, "n_candidates": 0}
    top = cands[0]
    # A1 (2026-10-16 audit): attempt_2 must be an INDEPENDENT hypothesis
    # (different strategy family), not just a distinct grid — a same-
    # family twin never saves the miss. Kaggle scores either attempt, so
    # p@2 uplift comes from genuinely different bets. Distinct-grid
    # remains last resort only when every candidate shares the family.
    top_fam = top["producers"][0][3]
    second = next((c for c in cands[1:]
                   if c["producers"][0][3] != top_fam), None)
    if second is None:
        second = next((c for c in cands[1:] if c["key"] != top["key"]),
                      None)
    dyn = top["producers"][0][3]
    if dyn.startswith("fallback:"):
        dyn = "fallback"
    return top["grid"], (second["grid"] if second else None), {
        "dynamic": dyn, "fallback": top["verifies"] < 0.01,
        "trace": trace, "n_candidates": len(cands)}
