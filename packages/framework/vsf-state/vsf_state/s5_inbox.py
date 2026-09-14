#!/usr/bin/env python3
"""
s5_inbox.py — S5 terminal inbox: CHECO + algedonic + chain + KPI + alerts.
Run:  python3 scripts/state/s5_inbox.py
      watch -n 120 python3 scripts/state/s5_inbox.py   (auto-refresh every 2min)

Reads via SSH to n02; no local state. Requires n02 reachable.
"""

import subprocess, json, sys, os

# Resolve LXC IDs from topology.json (clone-portable)
sys.path.insert(0, str(os.environ.get("VOSLAB_PATH", os.path.dirname(__file__))))
from topology_resolve import resolve_lxc

_STAR_LXC = resolve_lxc("s3star")
_NUCLEUS_LXC = resolve_lxc("nucleus")
from datetime import datetime, timezone

N02 = os.environ.get('VSF_N02', 'n02')
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']
W = 74

# ANSI
_R = '\033[31m'; _Y = '\033[33m'; _G = '\033[32m'; _C = '\033[36m'
_B = '\033[34m'; _M = '\033[35m'; _0 = '\033[0m'; _BO = '\033[1m'
_DIM = '\033[2m'


def _ssh(cmd: str, timeout: int = 12) -> tuple[str, bool]:
    try:
        r = subprocess.run(SSH + [N02, cmd], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode == 0
    except Exception as e:
        return f'[ssh error: {e}]', False


def _pct(lxc: int, cmd: str, timeout: int = 12) -> tuple[str, bool]:
    return _ssh(f"pct exec {lxc} -- bash -c {chr(39)}{cmd}{chr(39)}", timeout=timeout)


def _db(sql: str) -> tuple[str, bool]:
    return _ssh(f"sqlite3 /var/lib/vsf-state/state.db {chr(39)}{sql}{chr(39)}")


def hdr(title: str, color: str = _C) -> None:
    pad = '─' * max(0, (W - len(title) - 2) // 2)
    print(f'{color}{_BO}{pad} {title} {pad}{_0}')


def line(color: str = _DIM) -> None:
    print(f'{color}{"─" * W}{_0}')


def status_color(s: str) -> str:
    s = s.lower()
    if 'nominal' in s or 'ok' in s or 'stable' in s:
        return _G
    if 'warn' in s:
        return _Y
    if 'critical' in s or 'breach' in s or 'error' in s or 'fail' in s:
        return _R
    return _0


def main() -> None:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'\n{_BO}{"═" * W}{_0}')
    print(f'{_BO}  VSF S5 INBOX  ·  {now}{_0}')
    print(f'{_BO}{"═" * W}{_0}')

    # ── §1. CHECO PROJECTION ─────────────────────────────────────────────────
    hdr('§1  CHECO PROJECTION (S4 intelligence)')
    checo, ok = _pct(_STAR_LXC, 'cat /var/lib/vsf/s3_star/checo_report.vsm 2>/dev/null')
    if not ok or not checo:
        print(f'{_R}  CHECO report unavailable{_0}')
    else:
        for raw in checo.splitlines():
            ln = raw.strip()
            if not ln or ln.startswith('@vsm') or ln.startswith('//'):
                continue
            if 'status' in ln and '=' in ln:
                val = ln.split('=', 1)[1].strip().strip('"')
                c = status_color(val)
                print(f'  {_BO}status{_0}  = {c}{val}{_0}')
            elif 'action_hint' in ln:
                val = ln.split('=', 1)[1].strip().strip('"')
                c = status_color(val)
                print(f'  {c}{val}{_0}')
            elif any(k in ln for k in ('current', 'slope_per_h', 'ttb_warn_state',
                                        'ttb_critical_state', 'generated_at',
                                        'regime_current', 'viable_current')):
                print(f'  {ln}')

    # ── §2. KPI HEALTH (last row from kpi.db) ────────────────────────────────
    # sqlite3 CLI not installed in LXC 107 — use pct exec python3 (stdlib sqlite3)
    hdr('§2  KPI HEALTH (last poll)')
    kpi_py = (
        'import sqlite3; r=sqlite3.connect("/var/lib/vsf/s3_star/kpi.db")'
        '.execute("SELECT ts_poll,stasis_cos,trust,viable,regime FROM kpi '
        'ORDER BY ts_poll DESC LIMIT 1").fetchone(); '
        'print("|".join(str(x) for x in r) if r else "")'
    )
    kpi, ok = _ssh(f"pct exec {_STAR_LXC} -- python3 -c '{kpi_py}'")
    if ok and kpi:
        parts = kpi.split('|')
        if len(parts) >= 5:
            ts, sc, tr, vi, reg = parts[0], parts[1], parts[2], parts[3], parts[4]
            try:
                sc_c = _G if float(sc) > 0.90 else (_Y if float(sc) > 0.80 else _R)
                tr_c = _G if float(tr) > 0.80 else (_Y if float(tr) > 0.70 else _R)
            except ValueError:
                sc_c = tr_c = _0
            print(f'  ts_poll      = {_DIM}{ts}{_0}')
            print(f'  stasis_cos   = {sc_c}{sc}{_0}')
            print(f'  trust        = {tr_c}{tr}{_0}')
            print(f'  viable       = {_G if vi == "1" else _R}{vi}{_0}')
            print(f'  regime       = {reg}')
        else:
            print(f'  {_Y}unexpected kpi row format: {kpi}{_0}')
    else:
        print(f'  {_Y}kpi.db unavailable{_0}')

    # ── §3. CHAIN HEADS (AX-STATE) ───────────────────────────────────────────
    hdr('§3  CHAIN HEADS (AX-STATE)')
    chains, ok = _db(
        'SELECT chain_id,lxc,line_count,head_hash,last_event_ts '
        'FROM chain_state ORDER BY chain_id;')
    if ok and chains:
        for row in chains.splitlines():
            parts = row.split('|')
            if len(parts) >= 5:
                cid, lxc, lc, head, ts = parts[0], parts[1], parts[2], parts[3][:12], parts[4][:19]
                print(f'  {cid:<10}  LXC {lxc:>3}  lines={lc:>6}  head={_C}{head}…{_0}  {_DIM}{ts}{_0}')
    else:
        print(f'  {_Y}chain_state unavailable{_0}')

    # ── §4. ALERT COUNTS ─────────────────────────────────────────────────────
    hdr('§4  ALERT COUNTS')
    alerts, ok = _db('SELECT category,count,last_ts FROM alert_counts ORDER BY last_ts DESC;')
    if ok and alerts:
        for row in alerts.splitlines():
            parts = row.split('|')
            if len(parts) >= 3:
                cat, n, last = parts[0], parts[1], parts[2]
                c = _R if int(n or 0) > 5 else (_Y if int(n or 0) > 0 else _G)
                print(f'  {c}{cat:<30}{_0}  {n:>4}x  {_DIM}{last[:19]}{_0}')
    elif ok:
        print(f'  {_G}alert_counts: empty (no recorded alerts){_0}')
    else:
        print(f'  {_Y}alert_counts unavailable{_0}')

    # ── §5. RECENT ALGEDONIC EVENTS (φ↑ events.jsonl, LXC 101) ─────────────
    hdr('§5  RECENT ALGEDONIC EVENTS (φ↑, LXC 101)')
    evq = (r"tail -300 /var/lib/vsf/vsf_nucleus/events.jsonl 2>/dev/null | "
           r"python3 -c \"import sys,json;"
           r"[print(d.get('ts','?')[:19]+'|'+d.get('type','?')+'|'+(d.get('msg') or '')) "
           r"for ln in sys.stdin for d in [json.loads(ln)] "
           r"if d.get('type') in ('algedonic','L3','reframe_proposal') or d.get('level') in ('warn','critical')]\"")
    evs, ok = _pct(_NUCLEUS_LXC, evq, timeout=15)
    if ok and evs:
        for ev in evs.splitlines()[-8:]:
            parts = ev.split('|', 2)
            if len(parts) >= 2:
                ts, typ = parts[0].strip(), parts[1].strip()
                msg = parts[2].strip() if len(parts) > 2 else ''
                c = _R if 'critical' in typ or 'L3' in typ else (_Y if 'warn' in typ else _C)
                print(f'  {_DIM}{ts}{_0}  {c}{typ:<18}{_0}  {msg[:48]}')
    else:
        print(f'  {_DIM}no algedonic events in last 300 lines (φ↑ nominal){_0}')

    # ── §6. SA AUDITOR LAST RUN ───────────────────────────────────────────────
    # Meaningful SA log lines start with "SA:" — everything else is traceback/code context
    hdr('§6  SA AUDITOR (last run)')
    sa_py = (
        'lines=open("/var/log/vsf-sa.log").readlines(); '
        'sa=[l.rstrip() for l in lines if l.startswith("SA:")]; '
        'print("\\n".join(sa[-5:]))'
    )
    sa, ok = _ssh(f"pct exec {_STAR_LXC} -- python3 -c '{sa_py}' 2>/dev/null")
    if ok and sa:
        for ln in sa.splitlines():
            ln = ln.strip()
            if ln:
                c = _R if ('error' in ln.lower() or 'fail' in ln.lower()
                            or 'SCP' in ln or 'Timeout' in ln) else _0
                print(f'  {c}{ln[:W-4]}{_0}')
    elif ok:
        print(f'  {_DIM}SA log empty or no SA: lines yet{_0}')
    else:
        print(f'  {_Y}SA auditor log unavailable{_0}')

    # ── §7. RECENT GATE AUDITS (build/certify gates g2-g5) ──────────────────
    hdr('§7  RECENT GATE AUDITS')
    rf, ok = _db("SELECT ts,gate,passed,duration_s FROM audits "
                 "ORDER BY ts DESC LIMIT 6;")
    if ok and rf:
        for row in rf.splitlines():
            parts = row.split('|')
            if len(parts) >= 4:
                ts, gate, passed, dur = parts[0], parts[1], parts[2], parts[3]
                c = _G if passed == '1' else _R
                dot = '●' if passed == '1' else '○'
                dur_s = f'{float(dur):.1f}s' if dur else '?'
                print(f'  {c}{dot}{_0}  {gate}  {dur_s:>8}  {_DIM}{ts[:19]}{_0}')
    elif ok:
        print(f'  {_DIM}no gate audits recorded yet{_0}')
    else:
        print(f'  {_DIM}audits table unavailable{_0}')

    # ── §8. SERVICES HEALTH ───────────────────────────────────────────────────
    hdr('§8  SERVICES')
    svcs, ok = _db('SELECT lxc, name, active FROM services ORDER BY lxc, name;')
    if ok and svcs:
        for row in svcs.splitlines():
            parts = row.split('|')
            if len(parts) >= 3:
                lxc, name, active = parts
                c = _G if active == '1' else _R
                dot = '●' if active == '1' else '○'
                print(f'  {c}{dot}{_0}  LXC {lxc:>3}  {name}')
    else:
        print(f'  {_Y}services unavailable{_0}')

    print(f'\n{_DIM}{"─" * W}{_0}')
    print(f'{_DIM}  tip: watch -n 120 python3 scripts/state/s5_inbox.py{_0}\n')


if __name__ == '__main__':
    main()
