#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""
analyze_oe02.py — EXP-OE-02 figure: Maxwell's Demon on the REAL ℝ¹²⁸ KernelStepper.

Reproducible generator for fig_oe02_real_demon.pdf/.png from the two per-tick
CSVs produced by the maxwell_demon_real binary (LXC 108, scratch /tmp/oe02):

  oe02_libre.csv  — condition A: pure observer (no --demon)
  oe02_demon.csv  — condition B: S4-sorting demon (--demon)

Three panels, matching the paper's §sec:maxwell:
  (a) H(t)        — entropy over time, libre vs demon (Heq and Htarget lines)
  (b) stasis_cos  — geometric identity over time
  (c) D_eff       — effective dimension over time

Usage:
  python analyze_oe02.py oe02_demon.csv oe02_libre.csv fig_oe02_real_demon.pdf

FIG-COSMETIC (b): the raw 50k-tick traces saturate as a solid band; we
downsample for display (every Nth tick) AND apply alpha so the band shape
(not the per-tick noise) is what the reader sees.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
import vsf_style
vsf_style.apply()
C = vsf_style.C
PAL = vsf_style.PAL
FS = vsf_style.FS
FSIZE = vsf_style.FSIZE

# Display downsample — 50k ticks → 500 points per trace (band shape, not noise).
DOWNSAMPLE = 100
ALPHA = 0.55
BURN_IN = 500          # stationary window starts after burn-in (spec.vsm)

C_LIBRE = C['blue']
C_DEMON = C['red']


def load(csv_path: str) -> np.ndarray:
    return np.loadtxt(csv_path, delimiter=",", skiprows=1)


def downsample(arr: np.ndarray) -> np.ndarray:
    """Take every DOWNSAMPLE-th row so 50k ticks → 500 display points."""
    if len(arr) > DOWNSAMPLE:
        return arr[::DOWNSAMPLE]
    return arr


def main(argv):
    demon_path = argv[1] if len(argv) > 1 else "oe02_demon.csv"
    libre_path = argv[2] if len(argv) > 2 else "oe02_libre.csv"
    out_path   = argv[3] if len(argv) > 3 else "fig_oe02_real_demon.pdf"

    demon = load(demon_path)
    libre = load(libre_path)
    print(f"libre: {len(libre)} ticks | demon: {len(demon)} ticks")

    # Stationary-window means (post-burn-in), matching EXP-OE-02 results.vsm.
    libre_st = libre[libre[:, 0] >= BURN_IN]
    demon_st = demon[demon[:, 0] >= BURN_IN]
    h_eq  = float(np.mean(libre_st[:, 1]))
    h_tgt = 0.80  # spec.vsm params.h_target

    d_libre = downsample(libre)
    d_demon = downsample(demon)

    fig, axes = plt.subplots(3, 1, figsize=FS['fig_oe02'], sharex=True,
                             gridspec_kw={"hspace": 0.12})

    # ── (a) H(t) ─────────────────────────────────────────────────────────────
    ax = axes[0]
    ax.plot(d_libre[:, 0], d_libre[:, 1], color=C_LIBRE, lw=1.0, alpha=ALPHA,
            label="libre")
    ax.plot(d_demon[:, 0], d_demon[:, 1], color=C_DEMON, lw=1.0, alpha=ALPHA,
            label="demonio")
    ax.axhline(h_eq, color=C['gray'], ls=":", lw=1, label=rf"$H_{{eq}}$ = {h_eq:.4f}")
    ax.axhline(h_tgt, color=PAL['k0'], ls="--", lw=1, label=rf"$H_{{target}}$ = {h_tgt}")
    ax.set_ylabel(r"H(t) [bits]")
    ax.legend(loc="upper right", fontsize=FSIZE['legend'])
    ax.set_title("Maxwell's demon on the real 128 kernel", fontsize=FSIZE['title'])

    # ── (b) stasis_cos ───────────────────────────────────────────────────────
    ax = axes[1]
    ax.plot(d_libre[:, 0], d_libre[:, 2], color=C_LIBRE, lw=1.0, alpha=ALPHA,
            label="libre")
    ax.plot(d_demon[:, 0], d_demon[:, 2], color=C_DEMON, lw=1.0, alpha=ALPHA,
            label="demonio")
    ax.set_ylabel(r"$\cos(\theta_{stasis})$")
    ax.set_ylim(0.975, 1.005)
    ax.legend(loc="lower left", fontsize=FSIZE['legend'])

    # ── (c) D_eff ────────────────────────────────────────────────────────────
    ax = axes[2]
    ax.plot(d_libre[:, 0], d_libre[:, 3], color=C_LIBRE, lw=1.0, alpha=ALPHA,
            label="libre")
    ax.plot(d_demon[:, 0], d_demon[:, 3], color=C_DEMON, lw=1.0, alpha=ALPHA,
            label="demonio")
    ax.set_ylabel(r"$D_{eff}$")
    ax.set_xlabel("tick")
    ax.legend(loc="upper right", fontsize=FSIZE['legend'])

    for ax in axes:
        ax.axvspan(0, BURN_IN, color=C['gray'], alpha=0.08)
        ax.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path)
    png = str(Path(out_path).with_suffix(".png"))
    fig.savefig(png, dpi=150)
    print(f"wrote {out_path} + {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
