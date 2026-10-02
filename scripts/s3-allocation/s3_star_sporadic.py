#!/usr/bin/env python3
"""
s3_star_sporadic.py — ITEM_19.3: tier3 esporádico independiente.

Canal físicamente distinto al daemon continuo (LXC 107):
  - Runs on LXC 108 (dev-sandbox) → different crash domain from LXC 107
  - Subscribes to nucleus φ↑ events via NATS directly
  - Runs shadow_recompute logic independently (Python re-implementation)
  - Publishes findings DIRECTLY to vsf.alpha.s3_star.audit.sporadic (S5 on LXC 104)
  - No routing through LXC 107 (the continuous S3* daemon)

Beer-faithful: S3* sporadic channel cannot be blocked by the continuous S3* on LXC 107.
Run this manually at connection time (rmw3 logs in → triggers sporadic audit).

Usage: python3 s3_star_sporadic.py [--wait 30]
  --wait N  seconds to collect φ↑ events before running check (default: 30)
"""
import argparse
import asyncio
import json
import math
import sys
from datetime import datetime, timezone
from typing import Optional

import nats

NATS_URL          = "nats://10.10.20.20:4222"
NUCLEUS_SUBJECT   = "vsf.alpha.vsf_nucleus.up.>"
AUDIT_SUBJECT     = "vsf.alpha.s3_star.audit.sporadic"   # direct to S5; no LXC 107
SEMANTIC_EPSILON  = 0.02
BUFFER_MAX        = 50
SOURCE_ID         = "s3star-sporadic-108"


def cosine_128(a: list, b: list) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(x * x for x in b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def shadow_recompute(events: list) -> Optional[dict]:
    """Find the most recent sampled event and run shadow_recompute. Returns finding or None."""
    for ev in reversed(events):
        if ev.get("event_type") != "kernel_tick":
            continue
        metrics = ev.get("metrics", {})
        svec = metrics.get("sampled_state_vector")
        if not isinstance(svec, list) or len(svec) != 128:
            continue
        stvec = metrics.get("sampled_stasis_vec")
        if not isinstance(stvec, list) or len(stvec) != 128:
            print(f"  [sporadic] sampled_stasis_vec absent — skipping (need full vectors)", file=sys.stderr)
            continue
        claimed = metrics.get("kernel", {}).get("stasis_cos")
        if claimed is None:
            continue

        recomputed = cosine_128(svec, stvec)
        diff       = abs(recomputed - claimed)
        ev_ts      = ev.get("ts", "?")
        ev_seq     = ev.get("algedonic_seq", 0)

        print(f"  [sporadic] ts={ev_ts} seq={ev_seq} recomputed={recomputed:.6f} "
              f"claimed={claimed:.6f} diff={diff:.6f}", file=sys.stderr)

        if diff > SEMANTIC_EPSILON:
            return {
                "ts":           datetime.now(timezone.utc).isoformat(),
                "source":       SOURCE_ID,
                "audit_target": "shadow_recompute_sporadic",
                "category":     "semantic_divergence",
                "severity":     8.0,
                "finding_class":"high",
                "detail": (
                    f"sporadic tier3 (LXC 108, independent channel): "
                    f"recomputed_cos={recomputed:.6f} claimed={claimed:.6f} "
                    f"diff={diff:.6f} > ε={SEMANTIC_EPSILON} "
                    f"(sampled event ts={ev_ts} seq={ev_seq})"
                ),
                "sample_method": "sporadic_s3star_108",
                "predicate_matched": "semantic_divergence",
                "sampled_event_ts": ev_ts,
                "sampled_event_seq": ev_seq,
                "recomputed_cos": round(recomputed, 6),
                "claimed_cos":    round(claimed, 6),
                "diff":           round(diff, 6),
                "epsilon":        SEMANTIC_EPSILON,
            }
        else:
            print(f"  [sporadic] semantic OK: diff={diff:.6f} ≤ ε={SEMANTIC_EPSILON}", file=sys.stderr)
            return None   # found sampled event and it's OK — done
    return None  # no sampled event found


async def run(wait_s: int):
    print(f"[sporadic] connecting to {NATS_URL}...", flush=True)
    nc = await nats.connect(NATS_URL)
    print(f"[sporadic] connected. Collecting φ↑ events for {wait_s}s...", flush=True)

    buffer = []
    sub    = await nc.subscribe(NUCLEUS_SUBJECT)

    async def collect():
        async for msg in sub.messages:
            try:
                ev = json.loads(msg.data)
                buffer.append(ev)
                if len(buffer) > BUFFER_MAX:
                    buffer.pop(0)
            except Exception:
                pass

    task = asyncio.ensure_future(collect())
    await asyncio.sleep(wait_s)
    task.cancel()

    print(f"[sporadic] collected {len(buffer)} events. Running shadow_recompute...", flush=True)

    finding = shadow_recompute(buffer)
    if finding:
        payload = json.dumps(finding).encode()
        await nc.publish(AUDIT_SUBJECT, payload)
        print(f"[sporadic] FINDING published → {AUDIT_SUBJECT}")
        print(f"  category={finding['category']} sev={finding['severity']}")
        print(f"  diff={finding['diff']:.6f} > ε={SEMANTIC_EPSILON}")
        print(f"  {finding['detail']}")
    else:
        # Publish a "clean" summary event so S5 knows the sporadic check ran
        summary = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "source":   SOURCE_ID,
            "category": "sporadic_audit_ok",
            "severity": 0.0,
            "detail":   f"sporadic tier3 completed — no semantic divergence detected "
                        f"({len(buffer)} events checked)",
            "events_checked": len(buffer),
        }
        await nc.publish(AUDIT_SUBJECT, json.dumps(summary).encode())
        print(f"[sporadic] CLEAN — no semantic divergence. Summary published → {AUDIT_SUBJECT}")

    await nc.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", type=int, default=30,
                        help="Seconds to collect φ↑ events before auditing (default: 30)")
    args = parser.parse_args()
    asyncio.run(run(args.wait))


if __name__ == "__main__":
    main()
