#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""
fig_topology.py — EXP-TDA-01 figure: Betti curves + persistence diagram.

Reproduces the raw-cosine ℝ¹²⁸ regime from tda_calibrate.py (uniform subsample
to 400, cosine metric, maxdim=1) and renders fig9_topology.pdf:
  Left  — β₀(ε) and β₁(ε) step curves (the β₀=1 plateau, β₁≡0).
  Right — persistence diagram (one long H0 bar; H1 at the noise floor).

Usage:
  python fig_topology.py [npy_path] [output.pdf]
  
  Environment variables:
    TDA_DATA_DIR: Directory containing traj_full.npy (default: ~/tda-data2)
"""
import os
import sys
import numpy as np
import matplotlib
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', 'docs', 'papers', 'attractor_convergence'))
import vsf_style
vsf_style.apply()
C = vsf_style.C
FS = vsf_style.FS
FSIZE = vsf_style.FSIZE
matplotlib.use("Agg")
import matplotlib.pyplot as plt

MAX_POINTS = 400
PERSIST_FRAC = 0.25
ABS_FLOOR = 0.05


def betti_at(dgm, eps):
    """Number of features alive at filtration value eps (birth ≤ eps < death)."""
    if len(dgm) == 0:
        return 0
    births = dgm[:, 0]
    deaths = dgm[:, 1]
    return int(np.sum((births <= eps) & (deaths > eps)))


def main(argv):
    tda_data_dir = os.environ.get("TDA_DATA_DIR", os.path.expanduser("~/tda-data2"))
    default_npy = os.path.join(tda_data_dir, "traj_full.npy")
    npy_path = argv[1] if len(argv) > 1 else default_npy
    out_path = argv[2] if len(argv) > 2 else "fig9_topology.pdf"

    from ripser import ripser

    X = np.load(npy_path)
    n0 = X.shape[0]
    if X.shape[0] > MAX_POINTS:
        idx = np.linspace(0, X.shape[0] - 1, MAX_POINTS).astype(int)
        X = X[idx]
    print(f"loaded {n0} pts → subsampled to {X.shape[0]} × {X.shape[1]}")

    res = ripser(X, maxdim=1, metric="cosine")
    dgms = res["dgms"]
    h0, h1 = dgms[0], dgms[1]

    # H0: replace the infinite death (single connected component) with a display cap.
    h0_finite = h0[np.isfinite(h0[:, 1])]
    eps_max = float(np.max(h0_finite[:, 1])) * 1.6 if len(h0_finite) else 0.5
    h0_disp = h0.copy()
    h0_disp[~np.isfinite(h0_disp[:, 1]), 1] = eps_max

    # max finite persistences (for annotation)
    h0_maxp = float(np.max(h0_finite[:, 1] - h0_finite[:, 0])) if len(h0_finite) else 0.0
    h1_maxp = float(np.max(h1[:, 1] - h1[:, 0])) if len(h1) else 0.0
    sep = h0_maxp / h1_maxp if h1_maxp > 0 else float("inf")
    print(f"H0 max-persistence={h0_maxp:.4f}  H1 max-persistence={h1_maxp:.4f}  sep={sep:.0f}x")

    # ── Betti curves ──────────────────────────────────────────────────────────
    eps_grid = np.linspace(0, eps_max, 400)
    b0 = [betti_at(h0_disp, e) for e in eps_grid]
    b1 = [betti_at(h1, e) for e in eps_grid]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=FS['full_34'])

    axL.plot(eps_grid, b0, color=C['blue'], lw=2, label=r"$\beta_0(\varepsilon)$")
    axL.plot(eps_grid, b1, color=C['red'], lw=2, label=r"$\beta_1(\varepsilon)$")
    axL.axhline(1, color=C['gray'], ls=":", lw=1)
    # FIG-COSMETIC (a): Betti numbers are counts (β ≥ 0). symlog renders a
    # negative axis range (ticks below 0) which is meaningless here — use
    # linear with a hard floor at 0 instead.
    axL.set_yscale("linear")
    axL.set_ylim(bottom=0)
    axL.set_xlabel(r"filtration $\varepsilon$ (cosine distance)")
    axL.set_ylabel(r"Betti number")
    axL.set_title(r"Betti curves (raw $\mathbb{R}^{128}$ cosine)")
    axL.legend(loc="upper right")
    axL.annotate(r"$\beta_0=1$ plateau", xy=(h0_maxp * 1.15, 1),
                 xytext=(h0_maxp * 1.25, 6),
                 arrowprops=dict(arrowstyle="->", color=C['gray']), fontsize=FSIZE['label'])

    # ── Persistence diagram ───────────────────────────────────────────────────
    lim = eps_max
    axR.plot([0, lim], [0, lim], color=C['gray'], ls="--", lw=1, zorder=0)
    # H0 points (births at 0)
    axR.scatter(h0_disp[:, 0], h0_disp[:, 1], s=24, color=C['blue'],
                label=r"$H_0$", zorder=2)
    if len(h1):
        axR.scatter(h1[:, 0], h1[:, 1], s=24, color=C['red'],
                    marker="^", label=r"$H_1$", zorder=3)
    axR.set_xlim(-0.01, lim)
    axR.set_ylim(-0.01, lim)
    axR.set_xlabel("birth")
    axR.set_ylabel("death")
    axR.set_title("Persistence diagram")
    axR.legend(loc="lower right")
    axR.text(0.04 * lim, 0.92 * lim,
             f"$H_0$ max-persist = {h0_maxp:.3f}\n"
             f"$H_1$ max-persist = {h1_maxp:.4f}\n"
             rf"$\approx {sep:.0f}\times$ separation",
             fontsize=FSIZE['label'], va="top",
             bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.85))

    fig.tight_layout()
    fig.savefig(out_path)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
