#!/usr/bin/env python3
"""
Variety Accounting (Cyberfilter F3.d) — daily attenuation ratio events_in/alerts_out.

Ashby compliance made measurable: how much variety the Cyberfilter absorbs.
events_in  = φ↑ events journaled today (events.jsonl on n02 host path)
alerts_out = alerts indexed today in s5-alerts.db (LXC 101, via pct exec python3)
ratio      = events_in / alerts_out (attenuation factor; higher = more absorption)

Writes one row per day into state.db variety_metrics (idempotent INSERT OR REPLACE).
Runs on n02 host.

Schedule (n02 host crontab):
    55 23 * * * python3 /usr/local/bin/variety_accounting.py >> /var/log/vsf-variety.log 2>&1
"""

import json
import socket
import sqlite3
import subprocess
import sys
import os
from datetime import datetime, timezone

STATE_DB    = os.environ.get('VSF_STATE_DB', '/var/lib/vsf-state/state.db')
EVENTS_PATH = os.environ.get('VSF_EVENTS_PATH',
                             '/var/lib/vsf-telemetry/vsf_nucleus/events.jsonl')
ALERTS_LXC  = int(os.environ.get('VSF_ALERTS_LXC', '101'))
ALERTS_DB   = '/root/.vsf/s4/s5-alerts.db'
NATS_HOST   = os.environ.get('NATS_HOST', '10.10.20.20')
NATS_PORT   = int(os.environ.get('NATS_PORT', '4222'))
VSF_ID      = os.environ.get('VSF_ID', 'alpha')
_SUBJ       = f'vsf.{VSF_ID}.algedonic'
VARIETY_WARN_RATIO = 0.1   # attenuation ratio floor before algedonic


def _nats_publish(payload: dict) -> None:
    body = json.dumps(payload).encode()
    try:
        with socket.create_connection((NATS_HOST, NATS_PORT), timeout=5) as s:
            s.recv(1024)
            s.sendall(b'CONNECT {}\r\n')
            s.sendall(f'PUB {_SUBJ} {len(body)}\r\n'.encode() + body + b'\r\n')
    except Exception as e:
        print(f'WARN: NATS publish failed: {e}', file=sys.stderr)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def count_events(day: str) -> int:
    """Lines in the φ↑ journal carrying today's ISO date."""
    r = subprocess.run(['grep', '-c', f'{day}T', EVENTS_PATH],
                       capture_output=True, text=True, timeout=120)
    # grep exits 1 on zero matches — that is a valid count, not an error
    if r.returncode in (0, 1) and r.stdout.strip().isdigit():
        return int(r.stdout.strip())
    raise RuntimeError(f'grep failed: {r.stderr.strip()}')


def count_alerts(day: str) -> int:
    """Alerts indexed today in s5-alerts.db (query runs inside the LXC)."""
    code = ('import sqlite3;'
            f'c = sqlite3.connect("{ALERTS_DB}");'
            f'print(c.execute("SELECT COUNT(*) FROM meta WHERE indexed_at LIKE ?",'
            f' ("{day}%",)).fetchone()[0])')
    r = subprocess.run(['/usr/sbin/pct', 'exec', str(ALERTS_LXC), '--', 'python3', '-c', code],
                       capture_output=True, text=True, timeout=30)
    if r.returncode == 0 and r.stdout.strip().isdigit():
        return int(r.stdout.strip())
    raise RuntimeError(f'alert count failed: {r.stderr.strip() or r.stdout.strip()}')


def run() -> int:
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f'[{now_iso()}] variety_accounting day={day}')

    try:
        events_in = count_events(day)
        alerts_out = count_alerts(day)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    ratio = round(events_in / alerts_out, 2) if alerts_out else None

    conn = sqlite3.connect(STATE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS variety_metrics (
        day TEXT PRIMARY KEY, events_in INTEGER, alerts_out INTEGER,
        ratio REAL, computed_at TEXT)""")
    conn.execute('INSERT OR REPLACE INTO variety_metrics VALUES (?,?,?,?,?)',
                 (day, events_in, alerts_out, ratio, now_iso()))
    conn.commit()
    conn.close()

    print(f'variety: events_in={events_in} alerts_out={alerts_out} '
          f'attenuation_ratio={ratio if ratio is not None else "n/a (0 alerts)"}')

    if events_in == 0:
        payload = {'ts': now_iso(), 'source_id': 'variety_accounting',
                   'category': 'telemetry_missing', 'severity': 7,
                   'detail': f'events_in=0 — nucleus telemetry absent for {day}'}
        print(f'ALGEDONIC: {json.dumps(payload)}')
        _nats_publish(payload)
    elif ratio is not None and ratio < VARIETY_WARN_RATIO:
        payload = {'ts': now_iso(), 'source_id': 'variety_accounting',
                   'category': 'variety_low', 'severity': 5,
                   'detail': f'attenuation_ratio={ratio} < {VARIETY_WARN_RATIO} '
                             f'(events_in={events_in} alerts_out={alerts_out})'}
        print(f'ALGEDONIC: {json.dumps(payload)}')
        _nats_publish(payload)

    return 0


if __name__ == '__main__':
    sys.exit(run())
