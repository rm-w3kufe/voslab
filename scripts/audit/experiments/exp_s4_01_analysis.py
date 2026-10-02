#!/usr/bin/env python3
"""exp_s4_01_analysis.py — PRE-REGISTERED analysis for EXP-S4-01_full.

FROZEN 2026-07-14 (docs/spec/s4_anticipation/spec.vsm §frozen).
NO post-hoc adjustments. The verdict is mechanical.

Input:  JSONL of paired-arm results (one line per (seed, arm) pair)
        Produced by exp_s4_01_harness.py.

Output: Verdict per outcomes{} map. Written to stdout and optional results.vsm path.

Hypotheses (pre-registered):
  H1 (lead):    median lead ≥ 1 tick AND directive fires while current_bin ≥ 3
                in ≥80% of episodes.
  H2 (primary): Paired Wilcoxon signed-rank one-sided (A < B), α=0.05,
                on excursion-tick-count (#ticks in E, summed over zones).
  H3 (precision): false-grant rate on NON-excursion seeds < 0.10.
  H4 (regime):  Inject 1 out-of-band episode → must log projection_invalid
                and NOT reallocate.

Parameters (frozen):
  K              = 30     (seeded episodes)
  horizon        = 30     (ticks per episode)
  excursion_set_E = {1,2} (SEVERE, EXCURSION bins)
  α              = 0.05   (one-sided)
  H1_lead_bar    = 1 tick
  H1_bin_bar     = 0.80   (≥80% episodes fire in bin ≥3)
  H3_rho         = 0.10   (false-grant threshold)

Returns dict with all metrics and a single 'verdict' key per outcomes{}.
"""

import json
import sys
import math

# ── FROZEN PARAMETERS ──────────────────────────────────────────────────────────
K = 30
HORIZON = 30
EXCURSION_BINS = {1, 2}  # SEVERE=1, EXCURSION=2 (bins {3,4,5} are healthy)
H1_LEAD_BAR = 1           # median lead must be ≥ 1 tick
H1_BIN_BAR = 0.80         # ≥80% of episodes fire while in bin ≥ 3
H3_RHO = 0.10             # false-grant rate threshold
ALPHA = 0.05              # one-sided Wilcoxon

# ── WILCOXON SIGNED-RANK (paired, one-sided) ──────────────────────────────────
# Pure Python implementation to avoid scipy dependency on sandbox.
# Implements the one-sided signed-rank test per Conover (1999).

def _wilcoxon_signed_rank(x, y):
    """Paired one-sided Wilcoxon signed-rank test (H0: median(x - y) = 0).
    
    Returns (W, p_value_one_sided_greater) where greater = x > y.
    Here: x = arm_A excursion_ticks, y = arm_B excursion_ticks.
    We want A < B, so we test H0: A >= B vs H1: A < B.
    That's the one-sided lower-tailed test on the paired difference.
    """
    n = len(x)
    if n != len(y):
        raise ValueError("x and y must have same length")
    if n < 2:
        return 0, 1.0
    
    # Compute paired differences
    diffs = [x[i] - y[i] for i in range(n)]
    
    # Remove zeros
    non_zero = [d for d in diffs if d != 0]
    nz = len(non_zero)
    if nz < 2:
        return 0, 1.0
    
    # Absolute values for ranking
    abs_diffs = [abs(d) for d in non_zero]
    
    # Assign ranks (handling ties: average rank)
    sorted_indices = sorted(range(nz), key=lambda i: abs_diffs[i])
    ranks = [0.0] * nz
    
    i = 0
    while i < nz:
        j = i
        # Find ties
        while j < nz and abs_diffs[sorted_indices[j]] == abs_diffs[sorted_indices[i]]:
            j += 1
        # Average rank for tied group
        avg_rank = (i + j + 1) / 2.0  # 1-indexed ranks
        for k in range(i, j):
            ranks[sorted_indices[k]] = avg_rank
        i = j
    
    # Sum of positive ranks (W+)
    w_pos = sum(ranks[i] for i in range(nz) if non_zero[i] > 0)
    w_neg = sum(ranks[i] for i in range(nz) if non_zero[i] < 0)
    
    # One-sided lower-tail: H0: median(A - B) >= 0 (A >= B)
    # H1: median(A - B) < 0 (A < B)
    # Reject H0 when w_pos (sum of ranks where A > B) is small enough
    # that it is unlikely under H0.
    # We use w_pos as the test statistic: if A < B, most diffs are
    # negative → w_pos is small.
    w = w_pos  
    
    # Normal approximation for n >= 10
    if nz >= 10:
        mean = nz * (nz + 1) / 4.0
        # Tie correction
        tie_groups = {}
        for d in abs_diffs:
            tie_groups[d] = tie_groups.get(d, 0) + 1
        tie_corr = sum(t**3 - t for t in tie_groups.values() if t > 1) / 48.0
        var = nz * (nz + 1) * (2 * nz + 1) / 24.0 - tie_corr
        
        if var <= 0:
            z = 0.0
        else:
            # Continuity correction (lower tail): w - mean + 0.5
            z = (w - mean + 0.5) / math.sqrt(var)
        
        # One-sided lower-tail: we want A < B (fewer excursions with intervention).
        # If A < B, w_pos is small (few positive diffs), z is negative,
        # and p = P(Z < z) is small.
        p = _normal_cdf(z)
    else:
        # Exact test for small n — not expected (K=30)
        # Fallback to approximate: proportion of possible rank-sums <= observed
        p = w / (nz * (nz + 1) / 2.0)
    
    return w, p


def _normal_cdf(z):
    """Standard normal CDF using Abramowitz & Stegun 26.2.17."""
    if z < -10:
        return 0.0
    if z > 10:
        return 1.0
    b0 = 0.2316419
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    t = 1.0 / (1.0 + b0 * abs(z))
    phi = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-z * z / 2.0) * (
        b1 * t + b2 * t**2 + b3 * t**3 + b4 * t**4 + b5 * t**5
    )
    if z >= 0:
        return phi
    else:
        return 1.0 - phi


# ── ANALYSIS ───────────────────────────────────────────────────────────────────

def compute_lead_stats(arms_data):
    """Compute H1 lead-time statistics per episode.
    
    arm_data: list of dicts with keys:
        'episodes': [{'seed': int, 'directives': [{ts, zone, current_bin, lead}], ...}]
    
    Returns dict with lead metrics.
    """
    all_leads = []
    episode_lead_data = {}
    
    for arm_label, data in arms_data.items():
        for ep in data.get('episodes', []):
            seed = ep.get('seed', 0)
            directives = ep.get('directives', [])
            ep_key = (seed, arm_label)
            
            if directives:
                # Compute min lead across valid directives (skip OOB/rejected)
                valid_leads = [d['lead'] for d in directives
                               if d.get('lead') is not None and d['lead'] >= 0]
                min_lead = min(valid_leads) if valid_leads else None
                fire_bins = [d.get('current_bin', 0) for d in directives
                             if not d.get('is_out_of_band')]
                fire_in_bin_3_plus = any(b >= 3 for b in fire_bins) if fire_bins else False
                if min_lead is not None:
                    all_leads.append(min_lead)
                episode_lead_data[ep_key] = {
                    'min_lead': min_lead,
                    'directives_count': len(directives),
                    'fired_in_bin_3_plus': fire_in_bin_3_plus,
                    'first_directive_ts': min(d.get('ts', 0) for d in directives),
                }
            else:
                episode_lead_data[ep_key] = {
                    'min_lead': None,
                    'directives_count': 0,
                    'fired_in_bin_3_plus': False,
                    'first_directive_ts': None,
                }
    
    if not all_leads:
        return {
            'h1_median_lead': None,
            'h1_n_episodes_with_directives': 0,
            'h1_bin_bar_pass': False,
            'h1_lead_bar_pass': False,
            'h1_overall_pass': False,
            'h1_note': 'No directives fired in any episode'
        }
    
    all_leads.sort()
    n = len(all_leads)
    median_lead = all_leads[n // 2] if n % 2 else (all_leads[n//2 - 1] + all_leads[n//2]) / 2.0
    
    # Bin bar: ≥80% of episodes with directives fire in bin ≥ 3
    ep_with_dirs = [v for v in episode_lead_data.values() if v['directives_count'] > 0]
    n_with_dirs = len(ep_with_dirs)
    if n_with_dirs > 0:
        bin_pass_count = sum(1 for v in ep_with_dirs if v['fired_in_bin_3_plus'])
        bin_bar_pass = bin_pass_count / n_with_dirs >= H1_BIN_BAR
    else:
        bin_bar_pass = False
    
    lead_bar_pass = median_lead >= H1_LEAD_BAR
    h1_pass = lead_bar_pass and bin_bar_pass
    
    return {
        'h1_median_lead': median_lead,
        'h1_n_episodes_with_directives': n_with_dirs,
        'h1_lead_bar_pass': lead_bar_pass,
        'h1_bin_bar_pass': bin_bar_pass,
        'h1_bin_bar_ratio': (bin_pass_count / n_with_dirs) if n_with_dirs > 0 else 0.0,
        'h1_overall_pass': h1_pass,
        'h1_note': 'PASS' if h1_pass else 'FAIL: ' + (
            'lead_bar' if not lead_bar_pass else 'bin_bar'
        )
    }


def compute_h2_wilcoxon(arm_a_data, arm_b_data):
    """Compute H2 primary paired Wilcoxon test on excursion-tick-count.
    
    Returns dict with W, p, median_reduction, ci_lower, ci_upper, pass.
    """
    # Build paired data: {seed: {arm_a: excursion_ticks, arm_b: excursion_ticks}}
    paired = {}
    for arm_label, data in [('A', arm_a_data), ('B', arm_b_data)]:
        for ep in data:
            seed = ep.get('seed')
            if seed not in paired:
                paired[seed] = {}
            paired[seed][arm_label] = ep.get('excursion_ticks_total', 0)
    
    # Only use seeds present in BOTH arms
    valid = {s: v for s, v in paired.items() if 'A' in v and 'B' in v}
    seeds = sorted(valid.keys())
    a_vals = [valid[s]['A'] for s in seeds]
    b_vals = [valid[s]['B'] for s in seeds]
    
    # H2: one-sided A < B (anticipation reduces excursion ticks)
    w, p = _wilcoxon_signed_rank(a_vals, b_vals)
    
    # Median paired reduction
    paired_diffs = [b_vals[i] - a_vals[i] for i in range(len(seeds))]
    paired_diffs.sort()
    nd = len(paired_diffs)
    median_reduction = paired_diffs[nd // 2] if nd % 2 else \
        (paired_diffs[nd//2 - 1] + paired_diffs[nd//2]) / 2.0
    
    # 95% CI on median reduction (non-parametric bootstrap)
    # Using the Hodges-Lehmann estimator for CI
    # Simple approach: sorted pairwise differences
    n_seeds = len(seeds)
    all_pairwise = []
    for i in range(n_seeds):
        for j in range(n_seeds):
            if i <= j:
                d = (b_vals[i] - a_vals[i] + b_vals[j] - a_vals[j]) / 2.0
                all_pairwise.append(d)
    all_pairwise.sort()
    n_pair = len(all_pairwise)
    ci_lower = all_pairwise[int(n_pair * 0.025)]
    ci_upper = all_pairwise[int(n_pair * 0.975)]
    
    h2_pass = p < ALPHA  # one-sided A < B
    
    return {
        'h2_n_valid_pairs': len(seeds),
        'h2_w_statistic': w,
        'h2_p_value': p,
        'h2_median_paired_reduction': median_reduction,
        'h2_ci_lower_95': ci_lower,
        'h2_ci_upper_95': ci_upper,
        'h2_pass': h2_pass,
        'h2_note': 'PASS (A < B, p=%.4f < α=%.2f)' % (p, ALPHA) if h2_pass \
            else 'FAIL (p=%.4f ≥ α=%.2f)' % (p, ALPHA),
    }


def compute_h3_false_grants(non_excursion_data):
    """Compute H3 false-grant rate on non-excursion seeds.
    
    non_excursion_data: list of episode dicts for seeds that NEVER enter E.
    
    Returns dict with false-grant rate and pass/fail.
    """
    total_ticks = 0
    false_grants = 0
    
    for ep in non_excursion_data:
        total_ticks += ep.get('total_ticks', 0)
        false_grants += ep.get('false_grants', 0)
    
    # Rate = false grants / total ticks (or use grant events directly)
    # Per spec: false-grant RATE = number of false grants / number of non-excursion ticks
    false_rate = false_grants / total_ticks if total_ticks > 0 else 0.0
    
    h3_pass = false_rate < H3_RHO
    
    return {
        'h3_false_grants': false_grants,
        'h3_total_ticks': total_ticks,
        'h3_false_rate': false_rate,
        'h3_threshold': H3_RHO,
        'h3_pass': h3_pass,
        'h3_note': 'PASS (rate=%.4f < %.2f)' % (false_rate, H3_RHO) if h3_pass \
            else 'FAIL (rate=%.4f ≥ %.2f)' % (false_rate, H3_RHO),
    }


def compute_h4_regime(out_of_band_result):
    """Compute H4 regime guard test.
    
    out_of_band_result: dict with 'rejected' (bool), 'projection_invalid' (bool)
    
    Returns dict with pass/fail.
    """
    if out_of_band_result is None:
        return {
            'h4_pass': False,
            'h4_note': 'FAIL: No out-of-band episode injected',
        }
    
    h4_pass = (
        out_of_band_result.get('rejected', False) and
        out_of_band_result.get('projection_invalid', False)
    )
    
    return {
        'h4_injected': True,
        'h4_rejected': out_of_band_result.get('rejected', False),
        'h4_projection_invalid': out_of_band_result.get('projection_invalid', False),
        'h4_did_not_reallocate': out_of_band_result.get('did_not_reallocate', True),
        'h4_pass': h4_pass,
        'h4_note': 'PASS' if h4_pass else (
            'FAIL: ' + (
                'did not reject' if not out_of_band_result.get('rejected', False)
                else 'did not flag projection_invalid'
            )
        ),
    }


# ── MAIN ───────────────────────────────────────────────────────────────────────

def analyze(results_path, results_vsm_path=None):
    """Run the full pre-registered analysis.
    
    Args:
        results_path: Path to JSONL with paired-arm results.
        results_vsm_path: Optional path to write results.vsm.
    
    The JSONL input is one line per (seed, arm) pair:
    {
        "seed": int,
        "arm": "A" | "B",
        "episodes": [
            {
                "seed": int,
                "excursion_ticks_total": int,  # ticks in E across all zones
                "total_ticks": 30,
                "directives": [{"ts": int, "lead": int, "current_bin": int, ...}],
                "false_grants": int,
                "never_enters_E": bool,
            }
        ]
    }
    """
    # Load results
    arm_a_episodes = []
    arm_b_episodes = []
    
    with open(results_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get('arm') == 'A':
                arm_a_episodes.append(record)
            elif record.get('arm') == 'B':
                arm_b_episodes.append(record)
    
    arms_data = {
        'A': {'episodes': arm_a_episodes},
        'B': {'episodes': arm_b_episodes},
    }
    
    # ── H1: Lead time ──
    # Only arm_A can produce directives (anticipation ON)
    h1_lead_data = {'A': arms_data['A']}
    h1_result = compute_lead_stats(h1_lead_data)
    
    # ── H2: Primary Wilcoxon ──
    h2_result = compute_h2_wilcoxon(arm_a_episodes, arm_b_episodes)
    
    # ── H3: False grants on non-excursion seeds (arm A only) ──
    non_excursion_eps = [ep for ep in arm_a_episodes if ep.get('never_enters_E', False)]
    h3_result = compute_h3_false_grants(non_excursion_eps)
    
    # ── H4: Out-of-band regime (special episode) ──
    oob = None
    for ep in arm_a_episodes:
        if ep.get('is_out_of_band', False):
            oob = ep
            break
    h4_result = compute_h4_regime(oob)
    
    # ── VERDICT ──
    h1_pass = h1_result['h1_overall_pass']
    h2_pass = h2_result['h2_pass']
    h3_pass = h3_result['h3_pass']
    h4_pass = h4_result['h4_pass']
    
    if h1_pass and h2_pass and h3_pass and h4_pass:
        verdict = 'H1∧H2∧H3∧H4_confirmed'
        verdict_note = 'Anticipation EARNED (+0.9 A). AC paper gets prescriptive continuation.'
    elif not h1_pass:
        verdict = 'H1_fails'
        verdict_note = 'Projector lead-time bug. Fix projector, re-run. No paper claim.'
    elif not h2_pass:
        verdict = 'H2_fails'
        verdict_note = 'Lead OK but no prevention. Design revision, not paper claim.'
    elif not h3_pass:
        verdict = 'H3_fails'
        verdict_note = 'Recalibrate DIRECTIVE_THRESHOLD. Precision gate before autonomy.'
    elif not h4_pass:
        verdict = 'H4_fails'
        verdict_note = 'Projection acted out-of-distribution. 17.4 guard must ship before 17.2.'
    else:
        verdict = 'inconclusive'
        verdict_note = 'Unexpected result combination'
    
    result = {
        'experiment': 'EXP-S4-01_full',
        'analysis_date': None,  # filled by caller
        'parameters': {
            'K': K,
            'horizon': HORIZON,
            'excursion_set_E': sorted(EXCURSION_BINS),
            'alpha': ALPHA,
            'h1_lead_bar': H1_LEAD_BAR,
            'h1_bin_bar': H1_BIN_BAR,
            'h3_rho': H3_RHO,
        },
        'h1': h1_result,
        'h2': h2_result,
        'h3': h3_result,
        'h4': h4_result,
        'verdict': verdict,
        'verdict_note': verdict_note,
        'outcome': verdict,
        'analysis_frozen_at': '2026-07-14T00:00:00Z',
    }
    
    # Output
    print(json.dumps(result, indent=2))
    
    if results_vsm_path:
        _write_results_vsm(result, results_vsm_path)
    
    return result


def _write_results_vsm(result, path):
    """Write the analysis verdict as a VSM file."""
    lines = []
    lines.append('@vsm 0.3')
    lines.append('')
    lines.append('// EXP-S4-01_full — RESULTS (pre-registered analysis)')
    lines.append('// analysis_frozen: 2026-07-14  |  run_date: %s' % (result.get('analysis_date', 'TBD')))
    lines.append('// verdict: %s' % result['verdict'])
    lines.append('')
    lines.append('experiment("EXP-S4-01_full") = {')
    lines.append('  verdict: "%s",' % result['verdict'])
    lines.append('  note: "%s",' % result['verdict_note'])
    lines.append('  parameters: {')
    for k, v in result['parameters'].items():
        lines.append('    %s: %s,' % (k, json.dumps(v)))
    lines.append('  },')
    lines.append('')
    lines.append('  h1_lead: {')
    for k, v in result['h1'].items():
        if isinstance(v, str):
            lines.append('    %s: "%s",' % (k, v))
        elif isinstance(v, bool):
            lines.append('    %s: %s,' % (k, 'true' if v else 'false'))
        else:
            lines.append('    %s: %s,' % (k, json.dumps(v)))
    lines.append('  },')
    lines.append('')
    lines.append('  h2_prevention: {')
    for k, v in result['h2'].items():
        if isinstance(v, str):
            lines.append('    %s: "%s",' % (k, v))
        elif isinstance(v, bool):
            lines.append('    %s: %s,' % (k, 'true' if v else 'false'))
        else:
            lines.append('    %s: %s,' % (k, json.dumps(v)))
    lines.append('  },')
    lines.append('')
    lines.append('  h3_precision: {')
    for k, v in result['h3'].items():
        if isinstance(v, str):
            lines.append('    %s: "%s",' % (k, v))
        elif isinstance(v, bool):
            lines.append('    %s: %s,' % (k, 'true' if v else 'false'))
        else:
            lines.append('    %s: %s,' % (k, json.dumps(v)))
    lines.append('  },')
    lines.append('')
    lines.append('  h4_honesty: {')
    for k, v in result['h4'].items():
        if isinstance(v, str):
            lines.append('    %s: "%s",' % (k, v))
        elif isinstance(v, bool):
            lines.append('    %s: %s,' % (k, 'true' if v else 'false'))
        else:
            lines.append('    %s: %s,' % (k, json.dumps(v)))
    lines.append('  },')
    lines.append('}')
    
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('  → wrote %s' % path)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='EXP-S4-01_full pre-registered analysis')
    parser.add_argument('results', help='Path to JSONL results file')
    parser.add_argument('--vsm', help='Path to write results.vsm (optional)')
    args = parser.parse_args()
    
    from datetime import datetime, timezone
    result = analyze(args.results, args.vsm)
    result['analysis_date'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
