#!/usr/bin/env python3
"""
s2_contract_test.py — ITEM_18.3: S2 inter-domain contract verification.

Injects synthetic zone φ↑ events for both continental and marino domains,
then verifies that L0 carries global_stasis_cos + global_viability in
comparable, normalized units (the S2 inter-domain contract).

Hypothesis H_S2_CONTRACT:
  CONFIRMED if:
    - L1 events carry stasis_cos_sys, stasis_cos_min, viability_ratio
    - L0 event carries global_stasis_cos, global_viability
    - global_stasis_cos is the cross-domain mean (numeric, comparable)
    - Asymmetric excursion (continental stressed, marino quiescent) produces
      global_stasis_cos between the two domain values

Run on LXC 112:
  python3 /usr/local/bin/s2_contract_test.py
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

import nats

NATS_URL = "nats://10.10.20.20:4222"

# Inject at L2 level — l1_system.py subscribes to vsf.clima.{zone_id}.phi_up
CONTINENTAL_ZONES = ["tropical-arida", "semiarida", "mediterranea",
                     "templada-humeda", "subpolar"]
MARINO_ZONES      = ["humboldt", "enso-tropical", "pacifico-sur-medio"]

L1_SUBJECTS = {
    "continental": "vsf.clima.continental.phi_up",
    "marino":      "vsf.clima.marino.phi_up",
}
L0_SUBJECT = "vsf.clima.l0.phi_up"

WAIT_S = 15   # > debounce (5s) + L1 + L0 propagation


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zone_event(zone_id: str, system: str, mean_cos: float, min_cos: float,
                n_exc: int, n_children: int) -> bytes:
    viable = min_cos >= 0.0 and n_exc == 0
    return json.dumps({
        "ts":               _ts(),
        "source_id":        "s1-clima",
        "zone_id":          zone_id,
        "system":           system,
        "vsm_level":        2,
        "event_type":       "zone_aggregate",
        "n_children":       n_children,
        "n_calibrated":     n_children,
        "min_stasis_cos":   min_cos,
        "mean_stasis_cos":  mean_cos,
        "coherence":        0.95,
        "n_excursions":     n_exc,
        "excursion_nodes":  [],
        "viable":           viable,
        "_injected":        True,
    }).encode()


async def run():
    nc = await nats.connect(NATS_URL)
    print(f"[s2-contract] NATS connected", flush=True)

    l1_events: dict[str, list] = {"continental": [], "marino": []}
    l0_events: list = []

    async def on_l1_cont(msg):
        evt = json.loads(msg.data)
        l1_events["continental"].append(evt)
        print(f"[s2-contract] ← L1 continental"
              f"  stasis_sys={evt.get('stasis_cos_sys')}  viab={evt.get('viability_ratio')}"
              f"  regime={evt.get('regime')}", flush=True)

    async def on_l1_mar(msg):
        evt = json.loads(msg.data)
        l1_events["marino"].append(evt)
        print(f"[s2-contract] ← L1 marino"
              f"  stasis_sys={evt.get('stasis_cos_sys')}  viab={evt.get('viability_ratio')}"
              f"  regime={evt.get('regime')}", flush=True)

    async def on_l0(msg):
        evt = json.loads(msg.data)
        l0_events.append(evt)
        print(f"[s2-contract] ← L0"
              f"  global_stasis={evt.get('global_stasis_cos')}"
              f"  global_viab={evt.get('global_viability')}"
              f"  regime={evt.get('global_regime')}", flush=True)

    await nc.subscribe(L1_SUBJECTS["continental"], cb=on_l1_cont)
    await nc.subscribe(L1_SUBJECTS["marino"],      cb=on_l1_mar)
    await nc.subscribe(L0_SUBJECT,                 cb=on_l0)
    print("[s2-contract] waiting 10s for L1/L0 to stabilize...", flush=True)
    await asyncio.sleep(10)

    # ── SCENARIO A: asymmetric stress ─────────────────────────────────────────
    # Continental: 3/5 zones in excursion (stressed)
    # Marino: all quiescent
    print("\n── SCENARIO A: continental stressed, marino quiescent ───────────────", flush=True)
    l1_events["continental"].clear()
    l1_events["marino"].clear()
    l0_events.clear()

    # Continental zones: subpolar + templada_humeda + mediterranea stressed
    cont_configs = [
        ("tropical-arida", 0.85, 0.72,  0, 10),
        ("semiarida",       0.80, 0.68,  0, 10),
        ("mediterranea",   -0.35,-0.55,  7, 10),   # stressed
        ("templada-humeda",-0.20,-0.42,  5, 10),   # stressed
        ("subpolar",       -0.40,-0.60,  6, 10),   # stressed
    ]
    for zone_id, mean_cos, min_cos, n_exc, n_ch in cont_configs:
        subject = f"vsf.clima.{zone_id}.phi_up"
        await nc.publish(subject, _zone_event(zone_id, "continental", mean_cos, min_cos, n_exc, n_ch))
        await asyncio.sleep(0.05)

    # Marino zones: all quiescent
    mar_configs = [
        ("humboldt",           0.88, 0.75, 0, 10),
        ("enso-tropical",      0.82, 0.70, 0, 10),
        ("pacifico-sur-medio", 0.79, 0.65, 0, 10),
    ]
    for zone_id, mean_cos, min_cos, n_exc, n_ch in mar_configs:
        subject = f"vsf.clima.{zone_id}.phi_up"
        await nc.publish(subject, _zone_event(zone_id, "marino", mean_cos, min_cos, n_exc, n_ch))
        await asyncio.sleep(0.05)

    print(f"[s2-contract] all zones injected — waiting {WAIT_S}s...", flush=True)
    await asyncio.sleep(WAIT_S)

    # ── Evaluate ──────────────────────────────────────────────────────────────
    last_l1_cont = l1_events["continental"][-1] if l1_events["continental"] else {}
    last_l1_mar  = l1_events["marino"][-1]      if l1_events["marino"]      else {}
    last_l0      = l0_events[-1]                 if l0_events               else {}

    # Expected: continental_stasis_sys ≈ mean(-0.35, -0.20, -0.40, 0.85, 0.80) = 0.14
    # marino_stasis_sys ≈ mean(0.88, 0.82, 0.79) = 0.83
    # global_stasis_cos = mean(0.14, 0.83) = ~0.49

    cont_stasis = last_l1_cont.get("stasis_cos_sys")
    mar_stasis  = last_l1_mar.get("stasis_cos_sys")
    cont_viab   = last_l1_cont.get("viability_ratio")
    mar_viab    = last_l1_mar.get("viability_ratio")
    global_stasis = last_l0.get("global_stasis_cos")
    global_viab   = last_l0.get("global_viability")

    print("\n═══════════════════════════════════════════════════════════════════════", flush=True)
    print("ITEM_18.3 — S2 INTER-DOMAIN CONTRACT TEST RESULTS", flush=True)
    print("═══════════════════════════════════════════════════════════════════════", flush=True)
    print(f"\n  Continental (stressed):", flush=True)
    print(f"    stasis_cos_sys  = {cont_stasis}", flush=True)
    print(f"    viability_ratio = {cont_viab}", flush=True)
    print(f"    regime          = {last_l1_cont.get('regime')}", flush=True)
    print(f"\n  Marino (quiescent):", flush=True)
    print(f"    stasis_cos_sys  = {mar_stasis}", flush=True)
    print(f"    viability_ratio = {mar_viab}", flush=True)
    print(f"    regime          = {last_l1_mar.get('regime')}", flush=True)
    print(f"\n  L0 cross-domain aggregate:", flush=True)
    print(f"    global_stasis_cos = {global_stasis}", flush=True)
    print(f"    global_viability  = {global_viab}", flush=True)
    print(f"    global_regime     = {last_l0.get('global_regime')}", flush=True)

    # Hypothesis checks
    h1 = cont_stasis is not None and mar_stasis is not None  # both L1s carry stasis_cos_sys
    h2 = cont_viab is not None and mar_viab is not None      # both L1s carry viability_ratio
    h3 = global_stasis is not None                           # L0 carries global_stasis_cos
    h4 = global_viab is not None                             # L0 carries global_viability

    # H5: global is between the two domain values (asymmetric stress → intermediate global)
    if h1 and h3:
        lo = min(cont_stasis, mar_stasis)
        hi = max(cont_stasis, mar_stasis)
        h5 = lo <= global_stasis <= hi
    else:
        h5 = False

    # H6: stressed domain has lower viability than quiescent
    h6 = (cont_viab is not None and mar_viab is not None and cont_viab < mar_viab)

    print(f"\n  ── Hypothesis H_S2_CONTRACT ──────────────────────────────────────", flush=True)
    print(f"  H1 — L1 emits stasis_cos_sys (both domains): {'CONFIRMED ✓' if h1 else 'NULL ✗'}", flush=True)
    print(f"  H2 — L1 emits viability_ratio (both domains): {'CONFIRMED ✓' if h2 else 'NULL ✗'}", flush=True)
    print(f"  H3 — L0 emits global_stasis_cos: {'CONFIRMED ✓' if h3 else 'NULL ✗'}", flush=True)
    print(f"  H4 — L0 emits global_viability: {'CONFIRMED ✓' if h4 else 'NULL ✗'}", flush=True)
    print(f"  H5 — global_stasis_cos between domains ({lo:.3f}≤{global_stasis}≤{hi:.3f}): "
          f"{'CONFIRMED ✓' if h5 else 'NULL ✗'}", flush=True)
    print(f"  H6 — stressed domain viability < quiescent ({cont_viab}<{mar_viab}): "
          f"{'CONFIRMED ✓' if h6 else 'NULL ✗'}", flush=True)

    all_ok = h1 and h2 and h3 and h4 and h5 and h6
    print(f"\n  {'H_S2_CONTRACT: CONFIRMED ✓' if all_ok else 'H_S2_CONTRACT: PARTIAL / NULL'}", flush=True)
    print("═══════════════════════════════════════════════════════════════════════", flush=True)

    await nc.close()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
