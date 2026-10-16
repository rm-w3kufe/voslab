#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
Autonomous hunter v1 — the loop hunts by itself (human = last resort).

  order    : reporter cluster ranking (biggest family first)
  propose  : composition search, depth<=2 over toolbox primitives:
             g(f(trains, x)) with SHARED trains context, f structural
  verify   : LOO on TRAINS ONLY. Test outputs NEVER select rules
             (they only measure, in the final report, like always).
  remember : dead-ends registry (never retry a failed pair on a puzzle);
             hits registry (verified compositions as DATA, not code).
  grow     : recognizer --compose PATH loads the registry as one more
             dynamic. Toolbox grows by data; code untouched.

Bounds (v1): OPS_F structural (~9) x OPS_G (full chain) on 12 targets
(4 examples x top-3 unknown clusters). Per-puzzle timebox. Deterministic:
same inputs -> same dead-ends -> skippable re-runs.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import solver_smart_v2 as v2
import solver_v3 as v3
from recognizer import FALLBACK, verify_loo, compose

STATE = Path(__file__).parent / "state" / "rsi_reports"
DEAD_ENDS = STATE / "dead_ends.jsonl"
COMPOSED = STATE / "compositions.json"

# Structural first ops (reshape/relocate); second op = anything.
# NOTE: names are REGISTRY names (bare, e.g. "rotation"), NOT function
# names ("try_rotation"). A wrong name here once silently skipped the
# entire hunt (FNS.get -> None -> continue); hence the assert in main.
OPS_F = ["rotation", "reflection", "tiling",
         "diagonal_tiling", "adaptive_tiling", "flip_tiling",
         "crop_content", "extract_quadrant", "shape_expansion"]
FNS = {name: fn for name, fn in FALLBACK}


def load_dead_ends():
    dead = set()
    if DEAD_ENDS.exists():
        with open(DEAD_ENDS) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                    dead.add((d["puzzle"], d["f"], d["g"]))
                except Exception:
                    continue
    return dead


def record_dead(puzzle, f, g, why):
    with open(DEAD_ENDS, "a") as fh:
        fh.write(json.dumps({"puzzle": puzzle, "f": f, "g": g,
                             "why": why,
                             "ts": datetime.now(timezone.utc).isoformat()})
                 + "\n")


def record_hit(puzzle, f, g):
    reg = {}
    if COMPOSED.exists():
        try:
            reg = json.load(open(COMPOSED))
        except Exception:
            reg = {}
    reg.setdefault("compositions", [])
    entry = {"ops": [f, g], "verified_on": [puzzle]}
    if entry not in reg["compositions"]:
        reg["compositions"].append(entry)
    else:
        for e in reg["compositions"]:
            if e["ops"] == [f, g] and puzzle not in e["verified_on"]:
                e["verified_on"].append(puzzle)
    reg["updated"] = datetime.now(timezone.utc).isoformat()
    with open(COMPOSED, "w") as fh:
        json.dump(reg, fh, indent=1)


def hunt_puzzle(tid, puzzles, dead, timebox=120, swap=False):
    """Returns hits [(f, g)] verified LOO on trains. Test never consulted."""
    trains = v2.get_train_pairs(puzzles[tid])
    if len(trains) < 1:
        return []
    hits = []
    t0 = time.time()
    first = ([n for n, _ in FALLBACK] if swap else OPS_F)
    for fname in first:
        f = FNS.get(fname)
        if f is None:
            continue
        second = (OPS_F if swap else [n for n, _ in FALLBACK])
        for gname in second:
            g = FNS.get(gname)
            if g is None or gname == fname:
                continue
            if (tid, fname, gname) in dead:
                continue
            if time.time() - t0 > timebox:
                return hits
            comp = compose(f, g)
            try:
                ok = verify_loo(comp, trains)
            except Exception:
                ok = False
            if ok:
                hits.append((fname, gname))
                record_hit(tid, fname, gname)
            else:
                record_dead(tid, fname, gname, "loo-fail")
                dead.add((tid, fname, gname))
    return hits


def pick_targets(rep, per_cluster=4, n_clusters=3):
    seen, out = set(), []
    for c in rep.get("clusters", [])[:n_clusters]:
        for tid in c.get("examples", []):
            if tid not in seen:
                seen.add(tid)
                out.append(tid)
            if len([t for t in out]) >= per_cluster * n_clusters:
                break
    # top up from unknown rows if examples ran short
    for r in rep["rows"]:
        if len(out) >= per_cluster * n_clusters:
            break
        if r["dynamic"] == "unknown" and r["id"] not in seen:
            seen.add(r["id"])
            out.append(r["id"])
    return out[:per_cluster * n_clusters]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/tmp/opencode/arc-training/training")
    ap.add_argument("--report", default=None)
    ap.add_argument("--per-cluster", type=int, default=4)
    ap.add_argument("--n-clusters", type=int, default=3)
    ap.add_argument("--timebox", type=int, default=120)
    ap.add_argument("--targets", default=None,
                    help="comma-separated puzzle ids (overrides ranking)")
    ap.add_argument("--swap", action="store_true",
                    help="transpose search: f=anything, g=structural")
    args = ap.parse_args()

    puzzles = v2.load_puzzles(args.data)
    missing = [f for f in OPS_F if f not in FNS]
    assert not missing, f"OPS_F names not in registry: {missing}"
    if args.report is None:
        cands = sorted(STATE.glob("recognizer_*.json"))
        args.report = str(cands[-1])
    rep = json.load(open(args.report))
    solved = {r["id"] for r in rep["rows"] if r["solved"]}
    if args.targets:
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    else:
        targets = [t for t in pick_targets(rep, args.per_cluster,
                                           args.n_clusters)
                   if t not in solved]
    print(f"targets ({len(targets)}): {targets}")
    dead = load_dead_ends()
    print(f"dead-ends loaded: {len(dead)}")
    all_hits = {}
    for tid in targets:
        h = hunt_puzzle(tid, puzzles, dead, args.timebox, args.swap)
        all_hits[tid] = h
        print(f"  {tid}: hits={h if h else '-'}", flush=True)
    hits_n = sum(len(v) for v in all_hits.values())
    print(f"total hits: {hits_n}")
    print(f"registry: {COMPOSED} dead-ends: {DEAD_ENDS}")


if __name__ == "__main__":
    main()
