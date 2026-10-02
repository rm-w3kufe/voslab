#!/usr/bin/env python3
"""
s2_scale_test.py — ITEM_18.2: S2 variety attenuation at scale (10 nodes/zone).

Verifies that the debounce-patched l2_zone.py correctly batches 10 simultaneous
node excursions into 1 zone event (instead of 10 intermediate events).

Expected result:
  Without debounce: 10 node injections → 10 zone events
  With debounce:    10 node injections → 1 zone event (after 5s window)

Hypothesis H_S201b_SCALE:
  CONFIRMED if n_zone_events == 1 AND n_excursions == N_injected after window

Run on LXC 112:
  python3 /usr/local/bin/s2_scale_test.py
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

import nats

NATS_URL      = "nats://10.10.20.20:4222"
ZONE_ID       = "mediterranea"
ZONE_SUBJECT  = f"vsf.clima.{ZONE_ID}.phi_up"
ALG_SUBJECT   = "vsf.alpha.algedonic"

EXCURSION_COS = -0.40
DEBOUNCE_WAIT = 12   # > debounce window (5s) + headroom

NODES = [
    "s1-santiago", "s1-concepcion", "s1-rancagua", "s1-san-fernando",
    "s1-curico", "s1-talca", "s1-linares", "s1-chillan",
    "s1-los-angeles", "s1-temuco",
]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node_event(node_id: str, stasis_cos: float, in_omega: bool) -> bytes:
    return json.dumps({
        "ts": _ts(), "source_id": "s1-clima", "node_id": node_id,
        "vsm_level": 3, "event_type": "node_tick",
        "stasis_cos": stasis_cos, "in_omega": in_omega,
        "omega_calibrated": True, "_injected": True,
    }).encode()


async def run():
    nc = await nats.connect(NATS_URL)
    print(f"[s2-scale] NATS connected — {len(NODES)} nodes / zone={ZONE_ID}", flush=True)

    zone_events = []
    alg_events  = []

    async def on_zone(msg):
        evt = json.loads(msg.data)
        zone_events.append(evt)
        n_exc = evt.get("n_excursions", 0)
        viable = evt.get("viable", True)
        print(f"[s2-scale] ← ZONE #{len(zone_events)}"
              f"  n_exc={n_exc}  viable={viable}"
              f"  min_cos={evt.get('min_stasis_cos'):.3f}"
              f"  n_cal={evt.get('n_calibrated')}/{evt.get('n_children')}", flush=True)

    async def on_alg(msg):
        evt = json.loads(msg.data)
        if evt.get("zone_id") == ZONE_ID:
            alg_events.append(evt)
            print(f"[s2-scale] ← ALG  sev={evt.get('severity')}"
                  f"  {evt.get('message')}", flush=True)

    sub_zone = await nc.subscribe(ZONE_SUBJECT, cb=on_zone)
    sub_alg  = await nc.subscribe(ALG_SUBJECT,  cb=on_alg)

    # Wait for l2_zone service to (re)connect and subscribe to all children.
    # NATS is fire-and-forget — injecting before l2_zone subscribes loses messages.
    print("[s2-scale] waiting 10s for l2_zone to stabilize...", flush=True)
    await asyncio.sleep(10)

    # ── Inject all 10 nodes into excursion within 1 second ────────────────────
    print(f"\n── Injecting {len(NODES)} excursion events in rapid succession ─────────", flush=True)
    t0 = datetime.now(timezone.utc)
    for i, node in enumerate(NODES):
        cos = EXCURSION_COS - (i * 0.02)  # slight spread
        await nc.publish(f"vsf.clima.{node}.phi_up", _node_event(node, cos, False))
        print(f"[s2-scale] → {node}  cos={cos:.2f}", flush=True)
        await asyncio.sleep(0.05)  # 50ms between injections — well within debounce window

    elapsed_inject = (datetime.now(timezone.utc) - t0).total_seconds()
    print(f"\n[s2-scale] All {len(NODES)} nodes injected in {elapsed_inject:.2f}s", flush=True)
    print(f"[s2-scale] Waiting {DEBOUNCE_WAIT}s for debounce window to close...", flush=True)

    await asyncio.sleep(DEBOUNCE_WAIT)
    n_zone_after = len(zone_events)

    # ── Recovery ──────────────────────────────────────────────────────────────
    print(f"\n── Recovery injection ───────────────────────────────────────────────", flush=True)
    await sub_zone.unsubscribe()
    zone_events_recovery = []

    async def on_zone_rec(msg):
        evt = json.loads(msg.data)
        zone_events_recovery.append(evt)

    sub_rec = await nc.subscribe(ZONE_SUBJECT, cb=on_zone_rec)
    await asyncio.sleep(0.1)

    for node in NODES:
        await nc.publish(f"vsf.clima.{node}.phi_up", _node_event(node, 0.90, True))
        await asyncio.sleep(0.05)

    await asyncio.sleep(DEBOUNCE_WAIT)
    await sub_rec.unsubscribe()

    # ── Results ───────────────────────────────────────────────────────────────
    last_exc = None
    for evt in zone_events:
        if not evt.get("viable", True):
            last_exc = evt

    n_exc_final    = last_exc.get("n_excursions", 0) if last_exc else 0
    alg_fired      = len(alg_events) > 0
    recovery_ok    = any(evt.get("viable", False) for evt in zone_events_recovery)

    print("\n═══════════════════════════════════════════════════════════════════════", flush=True)
    print("ITEM_18.2 — S2 SCALE TEST RESULTS (debounce verification)", flush=True)
    print("═══════════════════════════════════════════════════════════════════════", flush=True)
    print(f"\n  Nodes injected simultaneously:       {len(NODES)}", flush=True)
    print(f"  Zone events emitted (excursion):     {n_zone_after}", flush=True)
    print(f"  Expected with debounce:              1", flush=True)
    print(f"  Expected without debounce:           {len(NODES)}", flush=True)
    print(f"  n_excursions in final zone event:    {n_exc_final}", flush=True)
    print(f"  Algedonic fired:                     {alg_fired}", flush=True)
    print(f"  Recovery → viable:                   {recovery_ok}", flush=True)

    # H_S201b_SCALE: debounce batches N simultaneous inputs → 1 output
    h_debounce   = n_zone_after == 1
    h_aggregated = n_exc_final == len(NODES)
    h_alg        = alg_fired
    h_recovery   = recovery_ok

    print(f"\n  ── Hypothesis H_S201b_SCALE ──────────────────────────────────────", flush=True)
    print(f"  H1 — debounce batching ({len(NODES)} inputs → {n_zone_after} events, expect 1):"
          f" {'CONFIRMED ✓' if h_debounce else 'NULL ✗'}", flush=True)
    print(f"  H2 — all excursions captured (n_exc={n_exc_final}=={len(NODES)}):"
          f" {'CONFIRMED ✓' if h_aggregated else 'NULL ✗'}", flush=True)
    print(f"  H3 — algedonic fired:                    {'CONFIRMED ✓' if h_alg else 'NULL ✗'}", flush=True)
    print(f"  H4 — recovery propagates:                {'CONFIRMED ✓' if h_recovery else 'NULL ✗'}", flush=True)

    all_ok = h_debounce and h_aggregated and h_alg and h_recovery
    print(f"\n  {'H_S201b_SCALE: CONFIRMED ✓' if all_ok else 'H_S201b_SCALE: PARTIAL / NULL'}", flush=True)
    print("═══════════════════════════════════════════════════════════════════════", flush=True)

    await sub_alg.unsubscribe()
    await nc.close()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
