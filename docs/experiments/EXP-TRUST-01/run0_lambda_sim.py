#!/usr/bin/env python3
"""
EXP-TRUST-01 Run 0 — theoretical λ calibration simulation.

Computes EMA decay curves for λ ∈ {0.05, 0.10, 0.15, 0.20} with obs=0.
Goal: determine how distinguishable per-axis λ_i values would be, and whether
the shared-λ implementation (adaptive_lambda, range [0.05, 0.20]) is sufficient.

Outputs JSON + terminal summary for phase_b_spec.vsm decision gate.
"""

import json, math, os

LAMBDA_CANDIDATES = [0.05, 0.10, 0.15, 0.20]
TICKS = 60          # simulate 60 ticks (~60 min at 60s/tick)
TRUST_INIT = 1.0    # steady-state starting value

AXIS_DOMAIN_PRIORS = {
    # Domain semantics → expected λ_i (from H_TRUST2)
    "behavioral":    0.20,  # fast: kernel behavior changes quickly, λ→ max
    "structural":    0.05,  # slow: binary integrity is slow to degrade/recover
    "predictive":    0.10,  # medium: regime changes within minutes
    "communicative": 0.15,  # medium-fast: emit health matters immediately
}

def decay_curve(lambda_i: float, ticks: int, trust_init: float = 1.0) -> list[float]:
    """EMA decay: trust(t) = (1-λ)^t * trust_init when obs=0."""
    return [(1 - lambda_i) ** t * trust_init for t in range(ticks + 1)]

def fit_lambda(curve: list[float], trust_init: float = 1.0) -> float:
    """Estimate λ from an observed decay curve via log-linear regression."""
    log_vals = []
    for t, v in enumerate(curve):
        if v > 0 and v <= trust_init:
            log_vals.append((t, math.log(v / trust_init)))
    if len(log_vals) < 2:
        return float("nan")
    # log(trust/trust_init) = t * log(1-λ) → slope = log(1-λ)
    n = len(log_vals)
    ts = [p[0] for p in log_vals]
    ys = [p[1] for p in log_vals]
    t_mean = sum(ts) / n
    y_mean = sum(ys) / n
    num = sum((ts[i] - t_mean) * (ys[i] - y_mean) for i in range(n))
    den = sum((ts[i] - t_mean) ** 2 for i in range(n))
    if den < 1e-12:
        return float("nan")
    slope = num / den
    return 1 - math.exp(slope)

def distinguishability(curve_a: list[float], curve_b: list[float]) -> float:
    """Mean absolute difference between two decay curves (0=identical)."""
    return sum(abs(a - b) for a, b in zip(curve_a, curve_b)) / len(curve_a)

# ── Compute curves ────────────────────────────────────────────────────────────
curves = {}
for lam in LAMBDA_CANDIDATES:
    curves[lam] = decay_curve(lam, TICKS)

# ── Key tick markers ──────────────────────────────────────────────────────────
markers = [5, 10, 15, 20, 30, 45, 60]

print("=== EXP-TRUST-01 Run 0: λ calibration simulation ===\n")
print(f"{'tick':>5}", end="")
for lam in LAMBDA_CANDIDATES:
    print(f"  λ={lam:.2f}", end="")
print()
for t in markers:
    print(f"{t:>5}", end="")
    for lam in LAMBDA_CANDIDATES:
        print(f"  {curves[lam][t]:.4f}", end="")
    print()

print("\n=== Distinguishability matrix (mean |curve_a - curve_b| over 60 ticks) ===")
print(f"{'':>8}", end="")
for lam_b in LAMBDA_CANDIDATES:
    print(f"  λ={lam_b:.2f}", end="")
print()
for lam_a in LAMBDA_CANDIDATES:
    print(f"λ={lam_a:.2f} ", end="")
    for lam_b in LAMBDA_CANDIDATES:
        d = distinguishability(curves[lam_a], curves[lam_b])
        print(f"  {d:.4f}", end="")
    print()

print("\n=== Domain priors vs shared-λ baseline ===")
shared_lambda_baseline = 0.10  # adaptive_lambda base rate
baseline_curve = decay_curve(shared_lambda_baseline, TICKS)
print(f"Shared λ baseline = {shared_lambda_baseline}")
print(f"{'axis':>15}  prior_λ  trust@t10  trust@t30  dist_vs_shared")
for axis, prior_lam in AXIS_DOMAIN_PRIORS.items():
    prior_curve = decay_curve(prior_lam, TICKS)
    d = distinguishability(prior_curve, baseline_curve)
    print(f"  {axis:13s}  {prior_lam:.2f}     "
          f"{prior_curve[10]:.4f}     {prior_curve[30]:.4f}     {d:.4f}")

print(f"\n  shared_λ=0.10       "
      f"{baseline_curve[10]:.4f}     {baseline_curve[30]:.4f}     ---")

# ── Decision logic ────────────────────────────────────────────────────────────
max_domain_dist = max(
    distinguishability(decay_curve(lam, TICKS), baseline_curve)
    for lam in AXIS_DOMAIN_PRIORS.values()
)
NOISE_FLOOR = 0.02  # trust measurement noise floor (estimated from phase A var)

print(f"\n=== Decision gate ===")
print(f"Max dist (domain prior vs shared λ): {max_domain_dist:.4f}")
print(f"Noise floor estimate (from phase A var): {NOISE_FLOOR:.4f}")
if max_domain_dist > 3 * NOISE_FLOOR:
    verdict = "PER-AXIS λ_i WARRANTED — curves significantly distinguishable above noise"
else:
    verdict = "SHARED λ SUFFICIENT — curves within noise floor, per-axis not warranted"
print(f"Verdict: {verdict}")

# ── Save results ──────────────────────────────────────────────────────────────
results = {
    "run": 0,
    "description": "theoretical λ calibration simulation",
    "ticks": TICKS,
    "lambda_candidates": LAMBDA_CANDIDATES,
    "curves": {str(lam): curves[lam] for lam in LAMBDA_CANDIDATES},
    "domain_priors": AXIS_DOMAIN_PRIORS,
    "shared_lambda_baseline": shared_lambda_baseline,
    "distinguishability": {
        f"{a}vs{b}": distinguishability(curves[a], curves[b])
        for a in LAMBDA_CANDIDATES for b in LAMBDA_CANDIDATES
    },
    "max_domain_dist_vs_shared": max_domain_dist,
    "noise_floor_estimate": NOISE_FLOOR,
    "verdict": verdict,
}

out_dir = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "run0_lambda_curves.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nResults written → {out_path}")
