#!/usr/bin/env python3
"""
monitor_reconcile.py — unified monitoring instrument roll-up (P5.3).

Queries the last-seen timestamp for each registered instrument and emits
an algedonic signal (category=monitoring_gap, severity=4) for any instrument
that has not produced output within 2× its expected interval.

Runs on n02 host (has local access to state.db + pct exec to LXCs).

Schedule (n02 host crontab):
    0 */6 * * * python3 /usr/local/bin/monitor_reconcile.py >> /var/log/vsf/monitor_reconcile.log 2>&1

Accept criteria: stop s3star_kpi cron → next run emits monitoring_gap for s3star_kpi.
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta

# Resolve LXC IDs from topology.json (clone-portable)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from topology_resolve import resolve_lxc

_NUCLEUS_LXC = resolve_lxc("nucleus")
_STAR_LXC = resolve_lxc("s3-star")

STATE_DB   = os.environ.get('VSF_STATE_DB', '/var/lib/vsf-state/state.db')
NATS_HOST  = os.environ.get('NATS_HOST', '10.10.20.20')
NATS_PORT  = int(os.environ.get('NATS_PORT', '4222'))
VSF_ID     = os.environ.get('VSF_ID', 'alpha')
_SUBJ      = f'vsf.{VSF_ID}.algedonic'


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S+00:00', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _nats_publish(payload: dict) -> None:
    body = json.dumps(payload).encode()
    try:
        with socket.create_connection((NATS_HOST, NATS_PORT), timeout=5) as s:
            s.recv(1024)
            s.sendall(b'CONNECT {}\r\n')
            s.sendall(f'PUB {_SUBJ} {len(body)}\r\n'.encode() + body + b'\r\n')
    except Exception as e:
        print(f'WARN: NATS publish failed: {e}', file=sys.stderr)


# ── Instrument query functions ─────────────────────────────────────────────────

def _q_statedb(sql: str) -> str | None:
    try:
        conn = sqlite3.connect(STATE_DB)
        row = conn.execute(sql).fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception as e:
        print(f'WARN: state.db query failed ({sql[:40]}): {e}', file=sys.stderr)
        return None


def _q_lxc_sqlite(lxc: int, db_path: str, sql: str) -> str | None:
    code = f"import sqlite3; c=sqlite3.connect('{db_path}'); print(c.execute('{sql}').fetchone()[0] or '')"
    try:
        r = subprocess.run(
            ['pct', 'exec', str(lxc), '--', 'python3', '-c', code],
            capture_output=True, text=True, timeout=15,
        )
        val = r.stdout.strip()
        return val if val else None
    except Exception as e:
        print(f'WARN: lxc={lxc} sqlite query failed: {e}', file=sys.stderr)
        return None


def _q_systemd_last_run(unit: str) -> str | None:
    """Return UTC ISO timestamp of last exec via ExecMainStartTimestamp (works for oneshot units)."""
    import re
    try:
        r = subprocess.run(
            ['systemctl', 'show', unit, '--property=ExecMainStartTimestamp'],
            capture_output=True, text=True, timeout=5,
        )
        val = r.stdout.strip()  # e.g. "ExecMainStartTimestamp=Fri 2026-06-12 10:30:45 -04"
        if not val or '=' not in val:
            return None
        val = val.split('=', 1)[1].strip()
        if not val:
            return None
        m = re.search(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ([+-]\d{2,4})', val)
        if not m:
            return None
        date_s, time_s, tz_s = m.group(1), m.group(2), m.group(3)
        if len(tz_s) == 3:   # ±HH → ±HH:00
            tz_s += ':00'
        elif len(tz_s) == 5: # ±HHMM → ±HH:MM
            tz_s = tz_s[:3] + ':' + tz_s[3:]
        dt = datetime.fromisoformat(f'{date_s}T{time_s}{tz_s}')
        return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        print(f'WARN: systemctl show {unit} failed: {e}', file=sys.stderr)
        return None


def _q_log_mtime(path: str) -> str | None:
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except OSError:
        return None


# ── Instrument registry ────────────────────────────────────────────────────────
# (id, label, last_ts_fn, stale_secs)
# stale_secs = 2× expected interval; alert fires if now - last_ts > stale_secs

def _build_instruments() -> list:
    return [
        ('state_attest',
         'state.db chain_state.refreshed_at',
         lambda: _q_statedb('SELECT MAX(refreshed_at) FROM chain_state'),
         600),    # 2× 5 min
        ('topology_reconcile',
         'systemd ActiveEnterTimestamp vsf-topology-reconcile.service',
         lambda: _q_systemd_last_run('vsf-topology-reconcile.service'),
         600),    # 2× 5 min
         ('s3star_kpi',
          'kpi.db LXC {} kpi.ts_poll'.format(_STAR_LXC),
          lambda: _q_lxc_sqlite(_STAR_LXC, '/var/lib/vsf/s3_star/kpi.db',
                                 'SELECT MAX(ts_poll) FROM kpi'),
          1200),   # 2× 10 min
        ('s3star_spotcheck',
         'state.db spot_checks.ts',
         lambda: _q_statedb('SELECT MAX(ts) FROM spot_checks'),
         7200),   # 2× 1 h
        ('vsf_auditd',
         'state.db audits.ts',
         lambda: _q_statedb('SELECT MAX(ts) FROM audits'),
         14400),  # 2× 2 h (Poisson mean ~1/h)
        ('service_watchdog',
         'log mtime /var/log/vsf/watchdog.log',
         lambda: _q_log_mtime('/var/log/vsf/watchdog.log'),
         600),    # 2× 5 min
         ('ac_algedonic',
          's5-alerts.db LXC {} meta.indexed_at'.format(_NUCLEUS_LXC),
          lambda: _q_lxc_sqlite(_NUCLEUS_LXC, '/root/.vsf/s4/s5-alerts.db',
                                 'SELECT MAX(indexed_at) FROM meta'),
          7200),   # 2× 1 h (variety attenuation: max 1 class-C per hour)
        ('variety_accounting',
         'state.db variety_metrics.computed_at',
         lambda: _q_statedb('SELECT MAX(computed_at) FROM variety_metrics'),
         93600),  # 2× 26 h (daily cron)
        ('tasks_reconcile',
         'state.db task_drift.ts',
         lambda: _q_statedb('SELECT MAX(ts) FROM task_drift'),
         172800), # 2× 24 h (daily cron)
    ]


# ── Main ───────────────────────────────────────────────────────────────────────

def run() -> int:
    now = datetime.now(timezone.utc)
    ts_now = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'[{ts_now}] monitor_reconcile poll')

    instruments = _build_instruments()
    gaps = []

    for inst_id, label, query_fn, stale_secs in instruments:
        raw_ts = query_fn()
        last_dt = _parse_ts(raw_ts)
        if last_dt is None:
            age_s = None
            status = 'no-data'
        else:
            age_s = (now - last_dt).total_seconds()
            status = f'age={int(age_s)}s'

        is_stale = (age_s is None and stale_secs < 172800) or \
                   (age_s is not None and age_s > stale_secs)

        print(f'  {inst_id}: {status} (stale>{stale_secs}s) — {"STALE" if is_stale else "ok"}')

        if is_stale:
            gaps.append({
                'instrument': inst_id,
                'label': label,
                'last_ts': raw_ts,
                'age_s': int(age_s) if age_s is not None else None,
                'stale_threshold_s': stale_secs,
            })

    if gaps:
        payload = {
            'ts':        ts_now,
            'source_id': 'monitor_reconcile',
            'category':  'monitoring_gap',
            'severity':  4,
            'detail':    f'{len(gaps)} instrument(s) stale: '
                         + ', '.join(g['instrument'] for g in gaps),
            'gaps':      gaps,
        }
        print(f'ALGEDONIC: monitoring_gap — {payload["detail"]}')
        _nats_publish(payload)
        return 1

    print(f'monitor_reconcile: all {len(instruments)} instruments current')
    return 0


if __name__ == '__main__':
    sys.exit(run())
