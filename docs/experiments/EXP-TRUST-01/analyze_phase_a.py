#!/usr/bin/env python3
"""
EXP-TRUST-01 Phase A analysis script.
Run after 2026-06-18T19:00Z (phase A close gate).
Produces stationarity stats + axis correlation matrix for phase B design.

Usage (on LXC 101 or after pulling events.jsonl locally):
  python3 analyze_phase_a.py [events.jsonl path]
"""

import json, sys, math
from datetime import datetime, timezone

EVENTS_PATH = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/vsf/vsf_nucleus/events.jsonl"
PHASE_A_START = datetime(2026, 6, 11, 19, 0, 0, tzinfo=timezone.utc)
PHASE_A_END   = datetime(2026, 6, 18, 19, 0, 0, tzinfo=timezone.utc)

events = []
with open(EVENTS_PATH, errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line or "kernel_tick" not in line:
            continue
        try:
            d = json.loads(line)
            ts = datetime.fromisoformat(d["ts"].replace("Z", "+00:00"))
            if ts < PHASE_A_START or ts > PHASE_A_END:
                continue
            m = d.get("metrics", {})
            ta = m.get("trust_axes", {})
            events.append({
                "ts": ts,
                "trust":         m.get("kernel", {}).get("trust"),
                "stasis_cos":    m.get("kernel", {}).get("stasis_cos"),
                "regime":        m.get("lyapunov", {}).get("regime"),
                "mean_dl":       m.get("lyapunov", {}).get("mean_dl"),
                "behavioral":    ta.get("behavioral"),
                "structural":    ta.get("structural"),
                "predictive":    ta.get("predictive"),
                "communicative": ta.get("communicative"),
                "min_axis":      ta.get("min_axis"),
                "lambda":        ta.get("lambda"),
            })
        except:
            pass

print(f"=== EXP-TRUST-01 Phase A Analysis ===")
print(f"Events in window: {len(events)}")
if not events:
    print("No events found. Check path and date range.")
    sys.exit(1)

print(f"First: {events[0]['ts'].isoformat()}")
print(f"Last:  {events[-1]['ts'].isoformat()}")
elapsed_h = (events[-1]['ts'] - events[0]['ts']).total_seconds() / 3600
print(f"Elapsed: {elapsed_h:.1f}h of 168h target ({elapsed_h/168*100:.1f}%)")

# Coverage
expected_ticks = elapsed_h * 3600 / 60  # ~60s per tick
print(f"Coverage: {len(events)/expected_ticks*100:.1f}% ({len(events)}/{int(expected_ticks)} expected)")

# Regime distribution
regimes = {}
for e in events:
    r = e["regime"] or "none"
    regimes[r] = regimes.get(r, 0) + 1
print(f"\nRegimes: {regimes}")

# Stationarity stats
def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    n = len(vals)
    mean = sum(vals) / n
    var = sum((x - mean)**2 for x in vals) / n
    std = math.sqrt(var)
    mn, mx = min(vals), max(vals)
    # lag-1 autocorr
    if n > 1:
        ac = sum((vals[i]-mean)*(vals[i-1]-mean) for i in range(1,n)) / (n*var) if var > 0 else 0
    else:
        ac = 0
    return {"n": n, "mean": round(mean,5), "std": round(std,6), "min": round(mn,5),
            "max": round(mx,5), "autocorr_lag1": round(ac,4)}

print("\n=== Stationarity ===")
for key in ["trust", "stasis_cos", "behavioral", "structural", "predictive", "communicative", "min_axis", "lambda"]:
    s = stats([e[key] for e in events])
    if s:
        print(f"  {key:15s}: mean={s['mean']:.5f}  std={s['std']:.6f}  "
              f"min={s['min']:.5f}  max={s['max']:.5f}  ac1={s['autocorr_lag1']:.4f}  n={s['n']}")

# Axis correlation matrix (post-D4 events only)
axes = ["behavioral", "structural", "predictive", "communicative"]
ax_events = [e for e in events if all(e[a] is not None for a in axes)]
print(f"\n=== Axis Correlation Matrix (n={len(ax_events)} post-D4 events) ===")
if len(ax_events) > 10:
    means = {a: sum(e[a] for e in ax_events)/len(ax_events) for a in axes}
    def corr(a, b):
        n = len(ax_events)
        num = sum((e[a]-means[a])*(e[b]-means[b]) for e in ax_events)
        da = math.sqrt(sum((e[a]-means[a])**2 for e in ax_events))
        db = math.sqrt(sum((e[b]-means[b])**2 for e in ax_events))
        return num/(da*db) if da*db > 0 else 0.0
    print(f"{'':14s}", end="")
    for b in axes:
        print(f"  {b[:8]:>8s}", end="")
    print()
    for a in axes:
        print(f"  {a:12s}", end="")
        for b in axes:
            print(f"  {corr(a,b):8.4f}", end="")
        print()
    print()
    print("H_TRUST1 (|corr|<0.3 for i≠j):", end=" ")
    off_diag = [abs(corr(a,b)) for i,a in enumerate(axes) for j,b in enumerate(axes) if i!=j]
    max_od = max(off_diag)
    print(f"max off-diagonal = {max_od:.4f} → {'CONFIRMED' if max_od < 0.3 else 'REFUTED'}")
else:
    print("  Insufficient post-D4 events for correlation.")

print("\n=== Phase B Readiness ===")
print("  Gate (trust_axes in telemetry): CLEARED (D4 508b374 2026-06-13)")
print("  run_2 target: corrupt binary on LXC 108 → structural ↓ → measure λ_structural")
print("  run_3 target: behavioral noise injection → cross-axis leak measurement")
print("  Safety: perturbations ONLY on LXC 108, never prod LXC 101")
