#!/usr/bin/env python3
"""EXP-LYAP-CERT — calibrate lyapunov.rs r_core / drift_band on the REAL live L-trajectory.

Reads the production events.jsonl, extracts every live kernel_tick's (l_x, mean_l, mean_dl, regime),
characterizes the steady-state (in_recurrent_set) distribution, and proposes calibrated thresholds.

Read-only. Pure stdlib. Run on the LXC that owns events.jsonl (101):
    python3 lyap_cert_analyze.py [/var/lib/vsf/vsf_nucleus/events.jsonl]

Spec: docs/experiments/lyapunov_cert/spec.vsm
"""
import json, sys, math

PATH = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/vsf/vsf_nucleus/events.jsonl"

# Current heuristic thresholds (calibration.rs) — for comparison.
CUR_R_CORE = 0.50
CUR_DRIFT_BAND = 1e-3
SIGMA_DRIFT_GAIN = 100.0   # W4 secondary check

def fmt(x):
    if x is None:
        return "None"
    if isinstance(x, float):
        if x != 0 and abs(x) < 1e-3:
            return f"{x:.3e}"
        return f"{x:.5f}"
    return str(x)

def stats(xs):
    n = len(xs)
    if n == 0:
        return dict(n=0, mean=None, std=None, mn=None, mx=None)
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / n if n > 1 else 0.0
    return dict(n=n, mean=mu, std=math.sqrt(var), mn=min(xs), mx=max(xs))

def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]

l_x_all, mean_l_all, mean_dl_all = [], [], []
l_x_R, mean_l_R, mean_dl_R = [], [], []   # in_recurrent_set subset (steady state)
regimes = {}
n_total = 0

with open(PATH, encoding="utf-8", errors="ignore") as fh:
    for line in fh:
        if "kernel_tick" not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        m = d.get("metrics", d)
        k, ly = m.get("kernel"), m.get("lyapunov")
        if not isinstance(k, dict) or not isinstance(ly, dict):
            continue   # pre-W1/W2 ticks lack these blocks → skipped
        lx, ml, mdl, reg = k.get("l_x"), ly.get("mean_l"), ly.get("mean_dl"), ly.get("regime")
        if lx is None or ml is None or mdl is None:
            continue
        n_total += 1
        regimes[reg] = regimes.get(reg, 0) + 1
        l_x_all.append(lx); mean_l_all.append(ml); mean_dl_all.append(mdl)
        if reg == "in_recurrent_set":
            l_x_R.append(lx); mean_l_R.append(ml); mean_dl_R.append(mdl)

print(f"# EXP-LYAP-CERT — live L-trajectory calibration")
print(f"source: {PATH}")
print(f"n_live_ticks (kernel+lyapunov present) = {n_total}")
print(f"regime counts = {regimes}")
print()

sL  = stats(mean_l_R)     # mean_l within recurrent set → drives r_core
sLx = stats(l_x_R)        # raw l_x within recurrent set (spread)
sD  = stats(mean_dl_R)    # mean_dl within recurrent set → drives drift_band

print("## steady-state (regime=in_recurrent_set) distributions")
print(f"  mean_l : n={sL['n']} mean={fmt(sL['mean'])} std={fmt(sL['std'])} "
      f"min={fmt(sL['mn'])} max={fmt(sL['mx'])} p99={fmt(pct(mean_l_R,0.99))}")
print(f"  l_x    : n={sLx['n']} mean={fmt(sLx['mean'])} std={fmt(sLx['std'])} "
      f"min={fmt(sLx['mn'])} max={fmt(sLx['mx'])} p99={fmt(pct(l_x_R,0.99))}")
print(f"  mean_dl: n={sD['n']} mean={fmt(sD['mean'])} std={fmt(sD['std'])} "
      f"min={fmt(sD['mn'])} max={fmt(sD['mx'])} |p99|={fmt(pct([abs(x) for x in mean_dl_R],0.99))}")
print()

# ── proposed calibrated thresholds ────────────────────────────────────────────
if sL["n"] >= 2 and sD["n"] >= 2:
    r_core_star = sL["mean"] + 6 * sL["std"]            # 6σ upper bound on mean_l in R
    drift_band_star = 3 * sD["std"]                     # 3σ ΔL noise floor
    print("## proposed calibration")
    print(f"  r_core*     = μ_L + 6σ_L      = {fmt(r_core_star)}   (current {CUR_R_CORE})")
    print(f"  drift_band* = 3·σ_ΔL         = {fmt(drift_band_star)}   (current {CUR_DRIFT_BAND})")
    print()
    # discriminative margin: how many σ_L of headroom does the CURRENT loose core give?
    margin_cur = (CUR_R_CORE - sL["mean"]) / sL["std"] if sL["std"] else float("inf")
    margin_new = (r_core_star - sL["mean"]) / sL["std"] if sL["std"] else float("inf")
    print("## discriminative power (headroom above μ_L, in σ_L units)")
    print(f"  current r_core=0.50 → {fmt(margin_cur)}σ_L  (huge ⇒ governed ~trivially true)")
    print(f"  r_core*            → {fmt(margin_new)}σ_L  (6σ ⇒ no false alarm, leaving R now detectable)")
    print(f"  max observed mean_l in R = {fmt(sL['mx'])} (must stay < r_core* for no false alarm: "
          f"{'OK' if sL['mx'] < r_core_star else 'VIOLATION'})")
    print()
    # H_LC1/H_LC2 verdicts
    h1 = r_core_star < CUR_R_CORE * 0.8
    h2 = (drift_band_star / CUR_DRIFT_BAND) < 3.0 and (CUR_DRIFT_BAND / max(drift_band_star,1e-12)) < 3.0
    print("## hypothesis verdicts")
    print(f"  H_LC1 (r_core loose, tighten): {'CONFIRMED' if h1 else 'REJECTED'} "
          f"(r_core* {fmt(r_core_star)} vs 0.50)")
    print(f"  H_LC2 (drift_band ~right, within 3x): {'CONFIRMED' if h2 else 'REJECTED'} "
          f"(drift_band* {fmt(drift_band_star)} vs 1e-3)")
    # H_LC4 W4 clock gain check
    half_speed_excess = 1.0 / SIGMA_DRIFT_GAIN          # mean_dl - band giving σ=1
    if sD["std"] and sD["std"] > 0:
        gain_sigmas = half_speed_excess / sD["std"]
        print(f"  H_LC4 (clock gain): σ=1 at mean_dl-band={half_speed_excess} = {fmt(gain_sigmas)}σ_ΔL "
              f"above floor → {'OK (only anomalous drift accelerates)' if gain_sigmas > 3 else 'TOO TWITCHY'}")
else:
    print("## insufficient steady-state samples — need more in_recurrent_set ticks")
