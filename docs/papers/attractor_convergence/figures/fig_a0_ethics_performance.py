#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""
fig_a0_ethics_performance.py — A0/A0.1 Ethics Governance Sandbox Performance (EXP-A01-01)
Outputs: fig_a0_ethics_performance.pdf + png
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
    # Wider aspect ratio and more breathing room
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.5),
                                  gridspec_kw={'wspace': 0.32})

    # ── Panel (a): TPR across violation categories (EXP-A01-01) ───────────────
    categories = ['A0 Violations\n(Covenant)', 'A0.1 Coercion\nPatterns', 'Clean Baseline\n(Specificity)']
    tpr_values = [0.93, 0.87, 0.98]
    colors = [PAL['bad'], PAL['alt'], PAL['good']]

    bars = ax1.bar(categories, tpr_values, color=colors, width=0.50, edgecolor=PAL['k0'], linewidth=0.8)
    ax1.set_ylim(0, 1.22)
    ax1.set_ylabel('Classification Rate (TPR / Specificity)')
    ax1.set_title('(a) Sandbox Accuracy (EXP-A01-01)', fontsize=FSIZE['title'], pad=12)
    ax1.axhline(0.90, color=PAL['ref'], ls='--', lw=0.9, label='Target threshold (0.90)')

    for bar, val in zip(bars, tpr_values):
        ax1.text(bar.get_x() + bar.get_width()/2., val + 0.04, f"{val*100:.0f}%",
                 ha='center', va='bottom', fontsize=FSIZE['annot'], fontweight='bold', color=PAL['k0'])

    ax1.legend(loc='lower left', fontsize=FSIZE['legend'])

    # ── Panel (b): Single-tick collapse and recovery dynamics ─────────────────
    ticks = np.arange(0, 15)
    V_curve = [0.102, 0.102, 0.102, 0.102, 0.0, 0.102, 0.102, 0.102, 0.102, 0.102, 0.102, 0.102, 0.102, 0.102, 0.102]
    
    ax2.plot(ticks, V_curve, 's-', color=PAL['data'], lw=2.0, ms=6, label=r'Viability functional $V$')
    
    ax2.axvline(4, color=PAL['bad'], ls=':', lw=1.2, label=r'Inject $\mathrm{dims}[53]=1$')
    ax2.axvline(9, color=PAL['good'], ls=':', lw=1.2, label=r'Reset signal')

    ax2.annotate('Single-tick collapse\n($V \to 0$ in 1 tick)',
                 xy=(4, 0.0), xytext=(1.0, 0.03),
                 arrowprops=dict(arrowstyle='->', color=PAL['bad'], lw=0.8),
                 fontsize=FSIZE['annot'], color=PAL['bad'],
                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=PAL['bad'], alpha=0.9))

    ax2.annotate('Immediate recovery\nto baseline',
                 xy=(9, 0.102), xytext=(6.5, 0.075),
                 arrowprops=dict(arrowstyle='->', color=PAL['good'], lw=0.8),
                 fontsize=FSIZE['annot'], color=PAL['good'],
                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=PAL['good'], alpha=0.9))

    ax2.set_xlim(-0.5, 14.5)
    ax2.set_ylim(-0.01, 0.135)
    ax2.set_xlabel('Tick ($t$)')
    ax2.set_ylabel(r'Viability $V$ ($g = 0.102$)')
    ax2.set_title('(b) Collapse & Recovery Dynamics', fontsize=FSIZE['title'], pad=12)
    ax2.legend(loc='lower right', fontsize=FSIZE['legend'])

    fig.tight_layout()
    out_pdf = OUT / "fig_a0_ethics_performance.pdf"
    out_png = OUT / "fig_a0_ethics_performance.png"
    fig.savefig(out_pdf)
    fig.savefig(out_png, dpi=300)
    plt.close()
    print("fig_a0_ethics_performance.pdf / .png rewritten with expanded layout.")


if __name__ == "__main__":
    generate_fig()
