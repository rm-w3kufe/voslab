#!/usr/bin/env python3
"""test_consumer_watchdog.py — verifica health_probe consumer/idle bajo systemd watchdog.

Simula el patrón del markov-bridge CONSUMER (sin publishes propios, heartbeat vía health_probe):
  - Se suscribe a un subject, NO llegan mensajes (idle)
  - health_probe cada PROBE_INTERVAL=10s hace nc.flush() + heartbeat
  - Si NATS está vivo → heartbeat → watchdog feliz
  - Si NATS muere → flush falla → NO heartbeat → watchdog expira → restart

Test escenarios bajo systemd (Type=notify, WatchdogSec=30):
  (a) Sano+idle 60s+: el probe mantiene vivo, NO falso-kill
  (b) Matar NATS → probe falla → watchdog timeout → 'Failed with result watchdog' + restart

Ejecutar:
  systemctl start vsf-test-consumer-watchdog
  journalctl -u vsf-test-consumer-watchdog -f
  # matar NATS en otra terminal
  # esperar 35s → verificar 'restart counter is at 1'
"""
import asyncio
import json
import os
import signal
import sys

sys.path.insert(0, "/usr/local/lib/vsf")
sys.path.insert(0, "/opt/vsf-clima/src")
sys.path.insert(0, "/tmp")

import vsf_nats

NATS_URL = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")

PROBE_INTERVAL = 10   # must be <= WatchdogSec/2 in systemd unit
FLUSH_TIMEOUT = 5.0
SUBJECT_IN = "vsf.test.consumer.input"

_stop_event = asyncio.Event()


async def main():
    nc = await vsf_nats.connect_resilient(NATS_URL, name="consumer-watchdog-test")
    vsf_nats.sd_notify_ready()
    print("[CONS-WD-TEST] READY=1 sent. Starting consumer (idle, health_probe active)...", flush=True)

    # Signal handling
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop_event.set)

    # Handler — simulates work on incoming messages
    async def handler(msg):
        try:
            data = json.loads(msg.data.decode())
            ts = data.get("ts", "?")
            print(f"[CONS-WD-TEST] received message at {ts} — processing OK", flush=True)
            if nc.is_connected:
                vsf_nats.sd_notify_watchdog()
        except Exception as e:
            print(f"[CONS-WD-TEST] handler error: {e}", flush=True)

    await nc.subscribe(SUBJECT_IN, cb=handler)
    print(f"[CONS-WD-TEST] subscribed {SUBJECT_IN}", flush=True)

    # Health probe — same pattern as s4_markov_bridge_pilot.py
    async def health_probe():
        while not _stop_event.is_set():
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=PROBE_INTERVAL)
                break  # _stop_event was set → shutdown
            except asyncio.TimeoutError:
                pass  # PROBE_INTERVAL elapsed → time to probe

            try:
                if nc.is_connected:
                    await asyncio.wait_for(nc.flush(), timeout=FLUSH_TIMEOUT)
                    if nc.is_connected:
                        vsf_nats.sd_notify_watchdog()
                        print(f"[CONS-WD-TEST] probe OK — watchdog heartbeat sent", flush=True)
            except Exception:
                # flush failed → no heartbeat → watchdog will restart us
                print(f"[CONS-WD-TEST] probe FAIL — no heartbeat (watchdog will fire)", flush=True)

    probe_task = asyncio.create_task(health_probe())

    await _stop_event.wait()

    probe_task.cancel()
    try:
        await probe_task
    except asyncio.CancelledError:
        pass

    print("[CONS-WD-TEST] shutting down...", flush=True)
    vsf_nats.sd_notify("STOPPING=1")
    await nc.drain()


if __name__ == "__main__":
    asyncio.run(main())
