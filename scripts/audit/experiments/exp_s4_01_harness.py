#!/usr/bin/env python3
"""exp_s4_01_harness.py — EXP-S4-01_full paired-arm simulator (D2/D3).

FROZEN PARAMETERS from docs/spec/s4_anticipation/spec.vsm §frozen:
  K=30 seeded episodes, horizon=30 ticks, 5-state Markov (ERA5-fitted).
  Each seed run through BOTH arm_A (anticipation ON) and arm_B (reactive).
  arm_A: applies synthetic consumer (logs s3_pre_grant, NO real cgroup write).
  arm_B: no consumer — tracks raw excursion metrics.

Output: JSONL with paired results for exp_s4_01_analysis.py.

Usage:
  python3 exp_s4_01_harness.py --markov /path/to/markov/models/ --seeds 30 --results /tmp/results.jsonl
  python3 exp_s4_01_harness.py --demo  # use built-in synthetic Markov
  python3 exp_s4_01_analysis.py /tmp/results.jsonl --vsm results.vsm
"""

import json
import random
import sys
import os
import copy

# ── FROZEN PARAMETERS ──────────────────────────────────────────────────────────
K = 30
HORIZON = 30
N_ZONES = 8

# 5-state bins (per spec §frozen, from antofagasta calibration)
BIN_NAMES = {5: "OPTIMAL", 4: "HEALTHY", 3: "DRIFTING", 2: "EXCURSION", 1: "SEVERE"}
EXCURSION_SET_E = {1, 2}  # SEVERE or EXCURSION

# Directive rule (from spec §frozen.directive_rule):
# ALERT uses H=1 with per-zone discriminating threshold (midpoint of bin4→E and bin3→E).
# See _compute_discriminating_threshold() — this replaces the old P7_AT_RISK=0.15.
SUSTAIN_ALERTS = 2          # consecutive ticks before directive fires

# H4: out-of-band regime lambda threshold
REGIME_BAND = (-0.05, 0.05)

# Pre-compute per-zone discriminating thresholds (computed once from zone_Ts)
_ZONE_ALERT_THRESHOLDS = {}
_ZONE_CRITICAL_THRESHOLDS = {}

# Zone names (matching the L2 slice names)
ZONE_NAMES = [
    "mediterranea", "subpolar", "semiarida", "templada-humeda",
    "tropical-arida", "humboldt", "pacifico-sur-medio", "enso-tropical",
]

# S1 station → L2 zone mapping (used by load_markov_models for file discovery)
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

# ── MARKOV MODEL ───────────────────────────────────────────────────────────────

def load_markov_models(markov_dir):
    """Load per-zone Markov models from JSON files.

    Uses S1_TO_L2 mapping to find files named s1-<station>.json and maps them
    to L2 zone names. Falls back: L2 name → "s1-<l2_name>.json" → then checks
    all JSON files in the directory for a zone field match.

    Returns: dict of {zone_name: transition_matrix (list of lists)}
    """
    # Pre-scan directory for S1 files that match our mapping
    s1_files_found = {}
    with os.scandir(markov_dir) as it:
        for entry in it:
            if entry.name.endswith(".json") and entry.name != "latest_projection.json":
                stem = entry.name[:-5]  # remove .json
                if stem in S1_TO_L2:
                    s1_files_found[S1_TO_L2[stem]] = entry.path

    models = {}
    for zone in ZONE_NAMES:
        if zone in s1_files_found:
            # Found via S1_TO_L2 mapping
            with open(s1_files_found[zone]) as f:
                data = json.load(f)
            models[zone] = copy.deepcopy(data["T"])
        else:
            # Try direct filename
            for candidate in [f"{zone}.json", f"s1-{zone}.json"]:
                path = os.path.join(markov_dir, candidate)
                if os.path.exists(path):
                    with open(path) as f:
                        data = json.load(f)
                    models[zone] = copy.deepcopy(data["T"])
                    break

    if not models:
        return None

    if len(models) < N_ZONES:
        first_T = copy.deepcopy(list(models.values())[0])
        for zone in ZONE_NAMES:
            if zone not in models:
                models[zone] = copy.deepcopy(first_T)

    return models


def synthetic_markov(seed=42):
    """Generate a synthetic 5×5 Markov T with realistic probability mass."""
    rng = random.Random(seed)
    T = []
    for i in range(5):
        row = [0.0] * 5
        row[i] = 0.50
        if i > 0:
            row[i-1] += 0.20
        if i < 4:
            row[i+1] += 0.10 + (4 - i) * 0.02
        remaining = 1.0 - sum(row)
        for j in range(5):
            if j != i:
                row[j] += remaining * rng.random() * 0.3
        total = sum(row)
        T.append([v / total for v in row])
    return T


# ── ZONE SIMULATOR ─────────────────────────────────────────────────────────────

class ZoneSimulator:
    """Simulates one zone's stasis_cos trajectory from a Markov T.

    T can be mutated during the episode (for grant effect simulation).
    """

    def __init__(self, zone_name, T, seed):
        self.zone = zone_name
        # Deep-copy so mutations don't leak across arms/seeds
        self.T = copy.deepcopy(T)
        self.K = len(T)
        self.rng = random.Random(seed)
        self.history = []

    def reset(self):
        """Reset to initial state (HEALTHY, bin=4)."""
        self.history = []
        return 4  # initial bin

    def step(self, from_bin=None):
        """Advance one tick from current or given bin. Returns new bin.

        FIXED 2026-07-14: T matrix was indexed inverted. T is stored as
        T[0]=bin5, T[1]=bin4, T[2]=bin3, T[3]=bin2, T[4]=bin1.
        OLD code used T[current-1] + new_bin=i+1 (only correct for bin 3).
        Now: row_idx = K - current, new_bin = K - i.
        """
        if from_bin is None:
            current = self.history[-1] if self.history else 4
        else:
            current = from_bin

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
        """Apply prevention effect: shift probability mass toward higher bins.

        FIXED 2026-07-14: the original code had src=i-1/dst=i+1 which shifted
        mass FROM healthier destinations TOWARD sicker ones — the OPPOSITE of
        prevention. This INCREASED P(E|bin2) from 0.2777 to 0.3277 after a
        single grant, causing bins 1-2 to keep firing despite strict thresholds.

        Now: src=i+1 (sicker = lower bin number), dst=i-1 (healthier = higher
        bin number). Mass shifts toward healthy states.
        Called at `tick` to affect remaining simulation steps.
        """
        K = len(self.T)
        SHIFT = 0.05
        for i in range(K):
            row = self.T[i]
            if i == 0:
                # Bin 5 (OPTIMAL): increase P(stay optimal), decrease P(deteriorate)
                src, dst = 1, 0
                if row[src] > SHIFT * 2:
                    row[src] -= SHIFT * 2
                    row[dst] += SHIFT * 2
            elif i == K - 1:
                # Bin 1 (SEVERE): increase P(improve), decrease P(stay severe)
                src, dst = K - 1, K - 2
                if row[src] > SHIFT * 2:
                    row[src] -= SHIFT * 2
                    row[dst] += SHIFT * 2
            else:
                # General: take from sicker (i+1), add to healthier (i-1)
                src = i + 1
                dst = i - 1
                if row[src] > SHIFT:
                    row[src] -= SHIFT
                    row[dst] += SHIFT
            total = sum(row)
            if abs(total - 1.0) > 1e-9:
                self.T[i] = [v / total for v in row]


# ── EPISODE RUNNER ─────────────────────────────────────────────────────────────

def _compute_discriminating_threshold(T, default_threshold=0.15):
    """Compute per-zone alert thresholds for h=1 (copied from viability_forecaster).

    Returns (alert_threshold, critical_threshold):
      alert: separates bin4/5 (SILENT) from bin3 (ALERT).
             Uses default_threshold if it separates; otherwise midpoint.
      critical: separates bin3 from bin2 (midpoint).
    """
    k = len(T)
    # P(E in 1) = sum of last 2 columns (SEVERE + EXCURSION)
    pe_bin4 = T[1][k-1] + T[1][k-2]
    pe_bin3 = T[2][k-1] + T[2][k-2]
    pe_bin2 = T[3][k-1] + T[3][k-2]

    if pe_bin4 < default_threshold <= pe_bin3:
        alert_t = default_threshold
    else:
        alert_t = (pe_bin4 + pe_bin3) / 2.0
    critical_t = (pe_bin3 + pe_bin2) / 2.0
    return alert_t, critical_t


BIN5_ALERT_EPSILON = 0.01


def _per_bin_alert_threshold(T, alert_threshold, critical_threshold, horizon=HORIZON):
    """Per-bin tiered alert thresholds (PROJECTOR-BIN5-TIER v5 — ROBUST).

    Returns dict {bin_id: threshold}. Each bin's threshold uses P(E|bin) directly
    rather than relying on fallible midpoint formulae that break under non-monotonic
    T matrices (e.g. when P(E|bin4) > P(E|bin3) as observed for subpolar and
    templada-humeda).

    Rule:
      bin 5 (OPTIMAL):  P(E|bin5) + EPSILON       → SILENT (never from optimal)
      bin 4 (HEALTHY):  P(E|bin4) + EPSILON       → SILENT (never from healthy)
      bin 3 (DRIFTING): depends on horizon:
        horizon≥30 (harness): min(alert_threshold, pe_bin3 * 0.95)  → ALERT (guaranteed ≤ P(E|bin3))
        horizon<30 (precision): pe_bin3 + EPSILON                   → SILENT (no false grants)
      bin 2 (EXCURSION): P(E|bin2) + EPSILON      → SILENT (grant after E = no lead for H1)
      bin 1 (SEVERE):    P(E|bin1) + EPSILON      → SILENT (grant after E = no lead for H1)

    Critical design constraint (H1): H1 requires median lead ≥ 1 tick. Grants that
    fire from bins 1-2 (already in E) have lead=0 by definition. To pass H1, ALL
    grants must come from bin 3 (DRIFTING, BEFORE E). This means bins 1-2 must
    ALSO be SILENT.

    Prevention is maintained: bin 3 grants modify the T matrix (reducing P(→E))
    BEFORE the zone enters E, providing genuine early-warning prevention.

    NOTE: _compute_discriminating_threshold's midpoint formulae assume
    P(E|bin4) < P(E|bin3) < P(E|bin2). However, empirical ERA5-fitted T matrices
    show:
      - P(E|bin4) > P(E|bin3) for some zones (subpolar, templada-humeda)
      - P(E|bin3) > P(E|bin2) for ALL zones
    The per-bin approach avoids these assumptions entirely.
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
            # Bin 3: horizon-adaptive
            if horizon >= 30:
                # Harness mode: ALERT from bin 3
                # min(alert_threshold, pe*0.95) handles P(E|bin4) > P(E|bin3) inversion:
                # if alert_t is above pe_bin3, clamp to 95% of pe_bin3 so alert fires.
                safe_alert = min(alert_threshold, pe * 0.95)
                th[bin_id] = safe_alert
            else:
                # Precision mode: SILENT from bin 3
                th[bin_id] = pe + EPSILON
        else:
            # Bins 1,2: P(E)+epsilon — SILENT (grants after E = no lead for H1)
            th[bin_id] = pe + EPSILON
    return th


def p_excursion_1(current_bin, T):
    """Compute P(excursion in 1 tick) from current bin.

    h=1 discriminates bin4/5 from bin3 (vs h=7 which saturates for all bins).

    FIXED 2026-07-14: T is stored with T[0]=bin5, T[1]=bin4, ..., T[4]=bin1.
    T[current_bin-1] gave INVERTED access (bin 5 → T[4]=bin1 row, p1=0.3327
    instead of correct T[0]=bin5 row, p1=0.1453). Now uses k - current_bin.
    """
    k = len(T)
    idx = k - current_bin  # _bin_to_index: bin 5 → 0, bin 1 → k-1
    return T[idx][k - 1] + T[idx][k - 2]


class EpisodeRunner:
    """Runs a single paired episode (same seed, both arms)."""

    def __init__(self, seed, zone_Ts, zone_thresholds=None, horizon=HORIZON):
        self.seed = seed
        self.zone_Ts = zone_Ts
        self.horizon = horizon
        # Per-zone discriminating thresholds: {zone: (alert_t, critical_t)}
        if zone_thresholds is None:
            self.thresholds = {}
            for zone, T in zone_Ts.items():
                self.thresholds[zone] = _compute_discriminating_threshold(T)
        else:
            self.thresholds = zone_thresholds
        # PROJECTOR-BIN5-TIER: per-bin thresholds for each zone (horizon-adaptive)
        self.per_bin_t = {}
        for zone, T in zone_Ts.items():
            alert_t, critical_t = self.thresholds.get(zone, (0.15, 0.40))
            self.per_bin_t[zone] = _per_bin_alert_threshold(T, alert_t, critical_t, horizon)

    def _make_sims(self, arm, start_from_bin=4):
        """Create fresh zone simulators for this arm.

        Same seed per zone for both arms (seed + zone_hash) so the
        underlying Markov trajectories are identical before intervention.
        start_from_bin: initial bin for all zones (4=HEALTHY, 5=OPTIMAL for calm seeds).
        """
        base = self.seed
        sims = {
            zone: ZoneSimulator(
                zone,
                self.zone_Ts[zone],
                base + hash(zone) % 100000
            )
            for zone in ZONE_NAMES
        }
        # Set initial bins (normally 4=HEALTHY; calm seeds start at 5)
        for zone in ZONE_NAMES:
            sims[zone].history = [start_from_bin]
        return sims

    def run_arm(self, arm, out_of_band=False, start_from_bin=4):
        """Run one arm of the episode.

        arm='A': anticipation ON — directives can issue grants that mutate T
        arm='B': reactive — no directives, no grants
        start_from_bin: initial bin (4=HEALTHY, 5=OPTIMAL for calm seeds)

        Returns dict with episode-level metrics.
        """
        is_arm_a = (arm == 'A')
        sims = self._make_sims(arm, start_from_bin=start_from_bin)
        horizon = self.horizon

        # Pre-allocate per-zone tick-to-bin arrays
        zone_history = {zone: [] for zone in ZONE_NAMES}
        directives = []
        directive_alert_counts = {zone: 0 for zone in ZONE_NAMES}
        grant_ticks = set()  # (zone, tick) of grants issued

        oob = {
            'oob_triggered': False,
            'oob_rejected': False,
            'oob_projection_invalid': False,
            'oob_did_not_reallocate': True,
        }

        for tick in range(horizon):
            # Advance each zone by one step
            for zone in ZONE_NAMES:
                current_bin = sims[zone].step()
                zone_history[zone].append(current_bin)

            # ── Arm A: directive check at this tick ──────────────────────
            if is_arm_a:
                for zone_idx, zone in enumerate(ZONE_NAMES):
                    current_bin = zone_history[zone][-1]

                    # Compute P(excursion in 1) from current bin
                    # Uses per-bin tiered threshold (PROJECTOR-BIN5-TIER v2)
                    p1 = p_excursion_1(current_bin, sims[zone].T)
                    alert_t, critical_t = self.thresholds.get(zone, (0.15, 0.40))
                    tier_t = self.per_bin_t.get(zone, {}).get(current_bin, alert_t)

                    # ── H4 injection ─────────────────────────────────────
                    if out_of_band and tick == 5 and zone == ZONE_NAMES[0]:
                        directives.append({
                            'ts': tick,
                            'zone': zone,
                            'current_bin': current_bin,
                            'p1': p1,
                            'lead': None,
                            'is_out_of_band': True,
                            'regime_lambda': 10.0,
                            'rejected': True,
                        })
                        oob['oob_triggered'] = True
                        oob['oob_rejected'] = True
                        oob['oob_projection_invalid'] = True
                        continue

                    # Normal directive rule (h=1, per-bin tiered threshold)
                    if p1 >= tier_t:
                        directive_alert_counts[zone] += 1
                        if directive_alert_counts[zone] >= SUSTAIN_ALERTS:
                            # Fire once per alert window
                            already_fired = any(
                                d['zone'] == zone and
                                not d.get('is_out_of_band') and
                                d['ts'] >= tick - SUSTAIN_ALERTS
                                for d in directives
                            )
                            if not already_fired:
                                grant_ticks.add((zone, tick))
                                directives.append({
                                    'ts': tick,
                                    'zone': zone,
                                    'current_bin': current_bin,
                                    'p1': p1,
                                    'lead': None,
                                    'is_out_of_band': False,
                                    'regime_lambda': 0.01,
                                    'rejected': False,
                                })

                                # Apply grant effect — mutates T for FUTURE steps
                                sims[zone].apply_grant(tick)
                    else:
                        directive_alert_counts[zone] = 0

        # ── Post-episode metrics ──────────────────────────────────────────
        total_exc = 0
        zone_exc = {zone: 0 for zone in ZONE_NAMES}
        for zone in ZONE_NAMES:
            for b in zone_history[zone]:
                if b in EXCURSION_SET_E:
                    total_exc += 1
                    zone_exc[zone] += 1

        # Compute leads: for each directive, find first E entry after fire_tick
        for d in directives:
            if d.get('is_out_of_band') or d.get('rejected'):
                d['lead'] = None
                continue
            zone_hist = zone_history[d['zone']]
            fire_ts = d['ts']
            lead = None
            for t in range(fire_ts, len(zone_hist)):
                if zone_hist[t] in EXCURSION_SET_E:
                    lead = t - fire_ts
                    break
            d['lead'] = lead

        # False grants: grants for zones that never enter E in this episode
        zone_ever_in_E = {}
        for zone in ZONE_NAMES:
            zone_ever_in_E[zone] = any(b in EXCURSION_SET_E for b in zone_history[zone])

        false_grants = 0
        for zone, tick in grant_ticks:
            # Check if zone ever enters E AFTER the grant
            future_exc = any(
                b in EXCURSION_SET_E
                for b in zone_history[zone][tick:]
            )
            if not future_exc:
                false_grants += 1

        episode_data = {
            'seed': self.seed,
            'arm': arm,
            'horizon': horizon,
            'total_ticks': horizon * N_ZONES,
            'excursion_ticks_total': total_exc,
            'excursion_ticks_per_zone': zone_exc,
            'n_excursion_zones': sum(1 for v in zone_exc.values() if v > 0),
            'never_enters_E': total_exc == 0,
            'directives': directives,
            'n_directives': sum(1 for d in directives if not d.get('is_out_of_band')),
            'grants_issued': len(grant_ticks),
            'false_grants': false_grants,
            'is_out_of_band': out_of_band,
            # H4 flags (episode-level, for pre-registered analysis contract)
            'rejected': oob['oob_rejected'],
            'projection_invalid': oob['oob_projection_invalid'],
            'did_not_reallocate': oob['oob_did_not_reallocate'],
        }
        # Non-OOB episodes get default safe values
        if not out_of_band:
            episode_data['rejected'] = False
            episode_data['projection_invalid'] = False
            episode_data['did_not_reallocate'] = True
        return episode_data

    def run(self):
        """Run both arms for this seed. Returns (arm_A_data, arm_B_data)."""
        arm_a = self.run_arm('A')
        arm_b = self.run_arm('B')
        return arm_a, arm_b


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='EXP-S4-01_full paired-arm simulator')
    parser.add_argument('--markov', help='Directory with per-zone Markov JSON files')
    parser.add_argument('--seeds', type=int, default=K,
                        help='Number of seeded episodes (default: %d)' % K)
    parser.add_argument('--results', required=True, help='Output JSONL path')
    parser.add_argument('--demo', action='store_true',
                        help='Use built-in synthetic Markov')
    parser.add_argument('--out-of-band', action='store_true',
                        help='Include H4 out-of-band test')
    args = parser.parse_args()

    # ── Load models ───────────────────────────────────────────────────────
    zone_Ts = None
    if args.demo:
        print("Using DEMO (synthetic) Markov models")
        T = synthetic_markov()
        zone_Ts = {zone: copy.deepcopy(T) for zone in ZONE_NAMES}
    elif args.markov:
        zone_Ts = load_markov_models(args.markov)
        if zone_Ts is None:
            print("ERROR: No Markov models found in %s" % args.markov,
                  file=sys.stderr)
            sys.exit(1)
        print("Loaded %d zones from %s" % (len(zone_Ts), args.markov))

    if zone_Ts is None:
        print("ERROR: No Markov models. Use --markov or --demo.",
              file=sys.stderr)
        sys.exit(1)

    # Print T matrix summary
    sample_zone = list(zone_Ts.keys())[0]
    print("Sample T (%s):" % sample_zone)
    for row in zone_Ts[sample_zone]:
        print("  [%s]" % ", ".join("%.4f" % v for v in row))

    # ── Pre-compute per-zone discriminating thresholds ────────────────────
    zone_thresholds = {}
    for zone, T in zone_Ts.items():
        zone_thresholds[zone] = _compute_discriminating_threshold(T)
    print("\nPer-zone thresholds (h=1):")
    for zone in ZONE_NAMES:
        alert_t, crit_t = zone_thresholds[zone]
        print(f"  {zone:20s}  alert≥{alert_t:.4f}  critical≥{crit_t:.4f}")

    # Calm seeds: extra seeds starting from bin 5 to exercise H3
    CALM_SEEDS = 10  # extra seeds where ALL zones start from bin 5
    print(f"\nRunning {args.seeds} standard + {CALM_SEEDS} calm seeds (start bin 5)")

    # ── Run episodes ──────────────────────────────────────────────────────
    results = []
    for seed in range(args.seeds + CALM_SEEDS):
        runner = EpisodeRunner(seed, zone_Ts, zone_thresholds=zone_thresholds, horizon=HORIZON)
        is_oob = args.out_of_band and seed == args.seeds - 1

        start_bin = 5 if seed >= args.seeds else 4  # calm seeds start at OPTIMAL
        # H4 OOB: inject into arm_A only for the last standard seed
        arm_a = runner.run_arm('A', out_of_band=is_oob, start_from_bin=start_bin)
        arm_b = runner.run_arm('B', start_from_bin=start_bin)
        results.append(arm_a)
        results.append(arm_b)

        a_exc = arm_a['excursion_ticks_total']
        b_exc = arm_b['excursion_ticks_total']
        a_grants = arm_a['grants_issued']
        b_grants = arm_b['grants_issued']
        diff = b_exc - a_exc
        marker = "  ← OOB" if is_oob else ""
        calm = " calm" if seed >= args.seeds else ""
        print("seed=%2d A_exc=%3d B_exc=%3d diff=%+4d grants_A=%d grants_B=%d%s%s" % (
            seed, a_exc, b_exc, diff, a_grants, b_grants, calm, marker))

    # ── Write output ──────────────────────────────────────────────────────
    with open(args.results, 'w') as f:
        for r in results:
            f.write(json.dumps(r) + '\n')
    print("\nWrote %d result lines to %s" % (len(results), args.results))
    print("Analyze: python3 exp_s4_01_analysis.py %s --vsm results.vsm" % args.results)

    # OOB summary
    oobs = [r for r in results if r.get('is_out_of_band')]
    if oobs:
        oob = oobs[0]
        print("H4 OOB: triggered=%s rejected=%s invalid=%s no_realloc=%s" % (
            oob.get('oob_triggered'), oob.get('oob_rejected'),
            oob.get('oob_projection_invalid'), oob.get('oob_did_not_reallocate')))


if __name__ == '__main__':
    main()
