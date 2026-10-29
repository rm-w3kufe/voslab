#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""
fig_vsm_operational_closure.py — Live 5-system VSM operational closure timeline (S1-S5)
Outputs: fig_vsm_operational_closure.pdf + png
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
    # Make canvas wider (8.5 inches) and taller (4.5 inches) to eliminate crowding
    fig, ax = plt.subplots(figsize=(8.5, 4.5))

    ticks = np.arange(1, 7)
    
    systems = ['S1: Operations ($\mathbf{R}^{128}$)', 
               'S2: Coordination (NATS)', 
               'S3: Control (CPU/Slack)', 
               'S4: Intelligence (Qwen)', 
               'S5: Policy / Algedonic']
    y_pos = np.arange(len(systems))

    ax.hlines(y_pos, 0.5, 6.5, color=PAL['k3'], lw=1.2, zorder=1)

    # S1 activity
    ax.plot(ticks, [0]*6, 's-', color=PAL['data'], ms=7, label='State transition active', zorder=3)
    
    # S2 coordination pulse
    ax.plot([1, 3, 5], [1, 1, 1], 'o', color=PAL['aux'], ms=6, label='Pub/Sub sync', zorder=3)

    # S3 control attempt & override
    ax.plot([2], [2], 'X', color=PAL['bad'], ms=10, label='S3 Over-allocation', zorder=4)
    ax.plot([3, 4, 5, 6], [2, 2, 2, 2], 'o', color=PAL['good'], ms=6, label='Regulated slack', zorder=3)

    # S4 async scan
    ax.plot([2, 5], [3, 3], 'd', color=PAL['gov'], ms=7, label='Async semantic scan', zorder=3)

    # S5 constitutional algedonic intervention
    ax.plot([3], [4], '*', color=PAL['bad'], ms=14, label='S5 Algedonic Veto (dims[53]=1)', zorder=5)
    ax.plot([4, 5, 6], [4, 4, 4], 'o', color=PAL['good'], ms=6, label='Homeostatic resume', zorder=3)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(systems, fontsize=FSIZE['label'])
    ax.set_xlim(0.3, 6.7)
    ax.set_ylim(-1.0, 5.2)
    ax.set_xlabel('Tick ($t$)')
    ax.set_title('Live VSM Operational Closure (S1–S5 Interlock)', fontsize=FSIZE['title'], pad=16)

    # Move text annotation entirely outside the plotting tracks to prevent any overlap
    ax.annotate('Conflict:\nS3 vs S5 Veto', xy=(3, 4), xytext=(3.2, 4.4),
                arrowprops=dict(arrowstyle='->', color=PAL['bad'], lw=0.9),
                fontsize=FSIZE['annot'], color=PAL['bad'],
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=PAL['bad'], alpha=0.95))

    ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.28), fontsize=FSIZE['legend'], ncol=3, framealpha=0.95)
    fig.tight_layout()

    out_pdf = OUT / "fig_vsm_operational_closure.pdf"
    out_png = OUT / "fig_vsm_operational_closure.png"
    fig.savefig(out_pdf, bbox_inches='tight')
    fig.savefig(out_png, dpi=300, bbox_inches='tight')
    plt.close()
    print("fig_vsm_operational_closure.pdf / .png rewritten with uncrowded layout.")


if __name__ == "__main__":
    generate_fig()
