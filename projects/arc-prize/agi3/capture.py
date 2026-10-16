#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Capture process graphics for the paper media gallery.

Usage:
  python3 arc-agi3/capture.py <puzzle_id> [--out DIR] [--no-pred]
  python3 arc-agi3/capture.py 05f2a901 00dbd492 --out docs/paper/media/

Renders train in/out (+ our test prediction when solvable) with the ARC
palette. Every capture lands in docs/paper/media/ with puzzle id + dynamic
in the filename, ready for the Kaggle Media Gallery.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import solver_smart_v2 as v2

PAL = ["#000000", "#0074D9", "#FF4136", "#2ECC40", "#FFDC00",
       "#AAAAAA", "#F012BE", "#FF851B", "#7FDBFF", "#870C25"]


def render(puzzle_id, out_dir, data_dir="/tmp/opencode/arc-training/training",
           with_pred=True):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    import numpy as np

    puzzles = v2.load_puzzles(data_dir)
    p = puzzles[puzzle_id]
    trains = v2.get_train_pairs(p)
    cols = [("train in", trains[0][0]), ("train out", trains[0][1])]
    dyn = ""
    if with_pred:
        from recognizer import solve_routed
        import solver_v3 as v3
        r = solve_routed(trains, v2.get_test_input(p))
        exp = p["test"][0]["output"]
        ok = r["pred"] is not None and v3.grids_equal(r["pred"], exp)
        dyn = r["dynamic"]
        cols.append((f"test pred: {dyn} {'OK' if ok else 'MISS'}", r["pred"]))
    fig, axes = plt.subplots(1, len(cols), figsize=(3 * len(cols), 3))
    if len(cols) == 1:
        axes = [axes]
    fig.suptitle(f"{puzzle_id} [{dyn or 'n/a'}]", fontsize=10, color="white")
    fig.patch.set_facecolor("#111111")
    for ax, (t, g) in zip(axes, cols):
        if g is None:
            ax.set_title(t + " (none)", fontsize=8, color="white")
            ax.axis("off")
            continue
        ax.imshow(np.array(g), cmap=ListedColormap(PAL),
                  vmin=0, vmax=9, interpolation="nearest")
        ax.set_title(t, fontsize=8, color="white")
        ax.axis("off")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{puzzle_id}_{dyn or 'na'}.png"
    plt.savefig(path, dpi=150, facecolor="#111111")
    plt.close()
    print(f"saved {path}")
    return str(path)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("puzzles", nargs="+")
    ap.add_argument("--out", default="docs/paper/media")
    ap.add_argument("--no-pred", action="store_true")
    ap.add_argument("--data", default="/tmp/opencode/arc-training/training")
    args = ap.parse_args()
    for tid in args.puzzles:
        render(tid, args.out, args.data, with_pred=not args.no_pred)


if __name__ == "__main__":
    main()
