#!/usr/bin/env python3
"""
algedonic_pub.py — thin NATS publisher for the vsf.alpha.algedonic channel.
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Runs inside LXC 101 (has nats-py + access to NATS on 10.10.20.20:4222).
Standalone CLI (no live callers in-repo; service_watchdog uses its own
raw-socket publisher): pct exec 101 -- python3 algedonic_pub.py --json '{...}'.

G1: token-auth + categorized subject. The old anonymous bare-subject publish
delivered nowhere (ledger subscribes vsf.<id>.algedonic.>), so the category
comes from the payload JSON and the subject always carries it; missing token
or missing category fails LOUD (exit 1), never silent.
"""
import asyncio, nats, json, sys, argparse, os

NATS_URL = os.environ.get('NATS_URL', 'nats://10.10.20.20:4222')
NATS_TOKEN = os.environ.get('NATS_TOKEN', '')
SUBJECT_BASE = 'vsf.alpha.algedonic'


async def _publish(payload: bytes, subject: str) -> None:
    if not NATS_TOKEN:
        print('algedonic_pub: NATS_TOKEN unset — refusing anonymous publish '
              '(anonymous delivers nowhere)', file=sys.stderr)
        sys.exit(1)
    nc = await nats.connect(NATS_URL, token=NATS_TOKEN, connect_timeout=5)
    await nc.publish(subject, payload)
    await nc.drain()


def main() -> int:
    p = argparse.ArgumentParser(description='Publish a JSON message to vsf.alpha.algedonic')
    p.add_argument('--json',  help='JSON payload string')
    p.add_argument('--stdin', action='store_true', help='read JSON from stdin')
    a = p.parse_args()

    if a.json:
        data = a.json.encode()
    elif a.stdin:
        data = sys.stdin.buffer.read()
    else:
        p.print_help()
        return 1

    try:
        obj = json.loads(data)
    except Exception as e:
        print(f'algedonic_pub: invalid JSON: {e}', file=sys.stderr)
        return 1
    cat = obj.get('category') if isinstance(obj, dict) else None
    if not cat or not str(cat).strip() or any(ch.isspace() for ch in str(cat)):
        print('algedonic_pub: payload needs a single-token category field '
              '(ledger subscribes per-category subjects); refusing '
              'bare-subject publish', file=sys.stderr)
        return 1

    subject = SUBJECT_BASE + '.' + str(cat)
    asyncio.run(_publish(data, subject))
    print(f'algedonic_pub: published {len(data)}B to {subject}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
