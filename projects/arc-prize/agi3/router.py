#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
Neural-free router — k-NN ranking + decision-tree mining over own labels.

No third-party deps (numpy only): auditable, deterministic (R10).

  solve order today : fixed FALLBACK chain (avg 8.35 tries, oracle 34)
  solve order router: k-NN votes from similar puzzles -> try winners first

Labels come from recognizer reports (dynamic + oracle solvers per puzzle).
Features are SINGLE-GRID computable (no train pairs needed at route time
for the test input; pair deltas use trains only) so the SAME featurizer
serves AGI-3 states. Shared vocabulary with agi3_collect.embed.

Validation (honest): leave-one-out over oracle-solvable puzzles.
  metric = rank of first true solver under kNN order vs fixed order.
Routing only REORDERS the chain (fallback intact) -> 0 regressions
by construction.

Tree miner: depth<=3 CART from scratch; splits are readable detector
hypotheses (machine proposes, LOO disposes).
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import solver_smart_v2 as v2
import solver_v3 as v3
from recognizer import (FALLBACK, bg_color, components, shape,
                        coarse_signature)
from agi3_collect import embed as env_embed

CHAIN = [name for name, _ in FALLBACK]
N_STRAT = len(CHAIN)

# ─── Single-grid features (AGI-3 reusable) ───────────────────────────

SINGLE_KEYS = ([f"h{i}" for i in range(16)] + ["mass", "nobjs", "sym",
               "r0", "r1", "c0", "c1", "ncolors", "aspect", "density"])


def single_grid_feats(grid):
    """One grid -> named float vector. No pairs needed."""
    base = env_embed(grid)  # 23 dims: hist16, mass, nobjs, sym, bbox4
    R, C = shape(grid)
    ncolors = len({int(c) for row in grid for c in row})
    aspect = (R / C) if C else 0.0
    bg = bg_color(grid)
    edge = 0
    tot = 0
    for r in range(R):
        for c in range(C):
            tot += 1
            if int(grid[r][c]) != bg:
                if r == 0 or c == 0 or r == R - 1 or c == C - 1:
                    edge += 1
    density = (edge / tot) if tot else 0.0
    vals = base + [float(ncolors), aspect, density]
    return dict(zip(SINGLE_KEYS, vals))


SIG_AXES = ["shp", "size", "col", "obj", "mass", "sym"]


def puzzle_feats(puzzle):
    """Puzzle -> feature dict. Test OUTPUT never touched (no leakage)."""
    trains = v2.get_train_pairs(puzzle)
    test_in = v2.get_test_input(puzzle)
    feats = {}
    for k, v in single_grid_feats(test_in).items():
        feats[f"test_{k}"] = v
    sig = coarse_signature(puzzle)
    for ax, val in zip(SIG_AXES, sig):
        feats[f"sig_{ax}={val}"] = 1.0
    # pair deltas (trains only)
    same = all(shape(i) == shape(o) for i, o in trains)
    feats["delta_same_shape"] = float(same)
    feats["delta_scale"] = float(
        all(shape(o)[0] % shape(i)[0] == 0 and
            shape(o)[1] % shape(i)[1] == 0 and shape(i)[0] > 0 and
            shape(i)[1] > 0 for i, o in trains))
    feats["n_train"] = float(len(trains))
    return feats


def featurize(ids, puzzles, key_order=None):
    rows = []
    for tid in ids:
        f = puzzle_feats(puzzles[tid])
        rows.append(f)
    if key_order is None:
        keys = set()
        for f in rows:
            keys.update(f.keys())
        key_order = sorted(keys)
    mat = np.array([[f.get(k, 0.0) for k in key_order] for f in rows],
                   dtype=float)
    return mat, key_order


def standardize_fit(mat):
    mu = mat.mean(axis=0)
    sd = mat.std(axis=0)
    sd[sd == 0] = 1.0
    return mu, sd


def standardize_apply(mat, mu, sd):
    return (mat - mu) / sd

# ─── k-NN ranker ─────────────────────────────────────────────────────

def knn_rank(query, mat, oracles, k=7, exclude=None):
    """Rank strategies by neighbor votes. Returns ordered strategy names."""
    d = np.sqrt(((mat - query) ** 2).sum(axis=1))
    idx = np.argsort(d)
    votes = defaultdict(float)
    used = 0
    for j in idx:
        if exclude is not None and j == exclude:
            continue
        w = 1.0 / (1.0 + d[j])
        for s in oracles[j]:
            votes[s] += w
        used += 1
        if used >= k:
            break
    ranked = sorted(votes, key=lambda s: -votes[s])
    # append never-voted strategies in fixed order (fallback intact)
    for s in CHAIN:
        if s not in votes:
            ranked.append(s)
    return ranked


def rank_of_first(ranked, oracles_row):
    want = set(oracles_row)
    for i, s in enumerate(ranked):
        if s in want:
            return i
    return len(ranked)


def fixed_rank(oracles_row):
    want = set(oracles_row)
    for i, s in enumerate(CHAIN):
        if s in want:
            return i
    return len(CHAIN)


def evaluate_knn(ids, puzzles, oracles, k=7):
    mat, _ = featurize(ids, puzzles)
    mu, sd = standardize_fit(mat)
    z = standardize_apply(mat, mu, sd)
    oracle_lists = [oracles[i] for i in ids]
    solvable = [i for i, o in enumerate(oracle_lists) if o]
    ranks_knn, ranks_fix = [], []
    for i in solvable:
        ranked = knn_rank(z[i], z, oracle_lists, k=k, exclude=i)
        ranks_knn.append(rank_of_first(ranked, oracle_lists[i]))
        ranks_fix.append(fixed_rank(oracle_lists[i]))
    top1 = sum(1 for r in ranks_knn if r == 0)
    top3 = sum(1 for r in ranks_knn if r <= 2)
    return {
        "n_solvable": len(solvable),
        "avg_rank_knn": round(float(np.mean(ranks_knn)), 2) if ranks_knn else 0,
        "avg_rank_fixed": round(float(np.mean(ranks_fix)), 2) if ranks_fix else 0,
        "top1": top1, "top3": top3,
        "k": k,
    }

# ─── Minimal CART (hypothesis miner) ─────────────────────────────────

def gini(counts, n):
    return 1.0 - sum((c / n) ** 2 for c in counts) if n else 0.0


def best_split(X, y, keys, max_thresholds=12):
    n = len(y)
    base = gini(Counter(y).values(), n)
    best = None
    for j, key in enumerate(keys):
        col = X[:, j]
        uniq = sorted(set(col.tolist()))
        if len(uniq) < 2:
            continue
        step = max(1, len(uniq) // max_thresholds)
        for t in range(0, len(uniq) - 1, step):
            thr = (uniq[t] + uniq[t + 1]) / 2.0
            left = [y[i] for i in range(n) if col[i] <= thr]
            right = [y[i] for i in range(n) if col[i] > thr]
            if not left or not right:
                continue
            g = (len(left) * gini(Counter(left).values(), len(left)) +
                 len(right) * gini(Counter(right).values(), len(right))) / n
            gain = base - g
            if best is None or gain > best[0]:
                best = (gain, key, thr, Counter(left).most_common(2),
                        Counter(right).most_common(2))
    return best


def mine_tree(ids, puzzles, labels, keys, depth=0, max_depth=3,
              min_leaf=5, prefix=""):
    n = len(ids)
    top = Counter(labels).most_common(3)
    node = {"n": n, "top": [(k, v) for k, v in top], "rule": prefix or "root"}
    if depth >= max_depth or n < 2 * min_leaf or len(set(labels)) == 1:
        return node
    X, _ = featurize(ids, puzzles, keys)
    split = best_split(X, labels, keys)
    if split is None or split[0] <= 0:
        return node
    gain, key, thr, ltop, rtop = split
    col = X[:, keys.index(key)]
    li = [ids[i] for i in range(n) if col[i] <= thr]
    ri = [ids[i] for i in range(n) if col[i] > thr]
    ll = [labels[i] for i in range(n) if col[i] <= thr]
    rl = [labels[i] for i in range(n) if col[i] > thr]
    node.update({"split": f"{key} <= {thr:.3f}", "gain": round(gain, 4),
                 "left": mine_tree(li, puzzles, ll, keys, depth + 1,
                                   max_depth, min_leaf,
                                   f"{key}<={thr:.3f}"),
                 "right": mine_tree(ri, puzzles, rl, keys, depth + 1,
                                    max_depth, min_leaf,
                                    f"{key}>{thr:.3f}")})
    return node


def render_tree(node, indent=0):
    pad = "  " * indent
    top = ",".join(f"{k}:{v}" for k, v in node["top"])
    lines = [f"{pad}[{node['rule']}] n={node['n']} top={top}"]
    if "split" in node:
        lines.append(f"{pad}split {node['split']} gain={node['gain']}")
        lines.append(render_tree(node["left"], indent + 1))
        lines.append(render_tree(node["right"], indent + 1))
    return "\n".join(lines)

# ─── Main ────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/tmp/opencode/arc-training/training")
    ap.add_argument("--report", default=None,
                    help="recognizer report JSON (dynamics+oracle)")
    ap.add_argument("--k", type=int, default=7)
    args = ap.parse_args()

    puzzles = v2.load_puzzles(args.data)
    if args.report is None:
        cands = sorted(Path("arc-agi3/state/rsi_reports").glob(
            "recognizer_*.json"))
        args.report = str(cands[-1])
    rep = json.load(open(args.report))
    ids = [r["id"] for r in rep["rows"]]
    oracles = {r["id"]: r["oracle"] for r in rep["rows"]}

    print(f"puzzles={len(ids)} chain={len(CHAIN)}")
    for k in (3, 5, 7, 11):
        ev = evaluate_knn(ids, puzzles, oracles, k=k)
        print(f"k={k}: solvable={ev['n_solvable']} "
              f"avg_rank knn={ev['avg_rank_knn']} fixed={ev['avg_rank_fixed']} "
              f"top1={ev['top1']} top3={ev['top3']}")

    # tree miner on non-unknown dynamics (+ unknown sample as background)
    dyn = {r["id"]: r["dynamic"] for r in rep["rows"]}
    known = [i for i in ids if dyn[i] != "unknown"]
    unk = [i for i in ids if dyn[i] == "unknown"][:60]
    tids = known + unk
    labels = [dyn[i] for i in tids]
    _, keys = featurize(tids, puzzles)
    tree = mine_tree(tids, puzzles, labels, keys)
    print("\ntree (depth<=3, readable detector hypotheses):")
    print(render_tree(tree))


if __name__ == "__main__":
    main()
