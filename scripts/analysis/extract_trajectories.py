#!/usr/bin/env python3
"""extract_trajectories.py — EXP-TDA-01 prereq #2 helper.

Parse a vsf-nucleus telemetry events.jsonl and extract the ℝ¹²⁸ state-vector
trajectory emitted by spec_boot (status == "stasis_vector"). The kernel nests the
payload as metrics.metrics.dims (init_step double-wraps), so we handle both that
and a flat metrics.dims for robustness.

Output: an .npy matrix (N × 128) + a sidecar .meta.json with per-row tick /
stasis_cos / l_x for run_4 (perturbation) analysis.

Usage:
  python extract_trajectories.py EVENTS.jsonl OUT_PREFIX
  # writes OUT_PREFIX.npy  +  OUT_PREFIX.meta.json
"""
import json
import sys


def _dims(ev):
    m = ev.get("metrics", {})
    if isinstance(m, dict):
        inner = m.get("metrics", m)  # double-nested or flat
        d = inner.get("dims")
        if isinstance(d, list) and d:
            return d, inner
    return None, {}


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    events_path, out_prefix = argv[1], argv[2]

    # accept both the stasis fixed-point dump and the full every-tick dump
    WANTED = ("stasis_vector", "traj_vector")
    rows, meta = [], []
    n_lines = 0
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line or not any(w in line for w in WANTED):
                continue
            n_lines += 1
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("status") not in WANTED:
                continue
            dims, inner = _dims(ev)
            if dims is None or len(dims) != 128:
                continue
            rows.append([float(x) for x in dims])
            meta.append({
                "tick": inner.get("tick"),
                "stasis_cos": inner.get("stasis_cos"),
                "l_x": inner.get("l_x"),
                "entropy_phase": inner.get("entropy_phase"),
            })

    if not rows:
        print(f"NO stasis_vector rows with 128 dims found in {events_path} "
              f"({n_lines} candidate lines).")
        return 1

    try:
        import numpy as np
    except ImportError:
        print("numpy not available — activate the TDA venv "
              "(/home/rmw3/tda-venv/bin/python).")
        return 3

    arr = np.asarray(rows, dtype=np.float64)
    np.save(out_prefix + ".npy", arr)
    with open(out_prefix + ".meta.json", "w") as f:
        json.dump(meta, f)

    cos = [m["stasis_cos"] for m in meta if m["stasis_cos"] is not None]
    print(f"extracted {arr.shape[0]} vectors × {arr.shape[1]} dims → {out_prefix}.npy")
    if cos:
        print(f"stasis_cos: min={min(cos):.4f} max={max(cos):.4f}")
    # crude spread: how collapsed is the attractor?
    spread = float(np.linalg.norm(arr - arr.mean(axis=0), axis=1).mean())
    print(f"mean distance to centroid = {spread:.4f} "
          f"(small ⇒ converged/collapsed attractor)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
