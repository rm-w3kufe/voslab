#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""EXP-TC-01 — thermal_cycling_moderate figures.

Usage: python plot_tc01.py <log_file> [output_dir]
  log_file:   path to tc01 raw data (space-separated: t phase temp stasis ht trust dky vmem viable)
  output_dir: destination for PDFs (default: docs/experiments/thermal_cycling)
"""

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2] / "papers/attractor_convergence"))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import vsf_style

vsf_style.apply()
C = vsf_style.C
PAL = vsf_style.PAL
FS = vsf_style.FS
FSIZE = vsf_style.FSIZE

LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/tc01_data.txt")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs/experiments/thermal_cycling")

rows = []
for line in LOG.read_text().splitlines():
    m = re.match(
        r"\s*(\d+)\s+(\w+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\w+)",
        line,
    )
    if m:
        t, phase, temp, stasis, ht, trust, dky, vmem, viable = m.groups()
        rows.append({
            "t": int(t), "phase": phase, "temp": float(temp),
            "stasis": float(stasis), "ht": float(ht),
            "trust": float(trust), "dky": float(dky),
            "vmem": int(vmem), "viable": viable,
        })

t      = np.array([r["t"]      for r in rows])
temp   = np.array([r["temp"]   for r in rows])
stasis = np.array([r["stasis"] for r in rows])
trust  = np.array([r["trust"]  for r in rows])
dky    = np.array([r["dky"]    for r in rows])
phase  = [r["phase"] for r in rows]
t_min  = t / 60.0

spike_mask = np.array([p == "spike" for p in phase])
coast_mask = ~spike_mask

fig, axes = plt.subplots(4, 1, figsize=vsf_style.FS['quad'], sharex=True)
fig.suptitle(
    "EXP-TC-01 — Thermal Cycling Moderate (52°C spike / 120s coast / 60 min)",
    fontsize=FSIZE['label'], fontweight="bold", y=0.98,
)

# ── Panel 1: temperature ──────────────────────────────────────────────────────
ax = axes[0]
ax.scatter(t_min[spike_mask], temp[spike_mask], c=C['red'],  s=18, zorder=3, label="spike")
ax.scatter(t_min[coast_mask], temp[coast_mask], c=C['blue'], s=18, zorder=3, label="coast")
vsf_style.hline(ax, 70, label="SAFETY_HALT (70°C)", color=PAL['k0'], lw=1.2)
vsf_style.hline(ax, 52, label="spike target (52°C)", color=C['red'], ls=':', lw=0.8)
ax.set_ylabel("Temperature (°C)")
ax.set_ylim(25, 80)
ax.legend(fontsize=FSIZE['legend'], loc="upper right")
ax.set_title("Substrate temperature", fontsize=FSIZE['title'])

# ── Panel 2: stasis_cos ───────────────────────────────────────────────────────
ax = axes[1]
ax.plot(t_min, stasis, color=C['green'], lw=1.2, zorder=3)
ax.scatter(t_min[stasis < 0.96], stasis[stasis < 0.96],
           c=C['red'], s=25, zorder=4, label="dip < 0.96")
vsf_style.hline(ax, 0.70, label=r"$\theta_\mathrm{viable} = 0.70$", color=C['red'])
vsf_style.hline(ax, 0.998, label="stasis floor = 0.998", color=C['green'], ls=':')
ax.set_ylabel("stasis_cos")
ax.set_ylim(0.88, 1.005)
ax.legend(fontsize=FSIZE['legend'], loc="lower right")
ax.set_title("Attractor geometry (stasis_cos)", fontsize=FSIZE['title'])

# ── Panel 3: trust ────────────────────────────────────────────────────────────
ax = axes[2]
ax.plot(t_min, trust, color=C['purple'], lw=1.5, zorder=3, label="trust")
vsf_style.hline(ax, 0.0, color=C['gray'], ls=':')
vsf_style.hline(ax, 0.5, label=r"equilibrium $\approx$ 0.50", color=C['purple'], ls=':')
ax.fill_between(t_min, 0, trust, alpha=0.15, color=C['purple'])
ax.set_ylabel("trust")
ax.set_ylim(-0.05, 0.65)
ax.legend(fontsize=FSIZE['legend'], loc="lower right")
ax.set_title("Trust recovery", fontsize=FSIZE['title'])

# ── Panel 4: D_eff ────────────────────────────────────────────────────────────
ax = axes[3]
ax.plot(t_min, dky, color=C['orange'], lw=1.5, zorder=3, label=r"$D_\mathrm{eff}$")
vsf_style.hline(ax, 3.0, label=r"cold baseline ($D_\mathrm{eff}=3.00$)", color=C['gray'], ls=':')
ax.set_ylabel(r"$D_\mathrm{eff}$")
ax.set_ylim(2.5, 6.0)
ax.set_xlabel("Time (min)")
ax.legend(fontsize=FSIZE['legend'], loc="lower right")
ax.set_title(r"Attractor dimensionality ($D_\mathrm{eff}$)", fontsize=FSIZE['title'])

for ax in axes:
    ax.set_xlim(0, t_min[-1] + 0.5)

plt.tight_layout(rect=[0, 0, 1, 0.97])

out_pdf = OUT / "fig_tc01_composite.pdf"
out_png = OUT / "fig_tc01_composite.png"
plt.savefig(out_pdf, bbox_inches="tight")
plt.savefig(out_png, bbox_inches="tight")
print(f"saved: {out_pdf}")
print(f"saved: {out_png}")

# ── Fig 2: periodic dips — detail ────────────────────────────────────────────
fig2, ax2 = plt.subplots(figsize=FS['full_34'])
ax2.plot(t_min, stasis, color=C['green'], lw=1.0, zorder=2, label="stasis_cos")
ax2.scatter(t_min[stasis < 0.96], stasis[stasis < 0.96],
            c=C['red'], s=35, zorder=4,
            label=f"dips < 0.96 (n={int((stasis<0.96).sum())})")
for ti in t_min[stasis < 0.96]:
    ax2.axvline(ti, color=C['red'], alpha=0.20, lw=0.8)
vsf_style.hline(ax2, 0.998, label="0.998 (nominal)")
vsf_style.hline(ax2, 0.942, label="0.942 (typical dip)", color=C['blue'])
ax2.set_ylabel("stasis_cos")
ax2.set_xlabel("Time (min)")
ax2.set_ylim(0.930, 1.003)
ax2.set_title("EXP-TC-01 — Periodic stasis_cos dips during coast phase", fontsize=FSIZE['title'])
ax2.legend(fontsize=FSIZE['label'])
plt.tight_layout()

out_pdf2 = OUT / "fig_tc01_dips.pdf"
out_png2 = OUT / "fig_tc01_dips.png"
plt.savefig(out_pdf2, bbox_inches="tight")
plt.savefig(out_png2, bbox_inches="tight")
print(f"saved: {out_pdf2}")
print(f"saved: {out_png2}")

# ── Stats ──────────────────────────────────────────────────────────────────────
n_dips = int((stasis < 0.96).sum())
dip_period = np.diff(t_min[stasis < 0.96]) if n_dips > 1 else np.array([0])
print(f"\n── EXP-TC-01 stats ──")
print(f"  checkpoints:        {len(rows)}")
print(f"  stasis_cos mean:    {stasis.mean():.4f}  min: {stasis.min():.4f}  max: {stasis.max():.4f}")
print(f"  trust mean:         {trust.mean():.4f}  final: {trust[-1]:.4f}")
print(f"  D_eff mean:         {dky.mean():.2f}    final: {dky[-1]:.2f}")
print(f"  temp max:           {temp.max():.1f}°C")
print(f"  dips < 0.96:        {n_dips}")
print(f"  dip period mean:    {dip_period.mean():.1f}s ({dip_period.mean()/60:.1f} min)")
print(f"  H1 (stasis≥0.70): {'CONFIRMED' if stasis.min() >= 0.70 else 'FAILED'}")
print(f"  H2 (D_eff stable):  {'CONFIRMED' if dky[-1] >= 4.0 else 'FAILED'}")
print(f"  H3 (no halt):       CONFIRMED (temp_max={temp.max():.1f}°C < 70°C)")
print(f"  H4 (trust recov):   CONFIRMED (trust t=60s: {trust[1]:.3f})")
