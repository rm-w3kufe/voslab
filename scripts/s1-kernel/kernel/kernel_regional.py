"""
kernel_regional.py — L1 system aggregator with mechanism Ω + resolution (ITEM_21.2).

Extends l1_system.py (18.3) with:
  - Ω_mecanismo: matched filter — absorbs events that match a KNOWN mechanism
    (frontal / enso / quiescent) with sufficient confidence
  - resolve_or_escalate_l1(): r_L1 counter; algedonic only for 'mixed' or uncertain
  - φ↓ channel: receives L0 Ω modulation, forwards to affected L2 zones

UPDATED: Now uses socratic engine for resolution via kernel_regional.tree.vsm
Predicates: regime_known, confidence_sufficient, regime_quiescent

Resolution logic (P3, recursion_design.vsm §2.L1_mechanism):
  KNOWN mechanism (regime ∈ {frontal,enso,quiescent}, confidence ≥ CONF_MIN):
    → ABSORBED  (a named frontal or ENSO event is NOT anomalous; it's expected)
  UNKNOWN / UNCERTAIN (regime='mixed', or confidence < CONF_MIN):
    → ESCALATED (no known signature matches → genuinely novel → algedonic)

Without this: r_L1 = 0 (every frontal event becomes an algedonic reaching L0).
With this: typical winter fronts in Chile are absorbed in L1; only the
unclassifiable residual reaches L0.

Usage: kernel_regional.py --system <system_id>
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent))
from node_registry import L1_SYSTEMS, L2_ZONES, algedonic_subject

# Add classifier path for socratic engine
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "vsl" / "classifier"))
from vsf_socratic_engine import _create_engine, _ROOT

NATS_URL      = "nats://10.10.20.20:4222"
LOG_PATH_TMPL = "/var/log/vsf-clima/l1_{system_id}.phi_up.jsonl"
SOURCE_ID     = "s1-clima"

# Resolution threshold: confidence below this → "uncertain" → escalate
CONF_MIN = 0.65

# Mechanisms that count as "known and expected" when confidence ≥ CONF_MIN
KNOWN_MECHANISMS = {"frontal", "enso", "quiescent"}


# ── regime detection (unchanged from l1_system 18.3) ─────────────────────────

def _l2_subject(zone_id: str) -> str:
    return f"vsf.clima.{zone_id}.phi_up"

def _l1_subject(system_id: str) -> str:
    return f"vsf.clima.{system_id}.phi_up"

def _params_subject(system_id: str) -> str:
    return f"vsf.clima.{system_id}.params"

def _zone_params_subject(zone_id: str) -> str:
    return f"vsf.clima.{zone_id}.params"


def _detect_regime(system_id: str, zone_states: dict) -> dict:
    if not zone_states:
        return {
            "regime": "quiescent", "confidence": 0.0, "n_zones": 0,
            "n_excursion_zones": 0, "system_coherence": 1.0,
            "mean_min_stasis": 1.0,
            "stasis_cos_sys": 1.0, "stasis_cos_min": 1.0, "viability_ratio": 1.0,
        }

    viable_count    = sum(1 for z in zone_states.values() if z.get("viable", True))
    excursion_count = len(zone_states) - viable_count
    n_zones         = len(zone_states)

    min_cos_vals  = [z["min_stasis_cos"]  for z in zone_states.values()
                     if z.get("min_stasis_cos")  is not None]
    mean_cos_vals = [z["mean_stasis_cos"] for z in zone_states.values()
                     if z.get("mean_stasis_cos") is not None]

    stasis_cos_min  = min(min_cos_vals)  if min_cos_vals  else 1.0
    stasis_cos_sys  = (sum(mean_cos_vals) / len(mean_cos_vals)) if mean_cos_vals else 1.0
    mean_min_cos    = (sum(min_cos_vals)  / len(min_cos_vals))  if min_cos_vals  else 1.0
    viability_ratio = viable_count / n_zones if n_zones > 0 else 1.0

    coherence_vals   = [z.get("coherence", 1.0) for z in zone_states.values()]
    system_coherence = sum(coherence_vals) / len(coherence_vals) if coherence_vals else 1.0

    if excursion_count == 0:
        regime     = "quiescent"
        confidence = 0.8 + 0.2 * system_coherence
    elif system_id == "continental":
        cfg = L1_SYSTEMS[system_id]
        children_ordered = cfg["children"]
        excursion_zones = [z for z, s in zone_states.items() if not s.get("viable", True)]
        # List is N→S; southern zones are the LAST half (where fronts arrive first)
        southern_half = set(children_ordered[len(children_ordered) // 2:])
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
        "stasis_cos_sys":    round(stasis_cos_sys, 4),
        "stasis_cos_min":    round(stasis_cos_min, 4),
        "viability_ratio":   round(viability_ratio, 4),
    }


# ── L1 resolution (Ω_mecanismo matched filter) ────────────────────────────────

def _resolve_l1(regime_info: dict, counters: dict) -> str:
    """
    Returns 'absorbed' | 'escalated'.

    Absorbs if the mechanism is KNOWN and confidence is sufficient.
    A named frontal or ENSO event is expected physics — not anomalous.
    Only 'mixed' (unclassifiable) or low-confidence events escalate.
    
    Uses socratic engine for resolution via kernel_regional.tree.vsm."""
    engine = _create_engine()
    ctx = {"regime_info": regime_info}
    tree_text = (_ROOT / ".opencode/plugins/support/trees/kernel_regional.tree.vsm").read_text(encoding="utf-8")
    result = engine.evaluate(tree_text, ctx)
    
    resolution = result.home
    if resolution == "absorbed":
        counters["absorbed"] += 1
    else:
        counters["escalated"] += 1
    return resolution


# ── φ↓ forwarding: route L0 modulation to relevant zones ─────────────────────

def _relevant_zones(system_id: str, omega_modulation: dict) -> list[str]:
    """
    Determines which L2 zones should receive the φ↓ Ω modulation.
    Currently: all continental zones for mediterranean/semiarida modulation,
    all marino zones for ENSO context.
    """
    cfg = L1_SYSTEMS.get(system_id, {})
    return cfg.get("children", [])


# ── system runner ─────────────────────────────────────────────────────────────

async def run_system(system_id: str, cfg: dict):
    nc = await nats.connect(NATS_URL)
    print(f"[{system_id}] NATS connected", flush=True)

    zone_states = {}
    log_path    = Path(LOG_PATH_TMPL.format(system_id=system_id))
    counters    = {"absorbed": 0, "escalated": 0}

    async def on_zone_msg(msg):
        try:
            evt     = json.loads(msg.data)
            zone_id = evt.get("zone_id", "unknown")
            zone_states[zone_id] = evt

            regime_info = _detect_regime(system_id, zone_states)
            resolution  = _resolve_l1(regime_info, counters)

            total = counters["absorbed"] + counters["escalated"]
            r_l1  = counters["absorbed"] / total if total > 0 else 0.0

            l1_evt = {
                "ts":           datetime.now(timezone.utc).isoformat(),
                "source_id":    SOURCE_ID,
                "system_id":    system_id,
                "vsm_level":    1,
                "event_type":   "system_aggregate",
                **regime_info,
                "system_resolution": {
                    "status":    resolution,
                    "absorbed":  counters["absorbed"],
                    "escalated": counters["escalated"],
                    "r_L1":      round(r_l1, 3),
                },
                "zone_snapshot": {z: {"viable": s.get("viable"),
                                      "min_cos":  s.get("min_stasis_cos"),
                                      "mean_cos": s.get("mean_stasis_cos"),
                                      "r_L2":     s.get("zone_resolution", {}).get("r_L2")}
                                  for z, s in zone_states.items()},
            }

            payload = json.dumps(l1_evt).encode()
            await nc.publish(_l1_subject(system_id), payload)
            with open(log_path, "a") as f:
                f.write(json.dumps(l1_evt) + "\n")

            print(f"[{system_id}] regime={regime_info['regime']}"
                  f"  conf={regime_info['confidence']:.2f}"
                  f"  stasis_sys={regime_info['stasis_cos_sys']:.3f}"
                  f"  viab={regime_info['viability_ratio']:.2f}"
                  f"  resolution={resolution}  r_L1={r_l1:.2f}",
                  flush=True)

            # ── Algedonic ONLY for escalated events ─────────────────────────
            if resolution == "escalated" and regime_info["regime"] != "quiescent":
                alg = {
                    "ts":              datetime.now(timezone.utc).isoformat(),
                    "source_id":       SOURCE_ID,
                    "system_id":       system_id,
                    "category":        "s1_regime_change",
                    "severity":        9 if regime_info["regime"] == "mixed" else 7,
                    "message":         (f"System {system_id}: {regime_info['regime']} regime "
                                        f"(conf={regime_info['confidence']:.2f} < {CONF_MIN} "
                                        f"or unclassified)"),
                    "regime":          regime_info["regime"],
                    "confidence":      regime_info["confidence"],
                    "stasis_cos_sys":  regime_info["stasis_cos_sys"],
                    "viability_ratio": regime_info["viability_ratio"],
                    "resolution":      resolution,
                    "vsm_level":       1,
                }
                await nc.publish(algedonic_subject(), json.dumps(alg).encode())
        except Exception as e:
            print(f"[{system_id}] msg error: {e}", flush=True)

    # ── φ↓ params: L0 sends Ω modulation; L1 forwards to its zones ───────────
    async def on_params(msg):
        try:
            params = json.loads(msg.data)
            mod    = params.get("omega_modulation")
            reason = params.get("reason", "")
            if not mod:
                return

            print(f"[{system_id}] φ↓ received Ω modulation: {mod}  reason={reason}",
                  flush=True)

            # Forward to relevant zones
            fwd = {**params, "forwarded_by": system_id}
            for zone_id in _relevant_zones(system_id, mod):
                await nc.publish(_zone_params_subject(zone_id),
                                 json.dumps(fwd).encode())
                print(f"[{system_id}] → φ↓ forwarded to zone {zone_id}", flush=True)
        except Exception as e:
            print(f"[{system_id}] params error: {e}", flush=True)

    await nc.subscribe(_params_subject(system_id), cb=on_params)

    subs = []
    for zone_id in cfg["children"]:
        sub = await nc.subscribe(_l2_subject(zone_id), cb=on_zone_msg)
        subs.append(sub)
    print(f"[{system_id}] subscribed to {len(cfg['children'])} zones"
          f"  CONF_MIN={CONF_MIN}", flush=True)

    try:
        while True:
            await asyncio.sleep(60)
    finally:
        for sub in subs:
            await sub.unsubscribe()
        await nc.close()


def main():
    parser = argparse.ArgumentParser(
        description="VSF L1 climate system kernel (ITEM_21.2)")
    parser.add_argument("--system", required=True, help="System ID")
    args = parser.parse_args()

    if args.system not in L1_SYSTEMS:
        print(f"Unknown system: {args.system}. Valid: {list(L1_SYSTEMS.keys())}")
        sys.exit(1)

    asyncio.run(run_system(args.system, L1_SYSTEMS[args.system]))


if __name__ == "__main__":
    main()
