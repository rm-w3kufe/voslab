#!/usr/bin/env python3
"""
vsf_l3_l2_aggregator.py — Aggregate L3 station projections into L2 zones.

Reads vsf-s4-markov-bridge's raw output (s4_markov_projection.json, 20 L3 stations
with current_sc each), groups by L2 zone using node_registry.py's canonical 8-zone
mapping (embedded here for zero cross-LXC dependency), computes the per-zone mean
current_sc, and writes the nucleus_projection_contract format to a separate file.

Design decision: simple mean. Rationale: absent a weighted scheme justified by the
clima domain, equal-weight mean is the least surprising default — it treats each
L3 station as an equally representative sample of its zone's state. A weighted
scheme (e.g. by station area, population, or historical variance) can be added
later without changing the output contract, as long as the zone keys and
current_sc range are preserved.

nucleus_projection_contract format (nucleus_realdata_wiring.spec.vsm):
  {ts: RFC3339, zones: [{name: string, current_sc: f64}, ...]}

Usage:
  python3 vsf_l3_l2_aggregator.py [--input PATH] [--output PATH]

Defaults:
  --input:  /var/lib/vsf/vsf_nucleus/s4_markov_projection.json
  --output: /var/lib/vsf/vsf_nucleus/s4_markov_l2_projection.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# ── Canonical L2→L3 mapping (embedded from climatica/node_registry.py v2) ──
# Single source of truth: 8 L2 zones, each with its child L3 station IDs.
# Last synced: 2026-07-30 from /opt/vsf-clima/src/node_registry.py (87 L3 nodes).
# If node_registry.py changes the zone/station topology, update this dict.
L2_ZONE_CHILDREN: dict[str, list[str]] = {
    "tropical-arida": [
        "s1-arica", "s1-antofagasta", "s1-iquique", "s1-tocopilla",
        "s1-calama", "s1-taltal", "s1-copiapo", "s1-huasco",
        "s1-diego-almagro", "s1-chanaral",
    ],
    "semiarida": [
        "s1-la-serena", "s1-ovalle", "s1-coquimbo", "s1-illapel",
        "s1-vicuna", "s1-combarbala", "s1-salamanca", "s1-los-vilos",
        "s1-petorca", "s1-ligua", "s1-pichidangui",
    ],
    "mediterranea": [
        "s1-santiago", "s1-concepcion", "s1-rancagua", "s1-san-fernando",
        "s1-curico", "s1-talca", "s1-linares", "s1-chillan",
        "s1-los-angeles", "s1-temuco", "s1-domingo", "s1-nacimiento",
        "s1-padre-las-casas",
    ],
    "templada-humeda": [
        "s1-valdivia", "s1-puerto-montt", "s1-osorno", "s1-la-union",
        "s1-castro", "s1-ancud", "s1-rio-negro", "s1-maullin",
        "s1-panguipulli", "s1-villarrica", "s1-lago-ranco", "s1-pucon",
    ],
    "subpolar": [
        "s1-coyhaique", "s1-punta-arenas", "s1-cochrane", "s1-chile-chico",
        "s1-puerto-aysen", "s1-villa-ohiggins", "s1-puerto-natales",
        "s1-porvenir", "s1-tortel", "s1-puerto-williams", "s1-magallanes",
    ],
    "humboldt": [
        "s1-juan-fernandez", "s1-hum-22s-73w", "s1-hum-25s-74w",
        "s1-hum-28s-73w", "s1-hum-31s-74w", "s1-hum-35s-75w",
        "s1-hum-38s-74w", "s1-hum-40s-76w", "s1-hum-43s-77w",
        "s1-hum-18s-72w",
    ],
    "enso-tropical": [
        "s1-easter-island", "s1-galapagos", "s1-enso-0s-100w",
        "s1-enso-2s-100w", "s1-enso-5s-100w", "s1-enso-0s-120w",
        "s1-enso-2s-120w", "s1-enso-5s-120w", "s1-enso-0s-140w",
        "s1-enso-10s-110w",
    ],
    "pacifico-sur-medio": [
        "s1-pso-25s-90w", "s1-pso-30s-90w", "s1-pso-30s-100w",
        "s1-pso-35s-95w", "s1-pso-35s-105w", "s1-pso-40s-95w",
        "s1-pso-40s-110w", "s1-pso-43s-90w", "s1-pso-45s-105w",
        "s1-pso-20s-100w",
    ],
}


def aggregate(raw_path: str, output_path: str) -> dict:
    """Read raw L3 projections, aggregate by L2 zone (mean current_sc), write output."""
    if not os.path.exists(raw_path):
        print(f"[l3-l2-aggregator] ERROR: raw projection not found: {raw_path}", file=sys.stderr)
        sys.exit(1)

    with open(raw_path) as f:
        raw = json.load(f)

    ts = raw.get("ts", datetime.now(timezone.utc).isoformat())
    projections = raw.get("projections", {})
    if not projections:
        print(f"[l3-l2-aggregator] ERROR: empty projections object in {raw_path}", file=sys.stderr)
        sys.exit(1)

    found_stations = set(projections.keys())
    zones = []

    for zone_name, children in L2_ZONE_CHILDREN.items():
        # Find which child stations have data in this cycle
        present = [c for c in children if c in projections]
        if not present:
            print(f"[l3-l2-aggregator] WARNING: zone '{zone_name}' has 0/{len(children)} stations with data — skipping", file=sys.stderr)
            continue

        # Simple mean of current_sc across present stations
        values = [projections[s]["current_sc"] for s in present]
        mean_sc = sum(values) / len(values)
        n_present = len(present)
        n_total = len(children)
        zones.append({
            "name": zone_name,
            "current_sc": round(mean_sc, 4),
            "_stations_present": n_present,
            "_stations_total": n_total,
        })

        if n_present < n_total:
            missing = [c for c in children if c not in projections]
            print(f"[l3-l2-aggregator] WARNING: zone '{zone_name}': {n_present}/{n_total} stations — missing: {missing}")

    output = {
        "ts": ts,
        "zones": zones,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    n_zones = len(zones)
    print(f"[l3-l2-aggregator] wrote {n_zones}/8 L2 zones to {output_path}")
    for z in zones:
        print(f"  {z['name']:25s}  current_sc={z['current_sc']:+.4f}  ({z['_stations_present']}/{z['_stations_total']} stations)")

    return output


def main():
    parser = argparse.ArgumentParser(description="Aggregate L3 station projections into L2 zones")
    parser.add_argument("--input", default="/var/lib/vsf/vsf_nucleus/s4_markov_projection.json",
                        help="Path to raw L3 projection JSON (default: %(default)s)")
    parser.add_argument("--output", default="/var/lib/vsf/vsf_nucleus/s4_markov_l2_projection.json",
                        help="Path for aggregated L2 projection JSON (default: %(default)s)")
    parser.add_argument("--output-host", default=None,
                        help="Optional second output path (e.g. bind-mount to host)")
    args = parser.parse_args()
    aggregate(args.input, args.output)
    if args.output_host:
        aggregate(args.input, args.output_host)


if __name__ == "__main__":
    main()
