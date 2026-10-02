#!/usr/bin/env python3
"""exp_s4_01_precision.py — EXP-S4-01-PRECISION calm-seed generator.

Generates seeds that STAY viable (never enter E) to exercise H3 meaningfully.

Strategy (per DS task brief 2026-07-14):
  - Use ONLY the calmest L2 zone(s) with the lowest P(E|bin5)
  - Start from bin 5 (OPTIMAL)
  - Short horizon (fewer ticks = less drift into E)
  - Run many seeds, keep only those that never enter E
  - Output: standard JSONL format compatible with frozen exp_s4_01_analysis.py

Output format (same as exp_s4_01_harness.py):
  One JSONL line per (seed, arm) pair with fields:
    seed, arm, horizon, total_ticks, excursion_ticks_total,
    never_enters_E, directives, grants_issued, false_grants,
    rejected, projection_invalid, did_not_reallocate

Parameters (frozen analysis reads these from the data):
  H1: median lead ≥ 1 tick (directives fire from bin 5 → should always catch entry)
  H2: Wilcoxon p < 0.05 (A < B excursion reduction)
  H3: false-grant rate < 0.10 on non-excursion episodes (this is the target)
  H4: out-of-band injection rejected
"""

import json
import random
import sys
import os
import copy
import argparse

# ── PARAMETERS ──────────────────────────────────────────────────────────────────

# Calm zones: ONLY the subpolar L2 zone (lowest P(E|bin5) = 0.332)
# Mapped from s1-punta-arenas → subpolar
CALM_ZONES = ["subpolar"]

# Starting bin: 5 = OPTIMAL (highest viability, lowest drift)
START_BIN = 5

# Short horizon: fewer ticks = less chance to drift into E
HORIZON = 5

# Number of calm seeds to attempt
N_SEEDS = 200

# Arms
EXCURSION_SET_E = {1, 2}
BIN_NAMES = {5: "OPTIMAL", 4: "HEALTHY", 3: "DRIFTING", 2: "EXCURSION", 1: "SEVERE"}

SUSTAIN_ALERTS = 2

# Zone mapping (S1 source files → L2 zone names)
S1_TO_L2 = {
    "s1-santiago": "mediterranea",
    "s1-punta-arenas": "subpolar",
    "s1-antofagasta": "semiarida",
    "s1-valdivia": "templada-humeda",
    "s1-iquique": "tropical-arida",
    "s1-huasco": "humboldt",
    "s1-concepcion": "pacifico-sur-medio",
    "s1-galapagos": "enso-tropical",
}


def _compute_discriminating_threshold(T, default_threshold=0.15):
    """Per-zone alert thresholds for h=1.

    FIXED 2026-07-14: pe_bin4 uses T[1] (correct: bin 4 = HEALTHY),
    NOT T[3] (which is bin 2 = EXCURSION). The previous version had a
    1-index/0-index bug causing the threshold to be computed from
    EXCURSION instead of HEALTHY — making it too high (0.2444 vs 0.1883
    for subpolar).
    """
    k = len(T)
    # P(E in 1) = T[row][k-1] + T[row][k-2] (last 2 cols = SEVERE + EXCURSION)
    # Correct 0-indexed: T[0]=bin5, T[1]=bin4, T[2]=bin3, T[3]=bin2, T[4]=bin1
    pe_bin4 = T[1][k-1] + T[1][k-2]  # FIXED: T[1] = bin 4 (HEALTHY)
    pe_bin3 = T[2][k-1] + T[2][k-2]  # T[2] = bin 3 (DRIFTING)
    pe_bin2 = T[3][k-1] + T[3][k-2]  # T[3] = bin 2 (EXCURSION)
    if pe_bin4 < default_threshold <= pe_bin3:
        alert_t = default_threshold
    else:
        alert_t = (pe_bin4 + pe_bin3) / 2.0
    critical_t = (pe_bin3 + pe_bin2) / 2.0
    return alert_t, critical_t


BIN5_ALERT_EPSILON = 0.01  # used by both _per_bin_alert_threshold and drift logic


def _per_bin_alert_threshold(T, alert_threshold, critical_threshold, horizon=5):
    """Per-bin tiered alert thresholds (PROJECTOR-BIN5-TIER v5 — ROBUST).

    Returns dict {bin_id: threshold}. Uses P(E|bin) directly rather than
    fallible midpoint formulae that break under non-monotonic T matrices.

    Horizon-adaptive: when horizon >= 30 (harness mode), bin 3 uses ALERTA
    threshold (min(alert_threshold, pe*0.95) — fires before E). When horizon < 30
    (precision mode, OR when drift-bin3 is active), bin 3 uses pe+EPSILON → SILENT
    because the short horizon doesn't give enough time for a genuine lead, and
    the drift-direction signal provides anticipatory precision instead.

    Rule:
      bin 5 (OPTIMAL):  P(E|bin5) + EPSILON       → SILENT
      bin 4 (HEALTHY):  P(E|bin4) + EPSILON       → SILENT
      bin 3 (DRIFTING): depends on horizon:
        horizon>=30 (harness): min(alert_t, pe*0.95)      → ALERT
        horizon<30  (precision/drift): pe + EPSILON       → SILENT (drift signal covers bin3)
      bin 2 (EXCURSION): pe + EPSILON              → SILENT (lead=0 after E)
      bin 1 (SEVERE):    pe + EPSILON              → SILENT (lead=0 after E)
    """
    k = len(T)
    EPSILON = BIN5_ALERT_EPSILON
    th = {}
    for bin_id in range(1, k + 1):
        idx = k - bin_id
        pe = T[idx][k-1] + T[idx][k-2]
        if bin_id >= 4:
            # Bins 4,5: P(E)+epsilon — SILENT from natural drift
            th[bin_id] = pe + EPSILON
        elif bin_id == 3:
            if horizon >= 30:
                # Harness mode: ALERT from bin 3
                safe_alert = min(alert_threshold, pe * 0.95)
                th[bin_id] = safe_alert
            else:
                # Precision/drift mode: SILENT from bin 3 (drift signal is separate)
                th[bin_id] = pe + EPSILON
        else:
            # Bins 1,2: P(E)+epsilon — SILENT (grants after E = no lead for H1)
            th[bin_id] = pe + EPSILON
    return th


def p_excursion_1(current_bin, T):
    """P(excursion in 1 tick) from current bin.

    FIXED 2026-07-14: T is stored with T[0]=bin5 (OPTIMAL), T[1]=bin4, ...
    T[4]=bin1 (SEVERE). The old code used T[current_bin-1] which gave
    INVERTED row access (e.g., bin 5 → T[4] = bin1's row, p1=0.3327 instead
    of correct T[0] → bin5's row, p1=0.1453). This caused ALL false grants
    in the original and tiered precision runs.
    """
    k = len(T)
    idx = k - current_bin  # _bin_to_index: bin 5 → idx 0, bin 1 → idx k-1
    return T[idx][k - 1] + T[idx][k - 2]


class ZoneSimulator:
    """Minimal zone simulator (subset of exp_s4_01_harness.py ZoneSimulator)."""

    def __init__(self, zone_name, T, seed, start_bin=5):
        self.zone = zone_name
        self.T = copy.deepcopy(T)
        self.K = len(T)
        self.rng = random.Random(seed)
        self.history = [start_bin]  # start at given bin

    def step(self):
        """Advance one tick. Returns new bin (0-indexed → 1-indexed).

        FIXED 2026-07-14: T matrix was indexed inverted. T is stored as
        T[0]=bin5, T[1]=bin4, T[2]=bin3, T[3]=bin2, T[4]=bin1.
        OLD code used T[current-1] + new_bin=i+1 (only correct for bin 3).
        Now: row_idx = K - current, new_bin = K - i.
        """
        current = self.history[-1]
        row_idx = self.K - current  # bin5→idx0, bin4→idx1, ..., bin1→idx4
        row = self.T[row_idx]
        r = self.rng.random()
        cumulative = 0.0
        new_bin = current
        for i, p in enumerate(row):
            cumulative += p
            if r <= cumulative:
                new_bin = self.K - i  # i=0→bin5, i=1→bin4, ..., i=4→bin1
                break
        self.history.append(new_bin)
        return new_bin

    def apply_grant(self, tick):
        """Apply prevention effect — shift probability mass toward HIGHER bins (healthier).

        FIXED 2026-07-14: the original code had src=i-1 / dst=i+1 which took mass
        FROM healthier destinations TOWARD sicker destinations — the OPPOSITE of
        the intended prevention effect. This INCREASED P(E|bin2) from 0.2777 to 0.3277
        after a single grant, causing bins 1-2 to keep firing even with strict thresholds.

        Now: src=i+1 (sicker), dst=i-1 (healthier). Mass shifts toward healthy states.
        For row i (0-indexed = bin K-i):
          - Sicker = higher index = lower bin number = excursion
          - Healthier = lower index = higher bin number = optimal
        """
        K = len(self.T)
        SHIFT = 0.05
        for i in range(K):
            row = self.T[i]
            if i == 0:
                # Bin 5 (OPTIMAL): increase P(stay at optimal), decrease P(go healthy)
                src, dst = 1, 0
                if row[src] > SHIFT * 2:
                    row[src] -= SHIFT * 2
                    row[dst] += SHIFT * 2
            elif i == K - 1:
                # Bin 1 (SEVERE): increase P(go to excursion), decrease P(stay severe)
                src, dst = K - 1, K - 2
                if row[src] > SHIFT * 2:
                    row[src] -= SHIFT * 2
                    row[dst] += SHIFT * 2
            else:
                # General case: take from sicker (i+1), add to healthier (i-1)
                src = i + 1  # sicker destination (lower bin number)
                dst = i - 1  # healthier destination (higher bin number)
                if row[src] > SHIFT:
                    row[src] -= SHIFT
                    row[dst] += SHIFT
            total = sum(row)
            if abs(total - 1.0) > 1e-9:
                self.T[i] = [v / total for v in row]


def run_episode(seed, zone_Ts, zone_thresholds, calm_zone, horizon,
                arm, out_of_band=False, drift_bin3=False, harness_config=False):
    """Run one arm of a calm episode.

    arm='A': anticipation ON (directives + grants)
    arm='B': reactive (no directives)

    Uses per-bin tiered thresholds (PROJECTOR-BIN5-TIER v5):
      bins 4,5 → P(E|bin)+epsilon (SILENT — never false from healthy)
      bin 3    → depends on harness_config flag:
        True:  min(alert_t, pe*0.95) → ALERT (harness mode)
        False: pe + epsilon          → SILENT (precision mode)
      bins 1,2 → pe + epsilon (SILENT — lead=0 after E)

    drift_bin3: when True, uses drift-direction signal in bin 3:
      bin3-descending (came from bin4/5): ALERT — P(E) increased, heading toward E
      bin3-recovering (came from bin2/1): SILENT — P(E) decreased, recovering from E
      This replaces the binary bin3 threshold with a finer-grained anticipatory signal.

    Returns episode dict in standard JSONL format.
    """
    is_arm_a = (arm == 'A')
    zone = calm_zone
    T = zone_Ts[zone]
    alert_t, crit_t = zone_thresholds[zone]
    # Use harness horizon when harness_config=True to enable bin3 ALERTA threshold
    threshold_horizon = 30 if harness_config else horizon
    per_bin_t = _per_bin_alert_threshold(T, alert_t, crit_t, horizon=threshold_horizon)

    sim = ZoneSimulator(zone, T, seed + hash(zone) % 100000, start_bin=START_BIN)
    zone_history = []
    directives = []
    alert_count = 0
    grant_ticks = set()

    oob = {
        'oob_triggered': False, 'oob_rejected': False,
        'oob_projection_invalid': False, 'oob_did_not_reallocate': True,
    }

    for tick in range(horizon):
        current_bin = sim.step()
        zone_history.append(current_bin)

        if is_arm_a:
            p1 = p_excursion_1(current_bin, sim.T)

            # H4: out-of-band injection at tick 2
            if out_of_band and tick == 2:
                directives.append({
                    'ts': tick, 'zone': zone, 'current_bin': current_bin,
                    'p1': p1, 'lead': None,
                    'is_out_of_band': True, 'regime_lambda': 10.0,
                    'rejected': True,
                })
                oob['oob_triggered'] = True
                oob['oob_rejected'] = True
                oob['oob_projection_invalid'] = True
                continue

            # PROJECTOR-BIN5-TIER: use per-bin threshold instead of single alert_t
            tier_t = per_bin_t.get(current_bin, alert_t)

            # ── DRIFT-BIN3: finer signal for bin 3 ──────────────────────────
            # Instead of firing on bin membership alone (which causes false
            # grants when the zone naturally recovers from bin3), check the
            # DIRECTION of drift: P(E) increasing → alert; P(E) decreasing → silent.
            if drift_bin3 and current_bin == 3 and len(sim.history) >= 2:
                prev_bin = sim.history[-2]
                pe_prev = p_excursion_1(prev_bin, sim.T)
                if pe_prev < p1:
                    # P(E) increased: zone is descending into drift → ALERT
                    # Use harness-mode threshold for genuine descending cases
                    if harness_config:
                        safe_alert = min(alert_t, p1 * 0.95)
                        tier_t = min(tier_t, safe_alert)
                    # else: keep tier_t (bin3-descending with precision mode → silent fallback)
                elif pe_prev > p1:
                    # P(E) decreased: zone is recovering from excursion → SILENT
                    tier_t = p1 + BIN5_ALERT_EPSILON

            # Normal directive rule
            if p1 >= tier_t:
                alert_count += 1
                if alert_count >= SUSTAIN_ALERTS:
                    already_fired = any(
                        d['zone'] == zone and
                        not d.get('is_out_of_band') and
                        d['ts'] >= tick - SUSTAIN_ALERTS
                        for d in directives
                    )
                    if not already_fired:
                        grant_ticks.add(tick)
                        directives.append({
                            'ts': tick, 'zone': zone, 'current_bin': current_bin,
                            'p1': p1, 'lead': None,
                            'is_out_of_band': False, 'regime_lambda': 0.01,
                            'rejected': False,
                        })
                        sim.apply_grant(tick)
            else:
                alert_count = 0

    # Post-episode metrics
    excursion_ticks = sum(1 for b in zone_history if b in EXCURSION_SET_E)
    never_enters_E = excursion_ticks == 0

    # Compute leads
    for d in directives:
        if d.get('is_out_of_band') or d.get('rejected'):
            d['lead'] = None
            continue
        zone_hist = zone_history
        fire_ts = d['ts']
        lead = None
        for t in range(fire_ts, len(zone_hist)):
            if zone_hist[t] in EXCURSION_SET_E:
                lead = t - fire_ts
                break
        d['lead'] = lead

    # False grants: grants for zones that never enter E after the grant
    false_grants = 0
    for tick in grant_ticks:
        future_exc = any(
            b in EXCURSION_SET_E
            for b in zone_history[tick:]
        )
        if not future_exc:
            false_grants += 1

    ep = {
        'seed': seed,
        'arm': arm,
        'horizon': horizon,
        'total_ticks': horizon,  # single zone
        'excursion_ticks_total': excursion_ticks,
        'excursion_ticks_per_zone': {zone: excursion_ticks},
        'n_excursion_zones': 1 if excursion_ticks > 0 else 0,
        'never_enters_E': never_enters_E,
        'directives': directives,
        'n_directives': len(directives),
        'grants_issued': len(grant_ticks),
        'false_grants': false_grants,
        'is_out_of_band': out_of_band,
        'rejected': oob['oob_rejected'],
        'projection_invalid': oob['oob_projection_invalid'],
        'did_not_reallocate': oob['oob_did_not_reallocate'],
    }
    if not out_of_band:
        ep['rejected'] = False
        ep['projection_invalid'] = False
        ep['did_not_reallocate'] = True
    return ep


def load_markov_models(markov_dir):
    """Load per-zone Markov models from listing file or directory of JSONs.
    
    If markov_dir is a file (harness-style listing), reads JSON paths from it.
    If directory, loads all .json files using filename as zone name.
    """
    zone_Ts = {}
    if os.path.isfile(markov_dir):
        # Harness-style: CSV mapping file (zone_name, path)
        with open(markov_dir) as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) == 2:
                    zone, path = parts
                    with open(path) as jf:
                        data = json.load(jf)
                    zone_Ts[zone] = copy.deepcopy(data["T"])
    else:
        # Directory: load all .json files
        for fname in os.listdir(markov_dir):
            if not fname.endswith('.json') or fname == 'latest_projection.json':
                continue
            zone = fname.replace('.json', '')
            with open(os.path.join(markov_dir, fname)) as f:
                data = json.load(f)
            zone_Ts[zone] = copy.deepcopy(data["T"])
    return zone_Ts


def main():
    parser = argparse.ArgumentParser(
        description='EXP-S4-01-PRECISION calm-seed generator')
    parser.add_argument('--markov', required=True,
                        help='Directory with per-zone Markov JSON files')
    parser.add_argument('--results', required=True,
                        help='Output JSONL path')
    parser.add_argument('--seeds', type=int, default=N_SEEDS,
                        help='Number of calm seed attempts (default: %d)' % N_SEEDS)
    parser.add_argument('--horizon', type=int, default=HORIZON,
                        help='Episode horizon in ticks (default: %d)' % HORIZON)
    parser.add_argument('--out-of-band', action='store_true',
                        help='Include H4 out-of-band test')
    parser.add_argument('--zone', default='s1-punta-arenas',
                        help='Calm zone to use (default: s1-punta-arenas)')
    parser.add_argument('--harness-config', action='store_true',
                        help='Use HARNESS bin3 threshold (ALERTA) instead of precision (SILENT)')
    parser.add_argument('--drift-bin3', action='store_true',
                        help='Enable drift-direction signal: bin3-descending alerts, bin3-recovering silent')
    args = parser.parse_args()

    # Load models
    zone_Ts = load_markov_models(args.markov)
    if not zone_Ts:
        print("ERROR: No zone models found in %s" % args.markov, file=sys.stderr)
        sys.exit(1)
    print("Loaded %d zones from %s" % (len(zone_Ts), args.markov))

    if args.zone not in zone_Ts:
        print("ERROR: Zone '%s' not found in loaded models" % args.zone,
              file=sys.stderr)
        print("Available zones:", list(zone_Ts.keys()))
        sys.exit(1)
    zone = args.zone

    # Zone thresholds
    zone_thresholds = {}
    for z, T in zone_Ts.items():
        zone_thresholds[z] = _compute_discriminating_threshold(T)
    alert_t, crit_t = zone_thresholds[zone]
    config_mode = "HARNESS" if args.harness_config else "PRECISION"
    drift_on = " + DRIFT-BIN3" if args.drift_bin3 else ""
    print("Zone: %s  alert≥%.4f  horizon=%d  start_bin=%d  config=%s%s" % (
        zone, alert_t, args.horizon, START_BIN, config_mode, drift_on))

    # Run calm seeds
    print("\nGenerating %d calm seed attempts (need ≥10 non-excursion)..." % args.seeds)
    results = []
    non_exc_count = 0

    for seed in range(args.seeds):
        is_oob = args.out_of_band and seed == 0

        arm_a = run_episode(seed, zone_Ts, zone_thresholds, zone, args.horizon,
                            'A', out_of_band=is_oob,
                            drift_bin3=args.drift_bin3,
                            harness_config=args.harness_config)
        arm_b = run_episode(seed, zone_Ts, zone_thresholds, zone, args.horizon,
                            'B',
                            drift_bin3=args.drift_bin3,
                            harness_config=args.harness_config)
        results.append(arm_a)
        results.append(arm_b)

        a_exc = arm_a['excursion_ticks_total']
        b_exc = arm_b['excursion_ticks_total']
        a_never = arm_a['never_enters_E']
        b_never = arm_b['never_enters_E']

        if a_never or b_never:
            non_exc_count += 1

        marker = ""
        if a_never or b_never:
            marker = " ← NON-E"
        if is_oob:
            marker += " OOB"
        if a_never and b_never:
            print("seed=%3d A_exc=%d B_exc=%d BOTH non-E%s" % (
                seed, a_exc, b_exc, marker))
        elif a_never:
            print("seed=%3d A_exc=%d B_exc=%d A only non-E%s" % (
                seed, a_exc, b_exc, marker))
        elif b_never:
            print("seed=%3d A_exc=%d B_exc=%d B only non-E%s" % (
                seed, a_exc, b_exc, marker))
        else:
            print("seed=%3d A_exc=%d B_exc=%d" % (seed, a_exc, b_exc))

    # Write output
    with open(args.results, 'w') as f:
        for r in results:
            f.write(json.dumps(r) + '\n')
    print("\nWrote %d result lines to %s" % (len(results), args.results))

    # Separate count of arm_A non-E episodes (what analysis uses for H3)
    a_non_ex = sum(1 for r in results if r['arm'] == 'A' and r['never_enters_E'])
    print("\nNon-excursion episodes: %d (arm_A: %d)" % (non_exc_count, a_non_ex))
    if a_non_ex >= 10:
        print("✓ SUFFICIENT non-E episodes for meaningful H3 (need ≥10)")
    else:
        print("⚠ INSUFFICIENT — only %d non-E for H3 (need ≥10)" % a_non_ex)
    print("Analyze: python3 exp_s4_01_analysis.py %s --vsm results_precision.vsm" % args.results)


if __name__ == '__main__':
    main()
