#!/usr/bin/env python3
"""
viability_forecaster.py — domain-agnostic viability forecaster.

Implements pattern(recursive_viability_forecaster) (docs/theory/vos_dev_cycle.vsm) and
operationalises §sec:markov of the attractor_convergence paper: the Markov projection over
stasis_cos bins is a DOMAIN-AGNOSTIC S-function. stasis_cos is the universal viability signal —
every viable subsystem computes it (its state vs its Ω centroid) — so the SAME forecaster nests
into any S1 at any recursion level (L3 station, L2 zone, L0 domain, the nucleus, econ, BBH).

Two layers, kept strictly separate:
  - SENSING  (domain-specific, NOT here): the S1's own kernel produces stasis_cos.
  - FORECAST (domain-agnostic, HERE): stasis_cos history → K-bin transition matrix →
              T^n projection → excursion probability + regime.

Each caller supplies only two things, both its OWN signal (never external re-fetch):
  - train():   an sc_series (the subsystem's stasis_cos history) → a model.
  - project(): a current_sc (the subsystem's LIVE stasis_cos, from its φ↑) + a model → a forecast.

Deterministic, stdlib only. Same inputs → same model/forecast (no timestamps in the math).
First instance: S1-Clima (12 L3 stations). See docs/spec/forecaster_live_state.spec.vsm.
"""
from __future__ import annotations
import math
import statistics

# ── Default binning of stasis_cos ∈ [-1, 1] into K=5 viability states ──────────
# (bin_id, name, lo_inclusive, hi_exclusive). bin 1 catches the rest (severe).
# These are FALLBACK defaults — per-zone percentile bins (computed via
# compute_percentile_bins) are STRONGLY preferred for real deployments.
DEFAULT_BINS = [
    (5, "OPTIMAL",   0.97, 1.01),
    (4, "HEALTHY",   0.92, 0.97),
    (3, "DRIFTING",  0.85, 0.92),
    (2, "EXCURSION", 0.70, 0.85),
    (1, "SEVERE",   -1.01, 0.70),
]
DEFAULT_K = 5
LAPLACE_ALPHA = 1          # add-1 smoothing → no zero transition is impossible
P7_AT_RISK = 0.15          # P(excursion within 7 steps) ≥ this ⇒ regime at_risk
P7_CRITICAL = 0.40         # ≥ this ⇒ critical
DEFAULT_HORIZONS = (7, 30)

# ── Per-zone percentile bin edges ───────────────────────────────────────────
# A typical day falls in bin 4 (HEALTHY). An extreme excursion falls in bin 1.
# Edges: [P5, P20, P50, P80] — bottom 5%, next 15%, middle 30%, next 30%, top 20%.
BIN_PCTS = [5.0, 20.0, 50.0, 80.0]


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated percentile of a SORTED list."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = p / 100.0 * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def compute_percentile_bins(sc_series: list[float]) -> list[tuple[int, str, float, float]]:
    """Compute per-zone bin edges from a stasis_cos series using percentiles.

    Returns bins in the same format as DEFAULT_BINS. Bounds clamped to [-1.01, 1.01].
    A typical day (≈P50) lands in bin 4; an extreme (≈P5) in bin 1.
    """
    valid = [s for s in sc_series if not (s is None or (isinstance(s, float) and math.isnan(s)))]
    if len(valid) < 100:
        return DEFAULT_BINS
    valid.sort()
    p5 = max(-1.01, _percentile(valid, BIN_PCTS[0]))
    p20 = _percentile(valid, BIN_PCTS[1])
    p50 = _percentile(valid, BIN_PCTS[2])
    p80 = min(1.01, _percentile(valid, BIN_PCTS[3]))
    return [
        (5, "OPTIMAL",   p80, 1.01),          # top 20%
        (4, "HEALTHY",   p50, p80),           # next 30% (typical day)
        (3, "DRIFTING",  p20, p50),           # middle 30%
        (2, "EXCURSION", p5,  p20),           # next 15%
        (1, "SEVERE",   -1.01, p5),           # bottom 5%
    ]


def sc_to_bin(sc: float, bins=None) -> int:
    """Discretise a stasis_cos value into its viability bin (or -1 if unusable).

    bins: list of (bin_id, name, lo, hi) tuples. Uses DEFAULT_BINS if None.
    """
    if bins is None:
        bins = DEFAULT_BINS
    if sc is None or (isinstance(sc, float) and math.isnan(sc)):
        return -1
    for bin_id, _name, lo, hi in bins:
        if lo <= sc < hi:
            return bin_id
    return 1  # below all upper bounds ⇒ severe


def _bin_to_index(b: int, k: int = DEFAULT_K) -> int:
    return k - b            # bin 5→0 … bin 1→(k-1)


def _index_to_bin(i: int, k: int = DEFAULT_K) -> int:
    return k - i


def _mat_pow_vec(T, v, n: int):
    """Apply the (row-stochastic) transition matrix T to distribution v, n times."""
    v = v[:]
    for _ in range(n):
        v = [sum(v[i] * T[i][j] for i in range(len(v))) for j in range(len(v))]
    return v


def train(sc_series, k: int = DEFAULT_K, bins=None, alpha: int = LAPLACE_ALPHA) -> dict:
    """Build a viability model from a subsystem's OWN stasis_cos history.

    sc_series: iterable of stasis_cos floats (chronological). NaN/None are skipped as
    transition endpoints. bins: if None, computes per-zone percentile bins from sc_series.
    Returns {K, T, pi, bin_edges, bin_stats, n_transitions, sc_mean, sc_sigma}.
    """
    if bins is None:
        bins = compute_percentile_bins(list(sc_series))
    bin_series = [sc_to_bin(sc, bins) for sc in sc_series]
    counts = [[alpha] * k for _ in range(k)]
    n_trans = 0
    for a, b in zip(bin_series, bin_series[1:]):
        if a < 1 or b < 1:
            continue
        counts[_bin_to_index(a, k)][_bin_to_index(b, k)] += 1
        n_trans += 1
    T = [[c / sum(row) for c in row] for row in counts]

    # stationary distribution (Perron-Frobenius via power iteration)
    pi = [1.0 / k] * k
    for _ in range(1000):
        pi = [sum(pi[i] * T[i][j] for i in range(k)) for j in range(k)]
        s = sum(pi)
        pi = [p / s for p in pi]

    bin_counts = [0] * k
    for b in bin_series:
        if b >= 1:
            bin_counts[_bin_to_index(b, k)] += 1
    total = max(sum(bin_counts), 1)
    bin_stats = {name: {"id": bid, "pct": round(bin_counts[_bin_to_index(bid, k)] / total * 100, 2)}
                 for bid, name, _lo, _hi in bins}

    valid_sc = [s for s in sc_series if not (s is None or (isinstance(s, float) and math.isnan(s)))]
    sc_mean = statistics.mean(valid_sc) if valid_sc else float("nan")
    sc_sigma = statistics.stdev(valid_sc) if len(valid_sc) > 1 else float("nan")

    return {
        "K": k, "T": T, "pi": pi,
        "bin_edges": bins,
        "bin_stats": bin_stats,
        "n_transitions": n_trans,
        "sc_mean": round(sc_mean, 4),
        "sc_sigma": round(sc_sigma, 4),
    }


def project(model: dict, current_sc: float, horizons=DEFAULT_HORIZONS, bins=None) -> dict:
    """Project a subsystem's viability forward from its LIVE current_sc.

    Returns {current_bin, current_sc, regime, p_excursion:{h:p}, expected_bin:{h:e}}.
    Uses model['bin_edges'] as bin thresholds if available, else DEFAULT_BINS.
    current_bin=-1 (regime 'unknown') iff current_sc is NaN/None — the honest failure mode
    the caller must surface, not paper over (this is what MARKOV-PROJECTION-INERT was).
    """
    if bins is None:
        bins = model.get("bin_edges", DEFAULT_BINS)
    k = model["K"]
    T = model["T"]
    current_bin = sc_to_bin(current_sc, bins)
    if current_bin < 1:
        return {"current_bin": -1, "current_sc": current_sc, "regime": "unknown",
                "p_excursion": {}, "expected_bin": {}}

    v0 = [0.0] * k
    v0[_bin_to_index(current_bin, k)] = 1.0

    p_exc, e_bin = {}, {}
    p7 = None
    for h in horizons:
        vh = _mat_pow_vec(T, v0, h)
        # P(excursion) = P(bin ≤ 2) = EXCURSION + SEVERE
        p = vh[_bin_to_index(2, k)] + vh[_bin_to_index(1, k)]
        p_exc[h] = round(p, 4)
        e_bin[h] = round(sum(_index_to_bin(i, k) * vh[i] for i in range(k)), 3)
        if h == min(horizons):
            p7 = p

    if p7 is not None and p7 >= P7_CRITICAL:
        regime = "critical"
    elif p7 is not None and p7 >= P7_AT_RISK:
        regime = "at_risk"
    elif current_bin <= 3:
        regime = "drifting"
    else:
        regime = "stable"

    return {"current_bin": current_bin, "current_sc": round(current_sc, 6), "regime": regime,
            "p_excursion": p_exc, "expected_bin": e_bin}


# ── self-test (deterministic) ─────────────────────────────────────────────────
if __name__ == "__main__":
    # Test 1: DEFAULT_BINS path (for subsystems without per-zone calibration)
    hist_default = ([0.99] * 40 + [0.93, 0.88, 0.80, 0.88, 0.94] + [0.98] * 30) * 3
    m_def = train(hist_default, bins=DEFAULT_BINS)
    assert m_def["K"] == 5 and len(m_def["T"]) == 5
    assert all(abs(sum(row) - 1.0) < 1e-9 for row in m_def["T"]), "rows must be stochastic"
    assert abs(sum(m_def["pi"]) - 1.0) < 1e-9
    healthy_def = project(m_def, 0.985, bins=DEFAULT_BINS)
    drift_def = project(m_def, 0.82, bins=DEFAULT_BINS)
    nan_def = project(m_def, float("nan"))
    assert healthy_def["current_bin"] == 5 and healthy_def["regime"] in ("stable", "at_risk", "critical")
    assert drift_def["current_bin"] == 2
    assert nan_def["current_bin"] == -1 and nan_def["regime"] == "unknown"
    assert 0.0 <= healthy_def["p_excursion"][7] <= 1.0
    print("Test 1 (DEFAULT_BINS): OK")
    print(f"  healthy(0.985): bin={healthy_def['current_bin']} {healthy_def['regime']} p_exc7={healthy_def['p_excursion'][7]}")
    print(f"  drift(0.82):    bin={drift_def['current_bin']} {drift_def['regime']}   p_exc7={drift_def['p_excursion'][7]}")
    print(f"  nan:            bin={nan_def['current_bin']} {nan_def['regime']}")

    # Test 2: percentile bin path (per-zone calibration, realistic spread)
    import random
    random.seed(42)
    # Realistic distribution: mean ~0.65, σ ~0.30 (matches s1-santiago)
    hist_real = [max(-1.0, min(1.0, random.gauss(0.65, 0.30))) for _ in range(3000)]
    m_re = train(hist_real)
    assert m_re["K"] == 5
    assert "bin_edges" in m_re
    assert len(m_re["bin_edges"]) == 5
    healthy_re = project(m_re, 0.60)   # ≈ P45-55 (typical day) → bin 3-4
    good_re = project(m_re, 0.90)      # ≈ P80+ (top 20%) → bin 5
    bad_re  = project(m_re, 0.05)      # ≈ P2-3 (extreme) → bin 1
    assert healthy_re["current_bin"] in (3, 4), f"typical day landed bin {healthy_re['current_bin']}"
    assert good_re["current_bin"] in (4, 5), f"good day landed bin {good_re['current_bin']}"
    assert bad_re["current_bin"] == 1, f"extreme day landed bin {bad_re['current_bin']}"
    print("Test 2 (percentile bins): OK")
    print(f"  typical(0.60):  bin={healthy_re['current_bin']} {healthy_re['regime']} p_exc7={healthy_re['p_excursion'][7]}")
    print(f"  good(0.90):     bin={good_re['current_bin']} {good_re['regime']}   p_exc7={good_re['p_excursion'][7]}")
    print(f"  bad(0.20):      bin={bad_re['current_bin']} {bad_re['regime']}    p_exc7={bad_re['p_excursion'][7]}")

    print("\nviability_forecaster self-test: ALL OK")
