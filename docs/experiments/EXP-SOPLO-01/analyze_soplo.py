#!/usr/bin/env python3
"""
EXP-SOPLO-01 — Landauer cost of the trust-soplo. Offline analysis.

Reads the σ-sweep telemetry produced by `vsf-nucleus soplo_landauer`
(run_soplo_landauer in src/main.rs) and computes, per σ:

  P1  per-event soplo ΔH        — the bare reset is an injective shift ⇒ Δτ ≡ +0.18
  P2  H(τ;σ) stationary         — histogram differential entropy + Gaussian cross-check
  P3  entropy balance           — noise injection rate vs deterministic removal rate
  P4  f_soplo(σ)                — resets / kernel / 1000 ticks (monotone ↑ in σ)
  P5  dissipation per soplo     — kT · (entropy removed)/n_soplos  ≠ kT·ln2 in general
  P6  Landauer floor            — dissipation ≥ 0, no Second-Law violation

The dissipation rate is the per-tick differential-entropy REMOVED by the
deterministic sub-step (drift + soplo + clamp): ΔH_det = H({trust}) − H({tau_noised}).
At stationarity ΔH_noise = H({tau_noised}) − H({tau_pre}) ≈ −ΔH_det (P3).
Physical Landauer cost = (bits removed) · k_B·T·ln2 at the measured CPU temperature.

Layout expected:
  <results_dir>/sigma_<val>/telemetry/vsf-nucleus/events.jsonl   (one dir per σ)
or a single events.jsonl passed directly (treated as one σ).

Usage:
  python3 analyze_soplo.py <results_dir> [--burn 500] [--temp 313] [--bins 64] [--plot]
"""

import json, sys, os, glob, math, argparse
from collections import defaultdict

K_B = 1.380649e-23     # J/K
LN2 = math.log(2.0)

# ── telemetry parsing ─────────────────────────────────────────────────────────
def iter_payloads(path, sub_status):
    """Yield the inner payload dict for init_step events of a given sub-status
    ('tau_sample' | 'soplo_event' | 'complete') belonging to the soplo_landauer step."""
    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or sub_status not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event_type") != "init_step" or d.get("status") != sub_status:
                continue
            m = d.get("metrics", {})
            if m.get("step") != "soplo_landauer":
                continue
            yield m.get("metrics", {})

# ── differential entropy (histogram, bits) ────────────────────────────────────
def diff_entropy_bits(samples, bins, lo=0.0, hi=1.0):
    """Histogram differential entropy estimate in bits:  −Σ p_i log2 p_i + log2(w)."""
    n = len(samples)
    if n < 2:
        return 0.0
    w = (hi - lo) / bins
    counts = [0] * bins
    for x in samples:
        if x <= lo:   b = 0
        elif x >= hi: b = bins - 1
        else:         b = int((x - lo) / w)
        counts[b] += 1
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / n
            h -= p * math.log2(p)
    return h + math.log2(w)   # add log2(bin width) for differential entropy

def gauss_entropy_bits(var):
    """½ ln(2πe·Var) in bits."""
    return 0.5 * math.log2(2.0 * math.pi * math.e * max(var, 1e-30))

def mean_var(xs):
    n = len(xs)
    if n == 0: return 0.0, 0.0
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / n
    return m, v

# ── per-σ analysis ────────────────────────────────────────────────────────────
def analyze_sigma(events_path, sigma_hint, burn, bins, temp):
    # gather tau_sample grouped by tick, plus pooled stationary values
    by_tick_pre     = defaultdict(list)
    by_tick_noised  = defaultdict(list)
    by_tick_post    = defaultdict(list)
    stationary_post = []
    kernels = set()
    max_tick = 0
    clamp_hits = 0
    clamp_tot  = 0

    for p in iter_payloads(events_path, "tau_sample"):
        t = p.get("tick", 0)
        max_tick = max(max_tick, t)
        kernels.add(p.get("kernel_id"))
        if t < burn:
            continue
        pre, noi, post = p.get("tau_pre"), p.get("tau_noised"), p.get("trust")
        if pre is None or noi is None or post is None:
            continue
        by_tick_pre[t].append(pre)
        by_tick_noised[t].append(noi)
        by_tick_post[t].append(post)
        stationary_post.append(post)
        clamp_tot += 1
        if post >= 1.0 - 1e-9:
            clamp_hits += 1

    # soplo events (stationary window)
    soplo_delta_err = 0.0
    soplo_clamped   = 0
    n_soplo         = 0
    for p in iter_payloads(events_path, "soplo_event"):
        if p.get("tick", 0) < burn:
            continue
        n_soplo += 1
        tb, ta = p.get("tau_before"), p.get("tau_after")
        if tb is not None and ta is not None:
            d = ta - tb
            soplo_delta_err = max(soplo_delta_err, abs(d - 0.18))
            if ta >= 1.0 - 1e-9:
                soplo_clamped += 1

    n_kernels = max(len(kernels), 1)
    stat_ticks = max(max_tick - burn + 1, 1)

    # σ from data if available
    sigma = sigma_hint
    if stationary_post:
        # try to read sigma off any payload
        for p in iter_payloads(events_path, "complete"):
            if "sigma" in p:
                sigma = p["sigma"]; break

    # P2 — H(τ;σ)
    m_post, v_post = mean_var(stationary_post)
    H_hist  = diff_entropy_bits(stationary_post, bins)
    H_gauss = gauss_entropy_bits(v_post)

    # P3 — entropy balance: per-tick ΔH_noise and ΔH_det, averaged over stationary ticks
    dH_noise_sum = 0.0
    dH_det_sum   = 0.0
    nt = 0
    for t in by_tick_post:
        pre, noi, post = by_tick_pre[t], by_tick_noised[t], by_tick_post[t]
        if len(pre) < 8:
            continue
        H_pre = diff_entropy_bits(pre, bins)
        H_noi = diff_entropy_bits(noi, bins)
        H_pst = diff_entropy_bits(post, bins)
        dH_noise_sum += (H_noi - H_pre)
        dH_det_sum   += (H_pst - H_noi)
        nt += 1
    dH_noise = dH_noise_sum / nt if nt else 0.0   # bits/tick injected
    dH_det   = dH_det_sum / nt if nt else 0.0      # bits/tick removed (≤0)
    diss_rate_bits = -dH_det                        # dissipation rate (bits/tick)
    balance_resid  = dH_noise + dH_det              # ≈0 at stationarity (P3)

    # P4 — soplo frequency (per kernel per 1000 ticks)
    f_soplo = n_soplo / (n_kernels * stat_ticks) * 1000.0

    # P5 — dissipation per soplo (bits)
    diss_total_bits = diss_rate_bits * stat_ticks * n_kernels
    diss_per_soplo  = diss_total_bits / n_soplo if n_soplo else float("nan")

    # P6 — physical Landauer anchor
    landauer_J_per_bit = K_B * temp * LN2
    diss_total_J = diss_total_bits * landauer_J_per_bit

    return {
        "sigma":            round(sigma, 5) if sigma is not None else None,
        "n_kernels":        n_kernels,
        "stationary_ticks": stat_ticks,
        "n_soplo":          n_soplo,
        # P1
        "soplo_delta_err":  soplo_delta_err,        # max |Δτ − 0.18|  → 0 confirms injective
        "soplo_clamped_frac": (soplo_clamped / n_soplo) if n_soplo else 0.0,
        # P2
        "tau_mean":         m_post,
        "tau_var":          v_post,
        "H_tau_hist_bits":  H_hist,
        "H_tau_gauss_bits": H_gauss,
        "clamp_sat_frac":   (clamp_hits / clamp_tot) if clamp_tot else 0.0,
        # P3
        "dH_noise_bits_tick": dH_noise,
        "dH_det_bits_tick":   dH_det,
        "balance_resid_bits": balance_resid,
        # P4
        "f_soplo_per_k_per_1k": f_soplo,
        # P5/P6
        "diss_rate_bits_tick":  diss_rate_bits,
        "diss_total_bits":      diss_total_bits,
        "diss_per_soplo_bits":  diss_per_soplo,
        "landauer_J_per_bit":   landauer_J_per_bit,
        "diss_total_J":         diss_total_J,
        "temp_K":               temp,
    }

# ── driver ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--burn", type=int, default=500)
    ap.add_argument("--temp", type=float, default=313.0, help="CPU temp (K) for J anchor")
    ap.add_argument("--bins", type=int, default=64)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    # discover σ-runs
    runs = []  # (sigma_hint, events_path)
    if os.path.isfile(args.results_dir):
        runs.append((None, args.results_dir))
    else:
        for d in sorted(glob.glob(os.path.join(args.results_dir, "sigma_*"))):
            ev = os.path.join(d, "telemetry", "vsf-nucleus", "events.jsonl")
            if os.path.isfile(ev):
                tag = os.path.basename(d).replace("sigma_", "")
                try:    hint = float(tag)
                except: hint = None
                runs.append((hint, ev))
        # fallback: a bare events.jsonl directly under results_dir
        if not runs:
            ev = os.path.join(args.results_dir, "events.jsonl")
            if os.path.isfile(ev):
                runs.append((None, ev))

    if not runs:
        print(f"no σ-runs found under {args.results_dir}", file=sys.stderr)
        sys.exit(1)

    results = []
    for hint, ev in runs:
        print(f"  analyzing σ≈{hint}  ({ev}) …", file=sys.stderr)
        results.append(analyze_sigma(ev, hint, args.burn, args.bins, args.temp))
    results.sort(key=lambda r: (r["sigma"] is None, r["sigma"]))

    # ── report table ──────────────────────────────────────────────────────────
    print("\n── EXP-SOPLO-01 — Landauer cost of the trust-soplo ───────────────────")
    print(f"   burn-in={args.burn}  bins={args.bins}  T={args.temp}K  "
          f"kT·ln2={K_B*args.temp*LN2:.3e} J/bit\n")
    hdr = ("σ", "n_soplo", "f_soplo", "H(τ)hist", "H(τ)gauss", "ΔH_noise",
           "ΔH_det", "balance", "diss/soplo", "clampSat", "Δτerr")
    print("  " + "  ".join(f"{h:>9}" for h in hdr))
    for r in results:
        print("  " + "  ".join(f"{v:>9}" for v in [
            f"{r['sigma']}",
            f"{r['n_soplo']}",
            f"{r['f_soplo_per_k_per_1k']:.3f}",
            f"{r['H_tau_hist_bits']:.3f}",
            f"{r['H_tau_gauss_bits']:.3f}",
            f"{r['dH_noise_bits_tick']:.4f}",
            f"{r['dH_det_bits_tick']:.4f}",
            f"{r['balance_resid_bits']:.4f}",
            f"{r['diss_per_soplo_bits']:.3f}",
            f"{r['clamp_sat_frac']:.3f}",
            f"{r['soplo_delta_err']:.1e}",
        ]))

    # ── verdicts ───────────────────────────────────────────────────────────────
    print("\n── verdicts ──────────────────────────────────────────────────────────")
    nz = [r for r in results if r["sigma"] and r["sigma"] > 0]
    p1 = max((r["soplo_delta_err"] for r in results), default=0.0)
    print(f"  P1 soplo injective (Δτ≡+0.18): max|Δτ−0.18| = {p1:.2e}  "
          f"→ {'CONFIRMED (per-event ΔH≡0)' if p1 < 1e-6 else 'VIOLATED (clamp engaged?)'}")
    if len(nz) >= 2:
        mono_H = all(nz[i]["H_tau_hist_bits"] <= nz[i+1]["H_tau_hist_bits"] + 1e-3
                     for i in range(len(nz)-1))
        mono_f = all(nz[i]["f_soplo_per_k_per_1k"] <= nz[i+1]["f_soplo_per_k_per_1k"] + 1e-6
                     for i in range(len(nz)-1))
        print(f"  P2 H(τ;σ) monotone ↑ in σ:           {'CONFIRMED' if mono_H else 'NOT monotone'}")
        print(f"  P4 f_soplo monotone ↑ in σ:          {'CONFIRMED' if mono_f else 'NOT monotone'}"
              f"   (seed said ∝1/σ — wrong sign)")
    worst_bal = max((abs(r["balance_resid_bits"]) for r in nz), default=0.0)
    print(f"  P3 entropy balance |resid|≤5%·ΔH_noise: worst |resid| = {worst_bal:.4f} bits/tick")
    floor_ok = all(r["diss_rate_bits_tick"] >= -1e-9 for r in results)
    print(f"  P6 Landauer floor (diss ≥ 0):        {'HELD' if floor_ok else 'VIOLATED'}")
    print(f"  P5 diss/soplo ≠ kT·ln2 (=1 bit): "
          + ", ".join(f"σ={r['sigma']}:{r['diss_per_soplo_bits']:.2f}b" for r in nz))

    # ── save summary ───────────────────────────────────────────────────────────
    out_dir = args.results_dir if os.path.isdir(args.results_dir) else os.path.dirname(args.results_dir)
    summ = os.path.join(out_dir, "soplo_landauer_summary.json")
    with open(summ, "w") as f:
        json.dump({"params": vars(args), "per_sigma": results}, f, indent=2)
    print(f"\n  summary → {summ}")

    # ── optional figure ────────────────────────────────────────────────────────
    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            sig = [r["sigma"] for r in nz]
            fig, ax = plt.subplots(1, 3, figsize=(13, 4))
            ax[0].plot(sig, [r["H_tau_hist_bits"] for r in nz], "o-")
            ax[0].set(xlabel="σ", ylabel="H(τ) [bits]", title="P2  register entropy")
            ax[1].plot(sig, [r["f_soplo_per_k_per_1k"] for r in nz], "s-", color="C1")
            ax[1].set(xlabel="σ", ylabel="f_soplo /k/1k", title="P4  reset frequency")
            ax[2].plot(sig, [r["diss_per_soplo_bits"] for r in nz], "^-", color="C2")
            ax[2].axhline(1.0, ls="--", color="grey", label="kT·ln2 (1 bit)")
            ax[2].set(xlabel="σ", ylabel="bits / soplo", title="P5  dissipation per reset")
            ax[2].legend()
            fig.tight_layout()
            figp = os.path.join(out_dir, "fig_soplo_landauer.pdf")
            fig.savefig(figp)
            print(f"  figure  → {figp}")
        except Exception as e:
            print(f"  (plot skipped: {e})", file=sys.stderr)

if __name__ == "__main__":
    main()
