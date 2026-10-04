#!/usr/bin/env python3
"""
fetch_chile.py — EXP-LL-01 data terrain: real Chile economic + population data.
ref: docs/experiments/EXP-LL-01/data_sources.vsm

Source: World Bank Open Data API (https://api.worldbank.org/v2) — FREE, NO AUTH, JSON.
Mirrors how EXP-S1-CLIMA-01/fierro_q123.py pulled real ERA5 (Open-Meteo). Caches raw +
writes cache/chile_params.json, which s1_econ_kernel.py loads to shape the live economy.

Scope: Chile (CHL), with the international gravitating forces that dominate a small open,
copper-export economy — China demand (copper) + global context.
"""
import json
import os
import sys
import urllib.request

WB = "https://api.worldbank.org/v2"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# Chile structural series → kernel sector shares
CHILE_SERIES = {
    "gdp_usd":        "NY.GDP.MKTP.CD",     # GDP (current US$)
    "population":     "SP.POP.TOTL",        # total population
    "inflation_cpi":  "FP.CPI.TOTL.ZG",     # CPI inflation (annual %)
    "va_agriculture": "NV.AGR.TOTL.ZS",     # agriculture, value added (% GDP)
    "va_industry":    "NV.IND.TOTL.ZS",     # industry (incl. mining), value added (% GDP)
    "va_manufactur":  "NV.IND.MANF.ZS",     # manufacturing, value added (% GDP)
    "va_services":    "NV.SRV.TOTL.ZS",     # services, value added (% GDP)
    "metal_exports":  "TX.VAL.MMTL.ZS.UN",  # ores & metals exports (% merch exports) — copper proxy
    "real_int_rate":  "FR.INR.RINR",        # real interest rate (%) — global financing force
}

# International gravitating forces (the environment E of the Chilean economy)
INTL_SERIES = {
    "china_gdp_growth": ("CHN", "NY.GDP.MKTP.KD.ZG"),  # China growth → copper demand driver
    "us_gdp_growth":    ("USA", "NY.GDP.MKTP.KD.ZG"),  # US growth / Fed context
    "world_gdp_growth": ("WLD", "NY.GDP.MKTP.KD.ZG"),  # global backdrop
}


def fetch(country, indicator):
    """Latest non-null value for a WB indicator. Returns (year, value) or (None, None)."""
    url = f"{WB}/country/{country}/indicator/{indicator}?format=json&mrv=12"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        return (None, None)
    for row in data[1]:                       # newest first → take first non-null
        if row.get("value") is not None:
            return (row.get("date"), row.get("value"))
    return (None, None)


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    raw = {"chile": {}, "international": {}}

    print("Fetching Chile structural series (World Bank, no auth)…", flush=True)
    for key, ind in CHILE_SERIES.items():
        yr, val = fetch("CHL", ind)
        raw["chile"][key] = {"indicator": ind, "year": yr, "value": val}
        print(f"  {key:<16} {ind:<18} {yr}  {val}", flush=True)

    print("\nFetching international gravitating forces…", flush=True)
    for key, (ctry, ind) in INTL_SERIES.items():
        yr, val = fetch(ctry, ind)
        raw["international"][key] = {"country": ctry, "indicator": ind, "year": yr, "value": val}
        print(f"  {key:<18} {ctry} {ind:<18} {yr}  {val}", flush=True)

    with open(os.path.join(CACHE_DIR, "chile_wb_raw.json"), "w") as f:
        json.dump(raw, f, indent=2)

    # ── derive kernel params ──────────────────────────────────────────────────────
    def v(k, d=0.0):
        x = raw["chile"][k]["value"]
        return float(x) if x is not None else d

    ag   = v("va_agriculture") / 100
    man  = v("va_manufactur") / 100
    ind  = v("va_industry") / 100
    serv = v("va_services") / 100
    mining = max(0.01, ind - man)                 # industry minus manufacturing ≈ extractive+
    shares = [mining, ag, man, serv]
    s = sum(shares) or 1.0
    shares = [round(x / s, 4) for x in shares]

    metal_share = v("metal_exports", 50.0)        # Chile ~ 50%+ metals
    params = {
        "sectors": ["mining", "agriculture", "manufacturing", "services"],
        "shares": shares,
        "export_base": [round(metal_share / 50.0, 3), 0.25, 0.30, 0.05],
        "population_m": round(v("population") / 1e6, 1),
        "_meta": {
            "source": "World Bank Open Data (no auth)",
            "gdp_usd_bn": round(v("gdp_usd") / 1e9, 1),
            "inflation_cpi_pct": v("inflation_cpi"),
            "metal_exports_pct": metal_share,
            "intl_forces": {k: raw["international"][k]["value"] for k in raw["international"]},
            "note": "shares = value-added split; mining ≈ industry − manufacturing. "
                    "copper/China is the dominant gravitating force (export_base[mining]).",
        },
    }
    with open(os.path.join(CACHE_DIR, "chile_params.json"), "w") as f:
        json.dump(params, f, indent=2)

    print("\n── kernel params (cache/chile_params.json) ──")
    print(json.dumps(params, indent=2))
    print(f"\nGDP {params['_meta']['gdp_usd_bn']}B USD · pop {params['population_m']}M · "
          f"metals {metal_share}% of exports · CPI {params['_meta']['inflation_cpi_pct']}%")


if __name__ == "__main__":
    sys.exit(main())
