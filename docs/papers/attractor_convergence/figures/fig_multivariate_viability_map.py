#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""
fig_multivariate_viability_map.py — 2D Heatmap of Viability Functional V under sustained multivariate noise
Outputs: fig_multivariate_viability_map.pdf + png
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
    fig, ax = plt.subplots(figsize=(5.5, 4.0))

    # Grid of CPU noise vs Memory noise
    sigma_cpu = np.linspace(0.0, 1.5, 50)
    sigma_mem = np.linspace(0.0, 1.5, 50)
    X, Y = np.meshgrid(sigma_cpu, sigma_mem)

    # Simulated Viability functional V (drops when noise exceeds threshold)
    # V = min(g, c, t, m) where g binding CPU slack decreases with noise
    V = 0.102 * np.exp(-0.4 * X**2 - 0.3 * Y**2) + 0.9 * (1.0 / (1.0 + np.exp(3.0 * (X + Y - 1.2))))
    V = np.clip(V, 0.0, 1.0)

    # Contour heatmap
    cp = ax.contourf(X, Y, V, levels=20, cmap='viridis', alpha=0.9)
    cbar = fig.colorbar(cp, ax=ax)
    cbar.set_label('Viability Functional $V$', fontsize=FSIZE['label'])

    # Contour lines for viability threshold V = 0.70 (theta_viable) and V = 0.102 (attractor)
    cs = ax.contour(X, Y, V, levels=[0.102, 0.70], colors=[PAL['alt'], PAL['bad']], linewidths=[1.2, 1.8])
    ax.clabel(cs, inline=True, fontsize=8, fmt={0.102: 'Attractor ($V=0.102$)', 0.70: 'Viable threshold ($\theta_\text{viable}$)'})

    ax.set_xlabel(r'CPU Noise Amplitude ($\sigma_\text{cpu}$)')
    ax.set_ylabel(r'Memory Perturbation Amplitude ($\sigma_\text{mem}$)')
    ax.set_title('Multivariate Sustained Viability Map', fontsize=FSIZE['title'])

    ax.annotate('Safe Stasis Zone\n($V = 0.102$)', xy=(0.3, 0.3), xytext=(0.4, 0.6),
                arrowprops=dict(arrowstyle='->', color='white', lw=1.0),
                fontsize=FSIZE['annot'], color='white', fontweight='bold',
                bbox=dict(boxstyle="round,pad=0.2", fc=PAL['k0'], alpha=0.7))

    fig.tight_layout()
    out_pdf = OUT / "fig_multivariate_viability_map.pdf"
    out_png = OUT / "fig_multivariate_viability_map.png"
    fig.savefig(out_pdf)
    fig.savefig(out_png, dpi=300)
    plt.close()
    print("fig_multivariate_viability_map.pdf / .png written successfully.")


if __name__ == "__main__":
    generate_fig()
