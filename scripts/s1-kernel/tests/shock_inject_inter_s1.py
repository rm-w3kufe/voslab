#!/usr/bin/env python3
"""
shock_inject_inter_s1.py — EXP-S2-01: inter-S1 oscillation test.

Injects simultaneous stress on s1-clima + s1-econ via NATS φ↑ messages,
then observes S3 (vsf-s3-alloc) response: does the proportional allocator
oscillate (grant→restore ping-pong) or handle both domains in parallel?

Pattern:
  Phase 1 (baseline):  30s idle — let S3 counters stabilise.
  Phase 2 (dual stress): publish low stasis_cos for CLIMA + ECON every 10s × 6
  Phase 3 (mixed):     CLIMA recovers → ECON stays stressed (×6)
  Phase 4 (all clear): both recover (×6)

  Each tick: publish → sleep 10s → journal snapshot.

Usage:
  python3 shock_inject_inter_s1.py [--dry-run] [--wait-clear] [--stress-cos=X]

Options:
  --dry-run        Print what would be published without connecting to NATS
  --wait-clear     Wait for pool to be green (grants_active=0) before starting
  --stress-cos=X   stasis_cos value for stress ticks (default: 0.40; 0.0 = max depth)
  --tick-s=N       Seconds between ticks (default: 10)
  --ticks=N        Ticks per phase (default: 6)

Requires:
  - nats-py (installed on LXC 101)
  - vsf-s3-alloc running on LXC 101
  - NATS at 10.10.20.20:4222
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

NATS_URL = "nats://10.10.20.20:4222"

# Subjects the S3 allocator listens on
CLIMA_SUBJECT = "vsf.clima.continental.phi_up"
ECON_SUBJECT  = "vsf.econ.chile.phi_up"
GRANT_SUBJECT = "vsf.alpha.s3.resource_grant"  # S3 publishes here

RECOVER_COS = 0.80   # above RECOVERY_THRESHOLD=0.70 → recovered


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clima_event(stasis_cos: float) -> bytes:
    """φ↑ event matching what s1-clima L0 continental emits."""
    evt = {
        "ts":           _ts(),
        "source_id":    "clima",
        "vsm_level":    3,
        "event_type":   "zone_aggregate",
        "stasis_cos":   round(stasis_cos, 4),
        "continental":  True,
        "_injected":    True,
    }
    return json.dumps(evt).encode()


def _econ_event(stasis_cos: float) -> bytes:
    """φ↑ event matching what s1-econ-kernel emits."""
    evt = {
        "ts":           _ts(),
        "source_id":    "econ",
        "event_type":   "phi_up",
        "domain":       "chile",
        "stasis_cos":   round(stasis_cos, 4),
        "_injected":    True,
    }
    return json.dumps(evt).encode()


async def journal_snapshot(label: str):
    """Capture recent S3 allocator log lines."""
    try:
        out = subprocess.run(
            ["journalctl", "-u", "vsf-s3-alloc", "--no-pager", "-n", "5",
             "--since", "30 seconds ago"],
            capture_output=True, text=True, timeout=5
        )
        lines = [l for l in out.stdout.split("\n") if l.strip()]
        print(f"  [journal {label}] {len(lines)} lines", flush=True)
        for l in lines[-3:]:
            print(f"    {l.strip()}", flush=True)
    except Exception as e:
        print(f"  [journal {label}] error: {e}", flush=True)


def _pool_state(nc) -> dict:
    """Quick check current pool state from NATS grant events."""
    import json
    evts = []
    done = asyncio.Event()

    async def cb(msg):
        evts.append(json.loads(msg.data))
        done.set()

    async def check():
        sub = await nc.subscribe(GRANT_SUBJECT, cb=cb)
        try:
            await asyncio.wait_for(done.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        await sub.unsubscribe()
        return evts

    evts = asyncio.run(check())
    # Parse latest pool state from events
    used_cores = 0
    zone = "unknown"
    for e in reversed(evts):
        if "pool_cores_remaining" in e:
            used_cores = e.get("pool_cores_remaining", 0)
            # remaining = total - used, so used = total - remaining
        if "pool_zone" in e:
            zone = e.get("pool_zone", zone)
    return {"used_cores": used_cores, "zone": zone}


async def run():
    parser = argparse.ArgumentParser(description="EXP-S2-01 inter-S1 oscillation test")
    parser.add_argument("--dry-run", action="store_true", help="No NATS publishes")
    parser.add_argument("--wait-clear", action="store_true", help="Wait for pool to be green before starting")
    parser.add_argument("--stress-cos", type=float, default=0.40, help="stasis_cos for stress ticks (default: 0.40)")
    parser.add_argument("--tick-s", type=float, default=10, help="Seconds between ticks (default: 10)")
    parser.add_argument("--ticks", type=int, default=6, help="Ticks per phase (default: 6)")
    args = parser.parse_args()

    STRESS_COS = args.stress_cos
    TICK_S = args.tick_s
    PHASE_TICKS = args.ticks
    dry_run = args.dry_run

    if dry_run:
        print("[shock] DRY RUN — no NATS publishes", flush=True)

    if not dry_run:
        try:
            import nats
        except ImportError:
            print("[shock] ERROR: nats-py not installed. Run on LXC 101.", flush=True)
            sys.exit(1)
        nc = await nats.connect(NATS_URL)
        print(f"[shock] NATS connected → {NATS_URL}", flush=True)

        # --wait-clear: poll pool state until green
        if args.wait_clear:
            print("[shock] --wait-clear: checking pool state...", flush=True)
            for attempt in range(30):
                try:
                    out = subprocess.run(
                        ["journalctl", "-u", "vsf-s3-alloc", "--no-pager", "-n", "1",
                         "--since", "30 seconds ago", "-o", "cat"],
                        capture_output=True, text=True, timeout=5
                    )
                    if "zone=green" in out.stdout:
                        print("[shock] pool is GREEN, starting test", flush=True)
                        break
                except Exception:
                    pass
                print(f"  [shock] waiting for green pool (attempt {attempt+1}/30)...", flush=True)
                await asyncio.sleep(5)
            else:
                print("[shock] WARNING: pool not green after 30 attempts, proceeding anyway", flush=True)
    else:
        nc = None

    stress_depth = max(0, min(1, (0.55 - STRESS_COS) / 0.55)) if STRESS_COS < 0.55 else 0.0
    print(f"[shock] EXP-S2-01 inter-S1 oscillation test", flush=True)
    print(f"[shock] stress_cos={STRESS_COS} (depth≈{stress_depth:.2f})  recover_cos={RECOVER_COS}  tick={TICK_S}s × {PHASE_TICKS}", flush=True)
    print(f"[shock] clima → {CLIMA_SUBJECT}", flush=True)
    print(f"[shock] econ  → {ECON_SUBJECT}", flush=True)
    print(f"[shock] watching → {GRANT_SUBJECT}", flush=True)
    print(flush=True)

    # Collect S3 grant events
    grant_events = []

    async def on_grant(msg):
        evt = json.loads(msg.data)
        grant_events.append(evt)
        print(f"  [grant] {evt.get('event_type')} vmid={evt.get('vmid')} "
              f"+{evt.get('grant_cores',0)}c +{evt.get('grant_mem_mb',0)}MB "
              f"depth={evt.get('stress_depth','?')} zone={evt.get('pool_zone','?')}",
              flush=True)

    grant_sub = None
    if nc:
        grant_sub = await nc.subscribe(GRANT_SUBJECT, cb=on_grant)
        await asyncio.sleep(0.3)

    # ── Phase 1: Baseline ─────────────────────────────────────────────────
    print("═══ PHASE 1: BASELINE (30s idle) ════════════════════════════════", flush=True)
    await asyncio.sleep(10)
    await journal_snapshot("baseline")

    # ── Phase 2: Dual stress ──────────────────────────────────────────────
    print("\n═══ PHASE 2: DUAL STRESS (clima + econ both low) ═══════════════", flush=True)
    for tick in range(PHASE_TICKS):
        if nc:
            await nc.publish(CLIMA_SUBJECT, _clima_event(STRESS_COS))
            await nc.publish(ECON_SUBJECT,  _econ_event(STRESS_COS))
        print(f"  [tick {tick+1}/{PHASE_TICKS}] published clima={STRESS_COS} econ={STRESS_COS}", flush=True)
        await asyncio.sleep(TICK_S)
        await journal_snapshot(f"p2-t{tick+1}")

    # ── Phase 3: Mixed recovery ───────────────────────────────────────────
    print("\n═══ PHASE 3: CLIMA RECOVERS (econ stays stressed) ══════════════", flush=True)
    for tick in range(PHASE_TICKS):
        if nc:
            await nc.publish(CLIMA_SUBJECT, _clima_event(RECOVER_COS))
            await nc.publish(ECON_SUBJECT,  _econ_event(STRESS_COS))
        print(f"  [tick {tick+1}/{PHASE_TICKS}] clima={RECOVER_COS} econ={STRESS_COS}", flush=True)
        await asyncio.sleep(TICK_S)
        await journal_snapshot(f"p3-t{tick+1}")

    # ── Phase 4: All clear ────────────────────────────────────────────────
    print("\n═══ PHASE 4: ALL CLEAR (both recover) ═══════════════════════════", flush=True)
    for tick in range(PHASE_TICKS):
        if nc:
            await nc.publish(CLIMA_SUBJECT, _clima_event(RECOVER_COS))
            await nc.publish(ECON_SUBJECT,  _econ_event(RECOVER_COS))
        print(f"  [tick {tick+1}/{PHASE_TICKS}] clima={RECOVER_COS} econ={RECOVER_COS}", flush=True)
        await asyncio.sleep(TICK_S)
        await journal_snapshot(f"p4-t{tick+1}")

    # ── Results ───────────────────────────────────────────────────────────
    print("\n══════════════════════════════════════════════════════════════════", flush=True)
    print("EXP-S2-01 — INTER-S1 OSCILLATION TEST RESULTS", flush=True)
    print("══════════════════════════════════════════════════════════════════", flush=True)
    print(f"\n  Total S3 grant/restore events: {len(grant_events)}", flush=True)

    grants = [e for e in grant_events if e.get("event_type") == "s3_resource_grant"]
    restores = [e for e in grant_events if e.get("event_type") == "s3_resource_restore"]
    algedonics = [e for e in grant_events if e.get("event_type") == "s3_pool_red_algedonic"]

    print(f"  Grants:   {len(grants)}", flush=True)
    print(f"  Restores: {len(restores)}", flush=True)
    print(f"  Algedonic RED: {len(algedonics)}", flush=True)

    # Check oscillation: alternating grants between LXCs
    if len(grants) >= 2:
        vmid_seq = [e["vmid"] for e in grants]
        alternations = sum(1 for i in range(1, len(vmid_seq)) if vmid_seq[i] != vmid_seq[i-1])
        print(f"  VMID grant sequence: {' → '.join(vmid_seq)}", flush=True)
        print(f"  Alternations (vmid switches): {alternations}/{len(grants)-1}", flush=True)

        # Oscillation: grants switching back and forth ≥2 times
        oscillates = alternations >= 2
        print(f"  Oscillation detected: {'YES ⚠️' if oscillates else 'NO ✓'}", flush=True)
    else:
        print(f"  Not enough grants to assess oscillation pattern", flush=True)
        oscillates = False

    # Pool zone transitions
    zones_seen = set(e.get("pool_zone") for e in grant_events if e.get("pool_zone"))
    print(f"  Pool zones observed: {', '.join(sorted(zones_seen)) if zones_seen else 'none'}", flush=True)

    verdict = "OSCILLATION DETECTED" if oscillates else "NO OSCILLATION"
    print(f"\n  VERDICT: {verdict}", flush=True)

    # ── Cleanup ──────────────────────────────────────────────────────────
    if grant_sub:
        await grant_sub.unsubscribe()
    if nc:
        await nc.close()

    return 1 if oscillates else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
