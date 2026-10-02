#!/usr/bin/env python3
"""s4_markov_bridge.py — NATS-RESILIENCE-FIX PILOT (3 capas).

PILOT: prueba de concepto con 1 instancia (markov-bridge).
Cuando [O] da luz verde, se aplica a clima-bridge + 4 scripts clima.

Capas:
  1. vsf_nats.connect_resilient() — reconnect infinito + callbacks ruidosos + fail-loud
  2. publish_safe() con timeout — no crash NO hang
  3. sd_notify WATCHDOG work-gated — heartbeat SOLO desde el camino de trabajo:
     - por cada mensaje procesado OK (handler) si nc.is_connected
     - probe periódico (30s) con nc.flush() para periodos sin mensajes
     - NUNCA desde un timer separado del trabajo NATS
"""
import asyncio
import json
import signal
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# Import vsf_nats — debe estar en PYTHONPATH o en el mismo dir
# Deploy: /usr/local/lib/vsf/vsf_nats.py  (LXC 101) / /opt/vsf-clima/src/vsf_nats.py (LXC 112)
_SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(_SRC))
sys.path.insert(0, "/usr/local/lib/vsf")
sys.path.insert(0, "/opt/vsf-clima/src")

import vsf_nats

NATS_URL = os.environ.get("NATS_URL", "nats://10.10.20.20:4222")
PROJECTION_PATH = Path("/var/lib/vsf/vsf_nucleus/s4_markov_projection.json")
SUBJECT_IN = "vsf.alpha.s4.markov.projection"
SUBJECT_DIRECTIVE = "vsf.alpha.s4.anticipatory_directive"

DIRECTIVE_THRESHOLD = 2

# Health probe config — bridges sin mensajes entrantes necesitan heartbeat periódico
# PROBE_INTERVAL: segundos entre flushes de salud → heartbeat de watchdog
# FLUSH_TIMEOUT: máximo esperar nc.flush() antes de considerar conexión muerta
# ⚠ WatchdogSec >= 2-3× PROBE_INTERVAL (p.ej. 30s para PROBE_INTERVAL=10s)
PROBE_INTERVAL = 10   # segundos — idle bridge heartbeats every 10s
FLUSH_TIMEOUT = 5.0   # segundos — timeout para nc.flush()

# ---- Señales vía asyncio.Event (no setattr(builtins,'_stop')) ----
_stop_event = asyncio.Event()
_consecutive_alerts = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _log(msg: str):
    print(f"[markov-bridge] {msg}", flush=True)


async def run():
    global _consecutive_alerts

    # ---- LAYER 1: reconnect infinito + callbacks ruidosos + fail-loud ----
    async def _on_reconnect():
        _log("NATS reconnected — subscriptions auto-restored by nats-py. Connection healthy.")

    nc = await vsf_nats.connect_resilient(
        NATS_URL, name="s4-markov-bridge", on_reconnect=_on_reconnect,
    )
    _log(f"connected {NATS_URL}")

    # ---- LAYER 3: ready notification ----
    vsf_nats.sd_notify_ready()

    # ---- Señales ----
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop_event.set)

    # ---- Suscripción ----
    async def handler(msg):
        global _consecutive_alerts
        try:
            payload = json.loads(msg.data.decode())

            # Write local file for s4_operational.rs
            PROJECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(PROJECTION_PATH, "w") as f:
                json.dump(payload, f)

            alert_zones = payload.get("alert_zones", [])
            multi_alert = payload.get("multi_zone_alert", False)
            n_zones = payload.get("n_zones", 0)

            if multi_alert:
                _consecutive_alerts += 1
            else:
                _consecutive_alerts = 0

            _log(f"projection received: {n_zones} zones  at_risk={len(alert_zones)}  multi={multi_alert}  consec={_consecutive_alerts}")

            # 17.2 — S4→S3 anticipatory directive
            if _consecutive_alerts >= DIRECTIVE_THRESHOLD:
                directive = {
                    "ts":          now_iso(),
                    "event_type":  "s4_anticipatory_directive",
                    "source":      "s4_markov",
                    "alert_zones": alert_zones,
                    "message":     (
                        f"Markov projects elevated excursion risk for {DIRECTIVE_THRESHOLD}+ "
                        f"consecutive cycles in zones: {', '.join(alert_zones)}. "
                        f"S3: pre-allocate resources or tighten monitoring."
                    ),
                    "lead_horizon": "7d",
                    "channel":     "markov",
                }
                # ---- LAYER 2: publish seguro con timeout ----
                ok = await vsf_nats.publish_safe(
                    nc, SUBJECT_DIRECTIVE, json.dumps(directive).encode(),
                    log_prefix="markov-bridge",
                )
                if ok:
                    _log(f"17.2 directive → S3: zones={alert_zones}")
                else:
                    _log(f"17.2 directive DEFERRED (publish transient error) — will retry next cycle")
                _consecutive_alerts = 0  # reset after sending

            # ---- LAYER 3: work-gated watchdog ----
            # Late SOLO si el handler procesó OK y la conexión está viva.
            # Si nc.is_connected es False (reconnect en curso), NO heartbeat →
            # systemd watchdog expira → reinicia el proceso.
            if nc.is_connected:
                vsf_nats.sd_notify_watchdog()

        except Exception as e:
            _log(f"handler error: {e}")

    await nc.subscribe(SUBJECT_IN, cb=handler)
    _log(f"subscribed {SUBJECT_IN}")

    # ---- Health probe periódico ----
    # Para periodos sin mensajes (el bridge no recibe proyecciones cada 5s),
    # este probe verifica que la conexión NATS sigue viva. Si nc.flush() falla
    # (conexión muerta, reconnect en curso), NO heartbeat → watchdog expira.
    async def health_probe():
        """Every PROBE_INTERVAL seconds, probe NATS connection.

        Uses _stop_event.wait(timeout=PROBE_INTERVAL) so:
        - Normal: timeout after PROBE_INTERVAL → do the flush probe
        - Shutdown: _stop_event is set → break immediately (clean exit)

        If flush fails (reconnect in progress, NATS down) → NO heartbeat →
        systemd watchdog expires → restarts the process.
        """
        while not _stop_event.is_set():
            try:
                # Wait PROBE_INTERVAL, but wake immediately if stop requested
                await asyncio.wait_for(_stop_event.wait(), timeout=PROBE_INTERVAL)
                break  # _stop_event was set → shutdown
            except asyncio.TimeoutError:
                pass  # PROBE_INTERVAL elapsed → time to probe

            try:
                if nc.is_connected:
                    # Probe activo: flush envía PING, espera PONG
                    await asyncio.wait_for(nc.flush(), timeout=FLUSH_TIMEOUT)
                    if nc.is_connected:
                        vsf_nats.sd_notify_watchdog()
            except Exception:
                pass  # flush falló → no heartbeat → watchdog reinicia

    probe_task = asyncio.create_task(health_probe())

    # ---- Esperar señal de shutdown ----
    await _stop_event.wait()

    probe_task.cancel()
    try:
        await probe_task
    except asyncio.CancelledError:
        pass

    _log("shutting down...")
    vsf_nats.sd_notify("STOPPING=1")
    await nc.drain()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
