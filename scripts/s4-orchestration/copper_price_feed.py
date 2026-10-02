#!/usr/bin/env python3
"""
copper_price_feed.py — Real copper price feed for s1-econ kernel (EXP-LL-01-COPPER).

Fetches COMEX copper futures (HG=F) via Yahoo Finance public API.
Returns a dimensionless "copper_force" ≈ current_price / 12mo_mean_price,
so that values cluster around 1.0 (range ~0.70–1.40).

Stdlib only (no pip dependencies). Caches results to avoid >1 fetch per 6h.

Usage:
    python3 copper_price_feed.py                    # print current price + force
    python3 copper_price_feed.py --fetch            # force re-fetch
    python3 copper_price_feed.py --serve            # continuous loop (for s1-econ import)
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

# ── Configuration ────────────────────────────────────────────────────────────
CACHE_FILE = os.environ.get(
    "COPPER_CACHE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "copper_price.json"),
)
CACHE_TTL_S = 6 * 3600  # 6 hours — copper settlement is daily
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/HG=F?interval=1mo&range=1y"
USER_AGENT = "VSF/1.0 (s1-econ copper feed; stdlib)"

# ── Data ─────────────────────────────────────────────────────────────────────


def _fetch_json(url: str) -> dict | None:
    """Fetch JSON from URL with user-agent header."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[copper] fetch failed: {e}", file=sys.stderr, flush=True)
        return None


def fetch_prices() -> list[dict] | None:
    """Fetch monthly copper futures prices from Yahoo Finance.
    Returns list of {date, price_usd_per_lb} sorted oldest-first.
    """
    data = _fetch_json(YAHOO_URL)
    if not data:
        return None
    try:
        r = data["chart"]["result"][0]
        timestamps = r["timestamp"]
        closes = r["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as e:
        print(f"[copper] unexpected Yahoo response format: {e}", file=sys.stderr, flush=True)
        return None

    prices = []
    for ts, close in zip(timestamps, closes):
        if close is not None:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            prices.append({"date": dt.strftime("%Y-%m-%d"), "price_usd_per_lb": round(close, 4)})
    return prices


def load_cache() -> dict | None:
    """Read cached copper data if fresh."""
    try:
        with open(CACHE_FILE) as f:
            c = json.load(f)
        age = time.time() - c.get("fetched_at", 0)
        if age < CACHE_TTL_S and c.get("prices"):
            return c
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def save_cache(prices: list[dict]) -> None:
    """Write copper data to cache."""
    os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump({"fetched_at": time.time(), "prices": prices}, f)
    print(f"[copper] cached {len(prices)} monthly prices to {CACHE_FILE}", flush=True)


def get_cache_or_fetch(force: bool = False) -> list[dict] | None:
    """Return cached prices, or fetch if stale/missing. Returns None on failure."""
    if not force:
        cached = load_cache()
        if cached:
            return cached["prices"]
    prices = fetch_prices()
    if prices:
        save_cache(prices)
        return prices
    # Fallback: use stale cache (better than nothing)
    try:
        with open(CACHE_FILE) as f:
            c = json.load(f)
        if c.get("prices"):
            print("[copper] using stale cache (fetch failed)", flush=True)
            return c["prices"]
    except Exception:
        pass
    return None


def compute_copper_force(prices: list[dict]) -> dict:
    """From monthly prices, compute normalized copper_force multiplier.
    Returns {copper_force, latest_price, mean_price, n_months}.
    """
    values = [p["price_usd_per_lb"] for p in prices]
    if not values:
        return {"copper_force": 1.0, "latest_price": None, "mean_price": None, "n_months": 0}
    mean_price = sum(values) / len(values)
    latest_price = values[-1]
    return {
        "copper_force": round(latest_price / mean_price, 4),
        "latest_price_usd_per_lb": latest_price,
        "mean_price_12mo": round(mean_price, 4),
        "n_months": len(values),
        "latest_date": prices[-1]["date"],
    }


def get_copper_force(force_fetch: bool = False) -> dict:
    """High-level: get copper_force multiplier. Returns dict with results."""
    prices = get_cache_or_fetch(force=force_fetch)
    if not prices:
        print("[copper] no data available — returning 1.0 (neutral force)", flush=True)
        return {"copper_force": 1.0, "source": "fallback", "n_months": 0}
    result = compute_copper_force(prices)
    result["source"] = "yahoo_finance" if prices else "fallback"
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Real copper price feed for s1-econ")
    parser.add_argument("--fetch", action="store_true", help="force re-fetch from Yahoo")
    parser.add_argument("--serve", action="store_true", help="continuous loop")
    args = parser.parse_args()

    if args.serve:
        print("[copper] serve mode — one fetch then print", flush=True)
        result = get_copper_force(force_fetch=args.fetch)
        print(json.dumps(result, indent=2))
        return 0

    result = get_copper_force(force_fetch=args.fetch)
    print(json.dumps(result, indent=2))
    if result.get("copper_force", 1.0) == 1.0 and result.get("n_months", 0) == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
