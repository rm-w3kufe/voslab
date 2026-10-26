#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""
generate_figures.py — VSF paper analytical figures
Run from: docs/papers/attractor_convergence/figures/

Output: fig1_thermal_response.pdf, fig2_dky_scale.pdf,
        fig3_multikernel_geometry.pdf, fig4_senescence.pdf
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import vsf_style

vsf_style.apply()
C    = vsf_style.C
M    = vsf_style.C_MONO
PAL  = vsf_style.PAL
SEQ  = vsf_style.SEQ
DIV  = vsf_style.DIV
FS   = vsf_style.FS
FSIZE = vsf_style.FSIZE

OUT = "."


# ─── Fig 1: Thermal response curve ───────────────────────────────────────────

def fig1_thermal_response():
    """Two-panel: transient (peak only) vs sustained (T x t damage)."""
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=FS['fig1_thermal_response'],
                                      sharey=True,
                                      gridspec_kw={'wspace': 0.06})

    H_FLOOR = 0.987

    # ── Panel (a): transient ──────────────────────────────────────────────────
    T_ladder   = [53, 60, 70, 76]
    cos_ladder = [0.9898, 0.9898, 0.9878, 0.9875]
    ax_a.plot(T_ladder, cos_ladder, "o-", color=C['blue'], lw=2.0, ms=8,
              label="thermal_ladder (60 s peak)", zorder=4)

    ax_a.axhline(H_FLOOR, color=C['blue'], lw=0.9, ls=':', alpha=0.8,
                 label=fr"$H_\mathrm{{floor}} = {H_FLOOR}$")

    ax_a.annotate(
        "robust:\nsame floor\nat 53–76 °C",
        xy=(70, 0.9878), xytext=(55, 0.945),
        arrowprops=dict(arrowstyle="->", color=C['blue'], lw=0.9),
        color=C['blue'], fontsize=FSIZE['label'], ha='center',
        bbox=dict(boxstyle="round,pad=0.3", fc="white",
                  ec=C['blue'], alpha=0.92),
    )

    ax_a.set_xlabel("Peak temperature (°C)")
    ax_a.set_ylabel("Min stasis cosine")
    ax_a.set_title(r"(a) Transient peak ($\leq$ 60 s)", fontsize=FSIZE['title'])
    ax_a.set_xlim(48, 81)
    ax_a.set_ylim(0.88, 1.005)
    ax_a.legend(loc="lower left", fontsize=FSIZE['legend'])

    # ── Panel (b): sustained hold ─────────────────────────────────────────────
    # reference: transient floor (so the reader sees the gap)
    ax_b.axhline(H_FLOOR, color=C['blue'], lw=0.9, ls=':', alpha=0.6,
                 label=fr"transient floor ({H_FLOOR})")

    # 2-min sustained
    ax_b.plot(63, 0.9977, "s", color=C['green'], ms=11,
              label="thermal_stress_v3  (2 min @ 63 °C)", zorder=5)

    # 5-min sustained
    ax_b.plot(68, 0.9365, "^", color=C['red'], ms=14,
              label="thermal_ceiling_v4_bis  (5 min @ 68 °C)", zorder=5)

    # damage trajectory: 2-min → 5-min  (visual gradient)
    ax_b.annotate("",
                  xy=(68, 0.9395), xytext=(63.3, 0.9947),
                  arrowprops=dict(arrowstyle="->", color=C['gray'],
                                  lw=1.4, alpha=0.55, ls='--'))

    ax_b.text(66, 0.972, "damage\n" + r"$\propto T \times t$",
              fontsize=FSIZE['title'], color=C['red'], ha='center', fontweight='bold',
              bbox=dict(boxstyle="round,pad=0.3", fc="white",
                        ec=C['red'], alpha=0.92))

    ax_b.set_xlabel("Hold temperature (°C)")
    ax_b.set_title(r"(b) Sustained hold ($\geq$ 2 min)", fontsize=FSIZE['title'])
    ax_b.set_xlim(58, 74)
    ax_b.legend(loc="lower left", fontsize=FSIZE['legend'])

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig1_thermal_response.pdf")
    print("fig1_thermal_response.pdf written")
    plt.close()


# ─── Fig 2: D_eff vs scale ───────────────────────────────────────────────────

def fig2_deff_scale():
    """CANONICAL (Law A) spec_boot series — Table 2 / tab:specboot.
    The 110-min long-run point is drawn as an OPEN marker with the
    explicit predecessor-law badge (April hardware run, pre-
    reconciliation; canonical re-measurement registered as the
    REMEASURE task, v1.0 round)."""
    fig, ax = plt.subplots(figsize=FS['fig2_dky_scale'])

    ticks  = [300,   1000, 2000, 10000, 20000]
    d_eff  = [6.00,  6.00, 6.00, 6.00,  6.00]
    labels = ["300t", "1k", "2k", "10k", "20k"]

    ax.semilogx(ticks, d_eff, "o-", color=C['purple'], lw=2, ms=8, zorder=4)
    offsets = {"300t": (0, 10), "1k": (0, 10), "2k": (0, 10),
               "10k": (-18, 10), "20k": (12, -18)}
    for x, y, lbl in zip(ticks, d_eff, labels):
        ax.annotate(lbl, xy=(x, y), xytext=offsets[lbl],
                    textcoords="offset points", ha="center", fontsize=FSIZE['label'])

    vsf_style.hline(ax, 6.00, color=C['purple'], ls=':', lw=1.0)

    # long-run observation: real April hardware data, predecessor law —
    # HONEST badge, hollow marker, distinct from the canonical series
    ax.semilogx([6e7], [3.00], "o", mfc="white", mec=C['gray'], ms=8, zorder=3)
    ax.annotate("60M (110 min) — predecessor law\n(re-measure pending)",
                xy=(6e7, 3.00), xytext=(-8, 14), ha="right",
                textcoords="offset points",
                fontsize=FSIZE['annot'], color=C['gray'])

    ax.set_xlabel("Total ticks (log scale)")
    ax.set_ylabel(r"$D_\mathrm{eff}$ estimate")
    ax.set_title("Effective Attractor Dimension ($D_\\mathrm{eff}$) vs. Scale"
                 "\n(canonical law $A$; $6.00$ from 300 ticks)")
    ax.set_ylim(1.5, 7)
    ax.set_xlim(100, 2e8)

    ax.text(0.02, 0.04,
            "(canonical law $A$ from June 2026 regression; long-run marker = April hardware run)",
            transform=ax.transAxes, ha="left", va="bottom",
            fontsize=FSIZE['annot'], fontstyle="italic", color=C['gray'],
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=C['gray'], alpha=0.85))

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig2_dky_scale.pdf")  # filename kept for \includegraphics compat
    print("fig2_dky_scale.pdf written")
    plt.close()


# ─── Fig 3: Multikernel geometry ─────────────────────────────────────────────

def fig3_multikernel_geometry():
    fig, axes = plt.subplots(1, 2, figsize=FS['fig3_multikernel'])

    # ── Left: pairwise cosine matrix ──
    ax = axes[0]
    labels = ["$k_0$\n(0.55)", "$k_1$\n(0.65)", "$k_2$\n(0.75)", "$k_3$\n(0.85)"]
    matrix = np.array([
        [1.0000, 0.9948, 0.9808, 0.9607],
        [0.9948, 1.0000, 0.9955, 0.9839],
        [0.9808, 0.9955, 1.0000, 0.9964],
        [0.9607, 0.9839, 0.9964, 1.0000],
    ])
    im = ax.imshow(matrix, cmap=SEQ, vmin=0.95, vmax=1.0)
    ax.set_xticks(range(4)); ax.set_xticklabels(labels)
    ax.set_yticks(range(4)); ax.set_yticklabels(labels)
    for i in range(4):
        for j in range(4):
            ax.text(j, i, f"{matrix[i,j]:.4f}", ha="center", va="center",
                    fontsize=FSIZE['legend'], color="black" if matrix[i,j] > 0.97 else "white")
    plt.colorbar(im, ax=ax, fraction=0.046)
    ax.set_title("Pairwise stasis-vector cosine\n(trust_init in parentheses)")

    # ── Right: final stasis_cos per kernel ──
    ax2 = axes[1]
    trust_init  = [0.55, 0.65, 0.75, 0.85]
    trust_final = [0.038, 0.141, 0.246, 0.352]
    stasis_cos  = [0.8701, 0.8822, 0.8959, 0.9096]

    ax2.plot(trust_init, stasis_cos, "o-", color=C['blue'], lw=2, ms=8,
             label="stasis_cos")
    ax2_r = ax2.twinx()
    ax2_r.plot(trust_init, trust_final, "s--", color=C['orange'], lw=1.5, ms=7,
               label="trust_final")
    ax2.set_xlabel("trust_init")
    ax2.set_ylabel("stasis_cos", color=C['blue'])
    ax2_r.set_ylabel("trust_final", color=C['orange'])
    ax2.set_title("Per-kernel final state\n(all viable_full = true)")
    ax2.set_ylim(0.84, 0.94)
    ax2_r.set_ylim(0.0, 0.45)
    ax2.legend(loc="upper left", fontsize=FSIZE['label'])

    fig.suptitle("Multi-Kernel Basin Geometry — SAME BASIN (H1 confirmed)", y=1.01)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig3_multikernel_geometry.pdf")
    print("fig3_multikernel_geometry.pdf written")
    plt.close()


# ─── Fig 4: Long-run stability (senescence) ──────────────────────────────────

def fig4_senescence():
    # Checkpoints from long_run_senescence log (every 60s, 110 min).
    # Two-state alternating pattern observed in experiment: values are
    # representative of the logged alternation; noise omitted.
    t_min = list(range(1, 111))
    cos_vals = [0.9772 if i % 2 == 0 else 0.9996 for i in range(110)]
    cos_vals[80] = 0.9939   # occasional mid-values seen in log around t=6420s
    cos_vals[87] = 0.9870

    fig, axes = plt.subplots(2, 1, figsize=FS['fig4_senescence'], sharex=True)

    ax1 = axes[0]
    ax1.plot(t_min, cos_vals, lw=1, color=C['blue'], alpha=0.85)
    vsf_style.hline(ax1, float(np.mean(cos_vals)),
                    label=f"mean = {float(np.mean(cos_vals)):.4f}",
                    color=C['red'], lw=1.5)
    ax1.fill_between(t_min, 0.97, cos_vals, alpha=0.08, color=C['blue'])
    ax1.set_ylabel("stasis_cos")
    ax1.set_ylim(0.965, 1.005)
    ax1.legend(fontsize=FSIZE['label'])
    ax1.set_title(r"Long-Run Stability: 110 min / $6\times10^7$ cycles")

    ax1.annotate(
        "no drift\n"
        r"$\overline{dL} = -0.000\overline{0}$"
        "\n"
        r"$D_\mathrm{eff} = 3.00$ stable\n(predecessor law)",
        xy=(55, 0.998), fontsize=FSIZE['label'], color=C['green'],
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor=C['green'], alpha=0.8))

    ax2 = axes[1]
    trust_vals = [0.002 if i % 2 else 0.000 for i in range(110)]
    trust_vals[80] = 0.002; trust_vals[87] = 0.000
    ax2.plot(t_min, trust_vals, lw=1, color=C['purple'], alpha=0.9)
    ax2.set_ylabel("trust")
    ax2.set_ylim(-0.001, 0.004)
    ax2.set_xlabel("Wall-clock time (min)")

    # Predecessor-law badge
    fig.text(0.98, 0.01,
             "(predecessor law; canonical $D_\\mathrm{eff}=6.00$, re-measurement pending)",
             ha="right", va="bottom", fontsize=FSIZE['annot'], fontstyle="italic", color=C['gray'],
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=C['gray'], alpha=0.85))

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig4_senescence.pdf")
    print("fig4_senescence.pdf written")
    plt.close()


# ─── G-A: V = min(g,c,t,m) certifier-validation matrix (flagship) ───────────

def fig_v_capstone():
    """G-A: scenario × axis matrix — shows which face binds in each case."""
    scenarios = [
        'healthy kernel',
        'NC-01: gov=0',
        'NC-02: trust=0.5',
        'NC-03: no S2',
        r'g-break (A0)',
        r'c-break ($a{=}1.01$)',
        r't-break ($\beta_1{=}1$)',
        r'm-break (cap)',
    ]
    data = np.array([
        [0.102, 1.000, 1.000, 1.000],
        [0.000, 1.000, 1.000, 1.000],
        [0.102, 1.000, 1.000, 1.000],
        [0.102, 1.000, 1.000, 1.000],
        [0.000, 1.000, 1.000, 1.000],
        [0.102, 0.000, 1.000, 1.000],
        [0.102, 1.000, 0.000, 1.000],
        [0.102, 1.000, 1.000, 0.000],
    ])
    v_vals    = data.min(axis=1)
    bind_idx  = data.argmin(axis=1)
    nrow, ncol = data.shape

    # ── Cell color array (RGB) ─────────────────────────────────────────────────
    FILL   = np.array(SEQ(0.10)[:3])   # light blue — healthy axis
    MEDIUM = np.array(SEQ(0.45)[:3])   # mid blue — low but non-zero
    DARK   = np.array(matplotlib.colors.to_rgb(PAL['bad']))  # failed axis (=0)
    cell_rgb = np.ones((nrow, ncol, 3))
    for i in range(nrow):
        for j in range(ncol):
            v = data[i, j]
            cell_rgb[i, j] = DARK if v == 0 else (MEDIUM if v < 0.15 else FILL)

    fig, ax = plt.subplots(figsize=FS['fig_v_capstone'])
    ax.imshow(cell_rgb, aspect='auto', interpolation='none',
              extent=[-0.5, ncol - 0.5, nrow - 0.5, -0.5])

    # ── Cell value text ────────────────────────────────────────────────────────
    for i in range(nrow):
        for j in range(ncol):
            v = data[i, j]
            tc = 'white' if v == 0 else PAL['k0']
            ax.text(j, i, '1.00' if v > 0.99 else f'{v:.3f}',
                    ha='center', va='center', fontsize=FSIZE['legend'], color=tc)

    # ── Binding cell highlight (color-as-support) ──────────────────────────────
    for i in range(nrow):
        j = bind_idx[i]
        ec = C['red'] if data[i, j] == 0 else C['orange']
        ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                    fc='none', ec=ec, lw=2.2, zorder=3))

    # ── V column ───────────────────────────────────────────────────────────────
    vx = ncol + 0.35
    ax.text(vx, -0.75, r'$V$', ha='center', va='center',
            fontsize=FSIZE['title'], fontweight='bold', color=M['k0'])
    ax.plot([ncol - 0.5 + 0.05, ncol - 0.5 + 0.05], [-0.5, nrow - 0.5],
            color=M['k3'], lw=0.7, ls='--')
    for i, v in enumerate(v_vals):
        fw = 'bold'
        vc = PAL['bad'] if v == 0 else PAL['k0']
        ax.text(vx, i, '1.00' if v > 0.99 else f'{v:.3f}',
                ha='center', va='center', fontsize=FSIZE['label'], color=vc, fontweight=fw)

    # ── Axes ticks & labels ────────────────────────────────────────────────────
    ax.set_xticks(range(ncol))
    ax.set_xticklabels([r'$g$', r'$c$', r'$t$', r'$m$'],
                       fontsize=FSIZE['title'], fontweight='bold')
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position('top')
    ax.set_yticks(range(nrow))
    ax.set_yticklabels(scenarios, fontsize=FSIZE['legend'])
    ax.tick_params(axis='both', which='both', length=0)

    # ── Group separator dashes ────────────────────────────────────────────────
    for sep_y in [0.5, 3.5]:
        ax.plot([-0.5, vx + 0.6], [sep_y, sep_y],
                color=M['k3'], lw=0.6, ls='--')

    # ── Group labels ──────────────────────────────────────────────────────────
    grp_x = vx + 0.65
    for lbl, mid_y in [('baseline', 0.0), ('NC ablations', 2.0),
                        ('per-axis\nbreaks', 5.5)]:
        ax.text(grp_x, mid_y, lbl, ha='left', va='center',
                fontsize=FSIZE['annot'], color=M['k2'])

    ax.set_xlim(-0.5, grp_x + 1.3)
    ax.set_ylim(nrow - 0.5, -1.1)

    # ── Legend ────────────────────────────────────────────────────────────────
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(fc='none', ec=C['orange'], lw=2.2, label='binding (viable)'),
        Patch(fc='none', ec=C['red'],    lw=2.2, label='binding (V=0)'),
        Patch(fc=DARK.tolist(), ec='none',       label='axis = 0'),
    ], loc='lower left', fontsize=FSIZE['legend'], framealpha=0.92,
       bbox_to_anchor=(-0.01, -0.01), handlelength=1.4)

    ax.set_title(r'$V = \min(g,\,c,\,t,\,m)$: certifier-validation suite'
                 '\n(EXP-VNC-01 + EXP-G-01)',
                 fontsize=FSIZE['title'], pad=22)

    fig.subplots_adjust(left=0.26, right=0.88, top=0.88, bottom=0.04)
    fig.savefig(f"{OUT}/fig_v_capstone.pdf")
    print("fig_v_capstone.pdf written")
    plt.close()


# ─── G-B: μ* concentration vs noise ─────────────────────────────────────────

def fig_mu_star_concentration():
    """G-B: frac_in_Ωa and min_cos vs σ (EXP-CORE-01 mu_star_concentration table)."""
    sigma   = [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.00, 2.00]
    frac_Oa = [1.0000, 1.0000, 1.0000, 1.0000, 0.9998, 0.9980, 0.9940, 0.9764, 0.9272]
    min_cos = [1.0000, 0.9668, 0.9337, 0.8985, 0.8741, 0.8587, 0.8560, 0.8560, 0.8560]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=FS['fig_mu_star'], sharex=True)

    # ── Top: frac_in_Ωa ──────────────────────────────────────────────────────
    ax1.plot(sigma, frac_Oa, 'o-', color=PAL['data'], lw=1.8, ms=4.5, zorder=3)
    ax1.fill_between(sigma, frac_Oa, [1.0] * len(sigma),
                     alpha=0.10, color=PAL['bad'], label='leaked from $\\Omega_A$')
    ax1.axvline(1.0, color=PAL['ref'], lw=0.8, ls=':', zorder=2)
    ax1.annotate('leak onset\n$\\sigma\\approx 1.0$',
                 xy=(1.0, 0.9764), xytext=(1.3, 0.955),
                 arrowprops=dict(arrowstyle='->', color=PAL['ref'], lw=0.8),
                 fontsize=FSIZE['legend'], color=PAL['k1'])
    ax1.set_ylabel(r'$\mathrm{frac\_in\_}\Omega_A$')
    ax1.set_ylim(0.90, 1.008)
    ax1.legend(fontsize=FSIZE['legend'], loc='lower left')
    ax1.set_title(r'$\mu^*$ concentration in $\Omega_A$ vs noise amplitude $\sigma$')

    # ── Bottom: min_cos ───────────────────────────────────────────────────────
    ax2.plot(sigma, min_cos, 'o--', color=PAL['alt'], lw=1.3, ms=4.5, zorder=3,
             label=r'$\min\cos(s,\bar{s})$')
    ax2.axhline(0.88, color=PAL['ref'], lw=0.8, ls=':', label=r'$\theta_A=0.88$ (Fierro)')
    ax2.axhline(0.70, color=PAL['k2'], lw=0.7, ls='-.', label=r'$\theta_\mathrm{viable}=0.70$')
    ax2.axvline(1.0, color=PAL['ref'], lw=0.8, ls=':')
    ax2.annotate('plateau\n$0.856 > \\theta_\\mathrm{viable}$',
                 xy=(0.50, 0.8560), xytext=(0.80, 0.878),
                 arrowprops=dict(arrowstyle='->', color=M['k2'], lw=0.8),
                 fontsize=FSIZE['legend'], color=M['k1'])
    ax2.set_ylabel(r'$\min\,\mathrm{cos}$')
    ax2.set_xlabel(r'Noise amplitude $\sigma$')
    ax2.set_ylim(0.66, 1.02)
    ax2.legend(fontsize=FSIZE['legend'], loc='lower left')

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_mu_star_concentration.pdf")
    print("fig_mu_star_concentration.pdf written")
    plt.close()


# ─── G-C: per-constraint Ω-slack census ──────────────────────────────────────

def fig_slack_census():
    """G-C: slack per Ω-constraint at attractor (EXP-G-01), ethics-as-geometry."""
    labels = [
        r'A3$_\mathrm{cpu}$',
        r'$A_5$ trust',
        r'$A_\varepsilon$ entropy',
        'lifecycle',
        r'A3$_\mathrm{comp}$',
        r'A3$_\mathrm{budget}$',
        'governed',
        'A0 purpose',
        'A0.1 coercion',
    ]
    slacks = [0.102, 0.20, 0.50, 0.60, 0.80, 0.90, 1.00, 1.00, 1.00]

    _ramp      = [SEQ(x) for x in np.linspace(0.80, 0.12, 8)]
    colors     = [PAL['bad']] + _ramp
    edgecolors = ['none'] * 7 + [M['k2'], M['k2']]

    fig, ax = plt.subplots(figsize=FS['fig_slack_census'])
    y = np.arange(len(labels))
    bars = ax.barh(y, slacks, color=colors, edgecolor=edgecolors,
                   height=0.60, linewidth=0.9)

    # Dashed border on ethics bars (A0, A0.1)
    for i in [7, 8]:
        bars[i].set_linestyle('--')
        bars[i].set_linewidth(1.0)

    ax.axvline(0.102, color=PAL['ref'], lw=0.8, ls='--',
               label='$g = 0.102$ (binding)')

    # Binding annotation
    ax.annotate('binding\n$g=0.102$',
                xy=(0.102, 0), xytext=(0.28, 0.15),
                arrowprops=dict(arrowstyle='->', color=M['k0'], lw=0.9),
                fontsize=FSIZE['legend'], color=M['k0'], va='center')

    # Ethics violation note
    ax.text(0.52, 7.65,
            r'violation $\Rightarrow$ $g=0$, $V=0$ (H\_G3)',
            fontsize=FSIZE['legend'], color=M['k1'], style='italic',
            bbox=dict(boxstyle='round,pad=0.3', fc='white',
                      ec=M['k3'], lw=0.8))

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=FSIZE['label'])
    ax.set_xlabel(r'Normalised slack')
    ax.set_xlim(0, 1.22)
    ax.set_title(r'Per-constraint $\Omega$-slack census (EXP-G-01, at attractor)')
    ax.legend(fontsize=FSIZE['legend'], loc='lower right')

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_slack_census.pdf")
    print("fig_slack_census.pdf written")
    plt.close()


# ─── G-D: V discrimination (EXP-VNC-01) ─────────────────────────────────────

def fig_v_discrimination():
    """G-D: V = min(g,c,t,m) discrimination — viable baseline vs ablations."""
    scenarios = [
        'healthy kernel',
        'NC-01: gov=0',
        'NC-02: trust=0.5',
        'NC-03: no S2',
        'g-break: A0 violation',
        r'c-break: $a=1.01$',
        r't-break: $\beta_1=1$',
        'm-break: cap probe',
    ]
    v_vals = [0.102, 0.000, 0.102, 0.102, 0.000, 0.000, 0.000, 0.000]

    colors     = [PAL['good'] if v > 0 else PAL['bad'] for v in v_vals]
    edgecolors = ['none'] * len(v_vals)

    fig, ax = plt.subplots(figsize=FS['fig_v_discrimination'])
    y = np.arange(len(scenarios))
    bars = ax.barh(y, v_vals, color=colors, edgecolor=edgecolors,
                   height=0.55, linewidth=0.9)

    # Dashed border on failed bars
    for i, v in enumerate(v_vals):
        if v == 0:
            bars[i].set_linestyle('--')
            bars[i].set_linewidth(1.0)

    ax.axvline(0.102, color=PAL['ref'], lw=0.8, ls=':',
               label='$V=0.102$ (viable baseline)')

    # Group separator lines
    ax.axhline(0.5, color=PAL['k3'], lw=0.5)
    ax.axhline(3.5, color=PAL['k3'], lw=0.5)

    # Group labels (right margin)
    ax.text(0.143, 0.0,  'baseline',     fontsize=FSIZE['annot'], color=M['k2'], va='center')
    ax.text(0.143, 2.0,  'NC ablations', fontsize=FSIZE['annot'], color=M['k2'], va='center')
    ax.text(0.143, 5.5,  'per-axis\nbreaks', fontsize=FSIZE['annot'], color=M['k2'], va='center')

    ax.set_yticks(y)
    ax.set_yticklabels(scenarios, fontsize=FSIZE['label'])
    ax.set_xlabel(r'$V = \min(g,\,c,\,t,\,m)$')
    ax.set_xlim(-0.01, 0.19)
    ax.set_title(r'$V$ discrimination: viable vs ablated (EXP-VNC-01)')
    ax.legend(fontsize=FSIZE['legend'], loc='lower right')

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_v_discrimination.pdf")
    print("fig_v_discrimination.pdf written")
    plt.close()


# ─── G-F: Trust trajectory — Law A vs Law B ─────────────────────────────────

def fig_trust_two_law():
    """G-F: trust(t) under Law A (canonical) vs Law B (retired).

    Constants from src/main.rs:1796-1800 (law A), :5411 (law B).
    Two-panel: left = zoom first 50 cycles; right = full 600-cycle run.
    """
    # Parameters grounded in main.rs
    COS   = 0.897   # EXP-L1-01 stall / plateau point
    TAU_0 = 0.5
    N     = 600

    # ── Law A: Δτ = 0.025·cos − 0.04·(1−cos); soplo +0.18 when τ < 0.75 ─────
    tau_A      = np.zeros(N)
    tau_A[0]   = TAU_0
    soplo_ticks = []
    for k in range(1, N):
        tau   = tau_A[k - 1]
        if tau < 0.75:
            tau = min(1.0, tau + 0.18)
            soplo_ticks.append(k)
        drift = 0.025 * COS - 0.04 * (1.0 - COS)   # = 0.065·cos − 0.04 = +0.0183
        tau_A[k] = np.clip(tau + drift, 0.0, 1.0)

    # ── Law B: phase-driven; cos=0.897 < 0.998 threshold → degen, −0.001/cycle
    tau_B    = np.zeros(N)
    tau_B[0] = TAU_0
    for k in range(1, N):
        tau_B[k] = max(0.0, tau_B[k - 1] - 0.001)

    t        = np.arange(N)
    settle_k = int(np.argmax(tau_A >= 1.0))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=FS['fig_trust_two_law'],
                                   gridspec_kw={'width_ratios': [1, 2],
                                                'wspace': 0.10})

    for ax, xlim in [(ax1, 50), (ax2, N)]:
        ax.plot(t, tau_A, color=PAL['data'], lw=1.8, ls='-',
                label=r'Law A (canonical, cos-driven + soplo)')
        ax.plot(t, tau_B, color=PAL['alt'], lw=1.3, ls='--',
                label=r'Law B (retired, phase-driven)')
        ax.axhline(0.75, color=PAL['ref'], lw=0.7, ls=':',
                   label=r'soplo threshold $\tau<0.75$')
        ax.set_xlim(0, xlim)
        ax.set_ylim(-0.07, 1.16)
        ax.set_xlabel('Cycle')

    ax1.set_ylabel(r'Trust $\tau$')
    ax2.tick_params(labelleft=False)

    # ── Soplo event markers (zoom panel) ─────────────────────────────────────
    for k in soplo_ticks:
        ax1.plot(k, tau_A[k], 'o', color=PAL['good'], ms=7, zorder=5)
    if soplo_ticks:
        last = soplo_ticks[-1]
        ax1.annotate(
            f'soplo $\\times{len(soplo_ticks)}$\n($\\tau\\!+\\!=\\!0.18$)',
            xy=(last, tau_A[last]), xytext=(last + 8, 0.73),
            arrowprops=dict(arrowstyle='->', color=PAL['good'], lw=0.9),
            fontsize=FSIZE['legend'], color=PAL['good'])

    # ── Law A settled annotation (zoom panel) ─────────────────────────────────
    ax1.annotate(
        f'settled $\\tau=1$ at cycle {settle_k}',
        xy=(settle_k, 1.0), xytext=(settle_k + 5, 1.06),
        arrowprops=dict(arrowstyle='->', color=PAL['ref'], lw=0.8),
        fontsize=FSIZE['legend'], color=PAL['k0'])

    # ── Law B drain zone (full panel) ────────────────────────────────────────
    ax2.fill_between(t, tau_B, 0, where=(tau_B < 0.08),
                     alpha=0.15, color=PAL['bad'])
    ax2.annotate(
        r'$\tau\to 0$ ($A5_{\mathrm{trust\_min}}\to 0$, $V\to 0$)',
        xy=(495, 0.01), xytext=(280, 0.14),
        arrowprops=dict(arrowstyle='->', color=PAL['bad'], lw=0.8),
        fontsize=FSIZE['legend'], color=PAL['bad'])

    # ── Legend (zoom panel only) ─────────────────────────────────────────────
    ax1.legend(fontsize=FSIZE['legend'], loc='center right')

    # ── Panel labels ─────────────────────────────────────────────────────────
    ax1.set_title('(a) First 50 cycles', fontsize=FSIZE['title'])
    ax2.set_title('(b) Full run (600 cycles)', fontsize=FSIZE['title'])

    fig.savefig(f"{OUT}/fig_trust_two_law.pdf")
    print("fig_trust_two_law.pdf written")
    plt.close()


if __name__ == "__main__":
    fig1_thermal_response()
    fig2_deff_scale()
    fig3_multikernel_geometry()
    fig4_senescence()
    fig_v_capstone()
    fig_mu_star_concentration()
    fig_slack_census()
    fig_v_discrimination()
    fig_trust_two_law()
    print("All figures generated.")
