#!/usr/bin/env python3
"""Dump P(E|bin) for all zones with correct bin labeling."""
import json, os, sys

MARKOV_DIR = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/vsf-clima/markov"

ZONE_FILES = {
    "mediterranea": "s1-santiago.json",
    "subpolar": "s1-punta-arenas.json",
    "semiarida": "s1-antofagasta.json",
    "templada-humeda": "s1-valdivia.json",
    "tropical-arida": "s1-iquique.json",
    "humboldt": "s1-huasco.json",
    "pacifico-sur-medio": "s1-concepcion.json",
    "enso-tropical": "s1-galapagos.json",
}

print(f"{'Zone':25s} {'P(E|b1)':>8s} {'P(E|b2)':>8s} {'P(E|b3)':>8s} {'P(E|b4)':>8s} {'P(E|b5)':>8s}  {'alert_t':>8s} {'crit_t':>8s} {'b3<crit?':>9s} {'b4<alert?':>9s}")
print("-" * 100)

for l2_name, fname in ZONE_FILES.items():
    path = os.path.join(MARKOV_DIR, fname)
    with open(path) as f:
        T = json.load(f)["T"]
    k = len(T)

    # P(E|bin) — compute for each bin using correct indexing
    pe = {}
    for bin_id in range(1, k + 1):
        idx = k - bin_id  # bin5→0, bin4→1, bin3→2, bin2→3, bin1→4
        pe[bin_id] = T[idx][k - 1] + T[idx][k - 2]

    # discriminating thresholds
    alert_t = 0.15 if pe[4] < 0.15 <= pe[3] else (pe[4] + pe[3]) / 2.0
    crit_t = (pe[3] + pe[2]) / 2.0

    b3_silent = pe[3] < crit_t
    b4_silent = pe[4] < alert_t

    print(f"{l2_name:25s} {pe[1]:8.4f} {pe[2]:8.4f} {pe[3]:8.4f} {pe[4]:8.4f} {pe[5]:8.4f}  {alert_t:8.4f} {crit_t:8.4f} {'SILENT' if b3_silent else 'ALERTS':>9s} {'SILENT' if b4_silent else 'ALERTS':>9s}")

# Also print the full T matrix for one zone
print("\n\nFull T matrix for subpolar (s1-punta-arenas):")
with open(os.path.join(MARKOV_DIR, "s1-punta-arenas.json")) as f:
    T = json.load(f)["T"]
print("     ", "  ".join(f"{'→b'+str(5-c):>8s}" for c in range(5)))
for i, row in enumerate(T):
    print(f"b{5-i}:  " + "  ".join(f"{v:8.4f}" for v in row))

print("\nFull T matrix for mediterranea (s1-santiago):")
with open(os.path.join(MARKOV_DIR, "s1-santiago.json")) as f:
    T = json.load(f)["T"]
print("     ", "  ".join(f"{'→b'+str(5-c):>8s}" for c in range(5)))
for i, row in enumerate(T):
    print(f"b{5-i}:  " + "  ".join(f"{v:8.4f}" for v in row))
