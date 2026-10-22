#!/usr/bin/env python3
"""
TASKS.vsm Drift Reconciler (DEBT-42) — report-only.

Scans TASKS.vsm for non-done tasks (open, seed, partial, deferred),
extracts evidence anchors (file=, path=, commit=, @ref), and verifies
each anchor against:
  1. Local filesystem (relative to VSF_ROOT)
  2. Git history (commit hash check via git cat-file)
  3. state.db deploys table (via SSH to n02 or local path)

Drift classes reported:
  ANCHOR_MISSING  — open task references a file/path that does not exist
  ANCHOR_EXISTS   — open task has a file anchor that exists (may be done)
  COMMIT_ABSENT   — referenced commit not in git history
  DEPLOY_PRESENT  — commit in deploys table (evidence task is deployed)
  STEP_DONE_BUT_OPEN — task has at least one step marked "done" inline

Run from VSF_ROOT (~/vsf) or set VSF_ROOT env var.

Usage:
    python3 scripts/state/tasks_reconcile.py [--state-db PATH] [--verbose]
"""

from pathlib import Path
import argparse
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

# S5 containment 2026-10-04: workspace root default (VSF_ROOT env still
# wins for upstream/covenant workflows).
VSF_ROOT = os.environ.get('VSF_ROOT') or os.environ.get('VOSLAB_PATH') \
    or str(Path(__file__).resolve().parents[3])
TASKS_FILE = os.path.join(VSF_ROOT, 'TASKS.vsm')
STATE_DB   = os.environ.get('VSF_STATE_DB', '/var/lib/vsf-state/state.db')
NATS_HOST  = os.environ.get('NATS_HOST', '10.10.20.20')
NATS_PORT  = int(os.environ.get('NATS_PORT', '4222'))
N02_SSH    = os.environ.get('N02_SSH', 'root@n02')
VSF_ID     = os.environ.get('VSF_ID', 'alpha')
_SUBJ      = f'vsf.{VSF_ID}.algedonic'
NON_DONE_STATUSES = {'open', 'seed', 'partial', 'deferred'}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _nats_publish(payload: dict) -> None:
    body = json.dumps(payload).encode()
    # Direct path (running on n02 host or LXC with VLAN20 access)
    try:
        with socket.create_connection((NATS_HOST, NATS_PORT), timeout=5) as s:
            s.recv(1024)
            s.sendall(b'CONNECT {}\r\n')
            s.sendall(f'PUB {_SUBJ} {len(body)}\r\n'.encode() + body + b'\r\n')
        return
    except Exception:
        pass
    # SSH relay via n02 (WSL path — VLAN20 not reachable directly)
    relay = (
        f"import socket, json\n"
        f"body = {json.dumps(json.dumps(payload))!r}.encode()\n"
        f"s = socket.create_connection(('{NATS_HOST}', {NATS_PORT}), 5)\n"
        f"s.recv(1024); s.sendall(b'CONNECT {{}}\\r\\n')\n"
        f"s.sendall(b'PUB {_SUBJ} ' + str(len(body)).encode() + b'\\r\\n' + body + b'\\r\\n')\n"
        f"s.close()\n"
    )
    try:
        r = subprocess.run(['ssh', N02_SSH, 'python3 -'],
                           input=relay, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            print(f'WARN: NATS relay failed: {r.stderr.strip()[:120]}', file=sys.stderr)
    except Exception as e:
        print(f'WARN: NATS publish failed: {e}', file=sys.stderr)


def _persist_findings(findings: list, db_path: str) -> int:
    """Write findings to state.db task_drift table. Returns row count inserted."""
    ts = _now_iso()
    rows = [{'task': f['task'], 'cls': f['class'], 'detail': f.get('detail', '')}
            for f in findings]

    # Local path (running on n02 or where state.db is mounted)
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS task_drift (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, task_id TEXT NOT NULL,
            finding TEXT NOT NULL, detail TEXT)""")
        for r in rows:
            conn.execute('INSERT INTO task_drift(ts, task_id, finding, detail) VALUES(?,?,?,?)',
                         (ts, r['task'], r['cls'], r['detail']))
        conn.commit()
        conn.close()
        return len(rows)

    # SSH fallback: write to n02 state.db via Python stdin relay (base64 to avoid quoting)
    import base64 as _b64
    payload_b64 = _b64.b64encode(json.dumps({'ts': ts, 'rows': rows, 'db': db_path}).encode()).decode()
    script = (
        f"import sqlite3, json, base64\n"
        f"p = json.loads(base64.b64decode('{payload_b64}').decode())\n"
        f"db = sqlite3.connect(p['db'])\n"
        f"db.execute('CREATE TABLE IF NOT EXISTS task_drift "
        f"(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        f"task_id TEXT NOT NULL, finding TEXT NOT NULL, detail TEXT)')\n"
        f"for r in p['rows']:\n"
        f"    db.execute('INSERT INTO task_drift(ts,task_id,finding,detail) VALUES(?,?,?,?)',\n"
        f"               (p['ts'], r['task'], r['cls'], r['detail']))\n"
        f"db.commit(); print(len(p['rows']))\n"
    )
    try:
        r = subprocess.run(['ssh', N02_SSH, 'python3 -'],
                           input=script, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return len(rows)
        print(f'WARN: SSH state.db write failed: {r.stderr.strip()[:120]}', file=sys.stderr)
    except Exception as e:
        print(f'WARN: state.db persist failed: {e}', file=sys.stderr)
    return 0


# ── Parser ─────────────────────────────────────────────────────────────────────

def parse_tasks(path: str) -> list:
    """Extract task blocks from TASKS.vsm. Returns list of task dicts."""
    tasks = []
    current = None

    with open(path, encoding='utf-8') as fh:
        lines = fh.readlines()

    for i, raw in enumerate(lines):
        line = raw.split('//')[0].rstrip()

        # New task block — both TASKS.vsm spellings:
        #   style A: task(R):                 (VSL, quoted or bare ids)
        #   style B: task("ASM-01", ...) = {  (canonical VSM blocks)
        # FND-RECONCILE-PARSER-BLIND-01: the old ^task\((\w+)\) matched
        # only style A (4 of ~140 tasks) and skipped hyphenated ids.
        m = re.match(r'^task\(\s*"?([A-Za-z0-9_-]+)"?', line)
        if m:
            if current:
                tasks.append(current)
            current = {
                'id': m.group(1),
                'status': None,
                'title': None,
                'anchors': [],
                'inline_done_steps': [],
                'line': i + 1,
                'raw_lines': [raw.rstrip()],
            }
            # Inline single-line task (style A uses `status = x`,
            # style B lines carry `status:` fields on their own line —
            # both accepted here for the block-head case)
            km = re.search(r'status\s*[=:]\s*(\w+)', line)
            if km:
                current['status'] = km.group(1)
            tm = re.search(r'title\s*=\s*"([^"]+)"', line)
            if tm:
                current['title'] = tm.group(1)
            _extract_anchors(line, current)
            continue

        if current is None:
            continue

        current['raw_lines'].append(raw.rstrip())

        # Status line (style A `status = x`, style B `status:  x`)
        sm = re.match(r'\s+status\s*[=:]\s*(\w+)', line)
        if sm and current['status'] is None:
            current['status'] = sm.group(1)

        # Title line
        tm = re.match(r'\s+title\s*=\s*"([^"]+)"', line)
        if tm and current['title'] is None:
            current['title'] = tm.group(1)

        _extract_anchors(line, current)

        # Inline sub-steps marked done: "Z1: done", "step1: done"
        if re.search(r'\b\w+\d*\s*:\s*done\b', line, re.IGNORECASE):
            current['inline_done_steps'].append(line.strip())

    if current:
        tasks.append(current)

    return tasks


def _extract_anchors(line: str, task: dict) -> None:
    """Extract file/path/commit evidence anchors from a line into task['anchors']."""
    # file=<path> or path=<path>
    for kw in ('file', 'path', 'files'):
        for m in re.finditer(rf'\b{kw}\s*=\s*([^\s,\]]+)', line):
            val = m.group(1).strip('"\'[]')
            if val and not val.startswith('@') and '.' in val or '/' in val:
                task['anchors'].append(('path', val))

    # commit=<hash>
    for m in re.finditer(r'\bcommit\s*=\s*([0-9a-f]{7,40})', line):
        task['anchors'].append(('commit', m.group(1)))

    # @ref <path>
    for m in re.finditer(r'@ref\s+(\S+)', line):
        task['anchors'].append(('path', m.group(1)))


# ── Verification ───────────────────────────────────────────────────────────────

def check_path(anchor_val: str) -> bool:
    """Check if path exists relative to VSF_ROOT or as absolute/home path."""
    p = anchor_val.replace('~/', os.path.expanduser('~/'))
    if os.path.isabs(p):
        return os.path.exists(p)
    return os.path.exists(os.path.join(VSF_ROOT, p))


def check_commit(sha: str) -> bool:
    """Return True if commit hash exists in local git history."""
    try:
        r = subprocess.run(
            ['git', '-C', VSF_ROOT, 'cat-file', '-t', sha],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def check_deploy(sha: str) -> bool:
    """Return True if commit appears in state.db deploys table."""
    # Try local path first (running on n02), then SSH
    if os.path.exists(STATE_DB):
        try:
            conn = sqlite3.connect(STATE_DB)
            row = conn.execute(
                "SELECT 1 FROM deploys WHERE to_sha LIKE ? LIMIT 1",
                (f'{sha}%',),
            ).fetchone()
            conn.close()
            return row is not None
        except Exception:
            pass
    try:
        r = subprocess.run(
            ['ssh', N02_SSH,
             f"sqlite3 {STATE_DB} \"SELECT 1 FROM deploys WHERE to_sha LIKE '{sha}%' LIMIT 1\""],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and r.stdout.strip() == '1'
    except Exception:
        return False


# ── Report ────────────────────────────────────────────────────────────────────

def reconcile(tasks: list, verbose: bool = False) -> list:
    """Run all checks. Returns list of finding dicts."""
    findings = []

    for t in tasks:
        if t['status'] not in NON_DONE_STATUSES:
            continue
        tid = t['id']

        # Sub-steps marked done inside an OPEN task (H-AD semantics,
        # S5 ratificado 2026-10-22: 'partial' es progreso EXPLICITO del
        # vocabulario de status (patron task(SEC)) y por design lleva
        # pasos done + pasos abiertos — no oculta nada. El detector solo
        # aplica a status='open' (el task que NO declara progreso).
        if t['status'] == 'open' and t['inline_done_steps']:
            findings.append({
                'task': tid,
                'class': 'STEP_DONE_BUT_OPEN',
                'detail': f"{len(t['inline_done_steps'])} inline step(s) marked done "
                          f"but task status={t['status']}: "
                          + '; '.join(t['inline_done_steps'][:3]),
            })

        seen = set()
        for anchor_type, anchor_val in t['anchors']:
            key = (anchor_type, anchor_val)
            if key in seen:
                continue
            seen.add(key)

            if anchor_type == 'path':
                exists = check_path(anchor_val)
                if exists:
                    findings.append({
                        'task': tid,
                        'class': 'ANCHOR_EXISTS',
                        'detail': f'path "{anchor_val}" exists — task may be done or partially done',
                    })
                elif verbose:
                    findings.append({
                        'task': tid,
                        'class': 'ANCHOR_MISSING',
                        'detail': f'path "{anchor_val}" NOT found (expected if task not started)',
                    })

            elif anchor_type == 'commit':
                in_git = check_commit(anchor_val)
                in_deploy = check_deploy(anchor_val) if in_git else False
                if in_git:
                    findings.append({
                        'task': tid,
                        'class': 'COMMIT_PRESENT',
                        'detail': f'commit {anchor_val} exists in git history'
                                  + (' + deploys table' if in_deploy else ''),
                    })
                else:
                    findings.append({
                        'task': tid,
                        'class': 'COMMIT_ABSENT',
                        'detail': f'commit {anchor_val} NOT in git history',
                    })

    return findings


def reconcile_write(tasks_file: str, dry_run: bool = False) -> int:
    """
    --write mode: for every DRIFT case (session() block references a task as
    resolved but the task() block status is not done), update the task block
    status=done + add a closed_by: reference to the session block.

    Returns number of tasks updated. In dry_run mode, only prints what WOULD change.
    """
    from collections import defaultdict

    with open(tasks_file, encoding='utf-8') as fh:
        lines = list(fh.readlines())

    # ── FIRST PASS: build token→line lookup ──────────────────────────────────
    # Map: task_id → last occurrence line
    task_lines = {}
    for i, raw in enumerate(lines):
        m = re.match(r'task\s*\(\s*"([^"]+)"\s*\)', raw)
        if not m:
            m = re.match(r'task\s*\(\s*(\w+)\s*\)', raw)
        if m:
            task_lines[m.group(1)] = i

    # ── Parse sessions to build resolved_ids → session_name mapping ──────────
    resolved_map = defaultdict(list)
    for i, raw in enumerate(lines):
        sm = re.match(r'session\s*\(\s*"([^"]+)"\s*\)', raw)
        if not sm:
            continue
        session_name = sm.group(1)
        # Look for the resolved: [ ... ] block
        block_text = " ".join(lines[i:i+30] if i+30 < len(lines) else lines[i:])
        rm = re.search(r'\bresolved\s*[:=]\s*\[([^\]]+)\]', block_text)
        if rm:
            ids_str = rm.group(1)
            for m in re.finditer(r'"([^"]+)"', ids_str):
                tid = m.group(1)
                if not tid.startswith('20') and not tid.startswith('-'):  # skip dates/urls
                    resolved_map[tid].append(session_name)

    # Filter to only task IDs that exist in the file
    resolved_map = {tid: sessions for tid, sessions in resolved_map.items()
                    if tid in task_lines}

    # ── Fix drift ────────────────────────────────────────────────────────────
    updated = 0
    for tid, session_list in sorted(resolved_map.items()):
        task_line = task_lines[tid]

        # Look ahead for status
        block_text = " ".join(lines[task_line:task_line+8])
        status_match = re.search(r'\bstatus\s*[:=]\s*(\S+)', block_text)
        current_status = status_match.group(1).rstrip(',})') if status_match else "UNSET"

        if _normalize_status_lookup(current_status) in ('done', 'superseded', 'dropped'):
            continue

        # Found drift
        session_ref = ", ".join(session_list)
        if dry_run:
            print(f'[DRY-RUN] task({tid}) L{task_line+1}: {current_status}→done ({session_ref})')
            updated += 1
            continue

        # Find exact status line
        found_line = None
        for j in range(task_line, min(task_line + 8, len(lines))):
            for patt in [r'\bstatus\s*=\s*(\S+)', r'\bstatus\s*:\s*(\S+)']:
                sm = re.search(patt, lines[j])
                if sm:
                    found_line = j
                    status_match = sm
                    break
            if found_line:
                break

        if found_line is not None:
            old = status_match.group(0)
            sep = '=' if '=' in old else ':'
            new_val = f'status{sep} done'
            lines[found_line] = lines[found_line].replace(old, new_val)
        else:
            # No status field — insert after first key field
            for j in range(task_line + 1, min(task_line + 15, len(lines))):
                if lines[j].strip().startswith('what') or '}' in lines[j]:
                    lines.insert(j, '  status: done,\n')
                    found_line = j
                    break

        if found_line is not None:
            ref_line = found_line + 1
            already = any('closed_by' in lines[k]
                          for k in range(task_line, min(task_line + 15, len(lines))))
            if not already:
                lines.insert(ref_line, '  closed_by: "' + session_ref + '",\n')
            updated += 1
            print(f'  task({tid}) L{task_line+1}: status→done ({session_ref})')

    if updated == 0:
        print('Reconcile: no drift to fix.')
        return 0

    if not dry_run:
        with open(tasks_file, 'w', encoding='utf-8', newline='') as fh:
            fh.writelines(lines)
        print(f'Reconcile: {updated} task(s) updated in {tasks_file}')
    return updated


def _normalize_status_lookup(raw: str) -> str:
    """Quick normalization lookup for dry-run detection."""
    s = raw.strip().lower().rstrip(',})')
    if s in ('done', 'superseded', 'dropped', 'closed'):
        return 'done'
    if s in ('partial', 'in_progress'):
        return 'in_progress'
    if s in ('discovery',):
        return 'in_progress'
    if s in ('open',):
        return 'open'
    if s in ('blocked', 'findings_pending'):
        return 'blocked'
    if s in ('gated', 'deferred'):
        return 'gated'
    if s in ('audited', 'acked', 'resolved'):
        return 'done'
    return s


def main(argv: list) -> int:
    global STATE_DB
    p = argparse.ArgumentParser(description='TASKS.vsm drift reconciler (DEBT-42)')
    p.add_argument('--state-db', default=STATE_DB)
    p.add_argument('--verbose', action='store_true',
                   help='also report ANCHOR_MISSING (expected for not-started tasks)')
    p.add_argument('--emit', action='store_true',
                   help='write findings to state.db task_drift + emit algedonic on STEP_DONE_BUT_OPEN')
    p.add_argument('--write', action='store_true',
                   help='write session-closure drift back into task() blocks (status=done + closed_by)')
    p.add_argument('--dry-run', action='store_true',
                   help='with --write, only show what would change')
    a = p.parse_args(argv[1:])

    STATE_DB = a.state_db

    if not os.path.exists(TASKS_FILE):
        print(f'ERROR: TASKS.vsm not found at {TASKS_FILE}', file=sys.stderr)
        return 1

    # --write mode: fix drift before reporting
    if a.write:
        return reconcile_write(TASKS_FILE, dry_run=a.dry_run)

    tasks = parse_tasks(TASKS_FILE)
    non_done = [t for t in tasks if t.get('status') in NON_DONE_STATUSES]
    print(f'TASKS.vsm: {len(tasks)} tasks total, {len(non_done)} non-done '
          f'({", ".join(t["id"] for t in non_done)})')

    findings = reconcile(tasks, a.verbose)

    if not findings:
        print('Reconciler: no drift detected.')
        return 0

    print(f'\nFindings ({len(findings)}):')
    for f in findings:
        tag = f['class']
        print(f'  [{tag}] task({f["task"]}): {f["detail"]}')

    suspect = [f for f in findings if f['class'] in ('ANCHOR_EXISTS', 'STEP_DONE_BUT_OPEN')]
    if suspect:
        print(f'\n  ⚠ {len(suspect)} finding(s) suggest task may already be done — '
              'verify and update TASKS.vsm status if confirmed.')

    if a.emit and findings:
        n = _persist_findings(findings, a.state_db)
        print(f'\nEmit: {n} findings written to {a.state_db} task_drift')
        step_done = [f for f in findings if f['class'] == 'STEP_DONE_BUT_OPEN']
        if step_done:
            payload = {
                'ts':        _now_iso(),
                'source_id': 'tasks_reconcile',
                'category':  'task_drift',
                'severity':  5,
                'detail':    f'{len(step_done)} task(s) have inline done-steps but remain open: '
                             + ', '.join(f["task"] for f in step_done[:5]),
            }
            _nats_publish(payload)
            print(f'Emit: algedonic published for {len(step_done)} STEP_DONE_BUT_OPEN finding(s)')

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
