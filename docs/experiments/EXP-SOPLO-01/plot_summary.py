#!/usr/bin/env python3
# design: docs/plans/figure_style_design_2026_10_25.vsm
"""EXP-SOPLO-01 figure from soplo_landauer_summary.json (runs on WSL, doc-gen)."""
import json, sys, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', 'papers', 'attractor_convergence'))
import vsf_style
vsf_style.apply()
C = vsf_style.C
PAL = vsf_style.PAL
FS = vsf_style.FS
FSIZE = vsf_style.FSIZE

src = sys.argv[1] if len(sys.argv) > 1 else "results/soplo_landauer_summary.json"
rows = json.load(open(src))["per_sigma"]
nz = [r for r in rows if r["sigma"] and r["sigma"] > 0]
sig = [r["sigma"] for r in nz]
allsig = [r["sigma"] for r in rows]

fig, ax = plt.subplots(2, 2, figsize=FS['comp3'])

# P2 — register entropy
ax[0,0].plot(allsig, [r["H_tau_hist_bits"] for r in rows], "o-", label="histogram")
ax[0,0].plot(allsig, [r["H_tau_gauss_bits"] for r in rows], "s--", color=C['red'], label="Gaussian ½ln(2πeσ²)")
ax[0,0].set(xlabel="σ  (register noise)", ylabel="H(τ)  [bits]",
            title="P2 — register entropy ↑ with σ")
ax[0,0].legend(fontsize=FSIZE['legend']); ax[0,0].grid(alpha=.3)

# P4 — soplo frequency (corrects seed's ∝1/σ)
ax[0,1].plot(allsig, [r["f_soplo_per_k_per_1k"] for r in rows], "^-", color=C['orange'])
ax[0,1].set(xlabel="σ", ylabel="resets / kernel / 1000 ticks",
            title="P4 — soplo frequency ↑ with σ  (seed said ∝1/σ — wrong sign)")
ax[0,1].grid(alpha=.3)

# F2 — clamp saturation: where the erasure lives
ax[1,0].plot(allsig, [r["clamp_sat_frac"] for r in rows], "D-", color=C['green'])
ax[1,0].set(xlabel="σ", ylabel="fraction of ticks at τ=1",
            title="F2 — clamp ceiling dominates erasure at low σ", ylim=(0,1.05))
ax[1,0].grid(alpha=.3)

# P5 — dissipation per soplo vs the naïve 1-bit claim; + dissipation RATE
ax2 = ax[1,1]
dps = [r["diss_per_soplo_bits"] for r in nz]
ax2.plot(sig, dps, "v-", color=C['purple'], label="diss / soplo  (measured)")
ax2.axhline(1.0, ls="--", color=C['gray'], label="kT·ln2  (naïve 1 bit/soplo)")
ax2.set(xlabel="σ", ylabel="bits / soplo", title="P5 — diss/soplo ≠ kT·ln2 (and ↓ with σ)")
ax2.set_yscale("log"); ax2.legend(fontsize=FSIZE['legend']); ax2.grid(alpha=.3)
axb = ax2.twinx()
axb.plot(allsig, [r["diss_rate_bits_tick"] for r in rows], ":", color=C['blue'],
         label="diss rate (bits/tick)")
axb.set_ylabel("dissipation rate [bits/tick]", color=C['blue'])
axb.tick_params(axis="y", labelcolor=C['blue'])

fig.suptitle("EXP-SOPLO-01 — Landauer cost of the trust-soplo: the reset is reversible (ΔH≡0);\n"
             "dissipation is an ensemble entropy-balance quantity, clamp+soplo jointly, ≠ kT·ln2/firing",
             fontsize=FSIZE['title'])
fig.tight_layout(rect=[0,0,1,0.96])
out = os.path.join(os.path.dirname(src), "fig_soplo_landauer.pdf")
fig.savefig(out); fig.savefig(out.replace(".pdf",".png"), dpi=110)
print("wrote", out)
