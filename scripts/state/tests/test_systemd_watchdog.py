#!/usr/bin/env python3
"""test_systemd_watchdog.py — verifica que la Capa 3 work-gated funciona bajo systemd real.

Escenario:
  1. nats-server corre en localhost:4222
  2. Este script se conecta, publica cada 5s, late watchdog SOLO si publish==True
  3. Si matan NATS, los publishes fallan → NO heartbeat → watchdog expira → systemd reinicia

Ejecutar bajo systemd:
  systemctl start vsf-test-watchdog
  # matar NATS → esperar 2×WatchdogSec → verificar NRestarts>0

Sin systemd: solo verifica que el loop no crashea (no hay watchdog real).
"""
import asyncio
import os
import sys
import signal

sys.path.insert(0, "/usr/local/lib/vsf")
sys.path.insert(0, "/opt/vsf-clima/src")
sys.path.insert(0, "/tmp")

import vsf_nats

NATS_URL = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")

_stop_event = asyncio.Event()


async def main():
    nc = await vsf_nats.connect_resilient(NATS_URL, name="watchdog-test")
    vsf_nats.sd_notify_ready()
    print("[WD-TEST] READY=1 sent. Watching...", flush=True)

    # Signal handling for clean shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop_event.set)

    tick = 0
    while not _stop_event.is_set():
        await asyncio.sleep(5)
        tick += 1
        ok = await vsf_nats.publish_safe(nc, "vsf.test.watchdog", f"tick-{tick}".encode())
        # Work-gated: heartbeat ONLY if publish OK AND connection alive.
        # nats-py publish() during reconnect returns True (buffers message)
        # without delivering it. nc.is_connected tells "really alive" from "reconnect queued".
        if ok and nc.is_connected:
            vsf_nats.sd_notify_watchdog()
            print(f"[WD-TEST] tick-{tick} published + watchdog OK", flush=True)
        else:
            # No heartbeat → watchdog expires if this persists
            print(f"[WD-TEST] tick-{tick} publish={'OK' if ok else 'FAIL'} "
                  f"connected={nc.is_connected} — no heartbeat", flush=True)

    print("[WD-TEST] shutting down...", flush=True)
    vsf_nats.sd_notify("STOPPING=1")
    await nc.drain()


if __name__ == "__main__":
    asyncio.run(main())
