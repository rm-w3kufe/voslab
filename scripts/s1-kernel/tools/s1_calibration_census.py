#!/usr/bin/env python3
"""
s1_calibration_census.py — AXIS 1 extended to the S1s.

Runs the P2/P3 instrument calibration census on the S1 φ↑ streams:
  - clima  → /var/log/vsf-clima/<node>.phi_up.jsonl (per station)
  - econ   → /var/log/s1-econ/phi_up.jsonl

For each instrument: does it VARY across the observed range?
PASS → calibrated. PINNED/degenerate → needs recalibration.

Usage:
  python3 s1_calibration_census.py /var/log/s1-econ/phi_up.jsonl  (econ check)
  python3 s1_calibration_census.py /var/log/vsf-clima/            (clima check, scans all s1-*.phi_up)

Returns exit code 0 if all instruments discriminate, 1 if any pinned.
"""

import json
import os
import sys
from pathlib import Path

# ── Discrimination thresholds (same principle as Axis-1) ──────────────────
STASIS_COS_MIN_SPAN = 0.05   # stasis_cos must vary by at least 0.05 to be discriminating
EXDEM_MIN_SPAN      = 0.01   # excess_demand_norm must span at least 0.01
COPPER_MIN_SPAN     = 0.10   # copper_force must span at least 0.10
CLIMA_COS_MIN_SPAN  = 0.10   # clima stasis_cos per station must span at least 0.10


def check_econ(path: str) -> dict:
    """Check econ instrument discrimination from phi_up.jsonl."""
    if not os.path.exists(path):
        return {"status": "error", "reason": f"file not found: {path}"}

    data = [json.loads(l) for l in open(path)]
    if not data:
        return {"status": "error", "reason": "empty file"}

    cos_vals = [d.get("stasis_cos", 0) for d in data
                if isinstance(d.get("stasis_cos"), (int, float))]
    exdem_vals = [d.get("excess_demand_norm", 0) for d in data
                  if isinstance(d.get("excess_demand_norm"), (int, float))]
    cf_vals = [d.get("copper_force", 0) for d in data
               if isinstance(d.get("copper_force"), (int, float))]
    regimes = set(d.get("regime", "") for d in data if d.get("regime"))

    if not cos_vals:
        return {"status": "error", "reason": "no numeric stasis_cos found"}

    cos_min = min(cos_vals)
    cos_max = max(cos_vals)
    cos_span = cos_max - cos_min
    cos_mean = sum(cos_vals) / len(cos_vals)

    exdem_min = min(exdem_vals) if exdem_vals else 0
    exdem_max = max(exdem_vals) if exdem_vals else 0
    exdem_span = exdem_max - exdem_min

    cf_min = min(cf_vals) if cf_vals else 0
    cf_max = max(cf_vals) if cf_vals else 0
    cf_span = cf_max - cf_min

    cos_discriminates = cos_span >= STASIS_COS_MIN_SPAN
    exdem_discriminates = exdem_span >= EXDEM_MIN_SPAN
    cf_discriminates = cf_span >= COPPER_MIN_SPAN

    all_pass = cos_discriminates and exdem_discriminates and cf_discriminates

    result = {
        "status": "pass" if all_pass else "fail",
        "system": "econ",
        "records": len(cos_vals),
        "regimes": sorted(regimes),
        "stasis_cos": {"min": round(cos_min, 4), "max": round(cos_max, 4),
                       "span": round(cos_span, 4), "mean": round(cos_mean, 4),
                       "discriminates": cos_discriminates},
        "excess_demand_norm": {"min": round(exdem_min, 6), "max": round(exdem_max, 6),
                               "span": round(exdem_span, 6),
                               "discriminates": exdem_discriminates},
        "copper_force": {"min": round(cf_min, 4), "max": round(cf_max, 4),
                         "span": round(cf_span, 4),
                         "discriminates": cf_discriminates},
    }
    return result


def check_clima(path: str) -> dict:
    """Check clima station instrument discrimination.

    Args:
        path: directory containing s1-*.phi_up.jsonl files, or a single file.
    """
    if os.path.isdir(path):
        files = sorted(Path(path).glob("s1-*.phi_up.jsonl"))
    else:
        files = [Path(path)]

    if not files:
        return {"status": "error", "reason": "no s1-* files found"}

    results = []
    total_calibrated = 0
    total_uncalibrated = 0
    total_none_cos = 0
    total_discriminating_some = 0
    all_pass = True

    for fp in files:
        data = [json.loads(l) for l in open(fp)]
        if not data:
            continue
        name = fp.name.replace(".phi_up.jsonl", "")
        latest = data[-1]

        cos = latest.get("stasis_cos")
        in_omega = latest.get("in_omega", False)
        omega_cal = latest.get("omega_calibrated", False)

        if cos is None or not omega_cal:
            total_none_cos += 1
            if not omega_cal:
                total_uncalibrated += 1
            results.append({
                "station": name,
                "status": "uncalibrated",
                "omega_calibrated": omega_cal,
                "in_omega": in_omega,
            })
            continue

        total_calibrated += 1

        # Check discrimination across all records for this station
        cos_vals = [d.get("stasis_cos", 0) for d in data
                    if isinstance(d.get("stasis_cos"), (int, float))]
        if not cos_vals:
            results.append({"station": name, "status": "no_data"})
            continue

        cos_min = min(cos_vals)
        cos_max = max(cos_vals)
        cos_span = cos_max - cos_min
        cos_mean = sum(cos_vals) / len(cos_vals)
        discriminates = cos_span >= CLIMA_COS_MIN_SPAN

        if discriminates:
            total_discriminating_some += 1

        station_pass = discriminates
        if not station_pass:
            all_pass = False

        results.append({
            "station": name,
            "status": "pass" if station_pass else "fail",
            "records": len(cos_vals),
            "stasis_cos": {
                "min": round(cos_min, 4),
                "max": round(cos_max, 4),
                "span": round(cos_span, 4),
                "mean": round(cos_mean, 4),
                "discriminates": discriminates,
            },
            "omega_calibrated": omega_cal,
            "in_omega": in_omega,
        })

    if total_uncalibrated > 0:
        effective_status = "partial"
    elif total_calibrated == 0:
        effective_status = "fail"
    else:
        effective_status = "pass" if all_pass else "partial"

    return {
        "status": effective_status,
        "system": "clima",
        "stations_total": len(files),
        "calibrated": total_calibrated,
        "uncalibrated_omega": total_uncalibrated,
        "discriminating": total_discriminating_some,
        "stations": results,
    }


def print_result(result: dict, verbose: bool = True):
    """Pretty-print a census result."""
    if result["status"] == "error":
        print(f"ERROR ({result.get('system', '?')}): {result.get('reason', 'unknown')}")
        return

    status_icon = "✅" if result["status"] == "pass" else \
                  "⚠️" if result["status"] == "partial" else "❌"

    if result["system"] == "econ":
        cos = result["stasis_cos"]
        exdem = result["excess_demand_norm"]
        cf = result["copper_force"]
        print(f"{status_icon} S1-CALIBRATION-CENSUS: econ")
        print(f"   Records: {result['records']}  Regimes: {result['regimes']}")
        print(f"   stasis_cos:        [{cos['min']:.4f}, {cos['max']:.4f}] span={cos['span']:.4f} "
              f"{'✅' if cos['discriminates'] else '❌'} (need ≥{STASIS_COS_MIN_SPAN})")
        print(f"   excess_demand_norm [{exdem['min']:.6f}, {exdem['max']:.6f}] span={exdem['span']:.6f} "
              f"{'✅' if exdem['discriminates'] else '❌'} (need ≥{EXDEM_MIN_SPAN})")
        print(f"   copper_force       [{cf['min']:.4f}, {cf['max']:.4f}] span={cf['span']:.4f} "
              f"{'✅' if cf['discriminates'] else '❌'} (need ≥{COPPER_MIN_SPAN})")
        print(f"   STATUS: {result['status'].upper()}")

    elif result["system"] == "clima":
        print(f"{status_icon} S1-CALIBRATION-CENSUS: clima")
        print(f"   Stations total: {result['stations_total']}")
        print(f"   Ω-calibrated:  {result['calibrated']}")
        print(f"   Ω-uncalibrated: {result['uncalibrated_omega']}")
        print(f"   Discriminating: {result['discriminating']}")
        if verbose and result.get("stations"):
            print(f"\n   Per-station detail:")
            for s in result["stations"]:
                cos_info = s.get("stasis_cos", {})
                if s["status"] == "uncalibrated":
                    print(f"     ⚠️ {s['station']:25s} UNCALIBRATED (Ω cal={s['omega_calibrated']})")
                elif s["status"] == "no_data":
                    print(f"     ⚠️ {s['station']:25s} NO DATA")
                elif s["status"] == "pass":
                    cos = cos_info
                    print(f"     ✅ {s['station']:25s} cos[{cos['min']:.3f},{cos['max']:.3f}] "
                          f"span={cos['span']:.3f}")
                else:
                    cos = cos_info
                    print(f"     ❌ {s['station']:25s} cos[{cos['min']:.3f},{cos['max']:.3f}] "
                          f"span={cos['span']:.3f} (need ≥{CLIMA_COS_MIN_SPAN})")
        print(f"   STATUS: {result['status'].upper()}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 s1_calibration_census.py <path>")
        print("  <path> = path to econ phi_up.jsonl OR clima directory with s1-*.phi_up.jsonl")
        sys.exit(1)

    path = sys.argv[1]
    verbose = "--quiet" not in sys.argv

    if os.path.isdir(path) or "clima" in path.lower():
        result = check_clima(path)
    else:
        result = check_econ(path)

    print_result(result, verbose)
    sys.exit(0 if result.get("status") == "pass" else 2)
