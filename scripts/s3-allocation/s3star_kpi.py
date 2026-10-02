#!/usr/bin/env python3
"""
S3* KPI Poller (Cyberstride S3*.a+b+e) — sporadic direct sampling of S1 KPIs
+ PERT-analog experiment-progress tracking (R1).

Reads nucleus φ↑ directly (RO bind-mount /mnt/telemetry/events.jsonl on LXC 107
— the S3* direct channel, bypassing S2 by design) → extracts kernel_tick KPIs →
appends to /var/lib/vsf/s3_star/kpi.db. Compares actuals against norm.vsm
bounds (the standing plan, F3.a) + detects stalls → exceptions table.

Experiment tracking (R1): parses index.vsm for status=running experiments;
flags overdue runs (>30d since start date, rate-limited 1/day) and records
each running experiment in poll_state so SA can correlate KPI deviations to
specific experiment phases.

Exceptions are SA-consumable (S3*.c wires them into sa_auditor's prompt).
Deterministic, local reads only — no LLM, no network (D6/R10).

Cron (LXC 107):
    */10 * * * * flock -n /var/lock/vsf_kpi.lock python3 /root/vsf-scripts/s3-allocation/s3star_kpi.py >> /var/log/vsf-kpi.log 2>&1
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import kpi_spc

EVENTS_PATH = os.environ.get('VSF_EVENTS_PATH', '/mnt/telemetry/events.jsonl')
KPI_DB      = os.environ.get('VSF_KPI_DB', '/var/lib/vsf/s3_star/kpi.db')
NORM_PATH   = os.environ.get('VSF_NORM_PATH', '/root/vsf-scripts/norm.vsm')
INDEX_PATH  = os.environ.get('VSF_EXP_INDEX', '/root/vsf-scripts/index.vsm')
TAIL_BYTES  = 256 * 1024          # read at most the last 256 KiB of the journal
EXP_OVERDUE_DAYS = 30             # flag running experiments older than this

# ── Algedonic publish (P2.4 — S3* exceptions → algedonic channel) ─────────────
NATS_URL      = os.environ.get('NATS_URL', 'nats://10.10.20.20:4222')
VSF_ID        = os.environ.get('VSF_ID', 'alpha')
_ALGED_SUBJ   = f'vsf.{VSF_ID}.algedonic'
_ALGED_KINDS  = frozenset({'out_of_norm', 'stall', 'telemetry_missing', 'governance_violation', 'spc_exception'})
_SEVERITY_MAP = {
    'telemetry_missing':   9,
    'out_of_norm':         6,
    'stall':               7,
    'governance_violation': 7,
    'spc_exception':       5,
}

try:
    import asyncio as _asyncio
    import nats as _nats_lib
    _NATS_OK = True
except ImportError:
    _NATS_OK = False


async def _nats_pub_async(payload: dict) -> None:
    nc = await _nats_lib.connect(NATS_URL, connect_timeout=5)
    await nc.publish(_ALGED_SUBJ, json.dumps(payload).encode())
    await nc.drain()


def _publish_algedonic(kind: str, detail: str, ref: str) -> bool:
    if not _NATS_OK:
        return False
    payload = {
        'ts':        now_iso(),
        'source_id': 's3star_kpi',
        'category':  kind,
        'severity':  _SEVERITY_MAP.get(kind, 5),
        'detail':    f'{detail} ({ref})',
    }
    try:
        _asyncio.run(_nats_pub_async(payload))
        return True
    except Exception as exc:
        print(f'KPI: algedonic publish failed: {exc}', file=sys.stderr)
        return False

# Fail-safe defaults — overridden by norm.vsm when present (mirrors ac_classifier)
NORM = {
    'stasis_warn': 0.80, 'stasis_critical': 0.70,
    'trust_warn': 0.8, 'regime_nominal': 'in_recurrent_set',
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_norm() -> str:
    """Block-aware key=value scan of norm.vsm; errors leave defaults standing."""
    if not os.path.exists(NORM_PATH):
        return 'built-in defaults'
    try:
        block, vals = None, {}
        with open(NORM_PATH, encoding='utf-8') as fh:
            for line in fh:
                line = line.split('//')[0].strip()
                m = re.match(r'^(\w+)\s*\{', line)
                if m:
                    block = m.group(1)
                    continue
                if line.startswith('}'):
                    block = None
                    continue
                m = re.match(r'^(\w+)\s*=\s*("?)([^"]*)\2', line)
                if m and block:
                    vals[f'{block}.{m.group(1)}'] = m.group(3).strip()
        NORM['stasis_warn']     = float(vals.get('stasis_cos.warn_below', NORM['stasis_warn']))
        NORM['stasis_critical'] = float(vals.get('stasis_cos.critical_below', NORM['stasis_critical']))
        NORM['trust_warn']      = float(vals.get('trust.warn_below', NORM['trust_warn']))
        NORM['regime_nominal']  = vals.get('regime.nominal', NORM['regime_nominal'])
        return NORM_PATH
    except Exception as exc:
        print(f'KPI: norm.vsm load failed ({exc}) — built-in defaults', file=sys.stderr)
        return 'built-in defaults'


def tail_events(path: str) -> tuple:
    """Parse last TAIL_BYTES of events.jsonl.
    Returns (ticks, raw_events): ticks = kernel_tick KPI dicts; raw_events = all parsed events."""
    with open(path, 'rb') as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - TAIL_BYTES))
        raw = fh.read().decode('utf-8', errors='replace')
    ticks, raw_events = [], []
    for line in raw.splitlines()[1:]:        # first line may be truncated
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw_events.append(e)
        if e.get('event_type') != 'kernel_tick':
            continue
        k = (e.get('metrics', {}) or {}).get('kernel', {}) or {}
        if k.get('stasis_cos') is None:
            continue
        ticks.append({
            'ts':         e.get('timestamp') or e.get('ts') or '',
            'tick':       k.get('tick'),
            'stasis_cos': k.get('stasis_cos'),
            'trust':      k.get('trust'),
            'viable':     k.get('viable'),
            'regime':     ((e.get('metrics', {}) or {}).get('lyapunov', {}) or {}).get('regime'),
        })
    return ticks, raw_events


def _check_param_change_integrity(ticks_raw: list) -> list:
    """C2.c integrity watch: flag param_change events missing _origin (governance violation).
    Scans the same tail events; only checks param_change event type."""
    violations = []
    for e in ticks_raw:
        if e.get('event_type') != 'param_change':
            continue
        metrics = e.get('metrics', {}) or {}
        origin = metrics.get('origin') or e.get('origin')
        if not origin:
            ts = e.get('timestamp') or e.get('ts') or '?'
            violations.append((
                'governance_violation',
                f'param_change at {ts} missing _origin — C2.c violation',
                'events.jsonl param_change',
            ))
    return violations


def _parse_running_experiments(path: str) -> list:
    """Scan index.vsm for exp blocks with status=running → [{id, name, date}]."""
    if not os.path.exists(path):
        return []
    running, cur_name = [], None
    try:
        with open(path, encoding='utf-8') as fh:
            for raw in fh:
                line = raw.split('//')[0].strip()
                m = re.match(r'^exp\((\w+)\)\s*:', line)
                if m:
                    cur_name = m.group(1)
                    continue
                if cur_name and 'status' in line and 'running' in line:
                    exp = {'name': cur_name}
                    for key in ('id', 'status', 'date'):
                        km = re.search(rf'\b{key}\s*=\s*(\S+)', line)
                        if km:
                            exp[key] = km.group(1).strip('"')
                    if exp.get('status') == 'running' and 'id' in exp:
                        running.append(exp)
    except Exception as exc:
        print(f'KPI: exp index parse error: {exc}', file=sys.stderr)
    return running


def _check_experiment_progress(conn: sqlite3.Connection, running_exps: list) -> list:
    """PERT analog: flag experiments overdue (>EXP_OVERDUE_DAYS since start date).
    Rate-limited to one exception per experiment per calendar day."""
    today = datetime.now(timezone.utc).date()
    exceptions = []
    for exp in running_exps:
        exp_id   = exp.get('id', 'UNKNOWN')
        exp_name = exp.get('name', exp_id)
        start_str = exp.get('date', '')

        # Record first observation of this experiment as running
        seen_key = f'exp_{exp_id}_running_since'
        if not conn.execute('SELECT 1 FROM poll_state WHERE key=?', (seen_key,)).fetchone():
            conn.execute("INSERT INTO poll_state(key, value) VALUES(?,?) "
                         'ON CONFLICT(key) DO NOTHING',
                         (seen_key, start_str or today.isoformat()))

        if not start_str:
            continue
        try:
            start_date = datetime.fromisoformat(start_str).date()
            age_days = (today - start_date).days
        except ValueError:
            continue

        if age_days > EXP_OVERDUE_DAYS:
            flag_key = f'exp_{exp_id}_overdue_flagged'
            row = conn.execute('SELECT value FROM poll_state WHERE key=?', (flag_key,)).fetchone()
            if not row or row[0] != today.isoformat():
                conn.execute("INSERT INTO poll_state(key, value) VALUES(?,?) "
                             'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                             (flag_key, today.isoformat()))
                exceptions.append((
                    'experiment_overdue',
                    f'{exp_id} status=running since {start_str} ({age_days}d) '
                    '— index.vsm may need status update',
                    f'index.vsm exp({exp_name})',
                ))
    return exceptions


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute("""CREATE TABLE IF NOT EXISTS kpi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_poll TEXT NOT NULL, ts_event TEXT, tick INTEGER,
        stasis_cos REAL, trust REAL, viable INTEGER, regime TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_poll TEXT NOT NULL, kind TEXT NOT NULL,
        detail TEXT NOT NULL, ref TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS poll_state (
        key TEXT PRIMARY KEY, value TEXT)""")
    return conn


def run() -> int:
    ts_poll = now_iso()
    norm_src = load_norm()
    print(f'[{ts_poll}] KPI poll — norm source: {norm_src}')

    running_exps = _parse_running_experiments(INDEX_PATH)
    print(f'KPI: {len(running_exps)} running experiment(s) tracked '
          f'({", ".join(e.get("id","?") for e in running_exps) or "none"})')

    exceptions = []          # (kind, detail, ref)

    if not os.path.exists(EVENTS_PATH):
        exceptions.append(('telemetry_missing',
                           f'{EVENTS_PATH} not found — mount or nucleus down', 'events.jsonl'))
        ticks, raw_events = [], []
    else:
        ticks, raw_events = tail_events(EVENTS_PATH)
        if not ticks:
            exceptions.append(('no_kernel_ticks',
                               'journal tail contains no kernel_tick events', 'events.jsonl'))
        # ── C2.c integrity watch: param_change events must have _origin ──────
        exceptions.extend(_check_param_change_integrity(raw_events))

    conn = connect(KPI_DB)
    latest = ticks[-1] if ticks else None

    # ── Experiment-progress tracking (R1 / PERT analog) ─────────────────────
    exp_exceptions = _check_experiment_progress(conn, running_exps)
    exceptions.extend(exp_exceptions)

    if latest:
        conn.execute(
            'INSERT INTO kpi (ts_poll, ts_event, tick, stasis_cos, trust, viable, regime) '
            'VALUES (?,?,?,?,?,?,?)',
            (ts_poll, latest['ts'], latest['tick'], latest['stasis_cos'],
             latest['trust'], 1 if latest['viable'] else 0, latest['regime']))

        # ── Plan comparison (norm.vsm = standing plan) ──────────────────────
        sc, tr = latest['stasis_cos'], latest['trust']
        if latest['viable'] is False:
            exceptions.append(('out_of_norm', 'viable=False', f"tick={latest['tick']}"))
        if sc is not None and sc < NORM['stasis_critical']:
            exceptions.append(('out_of_norm',
                               f"stasis_cos={sc:.4f} < critical {NORM['stasis_critical']}",
                               f"tick={latest['tick']}"))
        elif sc is not None and sc < NORM['stasis_warn']:
            exceptions.append(('out_of_norm',
                               f"stasis_cos={sc:.4f} < warn {NORM['stasis_warn']}",
                               f"tick={latest['tick']}"))
        if tr is not None and tr < NORM['trust_warn']:
            exceptions.append(('out_of_norm',
                               f"trust={tr:.3f} < {NORM['trust_warn']}",
                               f"tick={latest['tick']}"))
        if latest['regime'] is not None and latest['regime'] != NORM['regime_nominal']:
            exceptions.append(('out_of_norm', f"regime={latest['regime']}",
                               f"tick={latest['tick']}"))

        # ── Per-variable SPC (F3.c — EWMA + CUSUM, management by exception) ─
        spc_hits = kpi_spc.check_all(
            component='vsf-nucleus-operational',
            values={
                'stasis_cos': sc,
                'trust':      tr,
                'viable':     1 if latest['viable'] else 0,
            },
        )
        for var, reason in spc_hits:
            exceptions.append(('spc_exception', f'{var}: {reason}', f"tick={latest['tick']}"))

        # ── Stall detection (no new events since previous poll) ─────────────
        row = conn.execute("SELECT value FROM poll_state WHERE key='last_event_ts'").fetchone()
        if row and row[0] == latest['ts']:
            exceptions.append(('stall',
                               f"newest event ts unchanged since previous poll ({latest['ts']})",
                               'events.jsonl'))
        conn.execute("INSERT INTO poll_state(key, value) VALUES('last_event_ts', ?) "
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (latest['ts'],))

    now_hour = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
    for kind, detail, ref in exceptions:
        conn.execute('INSERT INTO exceptions (ts_poll, kind, detail, ref) VALUES (?,?,?,?)',
                     (ts_poll, kind, detail, ref))
        print(f'EXCEPTION [{kind}] {detail} ({ref})')
        # Algedonic publish: high-severity kinds only, rate-limited 1/hour per kind
        if kind in _ALGED_KINDS:
            rate_key = f'algedonic_pub_{kind}_{now_hour}'
            if not conn.execute('SELECT 1 FROM poll_state WHERE key=?', (rate_key,)).fetchone():
                conn.execute("INSERT INTO poll_state(key,value) VALUES(?,?) "
                             'ON CONFLICT(key) DO NOTHING', (rate_key, ts_poll))
                ok = _publish_algedonic(kind, detail, ref)
                print(f'KPI: algedonic →{_ALGED_SUBJ} [{kind}] published={ok}')

    conn.commit()
    n_kpi = conn.execute('SELECT COUNT(*) FROM kpi').fetchone()[0]
    conn.close()

    if latest and not exceptions:
        print(f"KPI: nominal — stasis_cos={latest['stasis_cos']:.4f} "
              f"trust={latest['trust']} regime={latest['regime']} (rows={n_kpi})")
    return 1 if exceptions else 0


if __name__ == '__main__':
    sys.exit(run())
