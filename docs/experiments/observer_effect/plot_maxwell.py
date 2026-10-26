#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""EXP-OE-01 Maxwell's Demon — generate figures for paper"""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2] / "papers/attractor_convergence"))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import vsf_style

vsf_style.apply()
C = vsf_style.C
PAL = vsf_style.PAL
FS = vsf_style.FS
FSIZE = vsf_style.FSIZE

OUT = str(Path(__file__).parent / "figures")
Path(OUT).mkdir(exist_ok=True)


# ── Simulate (exact Rust logic) ───────────────────────────────────────────────
def simulate(ticks=50000, demon=False, h_target=0.80):
    energies = [0.0, 0.5, 1.0, 1.5]
    kT = 1.0
    boltzmann = [math.exp(-e/kT) for e in energies]
    Z = sum(boltzmann)
    p_eq = [b/Z for b in boltzmann]

    p = [0.25]*4
    trust = 0.80
    h_max = 0.85 * math.log2(4)

    def entropy(dist):
        s = sum(dist)
        return -sum((pi/s)*math.log2(pi/s) for pi in dist if pi/s > 0)

    h_series, cos_series, dky_series, iv_series = [], [], [], []
    interventions = 0
    stasis_vec = [0.0]*128
    stasis_vec[32:36] = p[:]
    stasis_vec[24] = entropy(p)
    stasis_vec[10] = trust
    stasis_norm = math.sqrt(sum(x*x for x in stasis_vec))

    for tick in range(ticks):
        for i in range(4):
            p[i] = 0.99*p[i] + 0.01*p_eq[i]

        if demon and tick % 100 == 0:
            h_now = entropy(p)
            if h_now > h_target:
                shift = 0.05
                p[0] = min(p[0] + shift*2, 1.0)
                p[1] = min(p[1] + shift, 1.0)
                p[2] = max(p[2] - shift, 0.01)
                p[3] = max(p[3] - shift*2, 0.01)
                s = sum(p); p = [pi/s for pi in p]
                interventions += 1

        h_t = entropy(p)
        trust_delta = 0.002 if h_t < h_max*0.7 else -0.001
        trust = max(0.0, min(1.0, trust + trust_delta))

        sv = [0.0]*128
        sv[32:36] = p[:]
        sv[24] = h_t; sv[10] = trust; sv[13] = 1.0 if trust > 0.5 else 0.0
        dot = sum(a*b for a, b in zip(sv, stasis_vec))
        norm_sv = math.sqrt(sum(x*x for x in sv))
        cos = dot/(norm_sv*stasis_norm) if norm_sv*stasis_norm > 0 else 1.0

        active = sum(1 for pi in p if pi > 0.06)
        d_ky = active + trust*2.0

        h_series.append(h_t)
        cos_series.append(cos)
        dky_series.append(d_ky)
        iv_series.append(interventions)

    return h_series, cos_series, dky_series, iv_series, entropy(p_eq)


print("Simulating conditions A and B...")
hA, cA, dA, ivA, h_eq = simulate(50000, demon=False)
hB, cB, dB, ivB, _    = simulate(50000, demon=True)
ticks = list(range(50000))

STYLE = dict(linewidth=1.2)
ALPHA = 0.85


# ── Figure 1: H(t) comparison ─────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=vsf_style.FS['single'])
ax.plot(ticks, hA, color=C['blue'], label='A — free (2nd law)', **STYLE, alpha=ALPHA)
ax.plot(ticks, hB, color=C['red'],  label='B — with demon (S4 active)', **STYLE, alpha=ALPHA)
vsf_style.hline(ax, h_eq, label=f'H_eq = {h_eq:.4f} bits')
vsf_style.hline(ax, 0.80, label='H_target = 0.80', color=C['orange'], ls=':')
ax.set_xlabel('tick')
ax.set_ylabel('H(t)  [bits]')
ax.set_title("EXP-OE-01 — Maxwell's Demon: Shannon entropy H(t)")
ax.legend(fontsize=FSIZE['label'])
ax.set_xlim(0, 50000)
ax.set_ylim(0.5, 2.2)
fig.tight_layout()
fig.savefig(f'{OUT}/fig_oe01_entropy.pdf')
fig.savefig(f'{OUT}/fig_oe01_entropy.png')
plt.close()
print("fig_oe01_entropy: saved")

# ── Figure 2: stasis_cos comparison ──────────────────────────────────────────
fig, ax = plt.subplots(figsize=FS['full_34'])
ax.plot(ticks, cA, color=C['blue'], label='A — free', **STYLE, alpha=ALPHA)
ax.plot(ticks, cB, color=C['red'],  label='B — with demon', **STYLE, alpha=ALPHA)
vsf_style.hline(ax, 0.70, label=r'$\theta_\mathrm{viable} = 0.70$', color=C['red'], lw=1.0)
ax.set_xlabel('tick')
ax.set_ylabel('stasis_cos')
ax.set_title('EXP-OE-01 — Attractor stability (stasis_cos)')
ax.legend(fontsize=FSIZE['label'])
ax.set_xlim(0, 50000)
ax.set_ylim(0.98, 1.002)
fig.tight_layout()
fig.savefig(f'{OUT}/fig_oe01_stasis.pdf')
fig.savefig(f'{OUT}/fig_oe01_stasis.png')
plt.close()
print("fig_oe01_stasis: saved")

# ── Figure 3: D_eff + interventions (dual axis) ───────────────────────────────
fig, ax1 = plt.subplots(figsize=vsf_style.FS['single'])
ax2 = ax1.twinx()
ax1.plot(ticks, dA, color=C['blue'], label=r'$D_\mathrm{eff}$ A (free)', **STYLE, alpha=ALPHA)
ax1.plot(ticks, dB, color=C['red'],  label=r'$D_\mathrm{eff}$ B (demon)', **STYLE, alpha=ALPHA)
ax2.plot(ticks, ivB, color=C['orange'], linestyle='-', linewidth=0.8,
         alpha=0.6, label='interventions (B)')
ax1.set_xlabel('tick')
ax1.set_ylabel(r'$D_\mathrm{eff}$ (effective attractor dimension)')
ax2.set_ylabel('cumulative interventions', color=C['orange'])
ax2.tick_params(axis='y', labelcolor=C['orange'])
ax1.set_title(r'EXP-OE-01 — Attractor dimension $D_\mathrm{eff}$ + demon interventions')
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1+lines2, labels1+labels2, fontsize=FSIZE['label'])
ax1.set_xlim(0, 50000)
fig.tight_layout()
fig.savefig(f'{OUT}/fig_oe01_dky.pdf')
fig.savefig(f'{OUT}/fig_oe01_dky.png')
plt.close()
print("fig_oe01_dky: saved")

# ── Figure 4: composite 3-panel ───────────────────────────────────────────────
# Smooth the demon's per-100-tick oscillation so the trend is visible.
# Without smoothing, 500 saw-teeth across 50k ticks render as a solid block.
def smooth(arr, window=500):
    a = np.asarray(arr, dtype=float)
    if len(a) < window:
        return a
    kernel = np.ones(window) / window
    return np.convolve(a, kernel, mode='same')

hA_s, hB_s = smooth(hA), smooth(hB)
cA_s, cB_s = smooth(cA), smooth(cB)
dA_s, dB_s = smooth(dA), smooth(dB)

fig = plt.figure(figsize=FS['comp3'])
gs  = gridspec.GridSpec(3, 1, hspace=0.55, left=0.10, right=0.90,
                        top=0.94, bottom=0.08)

# ── panel 1: H(t) ────────────────────────────────────────────────────────────
ax0 = fig.add_subplot(gs[0])
# raw envelope (low alpha) so reader sees the oscillation amplitude
ax0.plot(ticks, hA, color=C['blue'], lw=0.7, alpha=0.20)
ax0.plot(ticks, hB, color=C['red'],  lw=0.7, alpha=0.20)
# smoothed trend (heavy line) — this is what the eye locks onto
ax0.plot(ticks, hA_s, color=C['blue'], lw=1.6, alpha=0.95,
         label='A — free (mean)')
ax0.plot(ticks, hB_s, color=C['red'],  lw=1.6, alpha=0.95,
         label='B — demon (mean)')
vsf_style.hline(ax0, h_eq, label=f'$H_{{eq}}$ = {h_eq:.3f} bits')
ax0.set_ylabel('H(t)  [bits]')
ax0.set_title("EXP-OE-01 — Maxwell's Demon: observer as entropic regulator",
              fontsize=FSIZE['title'])
ax0.set_xlim(0, 50000)
ax0.set_ylim(1.30, 2.05)
ax0.legend(fontsize=FSIZE['legend'], loc='lower right', ncol=3, framealpha=0.92)
ax0.text(0.020, 0.10,
         f'$\\Delta H = H_{{eq}} - \\langle H_B\\rangle = {h_eq - hB[-1]:.4f}$ bits',
         transform=ax0.transAxes, fontsize=FSIZE['label'], color=C['red'], fontweight='bold',
         bbox=dict(boxstyle='round,pad=0.25', fc='white',
                   ec=C['red'], alpha=0.92))

# ── panel 2: stasis_cos ──────────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[1])
ax1.plot(ticks, cA, color=C['blue'], lw=0.7, alpha=0.20)
ax1.plot(ticks, cB, color=C['red'],  lw=0.7, alpha=0.20)
ax1.plot(ticks, cA_s, color=C['blue'], lw=1.6, alpha=0.95, label='A — free')
ax1.plot(ticks, cB_s, color=C['red'],  lw=1.6, alpha=0.95, label='B — demon')
vsf_style.hline(ax1, 1.000, color=C['gray'], ls=':', lw=0.9)
ax1.set_ylabel('stasis_cos')
ax1.set_xlim(0, 50000)
# auto-fit to actual data range (ignore the first transient drop)
y_lo = min(np.min(cA[100:]), np.min(cB[100:])) - 0.0005
y_hi = 1.0010
ax1.set_ylim(y_lo, y_hi)
ax1.legend(fontsize=FSIZE['legend'], loc='lower right', ncol=2, framealpha=0.92)
ax1.text(0.020, 0.08,
         'stable plateau in both conditions $\\Rightarrow$ '
         'attractor geometry preserved (no collapse)',
         transform=ax1.transAxes, fontsize=FSIZE['label'], color=C['gray'])

# ── panel 3: D_eff + interventions ───────────────────────────────────────────
ax2 = fig.add_subplot(gs[2])
ax2r = ax2.twinx()
ax2.plot(ticks, dA, color=C['blue'], lw=0.7, alpha=0.20)
ax2.plot(ticks, dB, color=C['red'],  lw=0.7, alpha=0.20)
l_a, = ax2.plot(ticks, dA_s, color=C['blue'], lw=1.6, alpha=0.95,
                label=r'$D_\mathrm{eff}$ A (free)')
l_b, = ax2.plot(ticks, dB_s, color=C['red'],  lw=1.6, alpha=0.95,
                label=r'$D_\mathrm{eff}$ B (demon)')
l_iv, = ax2r.plot(ticks, ivB, color=C['orange'], lw=1.4, alpha=0.85,
                  label='cumul. interventions (B)')
ax2.set_ylabel(r'$D_\mathrm{eff}$')
ax2.set_xlabel('tick')
ax2.set_xlim(0, 50000)
ax2.set_ylim(2.7, 5.6)
ax2r.set_ylabel('cumulative interventions', color=C['orange'])
ax2r.tick_params(axis='y', labelcolor=C['orange'])
ax2r.set_ylim(0, 550)
ax2.legend([l_a, l_b, l_iv], [l.get_label() for l in (l_a, l_b, l_iv)],
           fontsize=FSIZE['legend'], loc='center right', framealpha=0.92)

fig.savefig(f'{OUT}/fig_oe01_composite.pdf')
fig.savefig(f'{OUT}/fig_oe01_composite.png')
plt.close()
print("fig_oe01_composite: saved")

print(f"\nAll figures -> {OUT}/")
print(f"H_eq={h_eq:.4f}  dH={h_eq - hB[-1]:.4f} bits  interventions={ivB[-1]}")
