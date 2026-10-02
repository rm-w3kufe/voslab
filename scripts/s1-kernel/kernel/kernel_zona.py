"""
kernel_zona.py — L2 climate zone aggregator with Ω-zone resolution (ITEM_21.2).

Extends l2_zone.py v2 with:
  - Ω_zona: calibrated zone-level viable range (mean_sc, coherence) per month
  - resolve_or_escalate(): absorbs node excursions that Ω_zona explains
  - r_L2 counter: measures local resolution rate (goal: r_L2 > 0 per §5 invariant)
  - φ↓ channel: receives Ω modulation from L1/L0 and forwards to children

UPDATED: Now uses socratic engine for resolution via kernel_zona.tree.vsm
Predicates: omega_available, within_omega_range

Resolution logic (P3, recursion_design.vsm §3):
  IF mean_sc ∈ [Ω_zona.mean_sc_lo, Ω_zona.mean_sc_hi]:
    → ABSORBED  (zone as a whole within historical range, even if 1 node oscillates)
  ELSE:
    → ESCALATED (zone itself has shifted; algedonic emitted)

Without this: r_L2 = 0 (every node excursion becomes a zone algedonic).
With this: typical single-node oscillation NEVER reaches L1.

Usage: kernel_zona.py --zone <zone_id>
"""
import argparse
import asyncio
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent))
from node_registry import L2_ZONES, phi_up_subject, algedonic_subject

# Add classifier path for socratic engine
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "vsl" / "classifier"))
from vsf_socratic_engine import _create_engine, _ROOT

NATS_URL      = "nats://10.10.20.20:4222"
LOG_PATH_TMPL = "/var/log/vsf-clima/l2_{zone_id}.phi_up.jsonl"
PARAMS_SUBJ_TMPL = "vsf.clima.{zone_id}.params"   # φ↓ from L1/L0
SOURCE_ID     = "s1-clima"

DEBOUNCE_S    = 5
OMEGA_DIR     = Path("/var/lib/vsf-clima/omega")


# ── zone Ω loader ─────────────────────────────────────────────────────────────

def _load_zone_omega(zone_id: str) -> dict | None:
    """Load calibrated zone Ω. Returns omega dict keyed by month str, or None."""
    p = OMEGA_DIR / f"zone_{zone_id}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return d.get("omega")


# ── resolution check (P3) ─────────────────────────────────────────────────────


def _resolve_or_escalate(zone_id: str, agg: dict,
                         omega_zona: dict | None,
                         omega_override: dict | None,
                         counters: dict) -> str:
    """
    Determines if a zone aggregate should be absorbed or escalated.

    Returns:
      'absorbed'  — Ω_zona explains this state; r_L2 increments
      'escalated' — outside Ω_zona; algedonic should fire
      'no_omega'  — no zone Ω available; fall through to legacy path
    
    Uses socratic engine for resolution via kernel_zona.tree.vsm."""
    engine = _create_engine()
    ctx = {
        "omega_zona": omega_zona,
        "omega_override": omega_override,
        "mean_stasis_cos": agg.get("mean_stasis_cos", 0.0),
        "coherence": agg.get("coherence", 1.0),
    }
    tree_text = (_ROOT / ".opencode/plugins/support/trees/kernel_zona.tree.vsm").read_text(encoding="utf-8")
    result = engine.evaluate(tree_text, ctx)
    
    resolution = result.home
    if resolution == "absorbed":
        counters["absorbed"] += 1
    elif resolution == "escalated":
        counters["escalated"] += 1
    else:
        counters["no_omega"] += 1
    return resolution


# ── aggregation (unchanged from l2_zone v2) ───────────────────────────────────

def _aggregate(zone_id: str, cfg: dict, child_states: dict) -> dict | None:
    cos_values = []
    excursions = []
    anomaly_nodes = []

    for node_id, evt in child_states.items():
        sc        = evt.get("stasis_cos")
        in_omega  = evt.get("in_omega", True)
        if sc is None or not evt.get("omega_calibrated", False):
            continue
        cos_values.append(sc)
        if not in_omega:
            excursions.append(node_id)
            anomaly_nodes.append({"node": node_id, "stasis_cos": sc})

    if not cos_values:
        return None

    min_sc  = min(cos_values)
    mean_sc = sum(cos_values) / len(cos_values)
    if len(cos_values) > 1:
        var = sum((v - mean_sc) ** 2 for v in cos_values) / len(cos_values)
        coherence = 1.0 - min(var / 1.0, 1.0)
    else:
        coherence = 1.0

    dominant_anomaly = (min(anomaly_nodes, key=lambda x: x["stasis_cos"])
                        if anomaly_nodes else None)

    return {
        "ts":               datetime.now(timezone.utc).isoformat(),
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


# ── zone runner ───────────────────────────────────────────────────────────────

async def run_zone(zone_id: str, cfg: dict):
    omega_zona     = _load_zone_omega(zone_id)
    omega_override = None   # populated by φ↓ params messages

    if omega_zona:
        print(f"[{zone_id}] Ω_zona loaded (12 months)", flush=True)
    else:
        print(f"[{zone_id}] WARNING: no zone Ω — resolution disabled (r_L2=0)", flush=True)

    counters = {"absorbed": 0, "escalated": 0, "no_omega": 0}

    nc = await nats.connect(NATS_URL)
    print(f"[{zone_id}] NATS connected", flush=True)

    children       = cfg["children"]
    child_states   = {}
    log_path       = Path(LOG_PATH_TMPL.format(zone_id=zone_id))
    _debounce_handle: asyncio.TimerHandle | None = None

    async def _emit_now():
        agg = _aggregate(zone_id, cfg, child_states)
        if agg is None:
            return

        # ── ITEM_21.2 resolution layer ───────────────────────────────────────
        resolution = _resolve_or_escalate(
            zone_id, agg, omega_zona, omega_override, counters)

        total  = counters["absorbed"] + counters["escalated"] + counters["no_omega"]
        r_l2   = counters["absorbed"] / total if total > 0 else 0.0

        # Enrich event with resolution metadata
        agg["zone_resolution"] = {
            "status":   resolution,
            "absorbed": counters["absorbed"],
            "escalated": counters["escalated"],
            "r_L2":     round(r_l2, 3),
        }

        # Publish φ↑ always (L1 uses the event regardless)
        payload = json.dumps(agg).encode()
        zone_subj = f"vsf.clima.{zone_id}.phi_up"
        await nc.publish(zone_subj, payload)

        with open(log_path, "a") as f:
            f.write(json.dumps(agg) + "\n")

        n_cal   = agg["n_calibrated"]
        status  = "viable" if agg["viable"] else f"EXCURSION({agg['n_excursions']}/{n_cal})"
        print(f"[{zone_id}] {status}  mean_cos={agg['mean_stasis_cos']:.3f}"
              f"  coherence={agg['coherence']:.3f}"
              f"  resolution={resolution}  r_L2={r_l2:.2f}",
              flush=True)

        # ── Algedonic only if ESCALATED (not absorbed) ──────────────────────
        if resolution in ("escalated", "no_omega") and not agg["viable"]:
            alg = {
                "ts":             datetime.now(timezone.utc).isoformat(),
                "source_id":      SOURCE_ID,
                "zone_id":        zone_id,
                "category":       "s2_zone_excursion",
                "severity":       8 if agg["min_stasis_cos"] < -0.3 else 6,
                "message":        (f"Zone {zone_id}: {agg['n_excursions']}/{n_cal} "
                                   f"nodes outside Ω (zone-level: {resolution})"),
                "min_stasis_cos": agg["min_stasis_cos"],
                "mean_stasis_cos": agg["mean_stasis_cos"],
                "coherence":      agg["coherence"],
                "resolution":     resolution,
                "vsm_level":      2,
            }
            await nc.publish(algedonic_subject(), json.dumps(alg).encode())

    def _schedule_emit():
        nonlocal _debounce_handle
        if _debounce_handle is not None:
            _debounce_handle.cancel()
        loop = asyncio.get_event_loop()
        _debounce_handle = loop.call_later(
            DEBOUNCE_S, lambda: asyncio.ensure_future(_emit_now()))

    async def on_child_msg(msg):
        try:
            evt     = json.loads(msg.data)
            node_id = evt.get("node_id", "unknown")
            child_states[node_id] = evt
            _schedule_emit()
        except Exception as e:
            print(f"[{zone_id}] msg error: {e}", flush=True)

    # ── φ↓ params channel (Ω modulation from L1/L0) ──────────────────────────
    async def on_params(msg):
        nonlocal omega_override
        try:
            params = json.loads(msg.data)
            mod    = params.get("omega_modulation")
            if mod:
                omega_override = mod
                print(f"[{zone_id}] φ↓ Ω override: {mod}  "
                      f"reason={params.get('reason')}", flush=True)
        except Exception as e:
            print(f"[{zone_id}] params error: {e}", flush=True)

    await nc.subscribe(
        PARAMS_SUBJ_TMPL.format(zone_id=zone_id), cb=on_params)

    subs = []
    for child_id in children:
        sub = await nc.subscribe(phi_up_subject(child_id), cb=on_child_msg)
        subs.append(sub)

    print(f"[{zone_id}] subscribed to {len(children)} children"
          f"  debounce={DEBOUNCE_S}s"
          f"  omega={'loaded' if omega_zona else 'MISSING'}", flush=True)

    if not children:
        print(f"[{zone_id}] WARNING: no children configured — zone idle", flush=True)

    try:
        while True:
            await asyncio.sleep(60)
    finally:
        for sub in subs:
            await sub.unsubscribe()
        await nc.close()


def main():
    parser = argparse.ArgumentParser(description="VSF L2 climate zone kernel (ITEM_21.2)")
    parser.add_argument("--zone", required=True, help="Zone ID")
    args = parser.parse_args()

    if args.zone not in L2_ZONES:
        print(f"Unknown zone: {args.zone}. Valid: {list(L2_ZONES.keys())}")
        sys.exit(1)

    asyncio.run(run_zone(args.zone, L2_ZONES[args.zone]))


if __name__ == "__main__":
    main()
