#!/usr/bin/env python3
"""tda_calibrate.py — EXP-TDA-01 persistent-homology calibration.

Loads an ℝ¹²⁸ trajectory (.npy from extract_trajectories.py) and computes
Betti numbers via Vietoris-Rips persistent homology in 3 regimes:
  (a) raw ℝ¹²⁸ with cosine distance
  (b) PCA → 3D, euclidean
  (c) SpectralEmbedding → 3D (diffusion-map-like learned metric), euclidean

For each regime it reports the persistence diagram summary and the
"viability signature" test (Hypothesis_ViabilityTopology):
    β_0 = 1  ∧  β_1 = 0  ∧  β_2 = 0   ⇔  single attractor.

A feature counts toward β_i if its persistence (death − birth) exceeds
PERSIST_FRAC × (max finite persistence in that dimension). Run via the TDA venv:
  /home/rmw3/tda-venv/bin/python tda_calibrate.py TRAJ.npy
"""
import sys

PERSIST_FRAC = 0.25  # relative gate: persistence > this × max-persistence …
ABS_FLOOR = 0.05     # … AND > this absolute floor (calibrated: separates real
                     # topology from sampling noise; tiny ≤0.03 loops are noise).


def betti_summary(dgms):
    """Return per-dimension (n_significant, max_persistence)."""
    out = []
    for dim, dgm in enumerate(dgms):
        if len(dgm) == 0:
            out.append((0, 0.0))
            continue
        finite = [(b, d) for b, d in dgm if d != float("inf")]
        pers = [d - b for b, d in finite]
        if dim == 0:
            # H0: count the infinite component(s) as the connected pieces that
            # survive to ∞ (β_0 of the whole space).
            n_inf = sum(1 for _, d in dgm if d == float("inf"))
            out.append((max(n_inf, 1), max(pers) if pers else 0.0))
            continue
        if not pers:
            out.append((0, 0.0))
            continue
        mx = max(pers)
        # significant ⇔ above BOTH the relative gate and the absolute noise floor.
        thr = max(PERSIST_FRAC * mx, ABS_FLOOR)
        n_sig = sum(1 for p in pers if p > thr)
        out.append((n_sig, mx))
    return out


def run_regime(name, points, metric, maxdim=1):  # maxdim=1 (β0,β1) is tractable; H2 via flag
    from ripser import ripser
    res = ripser(points, maxdim=maxdim, metric=metric)
    summ = betti_summary(res["dgms"])
    b0 = summ[0][0]
    b1 = summ[1][0] if len(summ) > 1 else 0
    b2 = summ[2][0] if len(summ) > 2 else 0
    viable_sig = (b0 == 1 and b1 == 0 and b2 == 0)
    print(f"\n[{name}]  metric={metric}")
    for dim, (n, mx) in enumerate(summ):
        print(f"  H{dim}: significant={n}  max_persistence={mx:.4f}")
    print(f"  ⇒ β_0={b0} β_1={b1} β_2={b2}  viability_signature={viable_sig}")
    return viable_sig


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    import numpy as np
    X = np.load(argv[1])
    print(f"loaded {X.shape[0]} points × {X.shape[1]} dims from {argv[1]}")
    if X.shape[0] < 4:
        print("too few points for meaningful homology (need ≥ 4).")
        return 1

    # ripser VR is O(n³) — subsample uniformly to keep it tractable.
    max_points = int(argv[2]) if len(argv) > 2 else 400
    maxdim = int(argv[3]) if len(argv) > 3 else 1  # β0,β1 by default; pass 2 for β2 (slow)
    skip = int(argv[4]) if len(argv) > 4 else 0    # drop first N rows (e.g. warmup blob)
    if skip > 0 and skip < X.shape[0]:
        X = X[skip:]
        print(f"skipped first {skip} rows → {X.shape[0]} remaining (excludes warmup)")
    if X.shape[0] > max_points:
        idx = np.linspace(0, X.shape[0] - 1, max_points).astype(int)
        X = X[idx]
        print(f"subsampled uniformly to {X.shape[0]} points (max_points={max_points})")

    results = {}
    # (a) raw R^128 cosine
    results["raw_cosine"] = run_regime("a/raw ℝ¹²⁸", X, metric="cosine", maxdim=maxdim)

    # (b) PCA → 3D euclidean
    try:
        from sklearn.decomposition import PCA
        d = min(3, X.shape[1], X.shape[0] - 1)
        Xp = PCA(n_components=d).fit_transform(X)
        results["pca3d"] = run_regime(f"b/PCA→{d}D", Xp, metric="euclidean", maxdim=maxdim)
    except Exception as e:  # noqa
        print(f"\n[b/PCA] skipped: {e}")

    # (c) SpectralEmbedding → 3D (diffusion-map-like)
    try:
        from sklearn.manifold import SpectralEmbedding
        d = min(3, X.shape[0] - 2)
        Xs = SpectralEmbedding(n_components=d, affinity="nearest_neighbors").fit_transform(X)
        results["spectral3d"] = run_regime(f"c/Spectral→{d}D", Xs, metric="euclidean", maxdim=maxdim)
    except Exception as e:  # noqa
        print(f"\n[c/Spectral] skipped: {e}")

    print("\n=== SUMMARY ===")
    for k, v in results.items():
        print(f"  {k:12s} viability_signature={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
