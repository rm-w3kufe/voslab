#!/usr/bin/env python3
"""
vsf_graph.py — VSF project dependency graph

Parses TASKS.vsm + experiment index/queue → SQLite DAG → CLI queries.
Answers: what can I start now? what does completing X unlock? what blocks Y?

Usage:
    python3 scripts/analysis/vsf_graph.py build           # (re)build DB from .vsm files
    python3 scripts/analysis/vsf_graph.py open            # open nodes by priority
    python3 scripts/analysis/vsf_graph.py roots           # startable now (no unresolved deps)
    python3 scripts/analysis/vsf_graph.py show <id>       # full node + edges
    python3 scripts/analysis/vsf_graph.py unblocks <id>   # what completing <id> enables
    python3 scripts/analysis/vsf_graph.py blocked-by <id> # what <id> requires
    python3 scripts/analysis/vsf_graph.py path <a> <b>    # shortest path a→b
    python3 scripts/analysis/vsf_graph.py dot             # graphviz DOT output
    python3 scripts/analysis/vsf_graph.py stats           # node/edge counts by type
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import deque
from pathlib import Path

VSF_ROOT = Path(__file__).resolve().parent.parent
DB_PATH  = VSF_ROOT / "scripts" / "vsf_deps.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL DEFAULT 'unknown',
    title       TEXT,
    status      TEXT DEFAULT 'unknown',
    priority    TEXT,
    effort      TEXT,
    source_file TEXT,
    meta        TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS edges (
    from_id  TEXT NOT NULL,
    to_id    TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_from ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_to   ON edges(to_id);
"""

DONE_STATUSES = {'done', 'closed'}
PRIORITY_RANK = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}


# ─── DB helpers ──────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def upsert_node(db, id, type='unknown', *, title=None, status=None,
                priority=None, effort=None, source_file=None, meta=None):
    db.execute("""
        INSERT INTO nodes(id, type, title, status, priority, effort, source_file, meta)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          type      = CASE WHEN excluded.type != 'unknown' THEN excluded.type ELSE type END,
          title     = COALESCE(excluded.title,     title),
          status    = COALESCE(excluded.status,    status),
          priority  = COALESCE(excluded.priority,  priority),
          effort    = COALESCE(excluded.effort,     effort),
          source_file = COALESCE(excluded.source_file, source_file),
          meta      = COALESCE(excluded.meta,      meta)
    """, (id, type, title, status, priority, effort, source_file,
          json.dumps(meta or {})))


def add_edge(db, from_id, to_id, relation):
    for nid in (from_id, to_id):
        db.execute("INSERT OR IGNORE INTO nodes(id, type) VALUES(?, 'unknown')", (nid,))
    db.execute(
        "INSERT OR IGNORE INTO edges(from_id, to_id, relation) VALUES(?,?,?)",
        (from_id, to_id, relation)
    )


# ─── Parsing helpers ──────────────────────────────────────────────────────────

def normalize_id(raw: str) -> str:
    """Normalize refs: 'task(V)' → 'task.V', 'EXP-SB-01' → 'exp.SB-01'."""
    raw = raw.strip().strip('"\'')
    m = re.match(r'task\(([^)]+)\)', raw)
    if m:
        return f"task.{m.group(1)}"
    m = re.match(r'EXP-(\S+)', raw)
    if m:
        return f"exp.{m.group(1)}"
    m = re.match(r'exp\((\S+)\)', raw)
    if m:
        return f"exp.{m.group(1)}"
    # Descriptions (long phrases) → skip
    if len(raw) > 30 or ' ' in raw.strip():
        return ''
    return raw.replace(' ', '_').lower()


def extract_str(text: str, key: str) -> str | None:
    """Extract scalar value. Takes LAST match (handles status=open → status=done override).
    Also handles inline compact format: task(X): title="..." status=done."""
    # Multiline: key at line start (standard format)
    matches = list(re.finditer(
        rf'^\s*{re.escape(key)}\s*[=:]\s*(?:"([^"]+)"|\'([^\']+)\'|([^\n,{{}}]+?))\s*(?://.*)?$',
        text, re.MULTILINE
    ))
    if matches:
        m = matches[-1]  # last match wins (handles override pattern)
        val = m.group(1) or m.group(2) or m.group(3)
        return val.strip() if val else None
    # Inline fallback: key anywhere on the first line (compact single-line format)
    first = text.split('\n')[0]
    m = re.search(rf'\b{re.escape(key)}\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(\S+))', first)
    if m:
        val = m.group(1) or m.group(2) or m.group(3)
        return val.strip().rstrip(',') if val else None
    return None


def extract_list(text: str, key: str) -> list[str]:
    """Extract list value: key = [a, b, c] or key = [a]."""
    m = re.search(
        rf'^\s*{re.escape(key)}\s*[=:]\s*\[([^\]]*)\]',
        text, re.MULTILINE | re.DOTALL
    )
    if not m:
        # Single-value (no brackets)
        sv = extract_str(text, key)
        return [sv] if sv and not sv.startswith('[') else []
    raw = m.group(1)
    items = re.findall(r'"([^"]+)"|\'([^\']+)\'|([^\s,\[\]"\']+)', raw)
    return [
        (a or b or c).strip()
        for a, b, c in items
        if (a or b or c).strip() and not (a or b or c).strip().startswith('//')
    ]


# ─── Parsers ─────────────────────────────────────────────────────────────────

def parse_tasks_vsm(db):
    path = VSF_ROOT / "TASKS.vsm"
    if not path.exists():
        return
    text = path.read_text()

    # Split on task block headers — task(X): at line start
    parts = re.split(r'(?=^task\([A-Z]+\):)', text, flags=re.MULTILINE)
    seen = set()
    for part in parts:
        m = re.match(r'task\(([^)]+)\):', part)
        if not m:
            continue
        letter = m.group(1)
        tid = f"task.{letter}"
        if tid in seen:
            # Duplicate task IDs in file (task Y/Z appear twice) — merge by skipping
            continue
        seen.add(tid)

        title    = extract_str(part, 'title')
        status   = (extract_str(part, 'status') or 'unknown').lower().split()[0]
        priority = extract_str(part, 'priority')
        effort   = extract_str(part, 'effort')

        upsert_node(db, tid, 'task', title=title, status=status,
                    priority=priority, effort=effort, source_file='TASKS.vsm')

        for dep in extract_list(part, 'depends_on'):
            dep_id = normalize_id(dep)
            if dep_id:
                add_edge(db, tid, dep_id, 'requires')

        for ub in extract_list(part, 'unblocks'):
            ub_id = normalize_id(ub)
            if ub_id:
                add_edge(db, tid, ub_id, 'enables')


def parse_experiment_index(db):
    path = VSF_ROOT / "docs/experiments/index.vsm"
    if not path.exists():
        return
    text = path.read_text()

    # exp(name): blocks
    parts = re.split(r'(?=^exp\([^)]+\):)', text, flags=re.MULTILINE)
    for part in parts:
        m = re.match(r'exp\(([^)]+)\):', part)
        if not m:
            continue
        name = m.group(1)
        id_m = re.search(r'id\s*=\s*(EXP-\S+)', part)
        if not id_m:
            continue
        raw_id = id_m.group(1)
        eid = f"exp.{raw_id[4:]}"  # EXP-SB-01 → exp.SB-01

        status_m = re.search(r'status\s*=\s*(\S+)', part)
        status = status_m.group(1).lower() if status_m else 'unknown'

        paper_m = re.search(r'paper\s*=\s*"([^"]+)"', part)
        title = paper_m.group(1) if paper_m else name

        upsert_node(db, eid, 'experiment', title=title, status=status,
                    source_file='docs/experiments/index.vsm')


def parse_experiment_queue(db):
    path = VSF_ROOT / "docs/experiments/queue.vsm"
    if not path.exists():
        return
    text = path.read_text()

    # experiment("name") = { ... }
    for m in re.finditer(r'experiment\("([^"]+)"\)\s*=\s*\{([^}]+)\}', text, re.DOTALL):
        name, body = m.group(1), m.group(2)
        eid      = f"exp.{name}"
        status   = extract_str(body, 'status')
        priority = extract_str(body, 'priority')
        effort   = extract_str(body, 'time')
        upsert_node(db, eid, 'experiment', title=name,
                    status=(status or 'unknown').lower(),
                    priority=(priority or '').lower() or None,
                    effort=effort, source_file='docs/experiments/queue.vsm')
        # blocks: ["task(O)"] means task.O requires this experiment
        for b in extract_list(body, 'blocks'):
            b_id = normalize_id(b)
            if b_id:
                add_edge(db, b_id, eid, 'requires')

    # spec("name") = { ... }
    for m in re.finditer(r'spec\("([^"]+)"\)\s*=\s*\{([^}]+)\}', text, re.DOTALL):
        name, body = m.group(1), m.group(2)
        sid      = f"spec.{name}"
        status   = extract_str(body, 'status')
        priority = extract_str(body, 'priority')
        effort   = extract_str(body, 'time')
        upsert_node(db, sid, 'spec', title=name,
                    status=(status or 'unknown').lower(),
                    priority=(priority or '').lower() or None,
                    effort=effort, source_file='docs/experiments/queue.vsm')
        for b in extract_list(body, 'blocks'):
            b_id = normalize_id(b)
            if b_id:
                add_edge(db, b_id, sid, 'requires')


def add_manual_graph(db):
    """
    Architecture-level nodes and edges not derivable from .vsm files.
    This is the hand-curated layer — update when architecture changes.
    """
    # ── Deliverables ──────────────────────────────────────────────────────────
    deliverables = [
        ('deliver.paper_submit',    'Submit attractor_convergence to preprint'),
        ('deliver.github_release',  'GitHub public release v1.0'),
        ('deliver.beer_outreach',   'Outreach Beer/Metaphorum/SCiO community'),
        ('deliver.exec_summary',    'Executive summary 2-3pp for Beer community'),
    ]
    for nid, title in deliverables:
        upsert_node(db, nid, 'deliver', title=title, status='open',
                    source_file='manual')

    # ── Infrastructure ────────────────────────────────────────────────────────
    infra = [
        ('infra.bbs_phase2',  'BBS phase 2: n01 reverse proxy to LXC 106', 'open'),
        ('infra.SBBS',        'SBBS: BBS v2.0 ECC security layer',         'pending_approval'),
        ('infra.n01_ssh',     'vsf user SSH auth on n01 (broken)',          'open'),
        ('infra.vsf_site',    'vsf.u2738.org — OFFLINE pending disclosure', 'blocked'),
    ]
    for nid, title, status in infra:
        upsert_node(db, nid, 'infra', title=title, status=status,
                    source_file='manual')

    # ── Security gaps ─────────────────────────────────────────────────────────
    security = [
        ('sec.M3', 'S5 stress signal → caution mode',          'open', '30min'),
        ('sec.M5', 'cargo --locked enforcement in deploy',      'open', '30min'),
        ('sec.M6', 'S3* binary integrity cron daily',           'open', '1h'),
        ('sec.M7', 'HMAC alert chain (req. before S1 write)',   'open', '2h'),
        ('sec.M9', 'Two-axis trust: behavioral + structural',   'open', '3h'),
    ]
    for nid, title, status, effort in security:
        upsert_node(db, nid, 'security', title=title, status=status, effort=effort,
                    source_file='docs/security/xz_threat_model.vsm')

    # ── Contacts ──────────────────────────────────────────────────────────────
    contacts = [
        ('contact.Espejo', 'Raúl Espejo — WOSC, Cybersyn director (draft ready)',  'open'),
        ('contact.Senna',  'Carlos Senna — Cybersyn original (context pending)',    'open'),
        ('contact.Fierro', 'Prof. Fierro UV — validated paper 2026-05-01',          'done'),
    ]
    for nid, title, status in contacts:
        upsert_node(db, nid, 'contact', title=title, status=status,
                    source_file='manual')

    # ── vOS milestones ────────────────────────────────────────────────────────
    vos = [
        ('vos.stage0', 'vOS Stage 0: vsf-nucleus kernel on n02',       'done'),
        ('vos.stage1', 'vOS Stage 1: V_sci + first ψ PSI handshake',   'open'),
        ('vos.stage2', 'vOS Stage 2: V_ref bare-metal + symbiogenesis', 'open'),
        ('vos.stage3', 'vOS Stage 3: autonomous loop, trust ≥ 0.80',    'open'),
        ('vos.stage4', 'vOS Stage 4: vOS vivo @approval_required rmw3', 'open'),
    ]
    for nid, title, status in vos:
        upsert_node(db, nid, 'vos', title=title, status=status,
                    source_file='manual')

    # ── Paper seeds ───────────────────────────────────────────────────────────
    seeds = [
        ('paper.NC_01',  'EXP-NC-01: S5-off negative control',          'seed', 'medium'),
        ('paper.NC_02',  'EXP-NC-02: trust-const negative control',      'seed', 'medium'),
        ('paper.NC_03',  'EXP-NC-03: no-S2 negative control',            'seed', 'medium'),
        ('paper.LY_01',  'EXP-LY-01: Lyapunov real (Benettin method)',   'seed', 'medium'),
        ('paper.MC_01',  'EXP-MC-01: Monte Carlo basin volume estimate',  'seed', 'low'),
        ('paper.AA',     'Paper §Theory: Markov chain formalization',     'seed', 'medium'),
    ]
    for nid, title, status, priority in seeds:
        upsert_node(db, nid, 'paper_seed', title=title, status=status,
                    priority=priority, source_file='manual')

    # ── Edges: paper pipeline ─────────────────────────────────────────────────
    paper_edges = [
        # task.V done → paper ready to submit
        ('deliver.paper_submit',   'task.V',     'requires'),
        # submit unlocks everything downstream
        ('deliver.exec_summary',   'deliver.paper_submit', 'requires'),
        ('deliver.beer_outreach',  'deliver.paper_submit', 'requires'),
        ('deliver.github_release', 'deliver.paper_submit', 'requires'),
        # outreach contacts require beer_outreach
        ('contact.Espejo',         'deliver.beer_outreach', 'requires'),
        ('contact.Senna',          'deliver.beer_outreach', 'requires'),
        # negative controls seed the paper (optional but strengthen it)
        ('deliver.paper_submit',   'paper.NC_01', 'seeds'),
        ('deliver.paper_submit',   'paper.NC_02', 'seeds'),
        ('deliver.paper_submit',   'paper.NC_03', 'seeds'),
        ('deliver.paper_submit',   'paper.LY_01', 'seeds'),
    ]

    # ── Edges: PSI/security pipeline ──────────────────────────────────────────
    psi_edges = [
        # theta_psi_stress experiment must run before PSI spec
        ('spec.psi_protocol',    'exp.theta_psi_stress', 'requires'),
        # PSI spec enables task.O
        ('task.O',               'spec.psi_protocol',    'requires'),
        # task.O enables vos.stage1
        ('vos.stage1',           'task.O',               'requires'),
        # vos.stage1 → stage2 → ...
        ('vos.stage2',           'vos.stage1',           'requires'),
        ('vos.stage3',           'vos.stage2',           'requires'),
        ('vos.stage4',           'vos.stage3',           'requires'),
        # security gates for stage2
        ('vos.stage2',           'sec.M7',               'requires'),
        ('vos.stage2',           'sec.M9',               'requires'),
    ]

    # ── Edges: BBS/SBBS pipeline ──────────────────────────────────────────────
    bbs_edges = [
        ('infra.SBBS',           'infra.bbs_phase2',    'requires'),
        # SBBS as substrate helps PSI
        ('task.O',               'infra.SBBS',          'seeds'),
    ]

    # ── Edges: GitHub release gates ───────────────────────────────────────────
    github_edges = [
        ('deliver.github_release', 'sec.M5',  'requires'),
        ('deliver.github_release', 'sec.M6',  'requires'),
        ('deliver.github_release', 'task.Z',  'requires'),  # pre-deploy checklist
    ]

    # ── Edges: vOS/Qwen chain ─────────────────────────────────────────────────
    vos_edges = [
        ('vos.stage1',           'task.S',   'requires'),  # Qwen VSL reading
        ('vos.stage2',           'task.U',   'requires'),  # VSL interpreter
        ('vos.stage2',           'task.X',   'requires'),  # semantic indexer
        ('task.U',               'task.S',   'requires'),  # interpreter needs Qwen
    ]

    for edges in (paper_edges, psi_edges, bbs_edges, github_edges, vos_edges):
        for f, t, r in edges:
            add_edge(db, f, t, r)


# ─── CLI commands ─────────────────────────────────────────────────────────────

def is_done(status: str | None) -> bool:
    return (status or '').lower() in DONE_STATUSES


def resolve_id(db, raw: str) -> str | None:
    """Resolve partial IDs via prefix match."""
    if db.execute("SELECT 1 FROM nodes WHERE id=?", (raw,)).fetchone():
        return raw
    rows = db.execute("SELECT id FROM nodes WHERE id LIKE ?", (f"{raw}%",)).fetchall()
    if len(rows) == 1:
        return rows[0]['id']
    if rows:
        print(f"Ambiguous '{raw}' — matches: {', '.join(r['id'] for r in rows)}")
    else:
        print(f"Node not found: {raw}")
    return None


def cmd_done(db, raw_id: str):
    """Mark a node done in its source .vsm file, rebuild DB, show what unlocks."""
    nid = resolve_id(db, raw_id)
    if not nid:
        return
    row = db.execute("SELECT type, status, source_file FROM nodes WHERE id=?", (nid,)).fetchone()
    if not row:
        print(f"Not found: {nid}"); return
    if is_done(row['status']):
        print(f"{nid} is already done."); return

    source = row['source_file']
    if source != 'TASKS.vsm':
        print(f"Auto-update not supported for source: {source}")
        print(f"Edit manually: {source}"); return

    path = VSF_ROOT / 'TASKS.vsm'
    text = path.read_text()
    letter = nid.split('.', 1)[1]

    # Split into blocks, find the right one, update status
    parts = re.split(r'(?=^task\([A-Z]+\):)', text, flags=re.MULTILINE)
    new_parts, updated = [], False
    for part in parts:
        m = re.match(r'task\(([^)]+)\):', part)
        if m and f"task.{m.group(1)}" == nid and not updated:
            new_part = re.sub(
                r'^(\s*status\s*=\s*)(?:open|seed|partial|pending|impl|ready|blocked|running)(\s*(?://.*)?$)',
                r'\1done\2',
                part, count=1, flags=re.MULTILINE
            )
            if new_part == part:
                # No replaceable status line found — append one
                new_part = part.rstrip() + f'\n  status = done  // vsf_graph done {raw_id}\n'
            new_parts.append(new_part)
            updated = True
        else:
            new_parts.append(part)

    if not updated:
        print(f"Could not locate {nid} in TASKS.vsm"); return

    path.write_text(''.join(new_parts))
    print(f"✓ {nid} → done  (TASKS.vsm updated)")
    cmd_build(db)
    print()
    cmd_unblocks(db, nid)


def cmd_build(db):
    db.execute("DELETE FROM edges")
    db.execute("DELETE FROM nodes")
    parse_tasks_vsm(db)
    parse_experiment_index(db)
    parse_experiment_queue(db)
    add_manual_graph(db)
    db.commit()
    nc = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    ec = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    print(f"Built: {nc} nodes, {ec} edges  →  {DB_PATH.relative_to(VSF_ROOT)}")


def cmd_stats(db):
    print("\nNodes by type:")
    for r in db.execute(
        "SELECT type, COUNT(*) AS n, SUM(CASE WHEN status IN ('done','closed') THEN 1 ELSE 0 END) AS done "
        "FROM nodes WHERE type!='unknown' GROUP BY type ORDER BY n DESC"
    ).fetchall():
        print(f"  {r['type']:<15} {r['n']:>3} total   {r['done']:>3} done")
    print("\nEdges by relation:")
    for r in db.execute(
        "SELECT relation, COUNT(*) AS n FROM edges GROUP BY relation ORDER BY n DESC"
    ).fetchall():
        print(f"  {r['relation']:<12} {r['n']:>3}")


def cmd_open(db):
    rows = db.execute("""
        SELECT id, type, title, status, priority, effort FROM nodes
        WHERE status NOT IN ('done','closed') AND type != 'unknown'
        ORDER BY
          CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
          type, id
    """).fetchall()
    current_prio = None
    for r in rows:
        p = (r['priority'] or 'unknown').lower()
        if p != current_prio:
            print(f"\n── {p.upper()} ──")
            current_prio = p
        effort = f"  [{r['effort']}]" if r['effort'] else ''
        print(f"  {r['id']:<32} [{r['status']:<12}] {r['title'] or ''}{effort}")


def cmd_roots(db):
    """Open nodes with no unresolved requires dependencies."""
    all_open = {
        r['id'] for r in db.execute(
            "SELECT id FROM nodes WHERE status NOT IN ('done','closed') AND type!='unknown'"
        )
    }
    blocked = set()
    for r in db.execute(
        "SELECT from_id, to_id FROM edges WHERE relation='requires'"
    ).fetchall():
        # from_id is blocked if to_id is still open
        if r['to_id'] in all_open:
            blocked.add(r['from_id'])

    roots = all_open - blocked
    if not roots:
        print("No startable nodes found (everything has open deps).")
        return
    print(f"Startable now — {len(roots)} nodes:\n")
    for nid in sorted(roots):
        r = db.execute(
            "SELECT type, title, priority, effort, status FROM nodes WHERE id=?", (nid,)
        ).fetchone()
        if not r:
            continue
        prio   = f"[{r['priority']}]" if r['priority'] else '[?]'
        effort = f"  [{r['effort']}]" if r['effort'] else ''
        print(f"  {nid:<32} {prio:<10}{effort}  {r['title'] or ''}")


def cmd_show(db, raw_id: str):
    nid = resolve_id(db, raw_id)
    if not nid:
        return
    r = db.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
    print(f"\n● {r['id']}")
    print(f"  type:     {r['type']}")
    print(f"  status:   {r['status']}")
    print(f"  priority: {r['priority'] or '—'}")
    print(f"  effort:   {r['effort'] or '—'}")
    print(f"  title:    {r['title'] or '—'}")
    print(f"  source:   {r['source_file'] or '—'}")

    req = db.execute(
        "SELECT to_id, relation FROM edges WHERE from_id=? AND relation IN ('requires','seeds')",
        (nid,)
    ).fetchall()
    enables = db.execute(
        "SELECT to_id FROM edges WHERE from_id=? AND relation='enables'", (nid,)
    ).fetchall()
    req_by = db.execute(
        "SELECT from_id FROM edges WHERE to_id=? AND relation='requires'", (nid,)
    ).fetchall()

    def _status(nid2):
        s = db.execute("SELECT status FROM nodes WHERE id=?", (nid2,)).fetchone()
        return f"[{s['status']}]" if s else ''

    if req:
        print(f"\n  requires:")
        for row in req:
            done = '✓' if is_done(db.execute("SELECT status FROM nodes WHERE id=?", (row['to_id'],)).fetchone()['status']) else ' '
            print(f"    {done} {row['to_id']} {_status(row['to_id'])}")
    if enables:
        print(f"\n  enables:")
        for row in enables:
            print(f"      {row['to_id']} {_status(row['to_id'])}")
    if req_by:
        print(f"\n  required by:")
        for row in req_by:
            print(f"      {row['from_id']} {_status(row['from_id'])}")


def bfs(db, start_ids: list[str], direction: str, relations: set[str]) -> dict[str, str]:
    """BFS. Returns {node_id: parent_id} for all reachable nodes."""
    prev = {nid: None for nid in start_ids}
    queue = deque(start_ids)
    rel_placeholders = ','.join('?' * len(relations))
    while queue:
        cur = queue.popleft()
        if direction == 'forward':
            sql = f"SELECT to_id AS next FROM edges WHERE from_id=? AND relation IN ({rel_placeholders})"
        else:
            sql = f"SELECT from_id AS next FROM edges WHERE to_id=? AND relation IN ({rel_placeholders})"
        for r in db.execute(sql, [cur] + list(relations)).fetchall():
            nxt = r['next']
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
    return prev


def cmd_unblocks(db, raw_id: str):
    nid = resolve_id(db, raw_id)
    if not nid:
        return
    # "What is waiting for X?" = nodes that (transitively) require X
    # = reverse BFS on 'requires' edges (from_id --requires--> to_id means to_id is prereq)
    # Reversing: follow edges where to_id == current → these from_ids depend on current
    direct = {r['from_id'] for r in db.execute(
        "SELECT from_id FROM edges WHERE to_id=? AND relation='requires'", (nid,)
    )}
    # Also follow explicit enables edges forward
    direct |= {r['to_id'] for r in db.execute(
        "SELECT to_id FROM edges WHERE from_id=? AND relation='enables'", (nid,)
    )}
    # Transitive: BFS reverse-requires from nid
    visited = {nid}
    queue = deque([nid])
    all_waiting: set[str] = set()
    while queue:
        cur = queue.popleft()
        for r in db.execute(
            "SELECT from_id FROM edges WHERE to_id=? AND relation IN ('requires','enables')", (cur,)
        ).fetchall():
            nxt = r['from_id']
            if nxt not in visited:
                visited.add(nxt)
                all_waiting.add(nxt)
                queue.append(nxt)
    transitive = all_waiting - direct

    if direct:
        print(f"\nCompleting {nid} directly unblocks:\n")
        for rid in sorted(direct):
            r = db.execute("SELECT type, title, status FROM nodes WHERE id=?", (rid,)).fetchone()
            if r and r['type'] != 'unknown':
                print(f"  {rid:<35} [{r['status']}]  {r['title'] or ''}")
    if transitive:
        print(f"\nTransitively enables ({len(transitive)} nodes):\n")
        for rid in sorted(transitive):
            r = db.execute("SELECT type, title, status FROM nodes WHERE id=?", (rid,)).fetchone()
            if r and r['type'] != 'unknown':
                print(f"  {rid:<35} [{r['status']}]  {r['title'] or ''}")
    if not direct and not transitive:
        print(f"No downstream nodes found for {nid}")


def cmd_blocked_by(db, raw_id: str):
    nid = resolve_id(db, raw_id)
    if not nid:
        return
    prev = bfs(db, [nid], 'forward', {'requires'})
    deps = set(prev) - {nid}

    open_deps, done_deps = [], []
    for did in sorted(deps):
        r = db.execute("SELECT type, title, status, priority FROM nodes WHERE id=?", (did,)).fetchone()
        if not r or r['type'] == 'unknown':
            continue
        (done_deps if is_done(r['status']) else open_deps).append((did, r))

    if open_deps:
        print(f"\nOpen blockers for {nid}:\n")
        for did, r in open_deps:
            p = f"[{r['priority']}]" if r['priority'] else '[?]'
            print(f"  {did:<35} {p:<10}  {r['title'] or ''}")
    if done_deps:
        print(f"\nCompleted prerequisites:\n")
        for did, r in done_deps:
            print(f"  ✓ {did:<33} {r['title'] or ''}")
    if not deps:
        print(f"{nid} has no dependencies.")


def cmd_path(db, raw_a: str, raw_b: str):
    a = resolve_id(db, raw_a)
    b = resolve_id(db, raw_b)
    if not a or not b:
        return
    # BFS following the "unlock sequence":
    #   reverse 'requires' (A is prereq of B → completing A reaches B)
    #   forward  'enables' (A enables B directly)
    prev: dict[str, str | None] = {a: None}
    queue = deque([a])
    while queue:
        cur = queue.popleft()
        if cur == b:
            break
        # reverse requires: things that cur unblocks
        for r in db.execute(
            "SELECT from_id AS nxt FROM edges WHERE to_id=? AND relation='requires'", (cur,)
        ).fetchall():
            nxt = r['nxt']
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
        # forward enables
        for r in db.execute(
            "SELECT to_id AS nxt FROM edges WHERE from_id=? AND relation='enables'", (cur,)
        ).fetchall():
            nxt = r['nxt']
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
    if b not in prev:
        print(f"No path found from {a} to {b}")
        return
    path = []
    cur = b
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    print(f"\nPath ({len(path)-1} hop{'s' if len(path)-1 != 1 else ''}):\n")
    for i, node in enumerate(path):
        r = db.execute("SELECT title, status FROM nodes WHERE id=?", (node,)).fetchone()
        prefix = "  → " if i > 0 else "     "
        status = f"[{r['status']}]" if r else ''
        title  = r['title'] if r else ''
        print(f"{prefix}{node:<35} {status}  {title}")


def cmd_dot(db):
    """Graphviz DOT output — pipe to dot -Tsvg > graph.svg."""
    COLORS = {
        'task':        '#aec6f7',
        'experiment':  '#b5ead7',
        'security':    '#ffd7b5',
        'spec':        '#e8d5f5',
        'deliver':     '#ffe4e1',
        'infra':       '#d4f1f9',
        'vos':         '#fffac8',
        'contact':     '#d5f5e3',
        'paper_seed':  '#fce5cd',
    }
    print('digraph vsf {')
    print('  rankdir=LR;')
    print('  node [shape=box fontsize=9 fontname="Helvetica"];')
    print('  edge [fontsize=8];')
    for r in db.execute(
        "SELECT id, type, status, title FROM nodes WHERE type!='unknown'"
    ).fetchall():
        color = COLORS.get(r['type'], '#eeeeee')
        done  = is_done(r['status'])
        style = 'filled,dashed' if done else 'filled'
        label = (r['title'] or r['id'])[:35].replace('"', "'")
        nid   = r['id'].replace('"', "'")
        print(f'  "{nid}" [label="{nid}\\n{label}" fillcolor="{color}" style="{style}"];')
    EDGE_STYLES = {
        'requires': 'solid',
        'enables':  'dashed',
        'seeds':    'dotted',
    }
    for r in db.execute("SELECT from_id, to_id, relation FROM edges").fetchall():
        style = EDGE_STYLES.get(r['relation'], 'solid')
        f = r['from_id'].replace('"', "'")
        t = r['to_id'].replace('"', "'")
        print(f'  "{f}" -> "{t}" [style={style} label="{r["relation"]}"];')
    print('}')


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="VSF project dependency graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('build',      help='Parse .vsm files and build DB')
    sub.add_parser('open',       help='List all open nodes by priority')
    sub.add_parser('roots',      help='Nodes startable now (no open deps)')
    sub.add_parser('stats',      help='Node/edge counts by type')
    sub.add_parser('dot',        help='Graphviz DOT output (pipe to dot -Tsvg)')

    sp = sub.add_parser('done',       help='Mark node done in source .vsm + rebuild + show unlocks')
    sp.add_argument('id')

    sp = sub.add_parser('show',       help='Show node details')
    sp.add_argument('id')

    sp = sub.add_parser('unblocks',   help='What completing <id> enables')
    sp.add_argument('id')

    sp = sub.add_parser('blocked-by', help='What blocks <id>')
    sp.add_argument('id')

    sp = sub.add_parser('path',       help='Shortest path between two nodes')
    sp.add_argument('from_id')
    sp.add_argument('to_id')

    args = p.parse_args()
    db = get_db()

    dispatch = {
        'build':      lambda: cmd_build(db),
        'open':       lambda: cmd_open(db),
        'roots':      lambda: cmd_roots(db),
        'stats':      lambda: cmd_stats(db),
        'dot':        lambda: cmd_dot(db),
        'done':       lambda: cmd_done(db, args.id),
        'show':       lambda: cmd_show(db, args.id),
        'unblocks':   lambda: cmd_unblocks(db, args.id),
        'blocked-by': lambda: cmd_blocked_by(db, args.id),
        'path':       lambda: cmd_path(db, args.from_id, args.to_id),
    }
    dispatch[args.cmd]()


if __name__ == '__main__':
    main()
