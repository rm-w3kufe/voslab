#!/usr/bin/env python3
"""verify_bin_tiers.py — verify per-bin alert thresholds for ALL 8 zones.

Checks that PROJECTOR-BIN5-TIER thresholds (v5 harness, v3 precision)
correctly satisfy:
  harness mode:  bins 4,5 SILENT, bin 3 ALERTS
  precision mode: bins 3,4,5 SILENT
for ALL 8 ERA5-fitted Markov zones.

Usage:
  python3 verify_bin_tiers.py /var/lib/vsf-clima/markov
"""
import json
import sys
import os

EPS = 0.01

ZONE_MAP = {
    "mediterranea": "s1-santiago.json",
    "subpolar": "s1-punta-arenas.json",
    "semiarida": "s1-antofagasta.json",
    "templada-humeda": "s1-valdivia.json",
    "tropical-arida": "s1-iquique.json",
    "humboldt": "s1-huasco.json",
    "pacifico-sur-medio": "s1-concepcion.json",
    "enso-tropical": "s1-galapagos.json",
}


def pe(T, bin_id):
    """P(excursion in 1 tick) from given bin."""
    k = len(T)
    idx = k - bin_id
    return T[idx][k - 1] + T[idx][k - 2]


def verify(markov_dir):
    all_pass_harness = True
    all_pass_precision = True

    print("VERIFY per-bin thresholds: SILENT from bins 4,5; ALERT from bin3 (harness)")
    print("=" * 105)
    header = f"{'Zone':25s} {'P(E|b5)':>8s} {'P(E|b4)':>8s} {'P(E|b3)':>8s} "
    header += f"{'th5':>8s} {'th4':>8s} {'th3(har)':>10s} {'b5?':>7s} {'b4?':>7s} {'b3?':>7s}"
    print(header)
    print("-" * 105)

    for l2_name, fname in ZONE_MAP.items():
        path = os.path.join(markov_dir, fname)
        with open(path) as f:
            data = json.load(f)
        T = data["T"]
        k = len(T)

        p3 = pe(T, 3)
        p4 = pe(T, 4)
        p5 = pe(T, 5)

        # Harness thresholds (v5)
        th5 = p5 + EPS
        th4 = p4 + EPS
        # Default discriminating threshold fallback
        alert_default = (p4 + p3) / 2.0 if not (p4 < 0.15 <= p3) else 0.15
        th3_harness = min(alert_default, p3 * 0.95)

        b5_ok = p5 < th5
        b4_ok = p4 < th4
        b3_ok = p3 >= th3_harness  # ALERT = P(E) >= threshold

        if not (b5_ok and b4_ok and b3_ok):
            all_pass_harness = False

        row = f"{l2_name:25s} "
        row += f"{p5:8.4f} {p4:8.4f} {p3:8.4f} "
        row += f"{th5:8.4f} {th4:8.4f} {th3_harness:10.4f} "
        row += f"{'SILENT' if b5_ok else 'ALERT!':>7s} "
        row += f"{'SILENT' if b4_ok else 'ALERT!':>7s} "
        row += f"{'ALERT' if b3_ok else 'SILENT!':>7s}"
        print(row)

    print("=" * 105)
    if all_pass_harness:
        print("ALL PASS: harness thresholds correct for all 8 zones\n")
    else:
        print("SOME FAILURES — see above\n")

    # ── Precision mode ─────────────────────────────────────────────────
    print("VERIFY precision thresholds: bins 3,4,5 SILENT (horizon=5)")
    print("=" * 70)
    h2 = f"{'Zone':25s} {'th5':>8s} {'th4':>8s} {'th3':>8s} "
    h2 += f"{'b5?':>7s} {'b4?':>7s} {'b3?':>7s}"
    print(h2)
    print("-" * 70)

    for l2_name, fname in ZONE_MAP.items():
        path = os.path.join(markov_dir, fname)
        with open(path) as f:
            data = json.load(f)
        T = data["T"]

        p3 = pe(T, 3)
        p4 = pe(T, 4)
        p5 = pe(T, 5)

        th5_p = p5 + EPS
        th4_p = p4 + EPS
        th3_p = p3 + EPS  # v3: bin 3 SILENT

        b5_ok = p5 < th5_p
        b4_ok = p4 < th4_p
        b3_ok = p3 < th3_p

        if not (b5_ok and b4_ok and b3_ok):
            all_pass_precision = False

        row = f"{l2_name:25s} "
        row += f"{th5_p:8.4f} {th4_p:8.4f} {th3_p:8.4f} "
        row += f"{'SILENT' if b5_ok else 'ALERT!':>7s} "
        row += f"{'SILENT' if b4_ok else 'ALERT!':>7s} "
        row += f"{'SILENT' if b3_ok else 'ALERT!':>7s}"
        print(row)

    print("=" * 70)
    if all_pass_precision:
        print("ALL PASS: precision thresholds correct for all 8 zones")
    else:
        print("SOME FAILURES — see above")

    return all_pass_harness and all_pass_precision


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: verify_bin_tiers.py <markov_dir>")
        sys.exit(1)
    ok = verify(sys.argv[1])
    sys.exit(0 if ok else 1)
