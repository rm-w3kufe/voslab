#!/usr/bin/env python3
"""VERIFY nodes — lightweight discrimination checks for ◐ instruments.

Checks:
1. stasis_cos (nucleus): varies under perturbation, healthy > 0.70
2. variety.delta: varies with load, not pinned
3. margin_free: post-BINDING-DIAG, the binding constraint changes with state

Usage:
  # Run against the live events.jsonl on LXC 101:
  python3 verify_nodes_discrimination.py --events /var/lib/vsf/events.jsonl
  
  # Or against a captured metrics file:
  python3 verify_nodes_discrimination.py --file metrics.json
"""

import json, sys, argparse, statistics, math, os

STASIS_COS_HEALTHY_MIN = 0.70
STASIS_COS_DEGRADED_MAX = 0.95  # healthy steady state should be ≥ this

def load_metrics(path: str) -> list[dict]:
    """Load JSON lines from a file. kernel is in data.metrics.kernel (canonical)."""
    metrics = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                m = data.get("metrics", {})
                if "kernel" in m and "stasis_cos" in m["kernel"]:
                    metrics.append(m)
            except json.JSONDecodeError:
                continue
    return metrics

def check_stasis_cos(metrics: list[dict]) -> dict:
    """Verify stasis_cos varies under perturbation and reads healthy in steady state."""
    cos_values = [m["kernel"]["stasis_cos"] for m in metrics if "kernel" in m]
    if not cos_values:
        return {"pass": False, "error": "no stasis_cos data"}
    
    c_min, c_max = min(cos_values), max(cos_values)
    c_median = statistics.median(cos_values)
    c_range = c_max - c_min
    
    # Varies? range should be > 0.001 for meaningful discrimination
    varies = c_range > 0.001
    
    # Healthy steady state should be > STASIS_COS_HEALTHY_MIN
    healthy = c_median > STASIS_COS_HEALTHY_MIN
    
    # Steady state should be ≥ STASIS_COS_DEGRADED_MAX (nucleus at idle is ~0.999)
    steady_ok = c_median > STASIS_COS_DEGRADED_MAX
    
    return {
        "pass": varies and healthy and steady_ok,
        "n_samples": len(cos_values),
        "min": round(c_min, 4),
        "max": round(c_max, 4),
        "median": round(c_median, 4),
        "range": round(c_range, 4),
        "varies": varies,
        "healthy": healthy,
        "steady_ok": steady_ok,
    }

def check_variety_delta(metrics: list[dict]) -> dict:
    """Verify variety.delta varies (not pinned at 0 or constant)."""
    deltas = []
    for m in metrics:
        v = m.get("variety", {})
        if "delta" in v:
            try:
                deltas.append(float(v["delta"]))
            except (ValueError, TypeError):
                pass
    
    if not deltas:
        return {"pass": False, "error": "no variety.delta data"}
    
    d_min, d_max = min(deltas), max(deltas)
    d_median = statistics.median(deltas)
    d_range = d_max - d_min
    d_nonzero = sum(1 for d in deltas if abs(d) > 0.001)
    pct_nonzero = d_nonzero / len(deltas) * 100
    
    # Varies if range > 0 (tolerance for numerical noise)
    varies = d_range > 0.0001
    # Not pinned if range is significant (even if median ~0 due to symmetric variation)
    not_pinned = d_median > 0.0001 or pct_nonzero > 10 or d_range > 0.001
    
    return {
        "pass": varies and not_pinned,
        "n_samples": len(deltas),
        "min": round(d_min, 4),
        "max": round(d_max, 4),
        "median": round(d_median, 4),
        "range": round(d_range, 4),
        "nonzero_pct": round(pct_nonzero, 1),
        "varies": varies,
        "not_pinned": not_pinned,
    }

def check_margin_free(metrics: list[dict]) -> dict:
    """Verify margin_free varies (should not be pinned at 0).

    margin_binding is a string label (constraint name) in telemetry —
    skip numeric check, only report the constraint landscape.
    """
    free_vals = []
    bind_names = set()
    for m in metrics:
        o = m.get("omega", {})
        if "margin_free" in o:
            try:
                free_vals.append(float(o["margin_free"]))
            except (ValueError, TypeError):
                pass
        if "margin_binding" in o:
            bind_names.add(str(o["margin_binding"]))
    
    if not free_vals:
        return {"pass": False, "error": "no margin_free data"}
    
    f_min, f_max = min(free_vals), max(free_vals)
    f_range = f_max - f_min
    
    # margin_free varies (should not be pinned at 0)
    free_varies = f_range > 0.0001
    
    return {
        "pass": free_varies,
        "n_samples": len(free_vals),
        "margin_free": {
            "min": round(f_min, 4),
            "max": round(f_max, 4),
            "range": round(f_range, 4),
            "varies": free_varies,
        },
        "margin_binding_labels": sorted(bind_names),
    }

def main():
    parser = argparse.ArgumentParser(description="VERIFY nodes discrimination checks")
    parser.add_argument("--file", help="path to metrics JSONL file")
    args = parser.parse_args()
    
    if args.file:
        if not os.path.exists(args.file):
            print(f"File not found: {args.file}")
            return 1
        metrics = load_metrics(args.file)
    else:
        # Default: read from events.jsonl via SSH
        import subprocess
        result = subprocess.run(
            ["ssh", "root@n02", "pct exec 101 -- tail -500 /var/lib/vsf/vsf_nucleus/events.jsonl 2>/dev/null"],
            capture_output=True, text=True, timeout=30,
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        metrics = []
        for l in lines:
            try:
                data = json.loads(l)
                m = data.get("metrics", {})
                if "kernel" in m and "stasis_cos" in m["kernel"]:
                    metrics.append(m)
            except json.JSONDecodeError:
                continue
    
    if not metrics:
        print("No metrics found. Point to a JSONL file with --file or run on a live nucleus.")
        return 1
    
    print(f"Loaded {len(metrics)} metric samples")
    print()
    
    # 1. stasis_cos
    print("─── stasis_cos (nucleus) ───")
    sc = check_stasis_cos(metrics)
    if sc.get("pass"):
        print(f"  ✓ DISCRIMINATES: median={sc['median']}, range={sc['range']}, varies={sc['varies']}, healthy={sc['healthy']}")
    elif sc.get("error"):
        print(f"  ✗ {sc['error']}")
    else:
        print(f"  ✗ FAILS: median={sc['median']}, range={sc['range']}, varies={sc['varies']}, healthy={sc['healthy']}")
    
    # 2. variety.delta
    print("─── variety.delta ───")
    vd = check_variety_delta(metrics)
    if vd.get("pass"):
        print(f"  ✓ DISCRIMINATES: median={vd['median']}, range={vd['range']}, nonzero={vd['nonzero_pct']}%")
    elif vd.get("error"):
        print(f"  ✗ {vd['error']}")
    else:
        print(f"  ✗ FAILS: median={vd['median']}, range={vd['range']}, varies={vd['varies']}, not_pinned={vd['not_pinned']}")
    
    # 3. margin_free
    print("─── omega.margin_free + margin_binding ───")
    mf = check_margin_free(metrics)
    if mf.get("pass"):
        print(f"  ✓ DISCRIMINATES: free_range={mf['margin_free']['range']}, free_varies={mf['margin_free']['varies']}")
        print(f"    binding labels: {mf.get('margin_binding_labels', [])}")
    elif mf.get("error"):
        print(f"  ✗ {mf['error']}")
    else:
        print(f"  ✗ FAILS: free_varies={mf['margin_free']['varies']}, free_range={mf['margin_free']['range']}")
    
    print()
    # Report
    all_pass = all([
        sc.get("pass", False),
        vd.get("pass", False),
        mf.get("pass", False),
    ])
    if all_pass:
        print("✓ VERIFY nodes: ALL INSTRUMENTS DISCRIMINATE.")
        return 0
    else:
        faulty = []
        if not sc.get("pass"): faulty.append("stasis_cos")
        if not vd.get("pass"): faulty.append("variety.delta")
        if not mf.get("pass"): faulty.append("margin_free/binding")
        print(f"✗ Some instruments need attention: {', '.join(faulty)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
