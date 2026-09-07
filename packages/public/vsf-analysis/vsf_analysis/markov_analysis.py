#!/usr/bin/env python3
"""Markov analysis for K_total worst-case estimation.

Implements gate3_experimental_plan.md §2 + §A.2-A.5 + A.8.

Usage:
  python3 markov_analysis.py <events.jsonl>
  python3 markov_analysis.py --synthetic   # validate pipeline with mock data

Output: per-state K_φ↑, stationary distribution π, K_total_worst with bootstrap CI.

Stdlib + numpy only. No external phase tagging library needed.
"""
import json
import sys
import argparse
import random
from collections import defaultdict, Counter
from datetime import datetime

import numpy as np

# Canonical state space (gate3_experimental_plan §2.2)
STATES = ["B0_PROFILE", "B1_PASSIVE", "B2_ACTIVE", "B3_ENUM",
          "B4_ANALYSIS", "B5_PARALLEL", "B6_AI", "B7_TRIAGE",
          "B8_SUBMIT", "IDLE", "ABORT"]
N_STATES = len(STATES)
S_IDX = {s: i for i, s in enumerate(STATES)}

# Event taxonomy (gate3_experimental_plan §4)
PHI_UP = {"kernel_tick", "anomaly_detected", "phase_complete",
          "tool_run", "thermal_wait", "signal_escalated",
          "invariant_check", "drift_alert", "finding_emitted"}
STATE_CHANGE = {"phase_complete", "bounded_self_correction"}
KERNEL_TICK = "kernel_tick"


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_events(path):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def synthesize_dataset(n_scans=5, seed=42):
    """Synthetic events.jsonl-equivalent matching the Markov model.
    Used to validate analysis pipeline before real data arrives.
    Per-phase emission rates calibrated to expected BBH workflow profile.
    """
    rng = random.Random(seed)
    # Realistic per-phase emission rates (phi_up events per state-change)
    phase_rates = {
        "B0_PROFILE":   0.4,
        "B1_PASSIVE":   0.3,
        "B2_ACTIVE":    1.2,  # active probing — peak regime
        "B3_ENUM":      0.6,
        "B4_ANALYSIS":  0.3,
        "B5_PARALLEL":  1.5,  # parallel workers — peak
        "B6_AI":        0.8,
        "B7_TRIAGE":    0.4,
        "B8_SUBMIT":    0.2,
        "IDLE":         1.0,  # kernel_tick only
        "ABORT":        0.1,
    }
    # Typical workflow path
    path = ["IDLE", "B0_PROFILE", "B1_PASSIVE", "B2_ACTIVE", "B3_ENUM",
            "B4_ANALYSIS", "B5_PARALLEL", "B6_AI", "B7_TRIAGE", "B8_SUBMIT", "IDLE"]
    events = []
    ts = datetime(2026, 5, 26, 12, 0, 0)
    from datetime import timedelta
    for scan in range(n_scans):
        for phase in path:
            # Dwell ~ 30 state-changes per phase (Poisson-like)
            dwell = rng.randint(10, 50)
            for k in range(dwell):
                ts = ts + timedelta(seconds=rng.randint(1, 30))
                # state-change event
                events.append({
                    "ts": ts.isoformat() + "Z",
                    "system_id": "bbh",
                    "event_type": "phase_complete" if k == 0 else "bounded_self_correction",
                    "phase": phase,
                })
                # phi_up emissions for this state
                n_phiup = np.random.poisson(phase_rates[phase])
                for _ in range(n_phiup):
                    et = rng.choice(["tool_run", "anomaly_detected", "finding_emitted"])
                    events.append({
                        "ts": (ts + timedelta(microseconds=rng.randint(1, 999999))).isoformat() + "Z",
                        "system_id": "bbh",
                        "event_type": et,
                        "phase": phase,
                    })
    return events


def build_transition_matrix(events):
    """Build P_ij from phase_complete events (with `phase` field).
    Only includes states actually visited (avoids spurious absorbing states)."""
    transitions = defaultdict(Counter)
    visits = Counter()
    prev_state = None
    for e in events:
        phase = e.get("phase")
        if phase not in S_IDX:
            continue
        if e["event_type"] == "phase_complete":
            if prev_state and prev_state != phase:
                transitions[prev_state][phase] += 1
            visits[phase] += 1
            prev_state = phase
    # Restrict to visited subspace
    visited = [s for s in STATES if visits[s] > 0]
    sub_idx = {s: i for i, s in enumerate(visited)}
    n = len(visited)
    P = np.zeros((n, n))
    for src in visited:
        i = sub_idx[src]
        total = sum(transitions[src].values())
        if total > 0:
            for dst, c in transitions[src].items():
                if dst in sub_idx:
                    P[i, sub_idx[dst]] = c / total
        else:
            P[i, i] = 1.0  # terminal but only over visited
    # Re-normalize rows that don't sum to 1 (missing dst that wasn't visited)
    for i in range(n):
        rs = P[i].sum()
        if rs > 0:
            P[i] /= rs
        else:
            P[i, i] = 1.0
    return P, transitions, visits, visited


def stationary_distribution(P):
    """Left eigenvector of P with eigenvalue 1, normalized to sum=1."""
    vals, vecs = np.linalg.eig(P.T)
    # Find eigenvalue closest to 1
    idx = np.argmin(np.abs(vals - 1.0))
    pi = np.real(vecs[:, idx])
    pi = pi / pi.sum()
    pi = np.clip(pi, 0, None)
    pi = pi / pi.sum()
    return pi


def per_state_K_phi_up(events):
    """K_φ↑(i) = phi_up events in state i / state changes in state i."""
    phiup = Counter()
    sc = Counter()
    for e in events:
        phase = e.get("phase")
        if phase not in S_IDX:
            continue
        if e["event_type"] in PHI_UP:
            phiup[phase] += 1
        if e["event_type"] in STATE_CHANGE:
            sc[phase] += 1
    K = {}
    for s in STATES:
        if sc[s] > 0:
            K[s] = phiup[s] / sc[s]
        else:
            K[s] = None  # not enough data
    return K, phiup, sc


def bootstrap_K_worst(events, n_boot=1000, seed=0):
    """Bootstrap CI for K_total_worst over event resamples."""
    rng = random.Random(seed)
    n = len(events)
    worst_samples = []
    for _ in range(n_boot):
        sample = [events[rng.randrange(n)] for _ in range(n)]
        K, _, _ = per_state_K_phi_up(sample)
        valid = [v for v in K.values() if v is not None]
        if valid:
            worst_samples.append(max(valid))
    if not worst_samples:
        return None, None, None
    worst_samples.sort()
    return (worst_samples[int(0.025 * n_boot)],
            worst_samples[int(0.5 * n_boot)],
            worst_samples[int(0.975 * n_boot)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--bootstrap", type=int, default=1000)
    args = ap.parse_args()

    if args.synthetic:
        print("=== MODE: SYNTHETIC (validating pipeline) ===")
        events = synthesize_dataset()
    else:
        if not args.path:
            print("Usage: markov_analysis.py <events.jsonl> | --synthetic")
            sys.exit(1)
        events = load_events(args.path)

    print(f"Events loaded: {len(events)}")
    types = Counter(e.get("event_type", "?") for e in events)
    print(f"Distinct event_types: {len(types)}")
    for t, n in types.most_common():
        print(f"  {t:30s} {n}")

    print(f"\n=== TRANSITION MATRIX P ===")
    P, transitions, visits, visited = build_transition_matrix(events)
    n_trans = sum(sum(v.values()) for v in transitions.values())
    print(f"Total transitions: {n_trans}")
    print(f"States visited: {len(visited)}/{N_STATES}  ({', '.join(visited)})")
    if n_trans < 30:
        print(f"⚠ WARN: <30 transitions, P estimate unreliable")

    print(f"\n=== STATIONARY DISTRIBUTION π (restricted to visited) ===")
    if len(visited) == 0:
        print("  ⚠ no phase_complete events with `phase` field — Markov undefined.")
        print("  (expected before BBH integration emits phase-tagged events)")
        return
    pi = stationary_distribution(P)
    residual = np.linalg.norm(pi @ P - pi)
    print(f"Residual ‖πP - π‖ = {residual:.2e}  (target < 1e-6)")
    pi_map = {s: pi[i] for i, s in enumerate(visited)}
    for s in visited:
        if pi_map[s] > 0.01:
            print(f"  π({s:15s}) = {pi_map[s]:.4f}")

    print(f"\n=== PER-STATE K_φ↑ ===")
    K, phiup_counts, sc_counts = per_state_K_phi_up(events)
    for s in STATES:
        if K[s] is not None and sc_counts[s] >= 5:
            print(f"  K_φ↑({s:15s}) = {K[s]:.4f}  "
                  f"(phi_up={phiup_counts[s]}, state_changes={sc_counts[s]}, π={pi_map.get(s, 0):.3f})")
        elif K[s] is not None:
            print(f"  K_φ↑({s:15s}) = {K[s]:.4f}  ⚠ N<5")

    print(f"\n=== K_total_worst (assuming K_φ↓=1.0 baseline) ===")
    valid_states = [(s, K[s], pi_map.get(s, 0)) for s in STATES
                    if K[s] is not None and pi_map.get(s, 0) >= 0.01]
    if valid_states:
        worst_state, worst_k, worst_pi = max(valid_states, key=lambda x: x[1])
        print(f"  Worst state: {worst_state}")
        print(f"  K_φ↑_worst = {worst_k:.4f}  (π={worst_pi:.3f})")
        print(f"  Bootstrap 95% CI...")
        lo, med, hi = bootstrap_K_worst(events, n_boot=args.bootstrap)
        if lo is not None:
            print(f"    [{lo:.4f}, {med:.4f}, {hi:.4f}]")
            covenant_ok = hi < 0.8
            stability_ok = hi < 1.0
            print(f"  Stability |G|<1:   {'PASS' if stability_ok else 'FAIL'} (upper={hi:.4f})")
            print(f"  Covenant K<0.8:    {'PASS' if covenant_ok else 'WARN'} (upper={hi:.4f})")

    print(f"\n=== END REPORT ===")


if __name__ == "__main__":
    main()
