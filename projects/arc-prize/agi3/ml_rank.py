#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Calibrated P(solves | puzzle, strategy) — Fase B.

Design (honest):
  rows    : (puzzle x strategy) pairs; label = 1 iff strategy in the
            puzzle's oracle list (toolbox ground truth, from report).
  features: puzzle feats (router.featurize: single-grid + signature +
            pair deltas) + strategy one-hot.
  split   : GroupKFold by PUZZLE (never same puzzle train/test).
            Metric only on solvable test puzzles (rank of first solver).
  compare : mean rank vs router-kNN (6.29) vs fixed order (9.85).
  output  : best pipeline + CalibratedClassifierCV -> state/ml/rank.pkl
            EV re-rank of unknowns -> state/ml/ev_rank.json
Run with: /tmp/opencode/arc-ml/bin/python arc-agi3/ml_rank.py
"""
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import solver_smart_v2 as v2
from router import featurize, CHAIN
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

N_STRAT = len(CHAIN)
STATE = Path(__file__).parent / "state" / "ml"


def build_dataset(puzzles, ids, oracles):
    """Returns X (pairs), y, groups, key_order, puzzle_feats matrix."""
    pmat, keys = featurize(ids, puzzles)
    n, d = pmat.shape
    strat_oh = np.eye(N_STRAT)
    rows, labels, groups = [], [], []
    for i in range(n):
        for j in range(N_STRAT):
            rows.append(np.concatenate([pmat[i], strat_oh[j]]))
            labels.append(1 if CHAIN[j] in oracles[ids[i]] else 0)
            groups.append(ids[i])
    feat_names = keys + [f"strat_{s}" for s in CHAIN]
    return np.array(rows), np.array(labels), np.array(groups), feat_names


def rank_metrics(clf, X, y, groups, ids, oracles):
    """Mean rank of first true solver + top1/top3 (solvable puzzles only)."""
    proba = clf.predict_proba(X)[:, 1]
    order = np.argsort(groups, kind="stable")
    ranks, top1, top3, n = [], 0, 0, 0
    i = 0
    gids = groups[order]
    # group contiguous blocks (same puzzle => N_STRAT consecutive rows)
    uniq, starts = np.unique(gids, return_index=True)
    for g, s0 in zip(uniq, starts):
        block = slice(s0, s0 + N_STRAT)
        if set(groups[block]) != {g}:
            continue  # safety: skip malformed blocks
        true = set(oracles[g])
        if not true:
            continue
        n += 1
        ranking = np.argsort(-proba[block], kind="stable")
        r = next(k for k, j in enumerate(ranking) if CHAIN[j] in true)
        ranks.append(r)
        top1 += int(r == 0)
        top3 += int(r <= 2)
    return {"n": n, "avg_rank": round(float(np.mean(ranks)), 2) if ranks else 0,
            "top1": top1, "top3": top3}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/tmp/opencode/arc-training/training")
    ap.add_argument("--report", default=None)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--out", default=str(STATE))
    args = ap.parse_args()

    puzzles = v2.load_puzzles(args.data)
    if args.report is None:
        cands = sorted(Path("arc-agi3/state/rsi_reports").glob(
            "recognizer_*.json"))
        args.report = str(cands[-1])
    rep = json.load(open(args.report))
    ids = [r["id"] for r in rep["rows"]]
    oracles = {r["id"]: r["oracle"] for r in rep["rows"]}
    print(f"puzzles={len(ids)} strategies={N_STRAT} "
          f"positives={sum(len(v) for v in oracles.values())}")

    t0 = time.time()
    X, y, groups, feat_names = build_dataset(puzzles, ids, oracles)
    print(f"dataset: {X.shape}, build {time.time()-t0:.0f}s")

    models = {
        "logreg": make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, class_weight="balanced")),
        "rf": RandomForestClassifier(n_estimators=200, min_samples_leaf=5,
                                     class_weight="balanced_subsample",
                                     n_jobs=-1, random_state=0),
        "hgb": HistGradientBoostingClassifier(max_iter=300,
                                              class_weight="balanced",
                                              random_state=0),
    }
    gkf = GroupKFold(n_splits=args.folds)
    results = {}
    for name, clf in models.items():
        ranks, t1s, t3s = [], [], []
        for tr, te in gkf.split(X, y, groups):
            clf.fit(X[tr], y[tr])
            m = rank_metrics(clf, X[te], y[te], groups[te], ids, oracles)
            ranks.append(m["avg_rank"])
            t1s.append(m["top1"])
            t3s.append(m["top3"])
        results[name] = {
            "avg_rank": round(float(np.mean(ranks)), 2),
            "top1": int(np.sum(t1s)), "top3": int(np.sum(t3s)),
            "folds": args.folds}
        print(f"{name}: avg_rank={results[name]['avg_rank']} "
              f"top1={results[name]['top1']} top3={results[name]['top3']} "
              f"(knn 6.29 / fixed 9.85)", flush=True)

    best = min(results, key=lambda k: results[k]["avg_rank"])
    print(f"best: {best}")
    final = models[best]
    final.fit(X, y)
    cal = CalibratedClassifierCV(final, method="sigmoid", cv=3)
    cal.fit(X, y)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": cal, "features": feat_names,
                 "strategies": CHAIN,
                 "results": results}, out / "rank.pkl")
    print(f"saved {out / 'rank.pkl'}")

    # EV re-rank of unknowns: max P(solve) over strategies.
    unk = [r["id"] for r in rep["rows"] if r["dynamic"] == "unknown"]
    pmat_u, _ = featurize(unk, puzzles)
    ev = []
    for i, tid in enumerate(unk):
        block = np.array([np.concatenate([pmat_u[i], np.eye(N_STRAT)[j]])
                          for j in range(N_STRAT)])
        p = cal.predict_proba(block)[:, 1]
        ev.append({"id": tid, "p_solve": round(float(p.max()), 4),
                   "best_strat": CHAIN[int(p.argmax())]})
    ev.sort(key=lambda e: -e["p_solve"])
    with open(out / "ev_rank.json", "w") as f:
        json.dump(ev, f, indent=1)
    print("top-10 EV unknowns:")
    for e in ev[:10]:
        print(f"  {e['p_solve']:.3f} {e['id']} via {e['best_strat']}")


if __name__ == "__main__":
    main()
