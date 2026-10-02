#!/opt/vsf-clima/bin/python
"""
exp_recursion_01_monitor.py — EXP-RECURSION-01: medir r_L por nivel.

Suscribe a todos los canales φ↑ y cuenta eventos absorbed vs escalated
por nivel, en operación real. Emite resumen cada REPORT_INTERVAL_S.

Verifica el invariante §5 de recursive_vsm_theory.md:
  |S(L)| ≤ |S(L+1)| · (1 - r_L),  r_L > 0 ∀L

Escribe a:
  /var/log/vsf-clima/exp_recursion_01.jsonl  — cada evento de resolución
  /var/log/vsf-clima/exp_recursion_01_summary.jsonl — resumen periódico

Usage: exp_recursion_01_monitor.py [--report-interval 300]
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import nats

NATS_URL          = "nats://10.10.20.20:4222"
LOG_EVENTS        = Path("/var/log/vsf-clima/exp_recursion_01.jsonl")
LOG_SUMMARY       = Path("/var/log/vsf-clima/exp_recursion_01_summary.jsonl")
REPORT_INTERVAL_S = 300   # 5 min

# Counters per level
counters = {
    "L2": {"absorbed": 0, "escalated": 0, "no_omega": 0, "events": 0},
    "L1": {"absorbed": 0, "escalated": 0, "events": 0},
}


def _r_L(c: dict) -> float:
    total = c["absorbed"] + c.get("escalated", 0) + c.get("no_omega", 0)
    return round(c["absorbed"] / total, 4) if total > 0 else 0.0


def _snapshot() -> dict:
    return {
        "ts":  datetime.now(timezone.utc).isoformat(),
        "L2":  {**counters["L2"], "r_L2": _r_L(counters["L2"])},
        "L1":  {**counters["L1"], "r_L1": _r_L(counters["L1"])},
        "invariant_ok": {
            "L2": _r_L(counters["L2"]) > 0,
            "L1": _r_L(counters["L1"]) > 0,
        },
    }


async def run(report_interval: int):
    nc = await nats.connect(NATS_URL)
    print(f"[EXP-RECURSION-01] started  report_interval={report_interval}s", flush=True)

    async def on_zone(msg):
        try:
            e   = json.loads(msg.data)
            res = e.get("zone_resolution")
            if not res:
                return
            status = res.get("status", "unknown")
            if status in ("absorbed", "escalated", "no_omega"):
                counters["L2"][status] = counters["L2"].get(status, 0) + 1
            counters["L2"]["events"] += 1

            ev = {
                "ts":      e.get("ts"),
                "level":   "L2",
                "zone_id": e.get("zone_id"),
                "status":  status,
                "mean_sc": e.get("mean_stasis_cos"),
                "r_L2":    res.get("r_L2"),
            }
            with open(LOG_EVENTS, "a") as f:
                f.write(json.dumps(ev) + "\n")
        except Exception as ex:
            print(f"[zone err] {ex}", flush=True)

    async def on_system(msg):
        try:
            e   = json.loads(msg.data)
            res = e.get("system_resolution")
            if not res:
                return
            status = res.get("status", "unknown")
            if status in ("absorbed", "escalated"):
                counters["L1"][status] = counters["L1"].get(status, 0) + 1
            counters["L1"]["events"] += 1

            ev = {
                "ts":        e.get("ts"),
                "level":     "L1",
                "system_id": e.get("system_id"),
                "status":    status,
                "regime":    e.get("regime"),
                "conf":      e.get("confidence"),
                "r_L1":      res.get("r_L1"),
            }
            with open(LOG_EVENTS, "a") as f:
                f.write(json.dumps(ev) + "\n")
        except Exception as ex:
            print(f"[system err] {ex}", flush=True)

    # Subscribe to all zone and system φ↑ channels
    await nc.subscribe("vsf.clima.*.phi_up", cb=on_zone)   # catches L2 zone events
    await nc.subscribe("vsf.clima.continental.phi_up", cb=on_system)
    await nc.subscribe("vsf.clima.marino.phi_up",      cb=on_system)

    async def reporter():
        while True:
            await asyncio.sleep(report_interval)
            snap = _snapshot()
            with open(LOG_SUMMARY, "a") as f:
                f.write(json.dumps(snap) + "\n")

            r2 = snap["L2"]["r_L2"]
            r1 = snap["L1"]["r_L1"]
            ok2 = snap["invariant_ok"]["L2"]
            ok1 = snap["invariant_ok"]["L1"]

            print(f"[EXP-RECURSION-01] r_L2={r2:.3f}({'✓' if ok2 else '✗'})"
                  f"  r_L1={r1:.3f}({'✓' if ok1 else '✗'})"
                  f"  L2_events={snap['L2']['events']}"
                  f"  L1_events={snap['L1']['events']}", flush=True)

    asyncio.ensure_future(reporter())

    try:
        while True:
            await asyncio.sleep(60)
    finally:
        await nc.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-interval", type=int, default=REPORT_INTERVAL_S)
    args = parser.parse_args()
    asyncio.run(run(args.report_interval))


if __name__ == "__main__":
    main()
