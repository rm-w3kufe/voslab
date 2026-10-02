#!/opt/vsf-clima/bin/python
"""
l1_system.py — L1 dynamical system aggregator (ITEM_18.3: S2 inter-domain contract).

Changes vs original:
  _detect_regime now returns 3 additional fields (S2 inter-domain contract §φ↑_s2):
    stasis_cos_sys  — mean(zone.mean_stasis_cos): system-level central tendency ∈ [-1,1]
    stasis_cos_min  — min(zone.min_stasis_cos):  worst-case system signal ∈ [-1,1]
    viability_ratio — viable_zones / n_zones ∈ [0,1]

  These allow L0 to compare continental vs. marino in common units, not just
  qualitative regime labels.

Q3 resolved: φ↑ L1→L0 carries:
  {regime, propagation_phase, mechanism_confidence}  ← original
  + {stasis_cos_sys, stasis_cos_min, viability_ratio} ← 18.3 S2 contract

Usage: l1_system.py --system <system_id>
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent))
from node_registry import L1_SYSTEMS, L2_ZONES, algedonic_subject

NATS_URL      = "nats://10.10.20.20:4222"
LOG_PATH_TMPL = "/var/log/vsf-clima/l1_{system_id}.phi_up.jsonl"
SOURCE_ID     = "s1-clima"


def _l2_subject(zone_id: str) -> str:
    return f"vsf.clima.{zone_id}.phi_up"


def _l1_subject(system_id: str) -> str:
    return f"vsf.clima.{system_id}.phi_up"


def _detect_regime(system_id: str, zone_states: dict) -> dict:
    if not zone_states:
        return {
            "regime": "quiescent", "confidence": 0.0, "n_zones": 0,
            "n_excursion_zones": 0, "system_coherence": 1.0,
            "mean_min_stasis": 1.0,
            # S2 contract fields
            "stasis_cos_sys": 1.0, "stasis_cos_min": 1.0, "viability_ratio": 1.0,
        }

    viable_count    = sum(1 for z in zone_states.values() if z.get("viable", True))
    excursion_count = len(zone_states) - viable_count
    n_zones         = len(zone_states)

    # ── S2 contract: numeric aggregates (domain-agnostic) ─────────────────────
    min_cos_vals  = [z["min_stasis_cos"]  for z in zone_states.values()
                     if z.get("min_stasis_cos")  is not None]
    mean_cos_vals = [z["mean_stasis_cos"] for z in zone_states.values()
                     if z.get("mean_stasis_cos") is not None]

    stasis_cos_min  = min(min_cos_vals)  if min_cos_vals  else 1.0  # worst case
    stasis_cos_sys  = (sum(mean_cos_vals) / len(mean_cos_vals)) if mean_cos_vals else 1.0
    mean_min_cos    = (sum(min_cos_vals)  / len(min_cos_vals))  if min_cos_vals  else 1.0
    viability_ratio = viable_count / n_zones if n_zones > 0 else 1.0

    coherence_vals   = [z.get("coherence", 1.0) for z in zone_states.values()]
    system_coherence = sum(coherence_vals) / len(coherence_vals) if coherence_vals else 1.0

    # ── Regime classification (unchanged from original) ────────────────────────
    if excursion_count == 0:
        regime     = "quiescent"
        confidence = 0.8 + 0.2 * system_coherence
    elif system_id == "continental":
        cfg = L1_SYSTEMS[system_id]
        children_ordered = cfg["children"]
        excursion_zones = [z for z, s in zone_states.items() if not s.get("viable", True)]
        southern_half = set(children_ordered[:len(children_ordered) // 2])
        southern_hit  = sum(1 for z in excursion_zones if z in southern_half)
        is_frontal = southern_hit > 0 and excursion_count <= 3
        is_enso    = excursion_count > 3 and system_coherence < 0.3

        if is_frontal and not is_enso:
            regime     = "frontal"
            confidence = 0.7 + 0.3 * (southern_hit / max(excursion_count, 1))
        elif is_enso:
            regime     = "enso"
            confidence = 0.5 + 0.5 * (1 - system_coherence)
        elif excursion_count > 0:
            regime     = "mixed"
            confidence = 0.4
        else:
            regime     = "quiescent"
            confidence = 0.9
    else:
        enso_core = {"enso-tropical"}
        enso_excursion = any(z in enso_core for z in zone_states
                             if not zone_states[z].get("viable", True))
        regime     = "enso" if enso_excursion else ("mixed" if excursion_count > 0 else "quiescent")
        confidence = 0.8 if enso_excursion else 0.5

    return {
        "regime":            regime,
        "confidence":        round(confidence, 3),
        "n_zones":           n_zones,
        "n_excursion_zones": excursion_count,
        "system_coherence":  round(system_coherence, 4),
        "mean_min_stasis":   round(mean_min_cos, 4),
        # S2 inter-domain contract (ITEM_18.3)
        "stasis_cos_sys":    round(stasis_cos_sys, 4),
        "stasis_cos_min":    round(stasis_cos_min, 4),
        "viability_ratio":   round(viability_ratio, 4),
    }


async def run_system(system_id: str, cfg: dict):
    nc = await nats.connect(NATS_URL)
    print(f"[{system_id}] NATS connected", flush=True)

    zone_states: dict[str, dict] = {}
    log_path = Path(LOG_PATH_TMPL.format(system_id=system_id))

    async def on_zone_msg(msg):
        try:
            evt = json.loads(msg.data)
            zone_id = evt.get("zone_id", "unknown")
            zone_states[zone_id] = evt

            regime_info = _detect_regime(system_id, zone_states)

            l1_evt = {
                "ts":           datetime.utcnow().isoformat() + "Z",
                "source_id":    SOURCE_ID,
                "system_id":    system_id,
                "vsm_level":    1,
                "event_type":   "system_aggregate",
                **regime_info,
                "zone_snapshot": {z: {"viable": s.get("viable"),
                                      "min_cos":  s.get("min_stasis_cos"),
                                      "mean_cos": s.get("mean_stasis_cos")}
                                  for z, s in zone_states.items()},
            }

            payload = json.dumps(l1_evt).encode()
            await nc.publish(_l1_subject(system_id), payload)
            with open(log_path, "a") as f:
                f.write(json.dumps(l1_evt) + "\n")

            print(f"[{system_id}] regime={regime_info['regime']}"
                  f"  stasis_sys={regime_info['stasis_cos_sys']:.3f}"
                  f"  viab={regime_info['viability_ratio']:.2f}"
                  f"  excl={regime_info['n_excursion_zones']}/{regime_info['n_zones']}",
                  flush=True)

            if regime_info["regime"] != "quiescent":
                alg = {
                    "ts":         datetime.utcnow().isoformat() + "Z",
                    "source_id":  SOURCE_ID,
                    "system_id":  system_id,
                    "category":   "s1_regime_change",
                    "severity":   7 if regime_info["regime"] == "frontal" else 8,
                    "message":    f"System {system_id}: {regime_info['regime']} regime "
                                  f"(stasis_sys={regime_info['stasis_cos_sys']:.3f},"
                                  f" viab={regime_info['viability_ratio']:.2f})",
                    "regime":         regime_info["regime"],
                    "stasis_cos_sys": regime_info["stasis_cos_sys"],
                    "viability_ratio":regime_info["viability_ratio"],
                    "vsm_level":  1,
                }
                await nc.publish(algedonic_subject(), json.dumps(alg).encode())
        except Exception as e:
            print(f"[{system_id}] msg error: {e}", flush=True)

    subs = []
    for zone_id in cfg["children"]:
        sub = await nc.subscribe(_l2_subject(zone_id), cb=on_zone_msg)
        subs.append(sub)
    print(f"[{system_id}] subscribed to {len(cfg['children'])} zones", flush=True)

    try:
        while True:
            await asyncio.sleep(60)
    finally:
        for sub in subs:
            await sub.unsubscribe()
        await nc.close()


def main():
    parser = argparse.ArgumentParser(description="VSF L1 system aggregator")
    parser.add_argument("--system", required=True, help="System ID (continental or marino)")
    args = parser.parse_args()

    if args.system not in L1_SYSTEMS:
        print(f"Unknown system: {args.system}. Valid: {list(L1_SYSTEMS.keys())}")
        sys.exit(1)

    cfg = L1_SYSTEMS[args.system]
    asyncio.run(run_system(args.system, cfg))


if __name__ == "__main__":
    main()
