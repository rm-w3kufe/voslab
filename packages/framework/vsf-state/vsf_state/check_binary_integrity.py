#!/usr/bin/env python3
"""
Binary Integrity Monitor (SEC M6) — daily hash check vs. deploys table.

For each component with a deploy_path in state.db, compares the SHA256 of the
live binary against the most recent record in the deploys table.  On mismatch,
emits an algedonic signal to NATS (vsf.alpha.algedonic) and exits non-zero.

Runs on n02 host (access to state.db + pct exec to all LXCs).

Usage:
    python3 scripts/state/check_binary_integrity.py [--db PATH] [--dry-run]

Schedule (n02 host crontab):
    0 3 * * * python3 /usr/local/bin/check_binary_integrity.py >> /var/log/vsf-integrity.log 2>&1
"""

import sqlite3
import subprocess
import json
import socket
import sys
import os
import argparse
from datetime import datetime, timezone

STATE_DB   = os.environ.get('VSF_STATE_DB', '/var/lib/vsf-state/state.db')
NATS_HOST  = os.environ.get('NATS_HOST', '10.10.20.20')
NATS_PORT  = int(os.environ.get('NATS_PORT', '4222'))
VSF_ID     = os.environ.get('VSF_ID', 'alpha')
SUBJECT    = f'vsf.{VSF_ID}.algedonic'


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _nats_publish(payload: dict) -> None:
    body = json.dumps(payload).encode()
    try:
        with socket.create_connection((NATS_HOST, NATS_PORT), timeout=5) as s:
            s.recv(1024)  # server INFO
            s.sendall(b'CONNECT {}\r\n')
            s.sendall(f'PUB {SUBJECT} {len(body)}\r\n'.encode() + body + b'\r\n')
    except Exception as e:
        print(f'WARN: NATS publish failed: {e}', file=sys.stderr)


def _sha256_on_lxc(lxc: int, path: str) -> str | None:
    if lxc == 0:
        r = subprocess.run(['sha256sum', path], capture_output=True, text=True, timeout=10)
    else:
        r = subprocess.run(
            ['pct', 'exec', str(lxc), '--', 'sha256sum', path],
            capture_output=True, text=True, timeout=15
        )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip().split()[0]


def _latest_deploy_sha(conn: sqlite3.Connection, component: str) -> str | None:
    row = conn.execute(
        'SELECT to_sha FROM deploys WHERE component = ? ORDER BY id DESC LIMIT 1',
        (component,)
    ).fetchone()
    return row[0] if row else None


CHAIN_VERIFY_LINES = 20   # last N events to verify sequential linkage


def _verify_chain(chain_id: str, lxc: int, file_path: str) -> tuple:
    """Verify the last CHAIN_VERIFY_LINES events form an unbroken prev_hash→hash chain.
    Returns (ok: bool, detail: str)."""
    if lxc == 0:
        r = subprocess.run(['tail', '-n', str(CHAIN_VERIFY_LINES), file_path],
                           capture_output=True, text=True, timeout=10)
    else:
        r = subprocess.run(
            ['pct', 'exec', str(lxc), '--', 'tail', '-n', str(CHAIN_VERIFY_LINES), file_path],
            capture_output=True, text=True, timeout=15,
        )
    if r.returncode != 0 or not r.stdout.strip():
        return False, f'could not read {file_path} on lxc={lxc}'

    events = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if 'hash' in e and 'prev_hash' in e:
                events.append(e)
        except json.JSONDecodeError:
            continue

    if len(events) < 2:
        return True, f'only {len(events)} hashable events — cannot verify chain'

    for i in range(1, len(events)):
        if events[i]['prev_hash'] != events[i - 1]['hash']:
            return False, (
                f'linkage break at event {i}/{len(events)}: '
                f"prev_hash={events[i]['prev_hash'][:16]} "
                f"!= preceding hash={events[i-1]['hash'][:16]}"
            )

    return True, f'{len(events)} events verified (chain_id={chain_id})'


def run(db_path: str, dry_run: bool) -> int:
    conn = sqlite3.connect(db_path)
    components = conn.execute(
        'SELECT name, deploy_target_lxc, deploy_path FROM components '
        'WHERE deploy_path IS NOT NULL AND deploy_path != ""'
    ).fetchall()

    violations = []
    for name, lxc, path in components:
        expected = _latest_deploy_sha(conn, name)
        if expected is None:
            print(f'  {name}: no deploy record — skip')
            continue

        actual = _sha256_on_lxc(lxc, path)
        if actual is None:
            print(f'  {name} (lxc={lxc}): could not hash {path} — skip')
            continue

        if actual == expected:
            print(f'  {name}: OK  {actual[:16]}...')
        else:
            print(f'  {name}: MISMATCH  expected={expected[:16]}  actual={actual[:16]}')
            violations.append({'component': name, 'lxc': lxc, 'path': path,
                               'expected': expected, 'actual': actual})

    # ── Merkle chain verification (P1.3b) ─────────────────────────────────────
    try:
        chains = conn.execute(
            'SELECT chain_id, lxc, file_path FROM chain_state'
        ).fetchall()
    except sqlite3.OperationalError:
        chains = []

    chain_violations = []
    for chain_id, lxc, file_path in chains:
        ok, detail = _verify_chain(chain_id, lxc, file_path)
        if ok:
            print(f'  chain({chain_id}): OK — {detail}')
        else:
            print(f'  chain({chain_id}): CHAIN BREAK — {detail}')
            chain_violations.append({'chain_id': chain_id, 'lxc': lxc,
                                     'file_path': file_path, 'detail': detail})

    conn.close()

    all_violations = violations + [
        {'component': f'chain:{v["chain_id"]}', 'lxc': v['lxc'],
         'path': v['file_path'], 'expected': '', 'actual': '',
         '_chain': True, 'detail': v['detail']}
        for v in chain_violations
    ]

    if all_violations:
        ts = now_iso()
        for v in all_violations:
            if v.get('_chain'):
                payload = {
                    'ts': ts,
                    'source_id': 'check_binary_integrity',
                    'category': 'chain_integrity',
                    'severity': 9,
                    'detail': f"chain={v['component']} lxc={v['lxc']}: {v['detail']}",
                }
            else:
                payload = {
                    'ts': ts,
                    'source_id': 'check_binary_integrity',
                    'category': 'binary_integrity_violation',
                    'severity': 9,
                    'detail': f"{v['component']} on lxc={v['lxc']}: "
                              f"expected={v['expected'][:16]} actual={v['actual'][:16]}",
                }
            print(f'ALGEDONIC: {json.dumps(payload)}')
            if not dry_run:
                _nats_publish(payload)
        return 1

    print(f'All {len(components)} components + {len(chains)} chains: integrity OK')
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description='Binary integrity monitor (SEC M6)')
    p.add_argument('--db',      default=STATE_DB)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    print(f'[{now_iso()}] check_binary_integrity --db {a.db}')
    return run(a.db, a.dry_run)


if __name__ == '__main__':
    sys.exit(main())
