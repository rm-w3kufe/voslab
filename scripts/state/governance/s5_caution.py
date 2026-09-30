#!/usr/bin/env python3
"""
S5 Caution Mode (SEC M3) — algedonic stress signal → 30-min autonomy ceiling.

When the system receives an s5_stress algedonic signal, caution mode is engaged:
all autonomous S4 actions (SA auditor, SD digest) defer or log-only until the
window expires. Caution state is persisted in s5_policy (state.db) so every
component can check it independently.

Commands:
    s5_caution.py set   [--minutes N]   — engage caution (default 30 min)
    s5_caution.py check                 — exit 0 if active, 1 if not; prints status
    s5_caution.py clear                 — lift caution immediately
    s5_caution.py init                  — add s5_stress to algedonic.allowed_categories

Caution mode is checked by sa_auditor.py at startup.
"""

import sqlite3
import json
import sys
import os
import argparse
from datetime import datetime, timezone, timedelta

STATE_DB = os.environ.get('VSF_STATE_DB', '/var/lib/vsf-state/state.db')
KEY_MODE    = 's5.caution_mode'
KEY_EXPIRES = 's5.caution_expires'
KEY_CATS    = 'algedonic.allowed_categories'


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _upsert(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        'INSERT INTO s5_policy(key, value) VALUES(?,?) '
        'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (key, value)
    )


def cmd_init(conn: sqlite3.Connection) -> int:
    row = conn.execute('SELECT value FROM s5_policy WHERE key=?', (KEY_CATS,)).fetchone()
    cats = json.loads(row[0]) if row else []
    if 's5_stress' not in cats:
        cats.append('s5_stress')
        _upsert(conn, KEY_CATS, json.dumps(cats))
        conn.commit()
        print(f"init: added s5_stress to {KEY_CATS}")
    else:
        print(f"init: s5_stress already in {KEY_CATS}")
    return 0


def cmd_set(conn: sqlite3.Connection, minutes: int) -> int:
    expires = (now_utc() + timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')
    _upsert(conn, KEY_MODE, 'true')
    _upsert(conn, KEY_EXPIRES, expires)
    conn.commit()
    print(f"caution: ENGAGED for {minutes} min — expires {expires}")
    return 0


def cmd_check(conn: sqlite3.Connection) -> int:
    row = conn.execute('SELECT value FROM s5_policy WHERE key=?', (KEY_MODE,)).fetchone()
    if not row or row[0] != 'true':
        print('caution: INACTIVE')
        return 1
    row_exp = conn.execute('SELECT value FROM s5_policy WHERE key=?', (KEY_EXPIRES,)).fetchone()
    if row_exp:
        expires = datetime.fromisoformat(row_exp[0].replace('Z', '+00:00'))
        if now_utc() > expires:
            print(f'caution: EXPIRED ({row_exp[0]})')
            return 1
        remaining = int((expires - now_utc()).total_seconds() // 60)
        print(f'caution: ACTIVE — expires {row_exp[0]} ({remaining} min remaining)')
    else:
        print('caution: ACTIVE (no expiry set)')
    return 0


def cmd_clear(conn: sqlite3.Connection) -> int:
    _upsert(conn, KEY_MODE, 'false')
    conn.commit()
    print('caution: CLEARED')
    return 0


def is_caution_active(db_path: str = STATE_DB) -> bool:
    """API for other scripts: returns True if caution mode is currently active."""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute('SELECT value FROM s5_policy WHERE key=?', (KEY_MODE,)).fetchone()
        if not row or row[0] != 'true':
            conn.close()
            return False
        row_exp = conn.execute('SELECT value FROM s5_policy WHERE key=?', (KEY_EXPIRES,)).fetchone()
        conn.close()
        if row_exp:
            expires = datetime.fromisoformat(row_exp[0].replace('Z', '+00:00'))
            return now_utc() <= expires
        return True
    except Exception:
        return False


def main() -> int:
    p = argparse.ArgumentParser(description='S5 caution mode manager (SEC M3)')
    p.add_argument('command', choices=['set', 'check', 'clear', 'init'])
    p.add_argument('--minutes', type=int, default=30)
    p.add_argument('--db', default=STATE_DB)
    a = p.parse_args()

    conn = sqlite3.connect(a.db)
    try:
        if a.command == 'init':    return cmd_init(conn)
        if a.command == 'set':     return cmd_set(conn, a.minutes)
        if a.command == 'check':   return cmd_check(conn)
        if a.command == 'clear':   return cmd_clear(conn)
    finally:
        conn.close()
    return 2


if __name__ == '__main__':
    sys.exit(main())
