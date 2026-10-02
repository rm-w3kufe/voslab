#!/usr/bin/env python3
"""markov_train.py — ITEM_17.1: entrena cadenas de Markov por zona sobre ERA5 1991-2020.

Runs on LXC 112 (s1-clima). Reads ERA5 historical cache + Ω calibration per zone,
computes historical stasis_cos time series, builds K×K transition matrix, saves model.

Uses scripts/forecaster/viability_forecaster.py for the domain-agnostic math.
Per-zone percentile bins computed from the training distribution so a typical day lands
in bin 4 (HEALTHY) and an extreme excursion lands in bin 1 (SEVERE).

Output: /var/lib/vsf-clima/markov/{zone}.json per calibrated zone.

Usage:
  python3 markov_train.py [--zone s1-santiago] [--verbose]
"""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

# Import domain-agnostic forecaster (deployed to same dir: /usr/local/bin/)
from viability_forecaster import (sc_to_bin, train, project, DEFAULT_BINS,
                                   _bin_to_index, LAPLACE_ALPHA, P7_AT_RISK, P7_CRITICAL)

CACHE_DIR  = Path("/var/lib/vsf-clima/cache")
OMEGA_DIR  = Path("/var/lib/vsf-clima/omega")
MARKOV_DIR = Path("/var/lib/vsf-clima/markov")

# ERA5 cache variable names (must match omega calibration)
ERA5_VARS = [
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "precipitation_sum",
    "pressure_msl_mean",
    "wind_speed_10m_max",
    "wind_direction_10m_dominant",
    "cloud_cover_mean",
    "shortwave_radiation_sum",
]

LAPLACE_ALPHA = 1


def stasis_cos(day_vals: dict, omega_month: dict) -> float:
    """Compute stasis_cos for a single day given daily variable values and monthly Ω bounds.
    Domain-specific: half-range normalization from the Ω bounds (5-95th percentile)."""
    total_dist = 0.0
    n = 0
    for var in ERA5_VARS:
        if var not in omega_month or var not in day_vals:
            continue
        xi  = day_vals[var]
        lo  = omega_month[var]["lo"]
        hi  = omega_month[var]["hi"]
        mid = omega_month[var]["mean"]
        if xi is None:
            continue
        half = (hi - lo) / 2.0 if hi != lo else 1.0
        if lo <= xi <= hi:
            dist = abs(xi - mid) / half if half > 0 else 0.0
        else:
            dist = 1.0 + min(abs(xi - lo), abs(xi - hi)) / half
        total_dist += dist
        n += 1
    if n == 0:
        return float("nan")
    mean_dist = total_dist / n
    return math.cos(math.pi / 2.0 * min(mean_dist, 2.0))


def train_zone(zone: str, verbose: bool = False) -> dict | None:
    """Train a Markov model for one zone. Returns model dict or None on failure."""
    era5_path  = CACHE_DIR / f"era5_{zone}_1991-01-01_2020-12-31.json"
    omega_path = OMEGA_DIR / f"{zone}.json"

    if not era5_path.exists():
        print(f"  [{zone}] ERA5 cache not found: {era5_path}", file=sys.stderr)
        return None
    if not omega_path.exists():
        print(f"  [{zone}] omega not found: {omega_path}", file=sys.stderr)
        return None

    with open(era5_path) as f:
        era5 = json.load(f)
    with open(omega_path) as f:
        omega_raw = json.load(f)
    omega = omega_raw.get("omega", omega_raw)

    dates = era5.get("time", [])
    n_days = len(dates)
    if n_days == 0:
        print(f"  [{zone}] empty ERA5 cache", file=sys.stderr)
        return None

    # ── Compute stasis_cos time series ────────────────────────────────────────
    sc_series: list[float] = []

    for i, date_str in enumerate(dates):
        month = int(date_str[5:7])
        omega_month = omega.get(str(month), {})
        day_vals = {var: era5[var][i] for var in ERA5_VARS if var in era5}
        sc = stasis_cos(day_vals, omega_month)
        sc_series.append(sc)

    # ── Train forecaster (domain-agnostic: percentile bins auto-computed) ─────
    model = train(sc_series, alpha=LAPLACE_ALPHA)

    # ── Add zone metadata ─────────────────────────────────────────────────────
    # Count how many days fall in each original default bin for comparison
    default_bin_counts = [0] * 5
    for sc_val in sc_series:
        b = sc_to_bin(sc_val, DEFAULT_BINS)
        if b >= 1:
            default_bin_counts[_bin_to_index(b)] += 1
    n_valid_default = max(sum(default_bin_counts), 1)
    default_bin_pcts = {
        name: round(default_bin_counts[_bin_to_index(bid)] / n_valid_default * 100, 2)
        for bid, name, _lo, _hi in DEFAULT_BINS
    }

    result = {
        "zone":              zone,
        "trained_at":        datetime.utcnow().isoformat() + "Z",
        "era5_range":        [dates[0], dates[-1]],
        "n_days":            n_days,
        "K":                 model["K"],
        "bin_edges":         model["bin_edges"],
        "bin_stats":         model["bin_stats"],
        "default_bin_pcts":  default_bin_pcts,
        "sc_mean":           model["sc_mean"],
        "sc_sigma":          model["sc_sigma"],
        "T":                 [[round(p, 6) for p in row] for row in model["T"]],
        "stationary":        [round(p, 6) for p in model["pi"]],
        "n_transitions":     model["n_transitions"],
        "laplace_alpha":     LAPLACE_ALPHA,
    }

    if verbose:
        edges = model["bin_edges"]
        print(f"  [{zone}] sc_mean={model['sc_mean']:.3f} sc_sigma={model['sc_sigma']:.3f}  n_trans={model['n_transitions']}")
        edge_str = '  '.join(f"{e[1]}: [{e[2]:.3f},{e[3]:.3f})" for e in edges)
        print(f"    bin_edges: {edge_str}")
        pi_str = '  '.join(f"{e[1]}={model['pi'][i]*100:.1f}%" for i, e in enumerate(edges))
        print(f"    stationary: {pi_str}")

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone", default=None, help="Train only this zone")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    MARKOV_DIR.mkdir(parents=True, exist_ok=True)

    # Discover zones: any omega file with matching ERA5 cache
    if args.zone:
        zones = [args.zone]
    else:
        zones = sorted(
            p.stem for p in OMEGA_DIR.glob("*.json")
            if (CACHE_DIR / f"era5_{p.stem}_1991-01-01_2020-12-31.json").exists()
        )

    print(f"Training Markov models for {len(zones)} zones (per-zone percentile bins)...")
    ok = 0
    for zone in zones:
        print(f"  {zone}...")
        model = train_zone(zone, verbose=args.verbose)
        if model:
            out = MARKOV_DIR / f"{zone}.json"
            with open(out, "w") as f:
                json.dump(model, f, indent=2)
            ok += 1
            print(f"  → {out}")

    print(f"\nDone: {ok}/{len(zones)} models trained → {MARKOV_DIR}")


if __name__ == "__main__":
    main()
