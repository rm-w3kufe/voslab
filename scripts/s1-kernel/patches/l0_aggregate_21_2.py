#!/opt/vsf-clima/bin/python
"""
l0_aggregate.py — L0 total system coordinator.
Subscribes to L1 systems, fetches ONI monthly, emits L0 φ↑.

Q11 resolved: ONI is NOT an S1 — it's an external env_sample into L0.
Q12 resolved: L0 updates monthly (ONI release) + on any L1 regime change.
"""
import asyncio
import json
import sys
import urllib.request
from datetime import datetime, date
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent))
from node_registry import L0_SYSTEM, L1_SYSTEMS, algedonic_subject

NATS_URL           = "nats://10.10.20.20:4222"
LOG_PATH           = Path("/var/log/vsf-clima/l0.phi_up.jsonl")
S4_CONTEXT_LOG     = Path("/var/log/vsf-clima/s4_context.jsonl")
ONI_CACHE          = Path("/var/lib/vsf-clima/state/oni_current.json")
STATE_DIR          = Path("/var/lib/vsf-clima/state")
SOURCE_ID          = "s1-clima"

S4_CONTEXT_SUBJECT = "vsf.clima.s4_context"

# Q11: ONI source — NOAA CPC Oceanic Niño Index
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
ONI_REFRESH_HOURS = 24 * 7  # weekly refresh (ONI is monthly, but check weekly)

# ONI thresholds (per NOAA definition)
EL_NINO_THRESHOLD = +0.5
LA_NINA_THRESHOLD = -0.5


def _fetch_oni() -> dict:
    """Fetch current ONI value from NOAA. Returns {value, season, date, enso_state}."""
    cache = ONI_CACHE
    if cache.exists():
        data = json.loads(cache.read_text())
        # Use cache if < 7 days old
        cached_ts = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        age_hours = (datetime.utcnow() - cached_ts).total_seconds() / 3600
        if age_hours < ONI_REFRESH_HOURS:
            return data

    try:
        with urllib.request.urlopen(ONI_URL, timeout=15) as r:
            text = r.read().decode("ascii", errors="ignore")

        # Parse last non-empty line
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("YR")]
        if not lines:
            raise ValueError("empty ONI response")

        last = lines[-1].split()
        # Format: YR SEAS TOTAL ANOM (columns vary by version; ANOM is last or 2nd to last)
        # CPC format: SEAS YR(1) YR(2) TOTAL  (3-month running mean)
        # Try to get the anomaly value
        try:
            yr   = int(last[0])
            seas = last[1]
            anom = float(last[-1])   # last column is the anomaly in most formats
        except (IndexError, ValueError):
            anom = float(last[-1]) if last else 0.0
            seas = "???"
            yr   = date.today().year

        if anom > EL_NINO_THRESHOLD:
            enso_state = "el_nino"
        elif anom < LA_NINA_THRESHOLD:
            enso_state = "la_nina"
        else:
            enso_state = "neutral"

        oni_data = {
            "value":      round(anom, 2),
            "season":     seas,
            "year":       yr,
            "enso_state": enso_state,
            "fetched_at": datetime.utcnow().isoformat(),
        }
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(oni_data))
        print(f"[l0] ONI fetched: {anom:+.2f} ({enso_state}, {seas} {yr})", flush=True)
        return oni_data

    except Exception as e:
        print(f"[l0] ONI fetch error: {e} — using last cache or 0.0", flush=True)
        if cache.exists():
            return json.loads(cache.read_text())
        return {"value": 0.0, "enso_state": "neutral", "fetched_at": "unavailable"}


def _l1_subject(system_id: str) -> str:
    return f"vsf.clima.{system_id}.phi_up"


def _l0_subject() -> str:
    return "vsf.clima.l0.phi_up"


async def run_l0():
    nc = await nats.connect(NATS_URL)
    print("[l0] NATS connected", flush=True)

    system_states: dict[str, dict] = {}

    # Initial ONI fetch
    oni = _fetch_oni()

    async def on_l1_msg(msg):
        try:
            evt = json.loads(msg.data)
            system_id = evt.get("system_id", "unknown")
            system_states[system_id] = evt

            # Re-evaluate L0 on any L1 update
            await emit_l0(nc, system_states, oni)
        except Exception as e:
            print(f"[l0] L1 msg error: {e}", flush=True)

    # Subscribe to both L1 systems
    subs = []
    for system_id in L0_SYSTEM["children"]:
        sub = await nc.subscribe(_l1_subject(system_id), cb=on_l1_msg)
        subs.append(sub)
        print(f"[l0] subscribed → {_l1_subject(system_id)}", flush=True)

    # Monthly ONI refresh loop
    async def oni_refresh_loop():
        nonlocal oni
        while True:
            await asyncio.sleep(3600 * 24)  # check daily, refresh if stale
            oni = _fetch_oni()

    asyncio.create_task(oni_refresh_loop())

    try:
        while True:
            await asyncio.sleep(60)
    finally:
        for sub in subs:
            await sub.unsubscribe()
        await nc.close()


async def emit_s4_context(nc, system_states: dict, oni: dict, l0_evt: dict):
    """Emit S4 domain context bundle (S4-MULTI-S1, spec §target_state.domain_bundle).
    Published to vsf.clima.s4_context for nucleus S4 cross-domain synthesis."""
    oni_value  = oni.get("value", 0.0)
    enso_state = oni.get("enso_state", "neutral")

    # Derive algedonic_status from system regimes
    regimes = {sid: s.get("regime", "quiescent") for sid, s in system_states.items()}
    if any(r in ("frontal",) for r in regimes.values()):
        algedonic_status = "B"  # frontal = urgent coordination
    elif any(r in ("enso",) for r in regimes.values()) or enso_state != "neutral":
        algedonic_status = "A"  # ENSO = systemic concern
    elif any(r in ("mixed",) for r in regimes.values()):
        algedonic_status = "B"
    else:
        algedonic_status = "C"  # quiescent

    # Events: L1 system summaries — includes S2 contract fields (ITEM_18.3)
    events = []
    for sid, state in system_states.items():
        events.append({
            "system_id":         sid,
            "regime":            state.get("regime", "quiescent"),
            "confidence":        state.get("confidence", 0.0),
            "n_excursion_zones": state.get("n_excursion_zones", 0),
            "n_zones":           state.get("n_zones", 0),
            "system_coherence":  state.get("system_coherence", 1.0),
            "mean_min_stasis":   state.get("mean_min_stasis", 1.0),
            # S2 inter-domain contract
            "stasis_cos_sys":    state.get("stasis_cos_sys"),
            "stasis_cos_min":    state.get("stasis_cos_min"),
            "viability_ratio":   state.get("viability_ratio"),
        })

    bundle = {
        "domain":           "s1-clima",
        "ts":               datetime.utcnow().isoformat() + "Z",
        "events":           events,
        "algedonic_status": algedonic_status,
        "baseline": {
            "global_regime":     l0_evt.get("global_regime", "quiescent"),
            "oni_value":         oni_value,
            "enso_state":        enso_state,
            "n_systems":         len(system_states),
            "omega_modulation":  l0_evt.get("omega_modulation", {}),
            # S2 inter-domain contract
            "global_stasis_cos": l0_evt.get("global_stasis_cos"),
            "global_stasis_min": l0_evt.get("global_stasis_min"),
            "global_viability":  l0_evt.get("global_viability"),
        },
    }

    payload = json.dumps(bundle).encode()
    await nc.publish(S4_CONTEXT_SUBJECT, payload)
    with open(S4_CONTEXT_LOG, "a") as f:
        f.write(json.dumps(bundle) + "\n")

    print(f"[l0] s4_context published algedonic={algedonic_status} "
          f"oni={oni_value:+.2f}({enso_state})", flush=True)


async def emit_l0(nc, system_states: dict, oni: dict):
    if not system_states:
        return

    # L0 regime: combination of L1 regimes
    regimes = {sid: s.get("regime", "quiescent") for sid, s in system_states.items()}
    all_quiescent = all(r == "quiescent" for r in regimes.values())

    enso_state = oni.get("enso_state", "neutral")
    oni_value  = oni.get("value", 0.0)

    # L0 Ω modulation: El Niño → widen zone Ω for rain-anomalous zones.
    # Structured format consumed by kernel_zona._within_zone_omega():
    #   mean_sc_bias: additive shift applied to (lo, hi) after stretch
    #   mean_sc_stretch: multiplicative factor applied to (lo, hi)
    # El Niño → Mediterranean/semi-arid expect more precipitation → stasis_cos lower
    #   is still "expected" → widen Ω (stretch) + shift floor down (bias negative)
    # Keyed by the zone_id that should receive the override.
    omega_modulation = {}
    if enso_state == "el_nino":
        omega_modulation = {
            "mediterranea":  {"mean_sc_bias": -0.10, "mean_sc_stretch": 1.15},
            "semiarida":     {"mean_sc_bias": -0.07, "mean_sc_stretch": 1.10},
            "tropical-arida":{"mean_sc_bias":  0.0,  "mean_sc_stretch": 1.05},
        }
    elif enso_state == "la_nina":
        omega_modulation = {
            "mediterranea":  {"mean_sc_bias":  0.05, "mean_sc_stretch": 1.05},
            "semiarida":     {"mean_sc_bias":  0.03, "mean_sc_stretch": 1.05},
        }

    # ── S2 inter-domain contract (ITEM_18.3) — cross-domain numeric aggregates ──
    # Weighted mean of stasis_cos_sys across both domains (equal weight)
    sys_cos_vals  = [s["stasis_cos_sys"] for s in system_states.values()
                     if "stasis_cos_sys" in s]
    sys_min_vals  = [s["stasis_cos_min"] for s in system_states.values()
                     if "stasis_cos_min" in s]
    viab_vals     = [s["viability_ratio"] for s in system_states.values()
                     if "viability_ratio" in s]

    global_stasis_cos  = round(sum(sys_cos_vals)  / len(sys_cos_vals),  4) if sys_cos_vals  else None
    global_stasis_min  = round(min(sys_min_vals),                        4) if sys_min_vals  else None
    global_viability   = round(sum(viab_vals)     / len(viab_vals),     4) if viab_vals     else None

    l0_evt = {
        "ts":               datetime.utcnow().isoformat() + "Z",
        "source_id":        "s1-clima",
        "node_id":          "l0-pacifico-sur-americano",
        "vsm_level":        0,
        "event_type":       "l0_aggregate",
        "system_regimes":   regimes,
        "global_regime":    "quiescent" if all_quiescent else "active",
        "oni":              oni_value,
        "enso_state":       enso_state,
        "omega_modulation": omega_modulation,
        # S2 inter-domain contract: normalized cross-domain viability
        "global_stasis_cos": global_stasis_cos,
        "global_stasis_min": global_stasis_min,
        "global_viability":  global_viability,
        "system_snapshot":  {s: {
                                "regime":          d.get("regime"),
                                "coherence":       d.get("system_coherence"),
                                "stasis_cos_sys":  d.get("stasis_cos_sys"),
                                "stasis_cos_min":  d.get("stasis_cos_min"),
                                "viability_ratio": d.get("viability_ratio"),
                             }
                             for s, d in system_states.items()},
    }

    await nc.publish(_l0_subject(), json.dumps(l0_evt).encode())
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(l0_evt) + "\n")

    print(f"[l0] emitted  global={l0_evt['global_regime']}"
          f"  stasis_cos={global_stasis_cos}  viab={global_viability}"
          f"  ONI={oni_value:+.2f}({enso_state})",
          flush=True)

    # S4 context bundle (S4-MULTI-S1, wave_1)
    await emit_s4_context(nc, system_states, oni, l0_evt)

    # ── φ↓ Ω modulation → L1 systems → L2 zones (ITEM_21.2 / ITEM_17 close) ──
    # L0 publishes structured modulation to each L1 params channel;
    # kernel_regional.py receives and forwards to its zones (kernel_zona.py applies).
    # Only published when ENSO state changes or is active (A5: single-loop, auto).
    if omega_modulation:
        for system_id in L1_SYSTEMS:
            params_msg = {
                "ts":               datetime.utcnow().isoformat() + "Z",
                "from_level":       0,
                "from_node":        "l0-pacifico-sur-americano",
                "omega_modulation": omega_modulation,
                "reason":           f"enso_{enso_state} (ONI={oni_value:+.2f})",
                "enso_state":       enso_state,
                "oni":              oni_value,
                "requires_human_ack": False,  # single-loop: S5 ratified ENSO→Ω rule
            }
            await nc.publish(
                f"vsf.clima.{system_id}.params",
                json.dumps(params_msg).encode())
        print(f"[l0] φ↓ Ω modulation published to {list(L1_SYSTEMS.keys())} "
              f"(enso={enso_state}, {len(omega_modulation)} zones targeted)",
              flush=True)

    # Algedonic if El Niño/La Niña active
    if enso_state != "neutral":
        alg = {
            "ts":         datetime.utcnow().isoformat() + "Z",
            "source_id":  "s1-clima",
            "category":   "s4_enso_context",
            "severity":   6,
            "message":    f"ENSO state: {enso_state} (ONI={oni_value:+.2f}) — Ω modulation active",
            "enso_state": enso_state,
            "oni":        oni_value,
            "vsm_level":  0,
        }
        await nc.publish(algedonic_subject(), json.dumps(alg).encode())


if __name__ == "__main__":
    asyncio.run(run_l0())
