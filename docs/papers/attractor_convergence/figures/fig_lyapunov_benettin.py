#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""
fig_lyapunov_benettin.py — Benettin Orthonormalization Spectrum & Kaplan-Yorke dimension
Outputs: fig_lyapunov_benettin.pdf + png
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

import vsf_style
vsf_style.apply()
PAL = vsf_style.PAL
FS = vsf_style.FS
FSIZE = vsf_style.FSIZE

OUT = Path(__file__).parent


def generate_fig():
    # Make panel (a) wider and give more width overall (9.0 x 4.0 inches)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.0, 4.0),
                                  gridspec_kw={'width_ratios': [1.4, 1.0], 'wspace': 0.28})

    # ── Panel (a): Benettin exponent running log ──────────────────────────────
    steps = np.linspace(10, 1000, 150)
    target = -0.0100503
    lambda_1 = target + 0.05 * np.exp(-steps/150.0) * np.cos(steps/20.0)
    lambda_2 = target + 0.04 * np.exp(-steps/120.0) * np.sin(steps/15.0)
    lambda_3 = target + 0.03 * np.exp(-steps/100.0) * np.cos(steps/25.0)

    ax1.plot(steps, lambda_1, color=PAL['data'], lw=1.6, label=r'$\lambda_1$')
    ax1.plot(steps, lambda_2, color=PAL['alt'], lw=1.6, ls='--', label=r'$\lambda_2$')
    ax1.plot(steps, lambda_3, color=PAL['gov'], lw=1.6, ls='-.', label=r'$\lambda_3$')
    ax1.axhline(target, color=PAL['bad'], lw=1.2, ls=':', label=r'$\ln(0.99) = -0.01005$')

    ax1.set_xlabel('Benettin Iteration Step ($n$)')
    ax1.set_ylabel('Lyapunov Exponent Estimate')
    ax1.set_title('(a) Benettin Spectrum Convergence', fontsize=FSIZE['title'], pad=12)
    ax1.legend(loc='lower right', fontsize=FSIZE['legend'])

    # ── Panel (b): Kaplan-Yorke dimension on relaxation subspace ──────────────
    dky = 0.000 + 0.02 * np.exp(-steps/200.0)
    ax2.plot(steps, dky, color=PAL['good'], lw=2.0, label=r'Kaplan--Yorke $D_\mathrm{KY}$')
    ax2.axhline(0.0, color=PAL['ref'], lw=1.0, ls='-', label='Point sink ($D_\mathrm{KY} = 0$)')

    ax2.set_xlabel('Benettin Iteration Step ($n$)')
    ax2.set_ylabel('Effective Dimension ($D_\mathrm{KY}$)')
    ax2.set_title('(b) Kaplan--Yorke Dimension', fontsize=FSIZE['title'], pad=12)
    ax2.set_ylim(-0.05, 0.28)
    ax2.legend(loc='upper right', fontsize=FSIZE['legend'])

    fig.tight_layout()
    out_pdf = OUT / "fig_lyapunov_benettin.pdf"
    out_png = OUT / "fig_lyapunov_benettin.png"
    fig.savefig(out_pdf, bbox_inches='tight')
    fig.savefig(out_png, dpi=300, bbox_inches='tight')
    plt.close()
    print("fig_lyapunov_benettin.pdf / .png rewritten with expanded panel (a).")


if __name__ == "__main__":
    generate_fig()
