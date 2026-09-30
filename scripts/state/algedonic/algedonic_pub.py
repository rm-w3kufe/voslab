#!/usr/bin/env python3
"""
algedonic_pub.py — thin NATS publisher for the vsf.alpha.algedonic channel.

Runs inside LXC 101 (has nats-py + access to NATS on 10.10.20.20:4222).
Called by service_watchdog.py via:
    pct exec 101 -- python3 /root/vsf-scripts/algedonic_pub.py --json '{...}'
"""
import asyncio, nats, json, sys, argparse, os

NATS_URL = os.environ.get('NATS_URL', 'nats://10.10.20.20:4222')
SUBJECT  = 'vsf.alpha.algedonic'


async def _publish(payload: bytes) -> None:
    nc = await nats.connect(NATS_URL, connect_timeout=5)
    await nc.publish(SUBJECT, payload)
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
        json.loads(data)
    except Exception as e:
        print(f'algedonic_pub: invalid JSON: {e}', file=sys.stderr)
        return 1

    asyncio.run(_publish(data))
    print(f'algedonic_pub: published {len(data)}B to {SUBJECT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
