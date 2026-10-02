#!/usr/bin/env python3
"""
omega_zone_calibrate.py — Ω calibration for L2 climate zones (ITEM_21.2).

Computes Ω_zona(zone, month) from historical ERA5 data by:
  1. For each zone: gather nodes with ERA5 cache + omega file
  2. For each day 1991-2020: compute stasis_cos per node (kernel_r32)
  3. Per (zone, month, day): compute mean_sc + coherence (1 - var(node scs))
  4. Ω_zona = {mean_sc_lo/hi, coherence_lo/hi} at 5-95 percentile per month

This makes r_L2 > 0 possible: a zone with mean_sc inside Ω_zona absorbs
individual-node excursions (1 node oscillating = normal; the zone as
a whole still within its historical range → ABSORBED, not escalated).

Output: /var/lib/vsf-clima/omega/zone_<zone_id>.json

Usage:
  omega_zone_calibrate.py [--zones z1 z2 ...] [--percentile-lo N] [--percentile-hi N]
"""
import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/opt/vsf-clima/src")
from node_registry import L2_ZONES, ERA5_START, ERA5_END

OMEGA_DIR    = Path("/var/lib/vsf-clima/omega")
CACHE_DIR    = Path("/var/lib/vsf-clima/cache")
ERA5_PERC_LO = 5
ERA5_PERC_HI = 95

# Var → dimension in ℝ³² (mirrors kernel_r32._var_dim_map)
_VAR_DIM = {
    "temperature_2m_mean":           0,
    "relative_humidity_2m_mean":     1,
    "precipitation_sum":             8,
    "pressure_msl_mean":             9,
    "wind_speed_10m_max":           16,
    "cloud_cover_mean":             24,
    "shortwave_radiation_sum":      25,
    "sea_surface_temperature_mean": 26,
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _percentile(sorted_vals: list, p: float) -> float:
    if not sorted_vals:
        return float("nan")
    k  = (len(sorted_vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (k - lo) * (sorted_vals[hi] - sorted_vals[lo])


def _stasis_cos_from_raw(raw_day: dict, omega: dict, month: int) -> float | None:
    """
    Compute stasis_cos for one ERA5 daily row using the node's Ω.
    Mirrors kernel_r32.stasis_cos() exactly so results are comparable.
    """
    month_key = str(month)
    omega_month = omega.get(month_key)
    if not omega_month:
        return None

    # Apply log1p to precipitation (matches calibration + kernel_r32)
    raw_precip = raw_day.get("precipitation_sum")
    if raw_precip is not None:
        raw_day = dict(raw_day)  # shallow copy
        raw_day["precipitation_sum"] = math.log1p(max(raw_precip, 0.0))

    n_active = 0
    total_dist = 0.0

    for var, dim in _VAR_DIM.items():
        if var == "sea_surface_temperature_mean":
            continue  # skip SST for continental calibration
        stats = omega_month.get(var)
        if not stats:
            continue
        xi = raw_day.get(var)
        if xi is None:
            continue

        lo   = stats["lo"]
        hi   = stats["hi"]
        mean = stats["mean"]
        half = (hi - lo) / 2.0 if hi != lo else 1.0

        if lo <= xi <= hi:
            dist = abs(xi - mean) / half if half > 0 else 0.0
        else:
            over = min(abs(xi - lo), abs(xi - hi))
            dist = 1.0 + over / half if half > 0 else 2.0

        total_dist += dist
        n_active   += 1

    if n_active == 0:
        return None

    mean_dist = total_dist / n_active
    return math.cos(math.pi / 2 * min(mean_dist, 2.0))


def _load_era5(node_id: str) -> dict | None:
    files = list(CACHE_DIR.glob(f"era5_{node_id}_*.json"))
    if not files:
        return None
    return json.loads(files[0].read_text())


def _load_node_omega(node_id: str) -> dict | None:
    p = OMEGA_DIR / f"{node_id}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return d.get("omega", d)


# ── per-zone calibration ──────────────────────────────────────────────────────

def calibrate_zone(zone_id: str, cfg: dict, perc_lo: float, perc_hi: float) -> dict | None:
    """
    Compute Ω_zona for one zone. Returns the calibration dict or None if
    no nodes have both ERA5 cache and omega file.
    """
    children = cfg["children"]

    # Gather nodes with both ERA5 cache and omega
    ready = []
    for node_id in children:
        era5 = _load_era5(node_id)
        omega = _load_node_omega(node_id)
        if era5 and omega:
            ready.append((node_id, era5, omega))

    if not ready:
        print(f"  [{zone_id}] SKIP — no calibrated nodes available")
        return None

    print(f"  [{zone_id}] using {len(ready)}/{len(children)} nodes: "
          f"{[r[0] for r in ready]}")

    # Build time index from first node's ERA5 (all share the same dates)
    dates = ready[0][1]["time"]  # ['1991-01-01', ...]

    # For each day, compute stasis_cos per ready node, then aggregate
    # Group: month → list of (mean_sc, coherence)
    monthly: dict[int, list[tuple]] = {m: [] for m in range(1, 13)}

    for i, date_str in enumerate(dates):
        dt_month = int(date_str[5:7])

        # Per-node stasis_cos for this day
        sc_vals = []
        for node_id, era5, omega in ready:
            # Build per-variable dict for this day
            raw_day = {}
            for var_key in _VAR_DIM:
                series = era5.get(var_key)
                if series and i < len(series) and series[i] is not None:
                    raw_day[var_key] = series[i]

            sc = _stasis_cos_from_raw(raw_day, omega, dt_month)
            if sc is not None and not math.isnan(sc):
                sc_vals.append(sc)

        if not sc_vals:
            continue

        # Zone-level aggregate for this day
        mean_sc = sum(sc_vals) / len(sc_vals)

        if len(sc_vals) > 1:
            variance = sum((s - mean_sc) ** 2 for s in sc_vals) / len(sc_vals)
            # Clamp coherence to [0, 1]: var can exceed 1 only if stasis_cos range > 1
            coherence = max(0.0, 1.0 - min(variance, 1.0))
        else:
            coherence = 1.0  # single node: perfect coherence by definition

        monthly[dt_month].append((mean_sc, coherence))

    # Build Ω_zona per month
    omega_zona: dict[str, dict] = {}
    for month, series in monthly.items():
        if not series:
            continue

        sc_sorted  = sorted(s[0] for s in series)
        coh_sorted = sorted(s[1] for s in series)

        omega_zona[str(month)] = {
            "mean_sc_lo":        round(_percentile(sc_sorted,  perc_lo), 4),
            "mean_sc_hi":        round(_percentile(sc_sorted,  perc_hi), 4),
            "mean_sc_mean":      round(sum(sc_sorted) / len(sc_sorted),  4),
            "coherence_lo":      round(_percentile(coh_sorted, perc_lo), 4),
            "coherence_hi":      round(_percentile(coh_sorted, perc_hi), 4),
            "coherence_mean":    round(sum(coh_sorted) / len(coh_sorted), 4),
            "n_days":            len(series),
            "n_nodes_used":      len(ready),
        }

    if not omega_zona:
        print(f"  [{zone_id}] ERROR — no monthly data produced")
        return None

    out = {
        "zone_id":       zone_id,
        "system":        cfg["system"],
        "calibrated":    date.today().isoformat(),
        "period":        f"{ERA5_START}/{ERA5_END}",
        "percentile_lo": perc_lo,
        "percentile_hi": perc_hi,
        "n_nodes_used":  len(ready),
        "nodes_used":    [r[0] for r in ready],
        "omega":         omega_zona,
    }
    return out


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zones",         nargs="*", default=None,
                        help="Zone IDs to calibrate (default: all)")
    parser.add_argument("--percentile-lo", type=float, default=ERA5_PERC_LO)
    parser.add_argument("--percentile-hi", type=float, default=ERA5_PERC_HI)
    args = parser.parse_args()

    zones_to_run = {k: v for k, v in L2_ZONES.items()
                    if args.zones is None or k in args.zones}

    OMEGA_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    skip = 0

    for zone_id, cfg in zones_to_run.items():
        print(f"\n── {zone_id} ({'→'.join([zone_id[:3]]*1)}) ────────────────────────────")
        result = calibrate_zone(zone_id, cfg, args.percentile_lo, args.percentile_hi)
        if result is None:
            skip += 1
            continue

        out_path = OMEGA_DIR / f"zone_{zone_id}.json"
        out_path.write_text(json.dumps(result, indent=2))

        # Summary
        months_done = sorted(int(m) for m in result["omega"])
        sc_range = [
            f"{result['omega'][str(m)]['mean_sc_lo']:.3f}–{result['omega'][str(m)]['mean_sc_hi']:.3f}"
            for m in [1, 6, 12] if str(m) in result["omega"]
        ]
        print(f"  → {out_path.name}  months={months_done}  "
              f"mean_sc [Jan,Jun,Dec]: {sc_range}  nodes={result['nodes_used']}")
        ok += 1

    print(f"\nDone: {ok} zones calibrated, {skip} skipped.")


if __name__ == "__main__":
    main()
