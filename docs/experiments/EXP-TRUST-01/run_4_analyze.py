#!/usr/bin/env python3
"""
run_4_analyze.py — EXP-TRUST-01 run_4 (REAL-LOOP) analysis.

Reads the operational nucleus events.jsonl (kernel_tick events with metrics.trust_axes)
and tests, on the REAL trust pipeline (not the retired simulator):

  H_TRUST1_B  axis independence under perturbation:
              |corr(Δperturbed, Δother)| < 0.3 over the breach window, per other axis.
  H_TRUST2    per-axis recovery rate λ_i fitted from the real recovery curve, compared
              against the real adaptive λ recorded per tick (trust_axes.lambda).
  H_TRUST3    real observable proxy ↔ target axis correlation during breach:
              behavioral → raw kernel_trust (pre-EMA);  structural → drift_alert rate.

Usage:
  python3 run_4_analyze.py --run4a results/run_4a --run4b results/run_4b --out results/
"""
import json, os, math, argparse
from datetime import datetime

CORR_THRESHOLD = 0.30   # H_TRUST1_B
PROXY_THRESHOLD = 0.70  # H_TRUST3


def parse_ts(ts):
    """events.jsonl ts → epoch seconds (float). Handles ISO-8601 strings and numerics."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def load_ticks(data_dir):
    """kernel_tick events → list of {tick, phase, breach_active, axes{}, kt_raw, kt_obs, lambda}.
    Prefers the committed trust_slim.json (tick+trust_axes+drift only); falls back to the full
    events.jsonl Merkle chain (kept on LXC 108, *.jsonl-ignored locally) when present."""
    slim = os.path.join(data_dir, "trust_slim.json")
    if os.path.exists(slim):
        with open(slim) as f:
            blob = json.load(f)
        ticks = [{
            "tick": t["tick"], "ts": parse_ts(t["ts"]), "phase": t["phase"],
            "breach_active": t.get("breach_active", False),
            "behavioral": t["behavioral"], "structural": t["structural"],
            "predictive": t["predictive"], "communicative": t["communicative"],
            "kt_raw": t.get("kernel_trust_raw"), "kt_obs": t.get("kernel_trust_obs"),
            "lambda": t.get("lambda"),
        } for t in blob["ticks"]]
        drift_ts = [parse_ts(d) for d in blob.get("drift_ts", [])]
        ticks.sort(key=lambda t: (t["tick"] is None, t["tick"]))
        return ticks, drift_ts

    path = os.path.join(data_dir, "events.jsonl")
    ticks, drift_ts = [], []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = ev.get("event_type")
            if et == "drift_alert":
                drift_ts.append(parse_ts(ev.get("ts")))
                continue
            if et != "kernel_tick":
                continue
            m = ev.get("metrics", {})
            ta = m.get("trust_axes")
            if not ta:
                continue
            ticks.append({
                "tick": m.get("tick"),
                "ts": parse_ts(ev.get("ts")),
                "phase": ta.get("phase"),
                "breach_active": ta.get("breach_active", False),
                "behavioral": ta["behavioral"],
                "structural": ta["structural"],
                "predictive": ta["predictive"],
                "communicative": ta["communicative"],
                "kt_raw": ta.get("kernel_trust_raw"),
                "kt_obs": ta.get("kernel_trust_obs"),
                "lambda": ta.get("lambda"),
            })
    ticks.sort(key=lambda t: (t["tick"] is None, t["tick"]))
    return ticks, drift_ts


def pearson(xs, ys):
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    xs, ys = xs[:n], ys[:n]
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs))
    dy = math.sqrt(sum((y-my)**2 for y in ys))
    if dx < 1e-15 or dy < 1e-15:
        return 0.0
    return max(-1.0, min(1.0, num/(dx*dy)))


def deltas(series):
    return [series[i] - series[i-1] for i in range(1, len(series))]


def fit_lambda(series, target, n_fit=80):
    """EMA recovery x(t+1)=x(t)+λ(target-x(t)) → ln(target-x(t)) linear in t, slope=ln(1-λ)."""
    pts = []
    for i, v in enumerate(series[:n_fit]):
        diff = target - v
        if diff <= 1e-9:
            break
        pts.append((i, math.log(diff)))
    if len(pts) < 5:
        return None
    n = len(pts)
    ts = [p[0] for p in pts]; ls = [p[1] for p in pts]
    tm, lm = sum(ts)/n, sum(ls)/n
    num = sum((t-tm)*(l-lm) for t, l in zip(ts, ls))
    den = sum((t-tm)**2 for t in ts)
    if abs(den) < 1e-15:
        return None
    return round(1.0 - math.exp(num/den), 6)


def stats(series):
    n = len(series)
    if n == 0:
        return {"n": 0}
    m = sum(series)/n
    sd = math.sqrt(sum((x-m)**2 for x in series)/n) if n > 1 else 0.0
    return {"n": n, "mean": round(m, 6), "std": round(sd, 6),
            "min": round(min(series), 6), "max": round(max(series), 6)}


def analyze(ticks, drift_ts, run_id, axis):
    breach = [t for t in ticks if t["breach_active"]]
    recov = [t for t in ticks if not t["breach_active"]]
    others = [a for a in ("behavioral", "structural", "predictive", "communicative") if a != axis]

    def col(rows, name): return [r[name] for r in rows]

    # ── H_TRUST1_B — Δ-correlation of perturbed axis vs the others, in the breach window
    d_perturbed = deltas(col(breach, axis))
    corrs = {o: round(pearson(d_perturbed, deltas(col(breach, o))), 4) for o in others}
    h1_pass = all(abs(c) < CORR_THRESHOLD for c in corrs.values())

    # ── H_TRUST2 — fit recovery λ for the perturbed axis (others are flat → no curve)
    rec_axis = col(recov, axis)
    target = max(rec_axis) if rec_axis else 1.0
    lam_fit = fit_lambda(rec_axis, target)
    lam_recorded = stats([t["lambda"] for t in recov if t["lambda"] is not None])
    lam_breach = stats([t["lambda"] for t in breach if t["lambda"] is not None])

    # ── H_TRUST3 — real observable proxy ↔ target axis during breach
    if axis == "behavioral":
        proxy_name = "kernel_trust_raw (pre-EMA)"
        h3_corr = round(pearson(col(breach, "kt_raw"), col(breach, axis)), 4)
        h3_note = "raw noisy signal vs EMA-smoothed behavioral axis"
    else:
        # structural breach is a STEP (obs forced 0) → the real cheap observable is the
        # drift_alert event RATE. Bin drift_alerts by breach tick window and correlate
        # the per-bin count with the (decaying) structural axis mean in that bin.
        proxy_name = "drift_alert rate (binned)"
        if breach and drift_ts:
            t0 = breach[0]["ts"]; t1 = breach[-1]["ts"]
            span = (t1 - t0) or 1
            nbins = 10
            bin_axis = [[] for _ in range(nbins)]
            for r in breach:
                b = min(nbins-1, int((r["ts"]-t0)/span*nbins))
                bin_axis[b].append(r[axis])
            bin_drift = [0]*nbins
            for d in drift_ts:
                if d is None or d < t0 or d > t1:
                    continue
                b = min(nbins-1, int((d-t0)/span*nbins))
                bin_drift[b] += 1
            axis_means = [sum(b)/len(b) if b else 0.0 for b in bin_axis]
            h3_corr = round(pearson(bin_drift, axis_means), 4)
            h3_note = f"{sum(bin_drift)} drift_alerts over {nbins} bins vs structural axis decay"
        else:
            h3_corr = 0.0
            h3_note = "no drift_alerts in breach window"
    h3_pass = abs(h3_corr) >= PROXY_THRESHOLD

    return {
        "run": run_id, "perturbed_axis": axis,
        "n_breach": len(breach), "n_recovery": len(recov),
        "breach_axis_stats": {a: stats(col(breach, a)) for a in ("behavioral", "structural", "predictive", "communicative")},
        "lambda_recorded_breach": lam_breach,
        "lambda_recorded_recovery": lam_recorded,
        "H_TRUST1_B": {
            "verdict": "CONFIRMED" if h1_pass else "REFUTED",
            "corrs_delta": corrs, "threshold": CORR_THRESHOLD, "pass": h1_pass,
        },
        "H_TRUST2": {
            "lambda_fit_recovery": lam_fit,
            "lambda_recorded_mean": lam_recorded.get("mean"),
            "note": "fitted recovery λ for the perturbed axis vs the real adaptive λ recorded per tick",
        },
        "H_TRUST3": {
            "verdict": "CONFIRMED" if h3_pass else "REFUTED",
            "proxy": proxy_name, "proxy_corr": h3_corr,
            "threshold": PROXY_THRESHOLD, "pass": h3_pass, "note": h3_note,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run4a", required=True, help="dir with run_4a (structural) events.jsonl")
    ap.add_argument("--run4b", required=True, help="dir with run_4b (behavioral) events.jsonl")
    ap.add_argument("--out", default="results", help="output dir")
    args = ap.parse_args()

    results = {}
    for run_id, data_dir, axis in [("run_4a", args.run4a, "structural"),
                                    ("run_4b", args.run4b, "behavioral")]:
        ticks, drift_ts = load_ticks(data_dir)
        r = analyze(ticks, drift_ts, run_id, axis)
        results[run_id] = r
        print(f"\n══ {run_id} — {axis} breach (real loop) ══════════════════════════════")
        print(f"  ticks: breach={r['n_breach']} recovery={r['n_recovery']}")
        print(f"  λ recorded (adaptive): breach mean={r['lambda_recorded_breach'].get('mean')} "
              f"recovery mean={r['lambda_recorded_recovery'].get('mean')}")
        for a, st in r["breach_axis_stats"].items():
            flag = " ←perturbed" if a == axis else ""
            print(f"    {a:14s} breach: mean={st.get('mean')} std={st.get('std')} "
                  f"[{st.get('min')}..{st.get('max')}]{flag}")
        h1 = r["H_TRUST1_B"]
        print(f"  H_TRUST1_B {h1['verdict']}: Δcorr {h1['corrs_delta']} (|·|<{CORR_THRESHOLD})")
        h2 = r["H_TRUST2"]
        print(f"  H_TRUST2: λ_fit(recovery)={h2['lambda_fit_recovery']} "
              f"vs λ_recorded_mean={h2['lambda_recorded_mean']}")
        h3 = r["H_TRUST3"]
        print(f"  H_TRUST3 {h3['verdict']}: proxy={h3['proxy']} corr={h3['proxy_corr']} "
              f"(≥{PROXY_THRESHOLD}) — {h3['note']}")

    print("\n══ run_4 cross-run summary ══════════════════════════════════════════════")
    la = results["run_4a"]["H_TRUST2"]["lambda_fit_recovery"]
    lb = results["run_4b"]["H_TRUST2"]["lambda_fit_recovery"]
    print(f"  λ_structural_recovery={la}  λ_behavioral_recovery={lb}")
    if la and lb:
        same = abs(la - lb) < 0.03
        print(f"  → axes recover at {'the SAME' if same else 'DIFFERENT'} rate "
              f"(|Δλ|={abs(la-lb):.4f}) ⇒ H_TRUST2 per-axis λ "
              f"{'REFUTED-by-design (shared λ governs)' if same else 'WARRANTED'}")
    for h in ("H_TRUST1_B", "H_TRUST3"):
        print(f"  {h}: run_4a={results['run_4a'][h]['verdict']}  run_4b={results['run_4b'][h]['verdict']}")

    out_path = os.path.join(args.out, "run_4_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  → {out_path}")


if __name__ == "__main__":
    main()
