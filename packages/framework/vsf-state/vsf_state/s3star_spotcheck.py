#!/usr/bin/env python3
"""
S3* Random Spot-Check (Cyberstride S3*.d) — the genuinely SPORADIC direct audit.

Each run picks ONE random component from state.db and inspects it directly:
  1. binary hash vs latest deploys record (M6 machinery, single target)
  2. service active state (if a systemd unit with the component name exists)
Randomized target selection = Beer's sporadic channel: no component can predict
when it is next inspected. Results → state.db spot_checks; hash mismatch or
dead service → algedonic NATS publish.

Runs on n02 host (state.db + pct exec access).

Schedule (n02 host crontab):
    17 * * * * python3 /usr/local/bin/s3star_spotcheck.py >> /var/log/vsf-spotcheck.log 2>&1
"""

import json
import os
import random
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

STATE_DB  = os.environ.get('VSF_STATE_DB', '/var/lib/vsf-state/state.db')
NATS_HOST = os.environ.get('NATS_HOST', '10.10.20.20')
NATS_PORT = int(os.environ.get('NATS_PORT', '4222'))
VSF_ID    = os.environ.get('VSF_ID', 'alpha')
SUBJECT   = f'vsf.{VSF_ID}.algedonic'


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _nats_publish(payload: dict) -> None:
    body = json.dumps(payload).encode()
    try:
        with socket.create_connection((NATS_HOST, NATS_PORT), timeout=5) as s:
            s.recv(1024)
            s.sendall(b'CONNECT {}\r\n')
            s.sendall(f'PUB {SUBJECT} {len(body)}\r\n'.encode() + body + b'\r\n')
    except Exception as e:
        print(f'WARN: NATS publish failed: {e}', file=sys.stderr)


def _exec(lxc: int, args: list) -> subprocess.CompletedProcess:
    if lxc == 0:
        return subprocess.run(args, capture_output=True, text=True, timeout=20)
    return subprocess.run(['pct', 'exec', str(lxc), '--'] + args,
                          capture_output=True, text=True, timeout=25)


def run() -> int:
    conn = sqlite3.connect(STATE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS spot_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        component TEXT NOT NULL, lxc INTEGER, hash_ok INTEGER,
        service_state TEXT, note TEXT)""")

    components = conn.execute(
        'SELECT name, deploy_target_lxc, deploy_path FROM components '
        "WHERE deploy_path IS NOT NULL AND deploy_path != ''").fetchall()
    if not components:
        print('spot-check: no components declared — nothing to inspect')
        return 0

    name, lxc, path = random.choice(components)
    ts = now_iso()
    print(f'[{ts}] spot-check target: {name} (lxc={lxc})')

    findings = []

    # ── 1. binary hash vs deploys record ─────────────────────────────────────
    row = conn.execute(
        'SELECT to_sha FROM deploys WHERE component=? ORDER BY id DESC LIMIT 1',
        (name,)).fetchone()
    expected = row[0] if row else None
    hash_ok = None
    if expected:
        r = _exec(lxc, ['sha256sum', path])
        actual = r.stdout.strip().split()[0] if r.returncode == 0 and r.stdout.strip() else None
        if actual is None:
            findings.append(f'could not hash {path}')
        else:
            hash_ok = 1 if actual == expected else 0
            if not hash_ok:
                findings.append(f'HASH MISMATCH expected={expected[:16]} actual={actual[:16]}')
    else:
        findings.append('no deploy record (M6 gap)')

    # ── 2. service state (only if a unit by this name exists) ────────────────
    service_state = 'no-unit'
    r = _exec(lxc, ['systemctl', 'cat', name])
    if r.returncode == 0:
        r2 = _exec(lxc, ['systemctl', 'is-active', name])
        service_state = r2.stdout.strip() or 'unknown'
        if service_state != 'active':
            findings.append(f'service {name} is {service_state}')

    note = '; '.join(findings) if findings else 'ok'
    conn.execute('INSERT INTO spot_checks (ts, component, lxc, hash_ok, service_state, note) '
                 'VALUES (?,?,?,?,?,?)', (ts, name, lxc, hash_ok, service_state, note))
    conn.commit()
    conn.close()

    print(f'spot-check: hash_ok={hash_ok} service={service_state} note={note}')

    hard = [f for f in findings if 'MISMATCH' in f or f'is failed' in f or 'is inactive' in f]
    if hard:
        _nats_publish({'ts': ts, 'source_id': 's3star_spotcheck',
                       'category': 'spotcheck_violation', 'severity': 8,
                       'detail': f'{name} (lxc={lxc}): ' + '; '.join(hard)})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(run())
