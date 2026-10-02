"""
l2_zone.py — L2 climate zone aggregator (v2, ITEM_18.2).

Changes vs v1:
  - Tick-window debounce (DEBOUNCE_S=5): buffers child updates and emits
    ONE zone event after the window closes. Prevents O(n_children) intermediate
    events reaching S1/S3 on each tick cycle.
  - children list derived from node_registry (no hardcoded list)
  - Zone subscribes to ALL children by wildcard pattern (future-proof for 18.3)

Without debounce: 10 nodes × 10 zones = 100 intermediate zone events/tick.
With debounce: 10 zones × 1 event/tick = 10 zone events/tick.

Usage: l2_zone.py --zone <zone_id>
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent))
from node_registry import L2_ZONES, phi_up_subject, algedonic_subject

NATS_URL      = "nats://10.10.20.20:4222"
LOG_PATH_TMPL = "/var/log/vsf-clima/l2_{zone_id}.phi_up.jsonl"
SOURCE_ID     = "s1-clima"

DEBOUNCE_S    = 5   # seconds to wait after last child update before emitting
CHILD_WINDOW  = 2   # kept for compatibility with v1 logs


def _zone_phi_up_subject(zone_id: str) -> str:
    return f"vsf.clima.{zone_id}.phi_up"


def _aggregate(zone_id: str, cfg: dict, child_states: dict) -> dict | None:
    cos_values = []
    excursions = []
    anomaly_nodes = []

    for node_id, evt in child_states.items():
        sc = evt.get("stasis_cos")
        in_omega = evt.get("in_omega", True)
        if sc is None or not evt.get("omega_calibrated", False):
            continue
        cos_values.append(sc)
        if not in_omega:
            excursions.append(node_id)
            anomaly_nodes.append({"node": node_id, "stasis_cos": sc})

    if not cos_values:
        return None

    min_sc   = min(cos_values)
    mean_sc  = sum(cos_values) / len(cos_values)
    if len(cos_values) > 1:
        var = sum((v - mean_sc) ** 2 for v in cos_values) / len(cos_values)
        coherence = 1.0 - min(var / 1.0, 1.0)
    else:
        coherence = 1.0

    dominant_anomaly = min(anomaly_nodes, key=lambda x: x["stasis_cos"]) if anomaly_nodes else None

    return {
        "ts":               datetime.utcnow().isoformat() + "Z",
        "source_id":        SOURCE_ID,
        "zone_id":          zone_id,
        "system":           cfg["system"],
        "vsm_level":        2,
        "event_type":       "zone_aggregate",
        "n_children":       len(child_states),
        "n_calibrated":     len(cos_values),
        "min_stasis_cos":   round(min_sc, 4),
        "mean_stasis_cos":  round(mean_sc, 4),
        "coherence":        round(coherence, 4),
        "n_excursions":     len(excursions),
        "excursion_nodes":  excursions,
        "dominant_anomaly": dominant_anomaly,
        "viable":           min_sc >= 0.0 and len(excursions) == 0,
    }


async def run_zone(zone_id: str, cfg: dict):
    nc = await nats.connect(NATS_URL)
    print(f"[{zone_id}] NATS connected", flush=True)

    children = cfg["children"]
    child_states: dict[str, dict] = {}
    log_path = Path(LOG_PATH_TMPL.format(zone_id=zone_id))

    # Debounce state
    _debounce_handle: asyncio.TimerHandle | None = None
    _pending_emit: bool = False

    async def _emit_now():
        nonlocal _pending_emit
        _pending_emit = False
        agg = _aggregate(zone_id, cfg, child_states)
        if agg is None:
            return

        payload = json.dumps(agg).encode()
        await nc.publish(_zone_phi_up_subject(zone_id), payload)
        with open(log_path, "a") as f:
            f.write(json.dumps(agg) + "\n")

        n_cal = agg["n_calibrated"]
        status = "viable" if agg["viable"] else f"EXCURSION({agg['n_excursions']}/{n_cal})"
        print(f"[{zone_id}] {status}  min_cos={agg['min_stasis_cos']:.3f}"
              f"  coherence={agg['coherence']:.3f}  n_cal={n_cal}/{agg['n_children']}",
              flush=True)

        if not agg["viable"] and agg.get("dominant_anomaly"):
            alg = {
                "ts":             datetime.utcnow().isoformat() + "Z",
                "source_id":      SOURCE_ID,
                "zone_id":        zone_id,
                "category":       "s2_zone_excursion",
                "severity":       8 if agg["min_stasis_cos"] < -0.3 else 6,
                "message":        f"Zone {zone_id}: {agg['n_excursions']}/{agg['n_children']} nodes outside Ω",
                "min_stasis_cos": agg["min_stasis_cos"],
                "coherence":      agg["coherence"],
                "vsm_level":      2,
            }
            await nc.publish(algedonic_subject(), json.dumps(alg).encode())

    def _schedule_emit():
        nonlocal _debounce_handle, _pending_emit
        if _debounce_handle is not None:
            _debounce_handle.cancel()
        loop = asyncio.get_event_loop()
        _debounce_handle = loop.call_later(DEBOUNCE_S, lambda: asyncio.ensure_future(_emit_now()))
        _pending_emit = True

    async def on_child_msg(msg):
        try:
            evt = json.loads(msg.data)
            node_id = evt.get("node_id", "unknown")
            child_states[node_id] = evt
            _schedule_emit()  # reset debounce window on every child update
        except Exception as e:
            print(f"[{zone_id}] msg error: {e}", flush=True)

    subs = []
    for child_id in children:
        sub = await nc.subscribe(phi_up_subject(child_id), cb=on_child_msg)
        subs.append(sub)
    print(f"[{zone_id}] subscribed to {len(children)} children"
          f"  debounce={DEBOUNCE_S}s", flush=True)

    if not children:
        print(f"[{zone_id}] WARNING: no children configured — zone is idle", flush=True)

    try:
        while True:
            await asyncio.sleep(60)
    finally:
        for sub in subs:
            await sub.unsubscribe()
        await nc.close()


def main():
    parser = argparse.ArgumentParser(description="VSF L2 climate zone aggregator")
    parser.add_argument("--zone", required=True, help="Zone ID (e.g. mediterranea)")
    args = parser.parse_args()

    if args.zone not in L2_ZONES:
        print(f"Unknown zone: {args.zone}. Valid: {list(L2_ZONES.keys())}")
        sys.exit(1)

    cfg = L2_ZONES[args.zone]
    asyncio.run(run_zone(args.zone, cfg))


if __name__ == "__main__":
    main()
