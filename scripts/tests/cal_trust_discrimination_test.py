#!/usr/bin/env python3
"""CAL-TRUST discrimination test — verify all 4 trust axes discriminate.

Injects a controlled breach on each axis (behavioral, structural, predictive,
communicative) via env vars. The env-var breach mechanism lives in operational.rs
and is extended by CALIBRATE-TRUST (2026-07-03) to cover all 4 axes.

Runs on LXC 108 (dev-sandbox) against the built vsf-nucleus binary.

IMPORTANT (2026-07-03): The binary writes trust_axes JSON to events.jsonl, NOT
stdout. This version truncates the existing events.jsonl on LXC 108 (dev-sandbox
only — prod data is on LXC 101). Uses --telemetry-canonical flag to activate
the bounded run (run_parallel_canonical).

PASS criterion (per calibration_batch.spec.vsm node(CALIBRATE-TRUST)):
  - Each axis drops measurably under its OWN breach (>=DROP_THRESHOLD)
  - Each axis does NOT drop under unrelated breaches (<=CROSS_TALK_MARGIN)
  - Each axis recovers when the breach clears (lambda=0.10 timescale)

Usage:
  # Push binary + script to LXC 108 first, then:
  ssh root@n02 "pct exec 108 -- python3 /root/scripts/tests/cal_trust_discrimination_test.py"
"""

import json, os, subprocess, sys, time
from pathlib import Path

NUCLEUS_BIN = "/root/vsf-nucleus-test"
BREACH_FROM = 10       # let the kernel settle first
BREACH_DURATION = 100  # ticks under breach (behavioral uses EMA→needs ~80+ for λ=0.10 convergence)
RECOVERY_TICKS = 100   # ticks to observe recovery
MAX_TICKS = BREACH_FROM + BREACH_DURATION + RECOVERY_TICKS

# How much axis value must drop to consider the breach effective
DROP_THRESHOLD = 0.15   # absolute drop (e.g. 1.0 -> 0.85)
# How much a NON-breached axis may drop from cross-talk (isolation margin)
CROSS_TALK_MARGIN = 0.10

AXES = ["behavioral", "structural", "predictive", "communicative"]

# Paths (LXC 108 — dev sandbox; safe to truncate events.jsonl)
EVENTS_FILE = Path("/var/lib/vsf/vsf_nucleus/events.jsonl")


def prepare_fresh_events() -> None:
    """Create a fresh empty events.jsonl on LXC 108 (dev sandbox).

    On LXC 108, the existing events.jsonl is test data from previous experiment
    runs (~1.97M lines, 1.6GB). We truncate it to start fresh. The production
    events live on LXC 101 — this is the dev sandbox.
    """
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Truncate: open for write (creates empty file)
    with open(str(EVENTS_FILE), "w") as f:
        f.write("")


def run_breach(axis: str, sigma: float = 0.30) -> list[dict]:
    """Run the nucleus with a breach on `axis`, return list of per-tick metrics."""
    prepare_fresh_events()

    env = os.environ.copy()
    env.update({
        "NUCLEUS_MODE": "operational",
        "VSF_EXP_MAX_TICKS": str(MAX_TICKS),
        "VSF_EXP_BREACH_AXIS": axis,
        "VSF_EXP_BREACH_FROM": str(BREACH_FROM),
        "VSF_EXP_BREACH_UNTIL": str(BREACH_FROM + BREACH_DURATION),
        "VSF_EXP_FAST": "1",          # collapse sleep for quick test
        "VSF_SOPLO_SIGMA": str(sigma),
        # Disable NATS to avoid network-dependent delay
        "NATS_URL": "",
    })

    try:
        proc = subprocess.run(
            [NUCLEUS_BIN, "--telemetry-canonical"],
            capture_output=True, text=True, env=env,
            timeout=60,  # 60s should be enough with VSF_EXP_FAST
        )
        # Log any stderr output for debugging
        stderr_lines = [l for l in proc.stderr.splitlines() if l.strip()]
        if stderr_lines:
            for l in stderr_lines[-5:]:
                print(f"  [stderr] {l}")
    except subprocess.TimeoutExpired:
        print(f"  WARN: binary timed out (60s) — will read partial events file")
    except Exception as e:
        print(f"  ERROR running binary: {e}")
        return []

    # Read trust_axes from events.jsonl
    metrics = read_events_file()
    return metrics


def read_events_file() -> list[dict]:
    """Parse all kernel_tick events from events.jsonl, return trust_axes metrics."""
    metrics = []
    if not EVENTS_FILE.exists():
        return metrics
    with open(str(EVENTS_FILE)) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Only process kernel_tick events with trust_axes
            m = data.get("metrics", {})
            if "trust_axes" in m:
                metrics.append({
                    "tick": m.get("tick", data.get("tick", 0)),
                    "trust_axes": m["trust_axes"],
                    "kernel": m.get("kernel", {}),
                })
    return metrics


def check_discrimination(axis: str, metrics: list[dict]):
    """Verify discrimination for one breach axis."""
    # Split metrics into pre-breach, breach, recovery windows
    pre = [m for m in metrics if m["tick"] < BREACH_FROM]
    during = [m for m in metrics if BREACH_FROM <= m["tick"] < BREACH_FROM + BREACH_DURATION]
    post = [m for m in metrics if m["tick"] >= BREACH_FROM + BREACH_DURATION]

    if not pre or not during or not post:
        return {"pass": False, "error": f"insufficient data: pre={len(pre)} during={len(during)} post={len(post)}"}

    def avg_axis(ms, ax):
        return sum(m["trust_axes"].get(ax, 0.0) for m in ms) / len(ms)

    def min_axis(ms, ax):
        return min(m["trust_axes"].get(ax, 1.0) for m in ms)

    results = {}
    for ax in AXES:
        pre_val = avg_axis(pre, ax)
        during_min = min_axis(during, ax)
        post_val = avg_axis(post[-20:], ax)  # last 20 ticks of recovery

        results[ax] = {
            "pre_avg": round(pre_val, 4),
            "during_min": round(during_min, 4),
            "post_avg_20": round(post_val, 4),
            "drop": round(pre_val - during_min, 4),
        }

        if ax == axis:
            # This axis should drop under its own breach
            drop = pre_val - during_min
            results[ax]["own_breach_pass"] = drop >= DROP_THRESHOLD
            results[ax]["recovers"] = post_val > pre_val - DROP_THRESHOLD / 2
        else:
            # Other axes should NOT drop significantly (isolation)
            drop = pre_val - during_min
            results[ax]["cross_talk_pass"] = drop < CROSS_TALK_MARGIN

    breached_ax = results[axis]
    own_pass = breached_ax.get("own_breach_pass", False)
    recovers = breached_ax.get("recovers", False)
    cross_fails = sum(1 for ax, r in results.items() if ax != axis and not r.get("cross_talk_pass", True))

    return {
        "pass": own_pass and recovers and cross_fails == 0,
        "axis": axis,
        "results": results,
        "own_breach_pass": own_pass,
        "recovers": recovers,
        "cross_talk_failures": cross_fails,
    }


def main():
    print(f"CAL-TRUST Discrimination Test")
    print(f"  breach window: ticks [{BREACH_FROM}, {BREACH_FROM+BREACH_DURATION})")
    print(f"  max ticks: {MAX_TICKS}")
    print(f"  drop threshold: {DROP_THRESHOLD}")
    print(f"  cross-talk margin: {CROSS_TALK_MARGIN}")
    print(f"  binary: {NUCLEUS_BIN}")
    print(f"  events: {EVENTS_FILE}")
    print()

    all_pass = True
    verdicts = {}

    for axis in AXES:
        print(f"-- Breach on {axis.upper()} --")
        try:
            metrics = run_breach(axis)
            print(f"  captured {len(metrics)} metric ticks from events.jsonl")

            if len(metrics) < 20:
                print(f"  FAIL: too few metrics ({len(metrics)})")
                if len(metrics) > 0:
                    ticks = sorted(set(m["tick"] for m in metrics))
                    print(f"  ticks sampled: {min(ticks)}..{max(ticks)} ({len(ticks)} unique)")
                all_pass = False
                continue

            result = check_discrimination(axis, metrics)
            verdicts[axis] = result

            for ax, r in result["results"].items():
                tag = "OK" if ax == axis and r.get("own_breach_pass") else \
                      "OK" if ax != axis and r.get("cross_talk_pass") else "XX"
                print(f"  {tag} {ax:15s} pre={r['pre_avg']:.3f} during_min={r['during_min']:.3f} post={r['post_avg_20']:.3f} drop={r['drop']:.3f}")

            status = "PASS" if result["pass"] else "FAIL"
            print(f"  -> {status} (own={result['own_breach_pass']}, recover={result['recovers']}, cross_talk={result['cross_talk_failures']})")
            if not result["pass"]:
                all_pass = False
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT: binary took >60s")
            all_pass = False
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            all_pass = False
        print()

    # Summary
    print("=== CAL-TRUST VERDICT ===")
    for axis in AXES:
        v = verdicts.get(axis, {})
        status = "DISCRIMINATES" if v.get("pass") else "FAILS"
        print(f"  {axis}: {status}")

    if all_pass:
        print("\nALL AXES DISCRIMINATE. Trust is CALIBRATED.")
        return 0
    else:
        failing = [ax for ax in AXES if not verdicts.get(ax, {}).get("pass")]
        print(f"\n{len(failing)}/{len(AXES)} axes fail:")
        for ax in failing:
            reasons = []
            v = verdicts.get(ax, {})
            if not v.get("own_breach_pass"):
                reasons.append("breach did not move axis")
            if not v.get("recovers"):
                reasons.append("axis did not recover")
            if v.get("cross_talk_failures", 0) > 0:
                reasons.append(f"{v['cross_talk_failures']} axes leaked")
            print(f"  {ax}: {', '.join(reasons)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
