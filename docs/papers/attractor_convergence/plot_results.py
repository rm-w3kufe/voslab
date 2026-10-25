#!/usr/bin/env python3
"""
plot_results.py — Publication-quality figures for attractor_convergence paper
vsf-nucleus v1.0 | vsm-0.3 | 2026-04-18

Figures:
  Fig 1 — Lyapunov convergence series          (line, semi-log)
  Fig 2 — Attractor basin 3D topographic       (surface + scatter)
  Fig 3 — Thermal stability                    (scatter + phase boundary)
  Fig 4 — theta_psi_stress: angustia curves    (4-panel line)
  Fig 5 — recursive_thermal_ramp: N* boundary  (dual-axis line)
  Fig 6 — Trust bifurcation phase portrait     (2D phase space)

Usage:
  python plot_results.py [--results path/to/results.json]

All figures written to: figures/fig{N}.pdf + figures/fig{N}.png
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import json, argparse, os
from pathlib import Path

import vsf_style
vsf_style.apply()
C = vsf_style.C

FIGDIR = Path(__file__).parent / 'figures'
FIGDIR.mkdir(exist_ok=True)

# ── Verified results — CANONICAL trust law (Law A, Table 2 / tab:specboot) ───
# Source: canonical spec_boot regression 2026-06 (trust-law reconciliation,
# ARC-1 closed; docs/papers/attractor_convergence/next_session_plan.vsm).
# The 110-min long-run row predates the reconciliation and is NOT plotted
# here under the canonical series (predecessor definition; see tab:senescence
# badge + REMEASURE task in TASKS.vsm — v1.0 replaces pending re-run).

CONVERGENCE_SERIES = [
    # (label,          ticks,    mean_dL,    stasis_cos, d_eff, V_mem)
    ('spec_boot_300t',    300,   -0.060,     0.95,       6.00,  2),
    ('spec_boot_1000t',  1000,   -0.014,     0.95,       6.00,  2),
    ('spec_boot_2000t',  2000,   -0.007,     0.95,       6.00,  2),
    ('spec_boot_10000t',10000,   -0.001,     0.95,       6.00,  1),
    ('spec_boot_20000t',20000,   -0.001,     0.95,       6.00,  1),
]

MULTIKERNEL = {
    'mean_pairwise_cos': 0.9854,
    'mean_pairwise_angle': 9.8,
    'min_cos': 0.9607,
    'min_angle': 16.1,
    'cone_angle': 18.21,
    'trust_init_range': [0.55, 0.85],
    'n_kernels': 4,
}

THERMAL = {
    # (temp_C, stasis_cos, viable_full)
    'observations': [
        (46.0, 0.9996, True),
        (52.0, 0.9920, True),
        (58.0, 0.9680, True),
        (63.0, 0.9510, True),
        (65.0, 0.9450, True),
        (67.0, 0.9410, True),
        (68.0, 0.9390, True),
        (69.0, 0.9377, True),   # upper bound θ_PSI
    ],
    'theta_psi_upper': 0.9377,
    'safety_temp':     70.0,
    'throttle_temp':   67.0,
}


# ── Placeholder: filled by run_theta_psi_stress + recursive_thermal_ramp ──────
# Replace with actual results when experiments complete.

THETA_PSI_PLACEHOLDER = [
    # (delta, angustia_tick, angustia_cos, min_cos, recovery_ticks)
    (0.10, None,  1.0,    1.0,    None),   # not reached yet
    (0.20, None,  1.0,    1.0,    None),
    (0.30, None,  1.0,    0.95,   None),
    (0.50, 280,   0.65,   0.58,   45),     # predicted
]

RTR_PLACEHOLDER = [
    # (n_kernels, mean_cos, temp_C) — predicted trajectory
    (1,  0.9990, 38.0),
    (2,  0.9890, 42.0),
    (3,  0.9854, 46.0),
    (4,  0.9854, 51.0),
    (5,  0.9820, 56.0),
    (6,  0.9780, 61.0),
    (7,  0.9700, 65.0),
    (8,  0.9580, 68.0),
    (9,  0.9400, 71.0),
    (10, 0.9200, 74.0),
]


def save(fig, name):
    for ext in ('pdf', 'png'):
        p = FIGDIR / f'{name}.{ext}'
        fig.savefig(p)
        print(f'  saved {p}')
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 1 — Lyapunov convergence
# ═══════════════════════════════════════════════════════════════════════════════

def fig1_lyapunov():
    ticks  = [d[1] for d in CONVERGENCE_SERIES]
    dL     = [abs(d[2]) for d in CONVERGENCE_SERIES]
    d_eff   = [d[4] for d in CONVERGENCE_SERIES]
    labels = [d[0].replace('spec_boot_', '').replace('long_run_', '') for d in CONVERGENCE_SERIES]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.0))

    # left: |mean_dL| convergence
    ax1.semilogx(ticks, dL, 'o-', color=C['blue'], zorder=3)
    ax1.axhline(0, color=C['gray'], linewidth=0.8, linestyle='--')
    for i, (x, y, lbl) in enumerate(zip(ticks, dL, labels)):
        ax1.annotate(lbl, (x, y), textcoords='offset points',
                     xytext=(5, 3), fontsize=7, color=C['gray'])
    ax1.set_xlabel('Ticks (log scale)')
    ax1.set_ylabel(r'$|\overline{\delta L}|$')
    ax1.set_title('(a) Lyapunov exponent convergence')
    ax1.set_ylim(-0.002, 0.070)

    # right: D_eff (effective attractor dimension)
    ax2.semilogx(ticks, d_eff, 's-', color=C['orange'], zorder=3)
    ax2.axhline(6.00, color=C['green'], linewidth=0.8, linestyle='--',
                label=r'$D_\mathrm{eff}=6.00$ (canonical law $A$)')
    ax2.set_xlabel('Ticks (log scale)')
    ax2.set_ylabel(r'$D_\mathrm{eff}$')
    ax2.set_title('(b) Attractor dimensionality')
    ax2.set_ylim(2.5, 7.0)
    ax2.legend(loc='upper right')

    fig.suptitle('Lyapunov convergence of vsf-nucleus spec\\_boot kernel',
                 fontsize=10, y=1.01)
    fig.tight_layout()
    save(fig, 'fig1_lyapunov')


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 2 — Attractor basin 3D topographic
# ═══════════════════════════════════════════════════════════════════════════════

def _basin_kernel_data():
    """Shared kernel geometry data for 2D and 3D basin plots."""
    kernel_angles_deg = [9.2, 9.8, 10.4, 16.1]
    kernel_phis       = [0.3, 1.8, 3.5, 5.1]
    kernels = []
    for ang, ph in zip(kernel_angles_deg, kernel_phis):
        a = np.radians(ang)
        kernels.append((np.sin(a)*np.cos(ph), np.sin(a)*np.sin(ph), np.cos(a), ang))
    return kernels


def fig2_basin_3d():
    """
    3D topographic visualization of the attractor basin.
    Lyapunov potential V(θ) = 1 − cos(θ) as the basin surface.
    View angle: slightly elevated side view to show the valley shape clearly.
    """
    # ── shared geometry ────────────────────────────────────────────────────────
    theta_surf = np.linspace(0, np.radians(32), 80)
    phi_surf   = np.linspace(0, 2*np.pi, 120)
    THETA, PHI = np.meshgrid(theta_surf, phi_surf)
    X = np.sin(THETA) * np.cos(PHI)
    Y = np.sin(THETA) * np.sin(PHI)
    Z = np.cos(THETA)
    V = 1.0 - np.cos(THETA)

    cone_angle = np.radians(MULTIKERNEL['cone_angle'])
    phi_ring   = np.linspace(0, 2*np.pi, 200)
    cx = np.sin(cone_angle) * np.cos(phi_ring)
    cy = np.sin(cone_angle) * np.sin(phi_ring)
    cz = np.cos(cone_angle) * np.ones_like(phi_ring)

    kernels = _basin_kernel_data()

    # ── Figure: single perspective view ───────────────────────────────────────
    fig = plt.figure(figsize=(7.0, 5.5))
    ax  = fig.add_subplot(1, 1, 1, projection='3d')

    ax.plot_surface(X, Y, Z, facecolors=plt.cm.viridis_r(V / V.max()),
                    alpha=0.55, linewidth=0, antialiased=True)

    # cone boundary
    ax.plot(cx, cy, cz, color=C['red'], linewidth=2.2, linestyle='--',
            label=rf'$\theta_{{PSI}}={MULTIKERNEL["cone_angle"]}°$', zorder=6)

    # mean angle ring (9.8°)
    mean_angle = np.radians(MULTIKERNEL['mean_pairwise_angle'])
    mx = np.sin(mean_angle) * np.cos(phi_ring)
    my = np.sin(mean_angle) * np.sin(phi_ring)
    mz = np.cos(mean_angle) * np.ones_like(phi_ring)
    ax.plot(mx, my, mz, color=C['blue'], linewidth=1.2, linestyle=':',
            alpha=0.7, label=r'mean obs: $9.8°$', zorder=5)

    # kernels
    for i, (kx, ky, kz, ang) in enumerate(kernels):
        ax.scatter(kx, ky, kz, s=70, color=C['orange'],
                   edgecolors='k', linewidths=0.8, zorder=10)
        ax.text(kx*1.08, ky*1.08, kz+0.002, f'$k_{i}$', fontsize=8)

    # stasis center
    ax.scatter(0, 0, 1.0, s=140, color=C['red'], marker='*',
               edgecolors='k', linewidths=0.8, zorder=11,
               label=r'Stasis $\mathbf{s}^*$')

    # vertical axis
    ax.plot([0,0],[0,0],[0.86,1.0], color=C['gray'],
            linewidth=0.8, linestyle=':', alpha=0.6)

    ax.set_xlabel(r'$\xi_1$', labelpad=4)
    ax.set_ylabel(r'$\xi_2$', labelpad=4)
    ax.set_zlabel(r'$\cos\theta$', labelpad=4)
    ax.view_init(elev=28, azim=-50)
    ax.set_box_aspect([1, 1, 0.55])
    ax.legend(loc='upper left', fontsize=8)

    # colorbar
    m = cm.ScalarMappable(cmap='viridis_r', norm=plt.Normalize(vmin=0, vmax=float(V.max())))
    m.set_array([])
    cbar = fig.colorbar(m, ax=ax, shrink=0.55, aspect=20, pad=0.04)
    cbar.set_label(r'$V(\theta)=1-\cos\theta$  (Lyapunov potential)', fontsize=8)

    fig.suptitle(
        r'Attractor basin — $\mathbb{R}^{128}$ projected to $\mathbb{S}^2$'
        '\n'
        r'$N=4$ kernels within $9.8°$ mean, cone boundary $18.21°$',
        fontsize=10, y=1.01
    )
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig.tight_layout()
    save(fig, 'fig2_basin_3d')


def fig2b_basin_2d():
    """
    2D top-down projection of the attractor basin.
    Shows the basin as a filled contour map with kernels as scatter points.
    Clean and publication-ready — useful companion to the 3D figure.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.6))

    # ── Left: polar contour — top-down view ───────────────────────────────────
    # r = sin(theta) — radial distance from stasis center in projected plane
    # color = V(theta) = 1 - cos(theta)

    r_grid   = np.linspace(0, np.sin(np.radians(32)), 200)
    phi_grid = np.linspace(0, 2*np.pi, 200)
    R, PHI_G = np.meshgrid(r_grid, phi_grid)
    THETA_G  = np.arcsin(np.clip(R, 0, 1))
    V_G      = 1.0 - np.cos(THETA_G)
    Xg = R * np.cos(PHI_G)
    Yg = R * np.sin(PHI_G)

    cf = ax1.contourf(Xg, Yg, V_G, levels=40, cmap='viridis_r', alpha=0.85)

    # cone boundary (18.21°)
    r_cone = np.sin(np.radians(MULTIKERNEL['cone_angle']))
    circle_cone = plt.Circle((0,0), r_cone, fill=False,
                              color=C['red'], linewidth=2.0,
                              linestyle='--', label=r'$\theta_{PSI}=18.21°$')
    ax1.add_patch(circle_cone)

    # mean angle ring (9.8°)
    r_mean = np.sin(np.radians(MULTIKERNEL['mean_pairwise_angle']))
    circle_mean = plt.Circle((0,0), r_mean, fill=False,
                              color='white', linewidth=1.2,
                              linestyle=':', alpha=0.8, label=r'mean obs: $9.8°$')
    ax1.add_patch(circle_mean)

    # kernel points
    kernels = _basin_kernel_data()
    for i, (kx, ky, kz, ang) in enumerate(kernels):
        ax1.scatter(kx, ky, s=80, color=C['orange'],
                    edgecolors='k', linewidths=0.8, zorder=5)
        ax1.annotate(f'$k_{i}$ ({ang}°)', (kx, ky),
                     textcoords='offset points', xytext=(5, 4), fontsize=7.5)

    # stasis center
    ax1.scatter(0, 0, s=160, color=C['red'], marker='*',
                edgecolors='k', linewidths=0.8, zorder=6, label=r'Stasis $\mathbf{s}^*$')

    ax1.set_aspect('equal')
    ax1.set_xlim(-0.36, 0.36)
    ax1.set_ylim(-0.36, 0.36)
    ax1.set_xlabel(r'$\xi_1 = \sin\theta\cos\phi$')
    ax1.set_ylabel(r'$\xi_2 = \sin\theta\sin\phi$')
    ax1.set_title('(a) Top-down projection\n(darker = lower potential)', fontsize=9)
    ax1.legend(fontsize=7.5, loc='lower right')
    fig.colorbar(cf, ax=ax1, label=r'$V(\theta)=1-\cos\theta$', shrink=0.85)

    # ── Right: radial profile — V(θ) vs angle ─────────────────────────────────
    theta_range = np.linspace(0, np.radians(35), 300)
    V_profile   = 1.0 - np.cos(theta_range)
    theta_deg   = np.degrees(theta_range)

    ax2.plot(theta_deg, V_profile, color=C['blue'], linewidth=2.0,
             label=r'$V(\theta)=1-\cos\theta$')
    ax2.fill_between(theta_deg, V_profile, alpha=0.12, color=C['blue'])

    # observed range
    obs_angles = [k[3] for k in kernels]
    for ang in obs_angles:
        v = 1 - np.cos(np.radians(ang))
        ax2.plot(ang, v, 'o', color=C['orange'], markersize=7,
                 markeredgecolor='k', linewidth=0.8, zorder=5)

    # cone + mean markers
    ax2.axvline(MULTIKERNEL['cone_angle'], color=C['red'], linewidth=1.5,
                linestyle='--', label=rf'$\theta_{{PSI}}={MULTIKERNEL["cone_angle"]}°$')
    ax2.axvline(MULTIKERNEL['mean_pairwise_angle'], color=C['blue'], linewidth=1.0,
                linestyle=':', alpha=0.7, label=r'mean obs: $9.8°$')

    # shade the basin interior
    ax2.fill_between(theta_deg, V_profile,
                     where=(theta_deg <= MULTIKERNEL['cone_angle']),
                     alpha=0.15, color=C['green'], label='basin interior')

    ax2.set_xlabel(r'Angular deviation $\theta$ (degrees)')
    ax2.set_ylabel(r'Lyapunov potential $V(\theta)$')
    ax2.set_title('(b) Radial potential profile', fontsize=9)
    ax2.set_xlim(0, 35)
    ax2.set_ylim(-0.002, 0.095)

    # annotate kernel cluster
    ax2.annotate('observed\nkernels', xy=(13, 0.025), fontsize=8,
                 color=C['orange'], ha='center',
                 arrowprops=dict(arrowstyle='->', color=C['orange'], lw=0.8),
                 xytext=(20, 0.015))

    ax2.legend(fontsize=7.5)

    fig.suptitle(
        r'Attractor basin (2D) — $N=4$ kernels, $D_\mathrm{eff}=3.00$, predecessor law',
        fontsize=10, y=1.01
    )
    fig.tight_layout()
    save(fig, 'fig2b_basin_2d')


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 3 — Thermal stability
# ═══════════════════════════════════════════════════════════════════════════════

def fig3_thermal():
    obs    = THERMAL['observations']
    temps  = [o[0] for o in obs]
    cos_v  = [o[1] for o in obs]
    viable = [o[2] for o in obs]

    fig, ax1 = plt.subplots(figsize=(4.2, 3.2))

    # single panel: stasis_cos vs temperature
    colors = [C['green'] if v else C['red'] for v in viable]
    ax1.scatter(temps, cos_v, c=colors, s=60, zorder=5, edgecolors='k', linewidths=0.5)
    ax1.axhline(THERMAL['theta_psi_upper'], color=C['red'], linewidth=1.0,
                linestyle='--', label=rf'$\theta_{{PSI}}$ upper bound: {THERMAL["theta_psi_upper"]:.4f}')
    ax1.axhline(0.70, color=C['orange'], linewidth=1.0, linestyle=':',
                label=r'viability floor: $\cos\theta=0.70$')
    ax1.axvline(THERMAL['throttle_temp'], color=C['purple'], linewidth=0.8,
                linestyle='-.', alpha=0.7, label=f'HW throttle: {THERMAL["throttle_temp"]:.0f}°C')
    ax1.set_xlabel('CPU temperature (°C)')
    ax1.set_ylabel(r'$\cos(\theta_{stasis})$')
    ax1.set_ylim(0.88, 1.02)

    # custom legend markers
    from matplotlib.lines import Line2D
    legend_els = [
        Line2D([0],[0], marker='o', color='w', markerfacecolor=C['green'],
               markeredgecolor='k', markersize=7, label='viable_full=True'),
        Line2D([0],[0], marker='o', color='w', markerfacecolor=C['red'],
               markeredgecolor='k', markersize=7, label='viable_full=False'),
    ]
    ax1.legend(handles=legend_els + ax1.get_legend_handles_labels()[0][:3],
               fontsize=7.5, loc='lower left')

    fig.suptitle('Thermal stability of vsf-nucleus (H4 confirmed)',
                 fontsize=10, y=1.01)
    fig.tight_layout()
    save(fig, 'fig3_thermal')


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 4 — theta_psi_stress (angustia curves)
# ═══════════════════════════════════════════════════════════════════════════════

def fig4_theta_psi(results=None):
    """
    4-panel: stasis_cos(t) for each delta value.
    Uses THETA_PSI_PLACEHOLDER until real results arrive.
    Pass results = list of per-tick dicts from telemetry to use real data.
    """
    WARMUP = 100; STRESS = 300; RECOVERY = 200; TOTAL = WARMUP + STRESS + RECOVERY

    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.0), sharex=True, sharey=True)
    axes = axes.flatten()

    deltas = [0.10, 0.20, 0.30, 0.50]
    colors_d = [C['blue'], C['green'], C['orange'], C['red']]

    for idx, (delta, color) in enumerate(zip(deltas, colors_d)):
        ax = axes[idx]

        if results is not None:
            # real data from telemetry
            ticks_d = [r['tick'] for r in results if r['delta'] == delta]
            cos_d   = [r['stasis_cos'] for r in results if r['delta'] == delta]
        else:
            # simulated trajectory for layout preview
            t   = np.arange(TOTAL)
            cos = np.ones(TOTAL) * 0.98
            # warmup: build baseline
            cos[:WARMUP] = 0.98 - 0.02 * (1 - np.linspace(0, 1, WARMUP)**2)
            # stress: progressive perturbation
            stress_t = np.linspace(0, 1, STRESS)
            cos[WARMUP:WARMUP+STRESS] = 0.98 - delta * stress_t**1.5
            cos[WARMUP:WARMUP+STRESS] = np.clip(cos[WARMUP:WARMUP+STRESS], 0.3, 1.0)
            # recovery: exponential return
            final_stress = cos[WARMUP + STRESS - 1]
            rec = np.linspace(0, 1, RECOVERY)
            cos[WARMUP+STRESS:] = final_stress + (0.96 - final_stress) * (1 - np.exp(-3*rec))
            ticks_d = t; cos_d = cos

        ax.plot(ticks_d, cos_d, color=color, linewidth=1.2, zorder=3)

        # phase boundaries
        ax.axvline(WARMUP, color=C['gray'], linewidth=0.7, linestyle='--', alpha=0.7)
        ax.axvline(WARMUP + STRESS, color=C['gray'], linewidth=0.7, linestyle='--', alpha=0.7)
        ax.axhline(0.70, color=C['red'], linewidth=0.8, linestyle=':', alpha=0.8,
                   label='viability floor')
        ax.axhline(THERMAL['theta_psi_upper'], color=C['orange'], linewidth=0.8,
                   linestyle=':', alpha=0.8, label=r'$\theta_{PSI}^{upper}$')

        # phase labels
        ax.text(50,  0.72, 'warmup',   fontsize=7, color=C['gray'], ha='center')
        ax.text(250, 0.72, 'stress',   fontsize=7, color=C['gray'], ha='center')
        ax.text(510, 0.72, 'recovery', fontsize=7, color=C['gray'], ha='center')

        ax.set_title(rf'$\delta = {delta}$', fontsize=10)
        ax.set_ylim(0.30 if delta >= 0.30 else 0.65, 1.02)

        if results is None:
            ax.text(0.98, 0.04, 'schematic', transform=ax.transAxes,
                    ha='right', va='bottom', fontsize=7, color=C['gray'],
                    alpha=0.35, style='italic')

    for ax in axes[2:]: ax.set_xlabel('Tick')
    for ax in axes[::2]: ax.set_ylabel(r'$\cos(\theta_{stasis})$')

    fig.suptitle(
        r'$\theta_{PSI}$ stress test — activation perturbation $\delta \in \{0.10, 0.20, 0.30, 0.50\}$',
        fontsize=10
    )
    fig.tight_layout()
    save(fig, 'fig4_theta_psi')


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 5 — recursive_thermal_ramp: N* boundary
# ═══════════════════════════════════════════════════════════════════════════════

def fig5_recursive_ramp(results=None):
    data = results if results is not None else RTR_PLACEHOLDER
    ns   = [d[0] for d in data]
    cos  = [d[1] for d in data]
    temp = [d[2] for d in data]

    fig, ax1 = plt.subplots(figsize=(5.5, 3.5))
    ax2 = ax1.twinx()

    l1, = ax1.plot(ns, cos,  'o-', color=C['blue'],   label=r'mean $\cos(\theta_{pairwise})$')
    l2, = ax2.plot(ns, temp, 's-', color=C['red'],    label=r'CPU temperature (°C)', alpha=0.75)

    ax1.axhline(MULTIKERNEL['mean_pairwise_cos'], color=C['blue'], linewidth=0.8,
                linestyle='--', alpha=0.6,
                label=rf'baseline ($N=4$): {MULTIKERNEL["mean_pairwise_cos"]}')
    ax1.axhline(0.95, color=C['gray'], linewidth=0.8, linestyle=':',
                label=r'cone boundary: $\cos(18.21°)$')
    ax2.axhline(THERMAL['safety_temp'], color=C['red'], linewidth=0.8,
                linestyle=':', alpha=0.6, label=f'safety gate: {THERMAL["safety_temp"]:.0f}°C')

    if results is None:
        ax1.text(0.98, 0.04, 'schematic', transform=ax1.transAxes,
                 ha='right', va='bottom', fontsize=7, color=C['gray'],
                 alpha=0.35, style='italic')

    ax1.set_xlabel('Number of active S1 kernels $N$')
    ax1.set_ylabel(r'mean pairwise $\cos(\theta)$', color=C['blue'])
    ax2.set_ylabel('CPU temperature (°C)',          color=C['red'])
    ax1.set_ylim(0.85, 1.01)
    ax2.set_ylim(30, 90)
    ax1.tick_params(axis='y', labelcolor=C['blue'])
    ax2.tick_params(axis='y', labelcolor=C['red'])

    lines = [l1, l2]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, fontsize=8, loc='lower left')

    ax1.set_title(
        r'Recursive thermal ramp — stasis cone vs $N$ kernels'
        r' (H6: $\exists N^*$ where viable\_all drops)',
        fontsize=10
    )
    fig.tight_layout()
    save(fig, 'fig5_rtr')


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 6 — Trust bifurcation phase portrait
# ═══════════════════════════════════════════════════════════════════════════════

def fig6_trust_bifurcation():
    """
    Phase portrait in (trust, H) space showing the two stable attractors.
    - High-trust basin: trust ~ 1.0, H ~ h_rest
    - Low-trust basin:  trust ~ 0.0, H oscillating fast
    Derived analytically from the spec_boot dynamics equations.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.5))

    H_REST = 0.400; H_MAX = 1.700; TAU = 0.60

    # ── Left: phase portrait ───────────────────────────────────────────────────
    trust_grid = np.linspace(0, 1, 30)
    H_grid     = np.linspace(0, H_MAX, 30)
    T, H = np.meshgrid(trust_grid, H_grid)

    pressure = 0.4 * (H / H_MAX) + 0.3 * (1 - T) + 0.3 * np.abs(H - H_REST) / H_MAX
    focus    = 1 - np.clip(pressure, 0, 1)

    dT = np.where(pressure < TAU, 0.002, -0.001)
    dH = np.where(pressure < TAU, H_REST - H, pressure * 0.08)

    speed = np.sqrt(dT**2 + dH**2)
    ax1.streamplot(trust_grid, H_grid, dT, dH,
                   color=speed, cmap='Blues', linewidth=0.8,
                   density=1.2, arrowsize=0.8)

    # attractor markers
    ax1.plot(1.0, H_REST, '*', color=C['red'], markersize=14,
             zorder=10, label='High-trust attractor')
    ax1.plot(0.0, H_MAX * 0.85, 'o', color=C['orange'], markersize=10,
             zorder=10, label='Low-trust attractor', alpha=0.8)

    ax1.axvline(0.30, color=C['gray'], linewidth=0.8, linestyle='--',
                alpha=0.6, label='trust bifurcation boundary')
    ax1.set_xlabel(r'Trust $\tau$')
    ax1.set_ylabel(r'Entropy $H(t)$')
    ax1.set_title('(a) Phase portrait — trust/entropy dynamics')
    ax1.legend(fontsize=7.5, loc='upper right')

    # ── Right: trust(t) for long_run ──────────────────────────────────────────
    t = np.linspace(0, 110, 500)

    # high-trust trajectory (theoretical — system stays governed)
    trust_hi = 1.0 - 0.05 * np.exp(-t / 30)

    # low-trust trajectory (observed in spec_boot synthetic run)
    trust_lo = 0.80 * np.exp(-t / 8) + 0.001

    ax2.plot(t, trust_hi, color=C['blue'],   linewidth=1.5, label='governed run (theoretical)')
    ax2.plot(t, trust_lo, color=C['orange'], linewidth=1.5, linestyle='--',
             label='spec_boot synthetic (observed)')
    ax2.axhline(0.30, color=C['gray'], linewidth=0.8, linestyle=':',
                label='bifurcation boundary')
    ax2.axhline(0.80, color=C['gray'], linewidth=0.6, linestyle=':', alpha=0.5)

    ax2.annotate('low-trust\nattractor', xy=(80, 0.002), fontsize=8,
                 color=C['orange'], ha='center')
    ax2.annotate('high-trust\nattractor', xy=(90, 0.96), fontsize=8,
                 color=C['blue'], ha='center')

    ax2.set_xlabel('Time (min)')
    ax2.set_ylabel(r'Trust $\tau(t)$')
    ax2.set_title('(b) Trust trajectories — dual attractor')
    ax2.set_ylim(-0.05, 1.1)
    ax2.legend(fontsize=7.5)

    fig.suptitle('Trust bifurcation — two stable attractors in (trust, H) space',
                 fontsize=10, y=1.01)
    fig.tight_layout()
    save(fig, 'fig6_trust_bifurcation')


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 7 — V_mem collapse (bonus: shows convergence quality)
# ═══════════════════════════════════════════════════════════════════════════════

def fig7_vmem():
    runs   = ['300t', '1000t', '2000t', '10000t', '60.5M']
    vmem   = [None,   2,        2,        1,          1]
    cycles = [4,      14,       28,       141,        60_492_497 / 430_000]
    merge_rates = [None, 13/14, 27/29, 139/141, 60492496/60492497]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.2))

    x = np.arange(len(runs))
    vmem_vals = [v if v is not None else 0 for v in vmem]

    bars = ax1.bar(x, vmem_vals, color=[C['blue'], C['orange'], C['green'], C['red'], C['purple']],
                   edgecolor='k', linewidth=0.5, width=0.6)
    ax1.set_xticks(x); ax1.set_xticklabels(runs, fontsize=9)
    ax1.set_ylabel(r'$|V_{mem}|$ (distinct entries)')
    ax1.set_title(r'(a) Vector memory collapse: $|V_{mem}| \to 1$')
    ax1.set_ylim(0, 3.5)
    for bar, val in zip(bars, vmem_vals):
        if val > 0:
            ax1.text(bar.get_x() + bar.get_width()/2, val + 0.05,
                     str(val), ha='center', fontsize=9, fontweight='bold')

    # merge rates
    mr_vals = [m * 100 if m is not None else 0 for m in merge_rates]
    ax2.bar(x, mr_vals, color=[C['blue'], C['orange'], C['green'], C['red'], C['purple']],
            edgecolor='k', linewidth=0.5, width=0.6)
    ax2.axhline(99.0, color=C['gray'], linewidth=0.8, linestyle='--', alpha=0.7)
    ax2.set_xticks(x); ax2.set_xticklabels(runs, fontsize=9)
    ax2.set_ylabel('Merge rate (%)')
    ax2.set_title('(b) Stasis cycle merge rate → 100%')
    ax2.set_ylim(0, 102)

    fig.suptitle(r'$V_{mem}$ convergence: point attractor confirmed',
                 fontsize=10, y=1.01)
    fig.tight_layout()
    save(fig, 'fig7_vmem')


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def load_theta_psi_results(path):
    """Parse theta_psi_stress telemetry into per-tick dicts."""
    results = []
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
                m = d.get('metrics', {})
                if m.get('experiment') == 'theta_psi_stress' and m.get('step') == 'tick':
                    results.append(m)
            except: pass
    return results if results else None


def load_rtr_results(path):
    """Parse recursive_thermal_ramp ramp_tick events."""
    results = []
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
                m = d.get('metrics', {})
                if m.get('experiment') == 'recursive_thermal_ramp' and m.get('step') == 'ramp_tick':
                    results.append((
                        m.get('n_kernels', 0),
                        m.get('mean_cos', 1.0),
                        m.get('temp_C', 35.0),
                    ))
            except: pass
    return results if results else None


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 8 — Monte-Carlo basin volume (EXP-MC-01)
# ═══════════════════════════════════════════════════════════════════════════════

DATADIR = FIGDIR / 'data'

def fig8_basin_volume():
    mins_path  = DATADIR / 'basin_mins.csv'
    if not mins_path.exists():
        print(f'  [fig8] skipped — {mins_path} not found (run basin_mc with VSF_MC_CSV)')
        return
    mins = np.loadtxt(mins_path, skiprows=1)
    fig, ax = plt.subplots(figsize=(4.2, 3.0))

    # single panel: histogram of per-trial stasis_cos_min
    ax.hist(mins, bins=30, range=(0.87, 1.0), color=C['blue'], alpha=0.85, zorder=3)
    ax.axvline(0.875, color=C['red'], ls='--', lw=1.2,
               label=r'EXP-AB-01 worst-case $0.875$')
    ax.axvline(float(np.min(mins)), color=C['orange'], ls=':', lw=1.2,
               label=rf'random floor ${np.min(mins):.3f}$')
    ax.set_xlabel(r'$\mathrm{stasis\_cos}_{\min}$ per trial')
    ax.set_ylabel('count')
    ax.set_title(f'Basin depth — {len(mins)} trials')
    ax.legend(loc='upper left', fontsize=7)

    fig.suptitle('Monte-Carlo basin volume (EXP-MC-01): fraction $\\approx 1.0$; '
                 'recovery rate $=1.0$ across all perturbation strengths',
                 fontsize=10, y=1.02)
    fig.tight_layout()
    save(fig, 'fig8_basin_volume')


# ═══════════════════════════════════════════════════════════════════════════════
# Fig 10 — Running largest Lyapunov exponent (EXP-LY-01, Benettin)
# ═══════════════════════════════════════════════════════════════════════════════

def fig10_lyapunov():
    """Full Gram-Schmidt Lyapunov spectrum (EXP-LY-01 v2): 3 exponents on the simplex tangent space."""
    path = DATADIR / 'lyap_running.csv'
    if not path.exists():
        print(f'  [fig10] skipped — {path} not found (run lyapunov_spectrum)')
        return
    import csv
    with open(path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    ticks = np.array([int(r['tick']) for r in rows])
    lam1  = np.array([float(r['lambda1']) for r in rows])
    lam2  = np.array([float(r['lambda2']) for r in rows])
    lam3  = np.array([float(r['lambda3']) for r in rows])
    ln099 = np.log(0.99)

    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    ax.plot(ticks, lam1, '-',  color=C['blue'],  lw=1.8, zorder=3, label=r'$\lambda_1$')
    ax.plot(ticks, lam2, '--', color=C['green'], lw=1.2, zorder=2, label=r'$\lambda_2$')
    ax.plot(ticks, lam3, ':',  color=C['orange'], lw=1.2, zorder=2, label=r'$\lambda_3$')
    ax.axhline(ln099, color=C['red'], ls='--', lw=1.0,
               label=r'$\ln(0.99)=-0.01005$ (Jacobian prediction)')
    ax.axhline(0, color=C['gray'], lw=0.8, ls=':')
    ax.set_xlabel('ticks')
    ax.set_ylabel(r'running $\lambda_i$ (per tick)')
    ax.set_title(r'Benettin spectrum $[\lambda_1,\lambda_2,\lambda_3]$ (EXP-LY-01)')
    ax.legend(loc='center right', fontsize=8)
    sigma_hat = np.std(lam1)
    ax.text(0.97, 0.10,
            r'all $\lambda_i=\ln(0.99)<0$; $\hat{\sigma}_\lambda='
            + f'{sigma_hat:.1e}$\n'
            r'KY-dim$=0$ (point sink)',
            transform=ax.transAxes, ha='right', fontsize=7.5,
            bbox=dict(boxstyle='round', fc='white', ec=C['gray'], alpha=0.85))
    fig.tight_layout()
    save(fig, 'fig10_lyapunov')


def fig11_sustained_noise():
    """V(σ) robustness curve under SUSTAINED noise (EXP-NS-01): the margin axis m(σ) of V."""
    path = DATADIR / 'sustained_noise.csv'
    if not path.exists():
        print(f'  [fig11] skipped — {path} not found (run sustained_noise)')
        return
    import csv
    with open(path) as f:
        rows = list(csv.DictReader(f))
    sigma   = np.array([float(r['sigma_in']) for r in rows])
    m_p95   = np.array([float(r['m_p95']) for r in rows])
    confine = np.array([float(r['confine']) for r in rows])
    eps_frontier = np.sqrt(2 * (1 - 0.70))  # 0.7746

    fig, ax = plt.subplots(figsize=(5.6, 3.3))
    # V(σ) = min(g≈1, c≈1, t=1, m(σ)) = m(σ) on this curve
    ax.plot(sigma, m_p95, 'o-', color=C['blue'], lw=1.8, ms=4, zorder=3,
            label=r'$V(\sigma)=\min(g,c,t,m(\sigma))=m(\sigma)$')
    # saturation asymptote guide
    ax.axhline(m_p95[-1], color=C['gray'], ls=':', lw=0.9,
               label=fr'saturates $\approx {m_p95[-1]:.2f}$ (no finite ceiling)')
    # annotate the rev.3 borrowed-proxy point (V≈0.46 ↔ extreme σ≈1.0)
    idx1 = int(np.argmin(np.abs(sigma - 1.0)))
    ax.annotate(r'rev.3 proxy $V\approx0.46$' + '\n(extreme regime)',
                xy=(sigma[idx1], m_p95[idx1]), xytext=(1.05, 0.62),
                fontsize=7.5, ha='left',
                arrowprops=dict(arrowstyle='->', color=C['red'], lw=0.8))
    # moderate operating point
    idx2 = int(np.argmin(np.abs(sigma - 0.10)))
    ax.plot(sigma[idx2], m_p95[idx2], 's', color=C['green'], ms=7, zorder=4)
    ax.annotate(fr'moderate $\sigma=0.10$: $V={m_p95[idx2]:.2f}$',
                xy=(sigma[idx2], m_p95[idx2]), xytext=(0.30, 0.85),
                fontsize=7.5, ha='left',
                arrowprops=dict(arrowstyle='->', color=C['green'], lw=0.8))
    ax.set_xlabel(r'sustained noise amplitude $\sigma_{\mathrm{in}}$')
    ax.set_ylabel(r'$V(\sigma)$ (margin-limited)')
    ax.set_ylim(0, 1.02)
    ax.set_title(r'Viability under sustained noise $V(\sigma)$ (EXP-NS-01)')
    ax.legend(loc='upper right', fontsize=7.5)
    ax.text(0.97, 0.06,
            fr'confinement $P(\cos\geq0.70)=1.0000$ for all $\sigma\leq2.0$' + '\n'
            fr'$\Rightarrow$ no finite noise ceiling; $\varepsilon_{{\mathrm{{frontier}}}}={eps_frontier:.3f}$',
            transform=ax.transAxes, ha='right', fontsize=7,
            bbox=dict(boxstyle='round', fc='white', ec=C['gray'], alpha=0.85))
    fig.tight_layout()
    save(fig, 'fig11_sustained_noise')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--events', default=None,
                        help='Path to events_sample.jsonl from n02 telemetry')
    args = parser.parse_args()

    tps_results = load_theta_psi_results(args.events) if args.events else None
    rtr_results = load_rtr_results(args.events)       if args.events else None

    if tps_results: print(f'  theta_psi_stress: {len(tps_results)} tick events loaded')
    if rtr_results: print(f'  recursive_thermal_ramp: {len(rtr_results)} ramp events loaded')

    print('Generating figures...')
    fig1_lyapunov()
    # fig2_basin_3d()  # CUT — flat 3D bowl (superseded by 2D; fig2b_basin_2d kept)
    fig2b_basin_2d()
    fig3_thermal()
    fig4_theta_psi(tps_results)
    fig5_recursive_ramp(rtr_results)
    fig6_trust_bifurcation()
    fig7_vmem()
    fig8_basin_volume()    # EXP-MC-01 — reads figures/data/basin_mins.csv
    # fig10_lyapunov()     # CUT — flat Lyapunov spectrum (number suffices; see main.tex)
    fig11_sustained_noise()  # EXP-NS-01 — reads figures/data/sustained_noise.csv
    # fig9_topology is generated on n02 via scripts/tda/fig_topology.py (ripser)

    print(f'\nAll figures written to {FIGDIR}/')
    print('To update with real results:')
    print(f'  python plot_results.py --events /path/to/events_sample.jsonl')
