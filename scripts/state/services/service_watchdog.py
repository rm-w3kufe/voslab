#!/usr/bin/env python3
"""
service_watchdog.py — n02 host, cron */5 min (P1.2).

Checks critical VSF services + NATS connectivity + disk + Ollama health.
On failure: publishes to vsf.alpha.algedonic via pct exec 101 algedonic_pub.py.
Writes every run to LOG_PATH for offline audit.

UPDATED: Now uses socratic engine for health classification via health_check.tree.vsm
Predicates: service_active, nats_reachable, nats_authenticated, disk_ok, alerts_db_ok

Install (run once as root on n02):
    cp /tmp/service_watchdog.py /root/vsf-scripts/service_watchdog.py
    chmod +x /root/vsf-scripts/service_watchdog.py
    echo "*/5 * * * * root python3 /root/vsf-scripts/service_watchdog.py >> /var/log/vsf/watchdog.log 2>&1" \
         >> /etc/cron.d/vsf-watchdog
"""
import subprocess, json, datetime, sys, os, socket
from pathlib import Path

# Add classifier path for socratic engine.
# FND-SVC-WATCHDOG-ROOT-DRIFT-01: the old path appended "scripts" to
# parents[2] (already .../scripts) and imported a _ROOT the engine copy
# never exported — derive both locally instead.
_ROOT = Path(__file__).resolve().parents[3]  # repo root
sys.path.insert(0, str(_ROOT / "scripts" / "vsl" / "classifier"))
from vsf_socratic_engine import _create_engine

VSF_ID      = os.environ.get('VSF_ID', 'alpha')
_ALGED_SUBJ = f'vsf.{VSF_ID}.algedonic'

# Load tree — health_check.tree.vsm is canonical under VSF_ROOT's
# .opencode (vOSlab ships without this tree); repo-local copy wins if present.
# S5 containment: the tree now ships in THIS workspace (copied 2026-10-04);
# env VSF_ROOT still overrides for operators that run against the upstream tree.
_TREE_ROOT = _ROOT if (_ROOT / ".opencode/plugins/support/trees/health_check.tree.vsm").exists() \
    else Path(os.environ.get("VSF_ROOT") or _ROOT)
TREE = _TREE_ROOT / ".opencode/plugins/support/trees/health_check.tree.vsm"

# ── Config ─────────────────────────────────────────────────────────────────────

SERVICES = [
    (101, 'vsf-nucleus-operational'),
    (101, 'vsf-motor2'),
    (110, 'ollama'),  # ollama's canonical home is 110 (s4-intelligence),
                      # moved off 101 by 2026-07-13; this check watched
                      # the wrong node ever since -- invisible until the
                      # pct-PATH bug fix above restored real signal
    (104, 'vsf-s5-algedonic'),
    (104, 'vsf-s3-phidown-actuator'),
    (106, 'nats-server'),
    (107, 'vsf-s3-star'),
    (109, 'vsf-view-host'),
]

NATS_HOST          = os.environ.get('VSF_NATS_HOST', '10.10.20.20')
NATS_PORT          = int(os.environ.get('VSF_NATS_PORT', '4222'))
NATS_TOKEN         = os.environ.get('VSF_NATS_TOKEN', '')  # no default on
                            # purpose -- must be set in the cron.d environment,
                            # never hardcoded/committed. Empty = auth-dependent
                            # checks/publishes degrade gracefully (logged, not
                            # silently pretended to succeed).
DISK_PATH          = '/var/lib/vsf/'          # checked inside LXC 101
DISK_WARN_PCT      = 85
ALGEDONIC_PUB      = '/root/vsf-scripts/algedonic_pub.py'
LOG_PATH           = '/var/log/vsf/watchdog.log'
ALERTS_DB_PATH     = '/root/.vsf/s4/s5-alerts.db'  # inside LXC 101
ALERTS_ROW_WARN    = 50_000
ALERTS_SIZE_WARN   = 500 * 1024 * 1024   # 500 MB


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _log(msg: str) -> None:
    line = f'{_ts()} {msg}'
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, 'a') as fh:
            fh.write(line + '\n')
    except OSError:
        pass


PCT_BIN = '/usr/sbin/pct'  # hardcoded: cron's minimal PATH doesn't include
                            # /usr/sbin, so bare 'pct' fails with
                            # FileNotFoundError on every cron-triggered run
                            # (found 2026-08-02, broken since deployment
                            # 2026-06-12 -- see docs/spec/sensor_omega_integration)


def _pct_exec(lxc: int, cmd: list, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PCT_BIN, 'exec', str(lxc), '--'] + cmd,
        capture_output=True, text=True, timeout=timeout
    )


# ── Checks ─────────────────────────────────────────────────────────────────────

def check_service(lxc: int, svc: str) -> tuple:
    try:
        r = _pct_exec(lxc, ['systemctl', 'is-active', svc])
        state = r.stdout.strip()
        return state == 'active', state
    except Exception as e:
        return False, str(e)[:80]


def check_nats() -> tuple:
    """Shallow probe: TCP connect + read the (unauthenticated) INFO banner.
    Cheap and fast, but insufficient alone -- NATS can accept a raw
    connection and hand out INFO while unable to actually serve real
    authenticated clients (verified live during the 2026-08-01/02 incident:
    this passed for ~20h while vsf-s4-clima-bridge's real connections kept
    failing). See check_nats_deep() for the real-traffic-equivalent probe."""
    try:
        s = socket.create_connection((NATS_HOST, NATS_PORT), timeout=5)
        s.recv(64)
        s.close()
        return True, 'reachable'
    except Exception as e:
        return False, str(e)[:80]


def check_nats_deep() -> tuple:
    """Deep probe: real authenticated CONNECT + PING/PONG round trip, same
    protocol steps a genuine client (e.g. vsf-s4-clima-bridge) performs.
    Closes the false-all-clear gap check_nats() alone has."""
    if not NATS_TOKEN:
        return True, 'skipped (VSF_NATS_TOKEN not configured)'
    connect = json.dumps({
        'verbose': False, 'pedantic': False,
        'auth_token': NATS_TOKEN, 'name': 'vsf-service-watchdog-deep',
    }).encode()
    try:
        s = socket.create_connection((NATS_HOST, NATS_PORT), timeout=5)
        s.settimeout(5)
        info = s.recv(4096)
        if not info.startswith(b'INFO'):
            s.close()
            return False, f'no INFO banner: {info[:40]!r}'
        s.sendall(b'CONNECT ' + connect + b'\r\n')
        s.sendall(b'PING\r\n')
        resp = s.recv(256)
        s.close()
        if b'PONG' in resp:
            return True, 'authenticated'
        if b'-ERR' in resp:
            return False, f'auth rejected: {resp[:60]!r}'
        return False, f'unexpected response: {resp[:60]!r}'
    except Exception as e:
        return False, str(e)[:80]


def check_disk() -> tuple:
    try:
        r = _pct_exec(101, ['df', '--output=pcent', DISK_PATH])
        lines = [l.strip() for l in r.stdout.splitlines()
                 if l.strip() and l.strip() != 'Use%']
        if not lines:
            return True, 'no-data'
        pct = int(lines[-1].rstrip('%'))
        return pct < DISK_WARN_PCT, f'{pct}%'
    except Exception as e:
        return False, str(e)[:80]


def check_alerts_db() -> tuple:
    code = (
        f"import sqlite3,os; db='{ALERTS_DB_PATH}'; "
        f"sz=os.path.getsize(db) if os.path.exists(db) else -1; "
        f"n=sqlite3.connect(db).execute('SELECT COUNT(*) FROM meta').fetchone()[0] "
        f"if sz>=0 else -1; print(n,sz)"
    )
    try:
        r = _pct_exec(101, ['python3', '-c', code], timeout=15)
        if r.returncode != 0 or not r.stdout.strip():
            return True, 'no-data'
        parts = r.stdout.strip().split()
        rows, size = int(parts[0]), int(parts[1])
        if rows > ALERTS_ROW_WARN or size > ALERTS_SIZE_WARN:
            return False, f'rows={rows} size={size // 1024 // 1024}MB'
        return True, f'rows={rows} size={size // 1024 // 1024}MB'
    except Exception as e:
        return True, f'check-error: {str(e)[:60]}'


def check_ollama() -> tuple:
    try:
        r = _pct_exec(110, ['curl', '-sf', '--max-time', '5',
                             'http://localhost:11434/api/tags'])
        return r.returncode == 0, 'ok' if r.returncode == 0 else r.stderr[:60]
    except Exception as e:
        return False, str(e)[:80]


# ── Alert ──────────────────────────────────────────────────────────────────────

def _publish_algedonic(severity: int, category: str, detail: str) -> None:
    """Publish via raw NATS socket (n02 host has direct LAN access to LXC 106).

    FOUND 2026-08-02: this previously sent CONNECT {} with no auth token --
    NATS rejects that with -ERR 'Authorization Violation' on every call, and
    since the old code never read a response after sending, it silently
    believed every publish succeeded. Verified live: zero rows from
    source='service_watchdog' ever landed in the real ledger
    (/root/algedonic/ledger.db, LXC 104) across this watchdog's entire ~7-week
    history. Fixed: send the real token, and actually read+check the
    post-CONNECT response so a future auth regression logs loudly instead of
    failing silently again."""
    body = json.dumps({
        'ts':        _ts(),
        'source_id': 'service_watchdog',
        'category':  category,
        'severity':  severity,
        'detail':    detail,
    }).encode()
    connect = json.dumps({
        'verbose': False, 'pedantic': False,
        'auth_token': NATS_TOKEN, 'name': 'vsf-service-watchdog',
    }).encode()
    try:
        with socket.create_connection((NATS_HOST, NATS_PORT), timeout=5) as s:
            s.settimeout(5)
            s.recv(1024)  # INFO banner
            s.sendall(b'CONNECT ' + connect + b'\r\n')
            s.sendall(f'PUB {_ALGED_SUBJ} {len(body)}\r\n'.encode() + body + b'\r\n')
            s.sendall(b'PING\r\n')
            resp = s.recv(256)
            if b'-ERR' in resp:
                _log(f'WATCHDOG: algedonic publish REJECTED by NATS: {resp[:80]!r}')
            elif b'PONG' not in resp:
                _log(f'WATCHDOG: algedonic publish — unexpected NATS response: {resp[:80]!r}')
    except Exception as e:
        _log(f'WATCHDOG: algedonic publish failed: {e}')


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    failures: list = []
    warnings: list = []

    for lxc, svc in SERVICES:
        ok, state = check_service(lxc, svc)
        _log(f'svc lxc{lxc}/{svc}: {"OK" if ok else "FAIL(" + state + ")"}')
        if not ok:
            failures.append(f'lxc{lxc}/{svc}={state}')

    ok, msg = check_nats()
    _log(f'nats {NATS_HOST}:{NATS_PORT}: {"OK" if ok else "FAIL(" + msg + ")"}')
    if not ok:
        _log(f'WATCHDOG ALERT sev=7 nats_unreachable: {msg}')
        _publish_algedonic(7, 'service_down', f'NATS unreachable: {msg}')

    ok, msg = check_nats_deep()
    _log(f'nats-deep {NATS_HOST}:{NATS_PORT}: {"OK" if ok else "FAIL(" + msg + ")"}')
    if not ok:
        _log(f'WATCHDOG ALERT sev=7 nats_degraded: {msg}')
        _publish_algedonic(7, 'service_down', f'NATS degraded (shallow probe OK, real auth failed): {msg}')

    ok, msg = check_disk()
    _log(f'disk lxc101:{DISK_PATH}: {msg}')
    if not ok:
        _log(f'WATCHDOG ALERT sev=7 disk_pressure: {msg}')
        _publish_algedonic(7, 'disk_pressure', f'disk pressure lxc101: {msg}')

    ok, msg = check_ollama()
    _log(f'ollama lxc110: {"OK" if ok else "FAIL(" + msg + ")"}')
    if not ok:
        _log(f'WATCHDOG ALERT sev=5 ollama_health: {msg}')
        _publish_algedonic(5, 'ollama_health', f'Ollama unreachable: {msg}')

    ok, msg = check_alerts_db()
    _log(f'alerts_db lxc101: {msg}')
    if not ok:
        _log(f'WATCHDOG WARN sev=5 alerts_db_pressure: {msg}')
        _publish_algedonic(5, 'disk_pressure', f'alerts_db pressure: {msg}')

    if failures:
        detail = 'SERVICE DOWN: ' + ', '.join(failures)
        _log(f'WATCHDOG ALERT sev=9 service_down: {detail}')
        _publish_algedonic(9, 'service_down', detail)
        return 1

    _log('WATCHDOG: all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
