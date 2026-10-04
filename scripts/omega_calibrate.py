#!/opt/vsf-clima/bin/python
"""
omega_calibrate.py — Ω calibration for all 12 L3 nodes.
ERA5 reanalysis 1991-2020 (WMO standard normal period).
Writes /var/lib/vsf-clima/omega/<node_id>.json per node.

Variables (Q8 resolved):
  Continental: temperature_2m_mean, relative_humidity_2m_mean, precipitation_sum (log1p),
               pressure_msl_mean, wind_speed_10m_max, cloud_cover_mean, shortwave_radiation_sum
  Oceanic: same + sea_surface_temperature_mean (NOAA OISST via Open-Meteo Marine if available)

Usage: omega_calibrate.py [--nodes node1 node2 ...]  (all nodes if omitted)
"""
import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from node_registry import (L3_NODES, CONTINENTAL_DAILY_VARS, MARINE_DAILY_VAR,
                            ERA5_START, ERA5_END, ERA5_PERCENTILE_LO, ERA5_PERCENTILE_HI)

OMEGA_DIR   = Path("/var/lib/vsf-clima/omega")
CACHE_DIR   = Path("/var/lib/vsf-clima/cache")
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL  = "https://marine-api.open-meteo.com/v1/marine"

# User-Agent is required: open-meteo returns HTTP 403 to urllib's default UA.
# This was the silent root-cause that left 51/87 nodes uncalibrated for months
# (workaround caches written out-of-band in June 2026 masked the bug).
UA = "vsf-clima/1.0 (research; contact=rmw3@vsf)"

# Epsilon floor for log1p: log1p(max(v, 0)) collapses to 0 when v==0, producing a
# degenerate envelope (lo=hi=mean=0) for genuinely dry months (hyper-arid zones).
# We floor at a tiny positive so the envelope stays a hair above zero — the month
# is STILL flagged as dry (small envelope near 0) but not silently vacuous.
# This is a methodology refinement (D4 [O] decision 2026-07-24), NOT a fix to
# silence the s1-domingo FINDING — that month being dry is a real climate signal.
PRECIP_EPSILON = 0.001  # mm/day — one thousandth; below noise floor of any gauge

# Rate-limit backoff schedule for Open-Meteo (403/429): 30s, 60s, 120s.
# Open-Meteo rate-limits with HTTP 403 (not 429), confirmed empirically 2026-07-24.
# 404/5xx are permanent → fail-loud immediately, no retry.
# 403/429 retry up to 3× with backoff, then fail-loud.
RETRY_DELAYS = (30, 60, 120)


def _open_with_ua(url: str, *, timeout: int = 120):
    """urlopen wrapper that sets User-Agent (open-meteo 403s the urllib default UA).

    HTTPError 403/429 (rate-limit) is returned to caller for retry with backoff.
    HTTPError 404/5xx is permanent — raised immediately, no retry.
    URLError (network/DNS) is retried by caller with backoff.
    No exception class is silently caught.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def _fail_loud(msg: str) -> None:
    """Emit a failure message that cannot be mistaken for a progress line:
    goes to stderr, prefixed with [FAIL], includes a traceback hint if applicable.
    A silent `print(... retry ...)` was what masked 36 failed fetches for months.
    """
    print(f"[FAIL] {msg}", file=sys.stderr, flush=True)


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    k  = (len(sorted_vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (k - lo) * (sorted_vals[hi] - sorted_vals[lo])


def _fetch_era5(node_id: str, lat: float, lon: float) -> dict:
    """Fetch ERA5 1991-2020 daily data. Returns {var: [float|None, ...]}."""
    cache = CACHE_DIR / f"era5_{node_id}_{ERA5_START}_{ERA5_END}.json"
    if cache.exists():
        print(f"  [{node_id}] loading from cache", flush=True)
        return json.loads(cache.read_text())

    vars_str = ",".join(CONTINENTAL_DAILY_VARS)
    params = "&".join([
        f"latitude={lat}", f"longitude={lon}",
        f"start_date={ERA5_START}", f"end_date={ERA5_END}",
        f"daily={vars_str}",
        "timezone=America%2FSantiago",
    ])
    url = f"{ARCHIVE_URL}?{params}"
    print(f"  [{node_id}] fetching ERA5 {ERA5_START}→{ERA5_END} …", flush=True)

    last_exc: Exception | None = None
    for attempt in range(len(RETRY_DELAYS)):
        try:
            with _open_with_ua(url) as r:
                data = json.loads(r.read())
            result = data["daily"]
            cache.write_text(json.dumps(result))
            return result
        except urllib.error.HTTPError as e:
            STATUS_TRANSIENT = {403, 429}  # rate-limit from Open-Meteo
            wait = RETRY_DELAYS[attempt]
            if e.code in STATUS_TRANSIENT and attempt < len(RETRY_DELAYS) - 1:
                # Rate-limit: retry with exponential backoff.
                print(f"    [{node_id}] ERA5 HTTP {e.code} (rate-limit, attempt {attempt+1}/{len(RETRY_DELAYS)}), "
                      f"backoff {wait}s…", flush=True)
                last_exc = e
                time.sleep(wait)
                continue
            # Permanent HTTP error (404/5xx) or exhausted retries → fail-loud.
            _fail_loud(f"[{node_id}] ERA5 fetch HTTP {e.code} {e.reason} — "
                       f"{'exhausted retries' if e.code in STATUS_TRANSIENT else 'permanent'}, "
                       f"NOT retrying. URL={url}")
            raise RuntimeError(f"ERA5 HTTP {e.code} for {node_id}: {e.reason}") from e
        except urllib.error.URLError as e:
            last_exc = e
            print(f"    [{node_id}] ERA5 transient (attempt {attempt+1}/{len(RETRY_DELAYS)}): {e}", flush=True)
            time.sleep(RETRY_DELAYS[attempt])
        except Exception as e:
            # Unexpected — surface it loudly, do not mask as 'retry'.
            _fail_loud(f"[{node_id}] ERA5 fetch unexpected {type(e).__name__}: {e!r}")
            raise
    _fail_loud(f"[{node_id}] ERA5 fetch exhausted retries: {last_exc!r}")
    raise RuntimeError(f"ERA5 fetch failed for {node_id} after {len(RETRY_DELAYS)} attempts: {last_exc}")


def _fetch_sst_era5(node_id: str, lat: float, lon: float) -> list[float | None]:
    """Fetch SST from Open-Meteo Marine API for oceanic nodes. Returns [float|None, ...]."""
    cache = CACHE_DIR / f"sst_{node_id}_{ERA5_START}_{ERA5_END}.json"
    if cache.exists():
        print(f"  [{node_id}] SST loading from cache", flush=True)
        return json.loads(cache.read_text())

    params = "&".join([
        f"latitude={lat}", f"longitude={lon}",
        f"start_date={ERA5_START}", f"end_date={ERA5_END}",
        f"daily={MARINE_DAILY_VAR}",
        "timezone=GMT",
    ])
    url = f"{MARINE_URL}?{params}"
    print(f"  [{node_id}] fetching SST {ERA5_START}→{ERA5_END} …", flush=True)

    last_exc: Exception | None = None
    for attempt in range(len(RETRY_DELAYS)):
        try:
            with _open_with_ua(url) as r:
                data = json.loads(r.read())
            vals = data["daily"].get(MARINE_DAILY_VAR, [])
            cache.write_text(json.dumps(vals))
            return vals
        except urllib.error.HTTPError as e:
            STATUS_TRANSIENT = {403, 429}
            wait = RETRY_DELAYS[attempt]
            if e.code in STATUS_TRANSIENT and attempt < len(RETRY_DELAYS) - 1:
                print(f"    [{node_id}] SST HTTP {e.code} (rate-limit, attempt {attempt+1}/{len(RETRY_DELAYS)}), "
                      f"backoff {wait}s…", flush=True)
                last_exc = e
                time.sleep(wait)
                continue
            _fail_loud(f"[{node_id}] SST fetch HTTP {e.code} {e.reason} — "
                       f"{'exhausted retries' if e.code in STATUS_TRANSIENT else 'permanent'}, "
                       f"NOT retrying. URL={url}")
            raise RuntimeError(f"SST HTTP {e.code} for {node_id}: {e.reason}") from e
        except urllib.error.URLError as e:
            last_exc = e
            print(f"    [{node_id}] SST transient (attempt {attempt+1}/{len(RETRY_DELAYS)}): {e}", flush=True)
            time.sleep(RETRY_DELAYS[attempt])
        except Exception as e:
            _fail_loud(f"[{node_id}] SST fetch unexpected {type(e).__name__}: {e!r}")
            raise

    # SST is optional (marine API may lack coverage for some coords). Unlike ERA5
    # (which is mandatory), we DO tolerate SST absence — but we say so loudly and
    # name the reason, never silently return an empty list.
    _fail_loud(f"[{node_id}] SST unavailable after 3 attempts: {last_exc!r} — falling back to no-SST (Ω continental-only)")
    return []


def calibrate_node(node_id: str) -> dict:
    cfg = L3_NODES[node_id]
    lat, lon = cfg["lat"], cfg["lon"]

    era5 = _fetch_era5(node_id, lat, lon)
    dates_raw = era5.get("time", [])

    # Optional SST for oceanic nodes
    sst_vals: list = []
    if cfg.get("type") == "oceanic":
        sst_vals = _fetch_sst_era5(node_id, lat, lon)

    # Bucket by calendar month
    monthly: dict[str, dict[str, list[float]]] = {str(m): {} for m in range(1, 13)}

    all_vars = list(CONTINENTAL_DAILY_VARS)
    if sst_vals:
        all_vars = all_vars + [MARINE_DAILY_VAR]

    for var in all_vars:
        for m in range(1, 13):
            monthly[str(m)][var] = []

    for i, d_str in enumerate(dates_raw):
        month = int(d_str[5:7])
        key = str(month)

        for var in CONTINENTAL_DAILY_VARS:
            col = era5.get(var, [])
            if i >= len(col) or col[i] is None:
                continue
            v = float(col[i])
            if var == "precipitation_sum":
                # log1p transform (Fierro Q1 fix) + epsilon-floor (D4 refinement 2026-07-24):
                # log1p(max(v, 0)) collapses genuinely-dry months to a vacuous envelope
                # (lo=hi=mean=0). We floor at PRECIP_EPSILON so the envelope stays a hair
                # above zero — a real dry month stays flagged as dry (tiny envelope) but
                # the bin is honest, not silently empty. See s1-domingo FINDING.
                v = math.log1p(max(v, PRECIP_EPSILON))
            monthly[key][var].append(v)

        if sst_vals and i < len(sst_vals) and sst_vals[i] is not None:
            monthly[key][MARINE_DAILY_VAR].append(float(sst_vals[i]))

    # Compute per-month, per-var: lo/hi/mean/std
    omega = {}
    for month_str, var_data in monthly.items():
        omega[month_str] = {}
        for var, vals in var_data.items():
            if len(vals) < 10:
                continue
            s    = sorted(vals)
            lo   = _percentile(s, ERA5_PERCENTILE_LO)
            hi   = _percentile(s, ERA5_PERCENTILE_HI)
            mean = statistics.mean(vals)
            std  = statistics.stdev(vals) if len(vals) > 1 else 1.0
            omega[month_str][var] = {
                "lo":   round(lo, 4),
                "hi":   round(hi, 4),
                "mean": round(mean, 4),
                "std":  round(std, 4),
                "n":    len(vals),
            }

    result = {
        "node_id":        node_id,
        "type":           cfg["type"],
        "zone":           cfg["zone"],
        "regime":         cfg["regime"],
        "calibrated":     str(date.today()),
        "period":         f"{ERA5_START}/{ERA5_END}",
        "percentile_lo":  ERA5_PERCENTILE_LO,
        "percentile_hi":  ERA5_PERCENTILE_HI,
        "variables":      all_vars,
        "omega":          omega,
    }

    out = OMEGA_DIR / f"{node_id}.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"  [{node_id}] Ω written → {out}  ({len(all_vars)} vars)", flush=True)
    return result


def main():
    OMEGA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(description="Calibrate Ω for L3 climate nodes")
    parser.add_argument("--nodes", nargs="*", default=list(L3_NODES.keys()),
                        help="Node IDs to calibrate (default: all)")
    args = parser.parse_args()

    print(f"Calibrating Ω for {len(args.nodes)} nodes: {args.nodes}", flush=True)
    for node_id in args.nodes:
        if node_id not in L3_NODES:
            print(f"Unknown node: {node_id}")
            continue
        calibrate_node(node_id)
        time.sleep(20)  # rate-limit Open-Meteo (30-year daily request is heavy)

    print("Calibration complete.")


if __name__ == "__main__":
    main()
