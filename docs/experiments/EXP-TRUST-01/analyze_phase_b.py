#!/usr/bin/env python3
"""
analyze_phase_b.py — EXP-TRUST-01 Phase B analysis

⚠⚠ SUPERSEDED 2026-06-19 by run_4_analyze.py (real-loop) — DO NOT USE FOR NEW VERDICTS ⚠⚠
   This analyzed the output of the STANDALONE SIMULATOR (main.rs::run_trust_phase_b), which
   hardcoded λ=0.10 and synthesised observations — a PROXY of the real trust pipeline. Its
   verdicts are simulator artifacts. The authoritative analysis is run_4_analyze.py over the
   real operational-loop events.jsonl. Kept for provenance. See run_4_spec.vsm.

Tests H_TRUST1_B (axis independence under perturbation), H_TRUST2 (per-axis λ_i),
H_TRUST3 (observable proxy correlation).

Usage:
  python3 analyze_phase_b.py --run2 <dir> --run3 <dir> [--out results/]
"""
import json, sys, os, math, argparse
from collections import defaultdict

CORR_THRESHOLD = 0.3   # H_TRUST1_B: |corr| < 0.3
PROXY_THRESHOLD = 0.7  # H_TRUST3: proxy corr >= 0.7


def load_ticks(data_dir):
    """Load trust_phase_b tick events from events.jsonl."""
    path = os.path.join(data_dir, "telemetry", "vsf-nucleus", "events.jsonl")
    ticks = []
    with open(path) as f:
        for line in f:
            ev = json.loads(line.strip())
            if ev.get("event_type") == "init_step":
                m = ev.get("metrics", {})
                if m.get("step") == "trust_phase_b" and m.get("metrics", {}).get("run") is not None:
                    inner = m["metrics"]
                    if inner.get("tick") is not None:
                        ticks.append(inner)
    return ticks


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx  = math.sqrt(sum((x-mx)**2 for x in xs))
    dy  = math.sqrt(sum((y-my)**2 for y in ys))
    if dx < 1e-15 or dy < 1e-15:
        return 0.0
    return max(-1.0, min(1.0, num / (dx*dy)))


def fit_lambda(series, target, n_fit=50):
    """
    Fit λ from an EMA recovery curve: x(t+1) = x(t) + λ·(target - x(t))
    Using log-linear regression: ln(target - x(t)) = ln(target - x(0)) + t·ln(1-λ)
    Returns estimated λ.
    """
    ys = []
    for i, v in enumerate(series[:n_fit]):
        diff = target - v
        if diff < 1e-12:
            break
        ys.append((i, math.log(diff)))
    if len(ys) < 5:
        return None
    n = len(ys)
    ts = [y[0] for y in ys]
    ls = [y[1] for y in ys]
    t_mean, l_mean = sum(ts)/n, sum(ls)/n
    num = sum((t-t_mean)*(l-l_mean) for t,l in zip(ts,ls))
    den = sum((t-t_mean)**2 for t in ts)
    if abs(den) < 1e-15:
        return None
    slope = num / den  # = ln(1-λ)
    lam = 1.0 - math.exp(slope)
    return round(lam, 6)


def analyze_run(ticks, run_id):
    breach = [t for t in ticks if t["phase"] == "breach"]
    recov  = [t for t in ticks if t["phase"] == "recovery"]

    def axis(phase_ticks, name):
        return [t["trust_axes"][name] for t in phase_ticks]

    # Breach window axis series
    b_beh  = axis(breach, "behavioral")
    b_stru = axis(breach, "structural")
    b_pred = axis(breach, "predictive")
    b_comm = axis(breach, "communicative")
    b_kt   = [t.get("kernel_trust", t["trust_axes"]["behavioral"]) for t in breach]

    # Recovery window axis series
    r_beh  = axis(recov, "behavioral")
    r_stru = axis(recov, "structural")
    r_pred = axis(recov, "predictive")
    r_comm = axis(recov, "communicative")

    # ── H_TRUST1_B: cross-axis independence during breach ────────────────────
    if run_id == "run_2":
        perturbed = b_stru
        others = {"behavioral": b_beh, "predictive": b_pred, "communicative": b_comm}
        proxy_series = b_stru   # structural_obs=0 → structural↓ (proxy=structural_obs)
        proxy_target = "structural"
    else:  # run_3
        perturbed = b_beh
        others = {"structural": b_stru, "predictive": b_pred, "communicative": b_comm}
        proxy_series = b_kt     # kernel_trust (σ-noise) drives behavioral↓
        proxy_target = "behavioral"

    corrs = {name: pearson(perturbed, series) for name, series in others.items()}
    h1b_pass = all(abs(r) < CORR_THRESHOLD for r in corrs.values())

    # ── H_TRUST2: per-axis λ fit from recovery curves ───────────────────────
    lambda_fits = {}
    if run_id == "run_2":
        # structural decayed to ~0 in breach; recovers toward 1.0
        lam_stru = fit_lambda(r_stru, 1.0)
        lambda_fits = {"structural_recovery": lam_stru,
                       "behavioral_recovery": fit_lambda(r_beh, 0.9987),
                       "predictive_recovery": fit_lambda(r_pred, 1.0),
                       "communicative_recovery": fit_lambda(r_comm, 1.0)}
    else:
        # behavioral was noisy in breach; recovers toward 0.9987
        lambda_fits = {"behavioral_recovery": fit_lambda(r_beh, 0.9987),
                       "structural_recovery": fit_lambda(r_stru, 1.0),
                       "predictive_recovery": fit_lambda(r_pred, 1.0),
                       "communicative_recovery": fit_lambda(r_comm, 1.0)}

    # H_TRUST2 verdict: all fitted λ should be close to 0.10 (shared λ)
    fits = [v for v in lambda_fits.values() if v is not None]
    h2_verdict = all(abs(v - 0.10) < 0.05 for v in fits) if fits else None
    h2_note = f"all ≈ 0.10 (shared λ)" if h2_verdict else "per-axis λ_i diverge OR not enough data"

    # ── H_TRUST3: observable proxy correlation with target axis ─────────────
    # run_2: structural_obs=0 during breach → proxy = [0.0]*n_breach; corr with structural
    # run_3: kernel_trust (noisy) drives behavioral; proxy = kernel_trust series
    if run_id == "run_2":
        proxy_obs = [0.0] * len(breach)   # structural_obs = 0 during entire breach
        h3_corr = pearson(proxy_obs, b_stru)
    else:
        h3_corr = pearson(proxy_series, b_beh)
    h3_pass = abs(h3_corr) >= PROXY_THRESHOLD

    # ── breach-window stats ──────────────────────────────────────────────────
    def stats(series):
        n = len(series)
        m = sum(series)/n
        std = math.sqrt(sum((x-m)**2 for x in series)/n) if n>1 else 0
        return {"mean": round(m,6), "std": round(std,6), "min": round(min(series),6), "max": round(max(series),6)}

    return {
        "run": run_id,
        "n_breach": len(breach),
        "n_recovery": len(recov),
        "breach_stats": {
            "behavioral": stats(b_beh),
            "structural": stats(b_stru),
            "predictive": stats(b_pred),
            "communicative": stats(b_comm),
        },
        "H_TRUST1_B": {
            "verdict": "CONFIRMED" if h1b_pass else "REFUTED",
            "corrs": {k: round(v, 4) for k,v in corrs.items()},
            "threshold": CORR_THRESHOLD,
            "pass": h1b_pass,
        },
        "H_TRUST2": {
            "verdict": "CONFIRMED" if h2_verdict else ("REFUTED" if h2_verdict is False else "INSUFFICIENT_DATA"),
            "lambda_fits": {k: v for k,v in lambda_fits.items()},
            "note": h2_note,
            "pass": h2_verdict,
        },
        "H_TRUST3": {
            "verdict": "CONFIRMED" if h3_pass else "REFUTED",
            "proxy_target": proxy_target,
            "proxy_corr": round(h3_corr, 4),
            "threshold": PROXY_THRESHOLD,
            "pass": h3_pass,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run2", required=True, help="VSF_DATA_DIR for run_2")
    ap.add_argument("--run3", required=True, help="VSF_DATA_DIR for run_3")
    ap.add_argument("--out", default="docs/experiments/EXP-TRUST-01/results", help="Output directory")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    results = {}

    for run_id, data_dir in [("run_2", args.run2), ("run_3", args.run3)]:
        print(f"\n── Analyzing {run_id} from {data_dir} ──")
        ticks = load_ticks(data_dir)
        print(f"   {len(ticks)} tick events loaded")
        r = analyze_run(ticks, run_id)
        results[run_id] = r

        # Print per-run summary
        print(f"\n   Breach stats (N={r['n_breach']}):")
        for axis, st in r["breach_stats"].items():
            print(f"     {axis:14s}: mean={st['mean']:.4f}  std={st['std']:.6f}  [{st['min']:.4f}..{st['max']:.4f}]")

        h1 = r["H_TRUST1_B"]
        print(f"\n   H_TRUST1_B ({h1['verdict']}): perturbed vs others")
        for axis, corr in h1["corrs"].items():
            flag = "✓" if abs(corr) < CORR_THRESHOLD else "✗"
            print(f"     |corr({run_id[:5]}_perturbed, {axis})| = {abs(corr):.4f}  {flag}")

        h2 = r["H_TRUST2"]
        print(f"\n   H_TRUST2 ({h2['verdict']}): recovery λ_i fits")
        for axis, lam in h2["lambda_fits"].items():
            print(f"     {axis:30s}: λ={lam}" if lam else f"     {axis:30s}: λ=<insufficient data>")

        h3 = r["H_TRUST3"]
        print(f"\n   H_TRUST3 ({h3['verdict']}): proxy→{h3['proxy_target']} corr = {h3['proxy_corr']:.4f}  "
              f"(threshold ≥ {h3['threshold']})")

    # Overall verdicts
    print("\n\n══ EXP-TRUST-01 Phase B — Overall Verdicts ══════════════════════════════")
    for hyp in ["H_TRUST1_B", "H_TRUST2", "H_TRUST3"]:
        v2 = results["run_2"][hyp]["verdict"]
        v3 = results["run_3"][hyp]["verdict"]
        print(f"  {hyp}: run_2={v2}  run_3={v3}")

    # Save JSON
    out_path = os.path.join(args.out, "trust_phase_b_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results written to {out_path}")


if __name__ == "__main__":
    main()
