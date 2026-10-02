#!/usr/bin/env python3
"""markov_project.py — ITEM_17.1/17.2/17.3: Markov projection service.

Runs on LXC 112 (s1-clima). Loads trained Markov models, reads current zone
stasis_cos from live NATS φ↑ (vsf.clima.*.phi_up) + log-file cold-start seed,
projects excursion probabilities using viability_forecaster module, and publishes:

  vsf.alpha.s4.markov.projection  — per-zone projections (S4 reads via bridge)
  vsf.alpha.algedonic.*           — regime-shift proposal (17.3) → algedonic_ledger

Beer: S4's job is to model the future of the system-in-its-environment.
      Markov gives P(state at t+n) — genuine τ(t+n) projection, not S3* retrospective.
"""
import asyncio
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import nats

# Import domain-agnostic forecaster (deployed to /usr/local/bin/viability_forecaster.py)
from viability_forecaster import project as forecaster_project
from viability_forecaster import P7_CRITICAL

# Read NATS_URL from env with fallback (parent token embedded in systemd unit's env)
NATS_URL         = os.environ.get("NATS_URL", "nats://10.10.20.20:4222")
MARKOV_DIR       = Path("/var/lib/vsf-clima/markov")
PROJECTION_FILE  = Path("/var/lib/vsf-clima/markov/latest_projection.json")
POLL_S           = 3600    # project every hour (same cadence as climate_kernel)
SUSTAIN_ALERTS   = 3       # consecutive high-risk projections before 17.3 policy proposal

# Zone state freshness: if no φ↑ received in 24h, treat as stale
ZONE_STALE_S     = 86400

# NATS subject format for L3 φ↑ (matches l3_node.py + node_registry.phi_up_subject)
PHI_UP_TEMPLATE  = "vsf.clima.{zone}.phi_up"

# L3 φ↑ JSONL log files (written by l3_node.py on each publish)
LOG_DIR          = Path("/var/log/vsf-clima")

# P(excursion in 7 days) thresholds from forecaster constants (imported above)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def load_models() -> dict[str, dict]:
    models = {}
    for p in MARKOV_DIR.glob("*.json"):
        if p.name == "latest_projection.json":
            continue
        try:
            with open(p) as f:
                m = json.load(f)
            if "T" in m and "zone" in m:
                models[m["zone"]] = m
        except Exception as e:
            print(f"[markov] warning: could not load {p}: {e}", flush=True)
    return models


# ── Live NATS φ↑ cache ──────────────────────────────────────────────────────

class ZoneStateCache:
    """Caches latest stasis_cos per zone from live L3 φ↑ NATS messages.

    Subscribes to vsf.clima.<zone>.phi_up for each trained model zone.
    On startup, seeds from the last φ↑ log line (avoids cold-start NaN).
    Values older than ZONE_STALE_S are treated as stale (NaN).
    """

    def __init__(self, nc, models: dict[str, dict]):
        self._nc = nc
        self._models = models
        # zone → {"stasis_cos": float, "ts": float (time.time)}
        self._data: dict[str, dict] = {}
        self._subs: list = []

    async def start(self):
        """Subscribe to φ↑ for each trained model zone. Seed from log files first."""
        self._seed_from_logs()
        for zone in self._models:
            subject = PHI_UP_TEMPLATE.format(zone=zone)
            sub = await self._nc.subscribe(subject, cb=self._make_callback(zone))
            self._subs.append(sub)
            print(f"[markov] subscribed {subject}", flush=True)

    def _seed_from_logs(self):
        """Read last φ↑ from each zone's JSONL log file as initial state."""
        for zone in self._models:
            log_file = LOG_DIR / f"{zone}.phi_up.jsonl"
            if not log_file.exists():
                continue
            try:
                mtime = log_file.stat().st_mtime
                if time.time() - mtime > ZONE_STALE_S:
                    continue
                with open(log_file, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    chunk_size = min(size, 4096)
                    f.seek(size - chunk_size)
                    tail = f.read()
                last_line = tail.split(b"\n")[-2] if tail.endswith(b"\n") else tail.split(b"\n")[-1]
                if not last_line:
                    continue
                payload = json.loads(last_line.decode("utf-8", errors="replace"))
                sc = payload.get("stasis_cos")
                if sc is not None and not math.isnan(float(sc)):
                    self._data[zone] = {
                        "stasis_cos": float(sc),
                        "ts": mtime,
                    }
                    print(f"[markov] seeded {zone} → stasis_cos={sc}", flush=True)
            except Exception as e:
                print(f"[markov] seed warning {zone}: {e}", flush=True)

    def _make_callback(self, zone: str):
        async def _cb(msg):
            try:
                payload = json.loads(msg.data.decode())
                sc = payload.get("stasis_cos")
                if sc is not None and not math.isnan(float(sc)):
                    self._data[zone] = {
                        "stasis_cos": float(sc),
                        "ts": time.time(),
                    }
            except Exception:
                pass
        return _cb

    def get_current_states(self) -> dict[str, float]:
        """Return {zone: stasis_cos} for zones with fresh data. Stale → NaN."""
        now = time.time()
        result: dict[str, float] = {}
        for zone in self._models:
            entry = self._data.get(zone)
            if entry is not None and (now - entry["ts"]) < ZONE_STALE_S:
                result[zone] = entry["stasis_cos"]
            else:
                result[zone] = float("nan")
        return result

    async def stop(self):
        for sub in self._subs:
            await sub.unsubscribe()


# ── Sustain tracker for 17.3 policy proposal ─────────────────────────────────

class SustainTracker:
    def __init__(self, threshold: int = SUSTAIN_ALERTS):
        self.counts: dict[str, int] = {}
        self.threshold = threshold

    def update(self, zone: str, is_critical: bool) -> bool:
        if is_critical:
            self.counts[zone] = self.counts.get(zone, 0) + 1
        else:
            self.counts[zone] = 0
        return self.counts.get(zone, 0) >= self.threshold

    def reset(self, zone: str):
        self.counts[zone] = 0


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run():
    sustain = SustainTracker()
    nc = await nats.connect(NATS_URL)
    print(f"[markov] connected {NATS_URL}")

    # Zone state cache: subscribes to live L3 φ↑ for each trained model zone
    models = load_models()
    if not models:
        print("[markov] no trained models found — run markov_train.py first")
        await asyncio.sleep(POLL_S)
        return

    cache = ZoneStateCache(nc, models)
    await cache.start()
    # Brief settle window for subscriptions to receive any in-flight φ↑
    await asyncio.sleep(5)

    while True:
        # Reload models (in case retrained)
        models = load_models()
        if not models:
            print(f"[markov] no trained models — retrying in {POLL_S}s", flush=True)
            await asyncio.sleep(POLL_S)
            continue

        current_states = cache.get_current_states()
        projections: dict[str, dict] = {}
        alert_zones: list[str] = []
        policy_zones: list[str] = []

        for zone, model in models.items():
            sc = current_states.get(zone, float("nan"))
            proj = forecaster_project(model, sc)
            projections[zone] = proj

            if proj.get("regime") in ("at_risk", "critical"):
                alert_zones.append(zone)

            p_exc_7 = proj.get("p_excursion", {}).get(7, 0.0)
            is_critical = p_exc_7 >= P7_CRITICAL
            if sustain.update(zone, is_critical):
                policy_zones.append(zone)
                sustain.reset(zone)

        multi_alert = len(alert_zones) >= 3

        payload = {
            "ts":              now_iso(),
            "n_zones":         len(projections),
            "projections":     projections,
            "alert_zones":     alert_zones,
            "multi_zone_alert": multi_alert,
        }

        # Publish projection (17.2 channel: S4 reads this)
        await nc.publish(
            "vsf.alpha.s4.markov.projection",
            json.dumps(payload).encode()
        )

        # 17.3 — Policy proposal when sustained critical + multi-zone
        if policy_zones and multi_alert:
            policy_payload = {
                "ts":             now_iso(),
                "event_type":     "markov_regime_shift",
                "source":         "s4_markov",
                "severity":       7.0,
                "zones":          policy_zones,
                "description":    (
                    f"Sustained P(excursion) ≥ {P7_CRITICAL:.0%} for {SUSTAIN_ALERTS} consecutive "
                    f"projections in zones: {', '.join(policy_zones)}. "
                    f"Consider adjusting Ω bounds or activating contingency."
                ),
                "recommendation": "ACK to note. Reject if false positive. Check ONI trend.",
            }
            await nc.publish(
                "vsf.alpha.algedonic.markov_regime_shift",
                json.dumps(policy_payload).encode()
            )
            print(f"[markov] 17.3 POLICY PROPOSAL → algedonic: zones={policy_zones}", flush=True)

        # Write local file for bridge
        PROJECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROJECTION_FILE, "w") as f:
            json.dump(payload, f)

        n_at_risk = len(alert_zones)
        print(f"[markov] projected {len(projections)} zones — at_risk={n_at_risk} multi={multi_alert}", flush=True)
        if alert_zones:
            for z in alert_zones:
                p = projections[z]
                p7 = p.get("p_excursion", {}).get(7, 0.0)
                print(f"  ⚠ {z}: p7d={p7:.2%}  regime={p['regime']}  bin={p['current_bin']}", flush=True)

        await asyncio.sleep(POLL_S)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
