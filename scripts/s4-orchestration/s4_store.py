#!/usr/bin/env python3
"""
S4 Store — SQLite FTS5 index for VSF S4 intelligence layer.

Three isolated stores (one per S4 function):
  nucleus  — experiment corpus for EP (RAG retrieval; rag-nucleus.db)
  s5       — algedonic alerts for SD synthesis (s5-alerts.db)
  audit    — coupling_registry + census for SA (sa-audit.db)

Store path: VSF_S4_DIR env var, or ~/.vsf/s4/ by default.

Usage (CLI):
    python3 scripts/s4-orchestration/s4_store.py index --spec SPEC.vsm --report REPORT.vsm [--store nucleus]
    python3 scripts/s4-orchestration/s4_store.py query  TEXT [--k 3] [--store nucleus] [--json]
    python3 scripts/s4-orchestration/s4_store.py stats  [--store nucleus]

API (imported by vsl_run.py, ac_algedonic.py, sd_digest.py, sa_auditor.py):
    from s4_store import index, query, stats
"""

import sqlite3, os, sys, re, json, datetime, argparse, hmac, hashlib, subprocess

# ── Config ─────────────────────────────────────────────────────────────────────

S4_DIR = os.environ.get('VSF_S4_DIR',
                        os.environ.get('VSF_S4_DIR',  # backward compat
                                       os.path.join(os.path.expanduser('~'), '.vsf', 's4')))
STORES = ('nucleus', 'audit', 's5')

# Characters of spec/report text surfaced per retrieved entry in the context block
_SNIPPET_CHARS = 400


# ── M7: HMAC alert chain ────────────────────────────────────────────────────────
# Key stored in S5-CA vault; absent key = warn + skip (graceful degradation).
# Verification: _verify_hmac() rejects any payload whose stored HMAC doesn't match.
_HMAC_KEY_PATH = os.path.join(os.path.expanduser('~'), '.vsf', 's5-ca', 'alert_hmac.key')

def _load_hmac_key() -> bytes | None:
    """Load 32-byte hex HMAC key from S5-CA vault. Returns None if absent."""
    try:
        with open(_HMAC_KEY_PATH, 'r') as fh:
            raw = fh.read().strip()
        return bytes.fromhex(raw)
    except (OSError, ValueError):
        return None

def _compute_hmac(text: str, key: bytes) -> str:
    return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()


_DB_NAMES = {
    'nucleus': 'rag-nucleus.db',   # EP — genuine RAG store
    's5':      's5-alerts.db',     # AC writes, SD reads
    'audit':   'sa-audit.db',      # SA store
}


def db_path(store: str = 'nucleus') -> str:
    os.makedirs(S4_DIR, exist_ok=True)
    return os.path.join(S4_DIR, _DB_NAMES[store])


def _connect(store: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(store))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS corpus USING fts5(
            exp_id,
            verdict,
            spec_text,
            report_text,
            timestamp,
            tokenize='porter ascii'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            exp_id      TEXT PRIMARY KEY,
            verdict     TEXT,
            spec_path   TEXT,
            report_path TEXT,
            indexed_at  TEXT,
            hmac_sha256 TEXT
        )
    """)
    # M7: migrate existing DBs that lack hmac_sha256 column
    try:
        conn.execute("ALTER TABLE meta ADD COLUMN hmac_sha256 TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    return conn


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_exp_id(text: str) -> str:
    # Format A: id = EXP-XX-NN  (vsl_run.py emit_report / VSL v1.0 exp block)
    m = re.search(r'\bid\s*=\s*([A-Z0-9][A-Z0-9_-]+)', text)
    if m:
        return m.group(1)
    # Format B: experiment(EXP-MC-01, ...) | results(EXP-MC-01, ...) | report("EXP-MC-01")
    m = re.search(r'(?:experiment|results|report)\s*[\("\']+\s*(EXP[-_][A-Z0-9-]+)',
                  text, re.IGNORECASE)
    if m:
        return m.group(1)
    # Format C: exp("name") { ... }
    m = re.search(r'\bexp\s*\(\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    return 'UNKNOWN'


def _extract_verdict(text: str) -> str:
    # Format A: verdict = PASS  (vsl_run.py emit_report)
    m = re.search(r'\bverdict\s*=\s*(\w+)', text)
    if m:
        return m.group(1).upper()
    # Format B: status: DONE  (older .vsm results files)
    m = re.search(r'\bstatus\s*[:=]\s*(\w+)', text)
    if m:
        return m.group(1).upper()
    return 'UNKNOWN'


def _fts5_query(text: str, max_terms: int = 20) -> str:
    """Extract meaningful identifier tokens for FTS5 MATCH; avoids special-char errors."""
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text)
    seen, unique = set(), []
    for w in words:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            unique.append(w)
    return ' '.join(unique[:max_terms]) or 'experiment'


def _extract_block_snippet(text: str, block: str, chars: int = 300) -> str:
    """Extract up to `chars` chars from a named block, falling back to text tail."""
    m = re.search(rf'\b{re.escape(block)}\s*[:{{]', text)
    if m:
        return text[m.start():m.start() + chars].replace('\n', ' ').strip()
    return text[-chars:].replace('\n', ' ').strip()


def _context_block(results: list) -> str:
    """Format retrieved entries as a compact context block for Qwen prompts."""
    if not results:
        return ''
    lines = [f'--- RETRIEVED CONTEXT ({len(results)} similar experiment(s)) ---\n']
    for i, r in enumerate(results, 1):
        # Prioritise the evaluation block (metric names) and protocol block (binary path)
        eval_snip  = _extract_block_snippet(r['spec_text'], 'evaluation', 250)
        proto_snip = _extract_block_snippet(r['spec_text'], 'protocol', 250)
        rep_snip   = _extract_block_snippet(r['report_text'], 'results', 300)
        lines.append(f'[{i}] {r["exp_id"]}  verdict={r["verdict"]}')
        lines.append(f'  evaluation: {eval_snip}')
        lines.append(f'  protocol:   {proto_snip}')
        lines.append(f'  results:    {rep_snip}')
        lines.append('')
    lines.append('--- END RETRIEVED CONTEXT ---\n')
    return '\n'.join(lines)


# ── Public API ─────────────────────────────────────────────────────────────────

def index(spec_path: str, report_path: str, store: str = 'nucleus') -> int:
    """Index a validated spec+report pair. Re-indexing the same exp_id replaces the entry."""
    try:
        with open(spec_path, encoding='utf-8') as f:
            spec_text = f.read()
        with open(report_path, encoding='utf-8') as f:
            report_text = f.read()
    except OSError as e:
        print(f"CRAG index ERROR: {e}")
        return 2

    exp_id = _extract_exp_id(spec_text)
    if exp_id == 'UNKNOWN':
        exp_id = _extract_exp_id(report_text)
    if exp_id == 'UNKNOWN':
        exp_id = os.path.basename(os.path.dirname(os.path.abspath(spec_path)))
    verdict = _extract_verdict(report_text)
    now     = datetime.datetime.now(datetime.timezone.utc).isoformat()

    conn = _connect(store)
    conn.execute("DELETE FROM corpus WHERE exp_id = ?", (exp_id,))
    conn.execute("DELETE FROM meta   WHERE exp_id = ?", (exp_id,))
    conn.execute(
        "INSERT INTO corpus(exp_id,verdict,spec_text,report_text,timestamp) VALUES(?,?,?,?,?)",
        (exp_id, verdict, spec_text, report_text, now)
    )
    conn.execute(
        "INSERT INTO meta(exp_id,verdict,spec_path,report_path,indexed_at) VALUES(?,?,?,?,?)",
        (exp_id, verdict, spec_path, report_path, now)
    )
    conn.commit()
    conn.close()
    print(f"CRAG index  {exp_id}  verdict={verdict}  store={store}  → {db_path(store)}")
    return 0


def query(text: str, k: int = 3, store: str = 'nucleus') -> list:
    """BM25 FTS5 search. Returns up to k dicts with exp_id, verdict, spec_text, report_text."""
    conn = _connect(store)
    q = _fts5_query(text)
    try:
        rows = conn.execute(
            """SELECT exp_id, verdict, spec_text, report_text, bm25(corpus) AS score
               FROM corpus WHERE corpus MATCH ?
               ORDER BY bm25(corpus) LIMIT ?""",
            (q, k)
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def context_for_prompt(text: str, k: int = 3, store: str = 'nucleus') -> str:
    """Return a formatted context block (empty string if corpus is empty or no match)."""
    return _context_block(query(text, k, store))


# ── EP domain-first retrieval (S4-MULTI-S1, Phase 3) ─────────────────────────
# Spec §phase_3_ep_extension: propose retrieves from rag-{domain}.db FIRST,
# then falls back cross-domain (rag-nucleus.db) only when k < 3 results.
# No LLM, no NATS — pure FTS5 on the per-domain bundle stores.

DOMAIN_ALIASES = {
    'nucleus':  'nucleus',        # vsf-nucleus experiment corpus (existing)
    'clima':    'clima',          # s1-clima bundle store (rag-clima.db, LXC 101)
    'econ':     'econ',           # s1-econ bundle store (rag-econ.db, LXC 101)
    's1-clima': 'clima',
    's1-econ':  'econ',
}

# Remote bundle stores live on LXC 101 (canonical), pulled on demand (sd_digest pattern)
_REMOTE_DOMAIN_STORE = {
    'clima': ('root@n02', 'pct pull 101 /var/lib/vsf/vsf_nucleus/rag-clima.db /tmp/s4_pull_rag_clima.db'),
    'econ':  ('root@n02', 'pct pull 101 /var/lib/vsf/vsf_nucleus/rag-econ.db /tmp/s4_pull_rag_econ.db'),
}
_PULL_CACHE = '/tmp/s4_pull_rag_{domain}.db'


def _domain_store_path(domain: str) -> str | None:
    """Local path of the per-domain bundle store (rag-{domain}.db) or None.

    Checks local S4_DIR first (WSL side), then pulls from LXC 101 on demand
    (mirrors sd_digest._pull_s5_db). Returns None if neither is available.
    """
    alias = DOMAIN_ALIASES.get(domain)
    if not alias:
        return None
    local = os.path.join(S4_DIR, f'rag-{alias}.db')
    if os.path.exists(local):
        return local
    pull_cfg = _REMOTE_DOMAIN_STORE.get(alias)
    if not pull_cfg:
        return None
    host, cmd = pull_cfg
    cache = _PULL_CACHE.format(domain=alias)
    try:
        r = subprocess.run(['ssh', host, cmd], capture_output=True, timeout=20)
        if r.returncode != 0:
            return None
        r2 = subprocess.run(['scp', '-q', f'{host}:{cache}', cache],
                            capture_output=True, timeout=20)
        return cache if r2.returncode == 0 else None
    except Exception:
        return None


def query_domain(text: str, domain: str, k: int = 3) -> list:
    """BM25 FTS5 search of a per-domain bundle store (rag-{domain}.db).

    Returns up to k dicts with domain, ts, algedonic_status, enso_state,
    events_text (bundle-store schema). Empty list if the store is unreachable
    or has no match — caller falls back cross-domain (spec rule: no cross-writes;
    cross-READ allowed only for EP fallback when k < 3).
    """
    path = _domain_store_path(domain)
    if not path:
        return []
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        q = _fts5_query(text)
        rows = conn.execute(
            """SELECT domain, ts, algedonic_status, enso_state, events_text,
                      bm25(context_store) AS score
               FROM context_store WHERE context_store MATCH ?
               ORDER BY bm25(context_store) LIMIT ?""",
            (q, k)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    except Exception:
        return []


def _domain_context_block(results: list) -> str:
    """Format per-domain bundle-store results as a compact context block."""
    if not results:
        return ''
    lines = [f'--- RETRIEVED DOMAIN CONTEXT ({len(results)} recent bundle(s)) ---\n']
    for i, r in enumerate(results, 1):
        lines.append(f'[{i}] domain={r.get("domain", "?")}  ts={r.get("ts", "?")}  '
                     f'algedonic={r.get("algedonic_status", "?")}  state={r.get("enso_state", "?")}')
        lines.append(f'  events: {r.get("events_text", "")[:300]}')
        lines.append('')
    lines.append('--- END RETRIEVED DOMAIN CONTEXT ---\n')
    return '\n'.join(lines)


def context_for_prompt_domain_first(text: str, domain: str, k: int = 3) -> str:
    """EP domain-first retrieval: query rag-{domain}.db, fallback to rag-nucleus.db
    when k < 3 results (spec §phase_3_ep_extension + store_isolation rule 7).

    Returns combined formatted context (domain block first, then cross-domain
    experiment block). Empty string if both stores are unreachable/empty.
    """
    domain_results = query_domain(text, domain, k)
    ctx = _domain_context_block(domain_results)

    shortfall = k - len(domain_results)
    if shortfall > 0:
        # Cross-domain fallback (read-only; spec rule 7) — nucleus experiment corpus
        nucleus_results = query(text, shortfall, store='nucleus')
        if nucleus_results:
            if ctx:
                ctx += '\n'
            ctx += _context_block(nucleus_results)
    return ctx


# ── Algedonic alert persistence (s5-alerts.db — AC/qwen_client writers) ─────────

ALERTS_DIR = os.path.join(os.path.expanduser('~'), '.vsf', 'alerts')


def persist_alert(vsm: str, timestamp: str, alerts_dir: str = ALERTS_DIR) -> str:
    """Write alert.vsm to disk and index into s5-alerts.db. Returns file path."""
    os.makedirs(alerts_dir, exist_ok=True)
    fname = f'alert-{timestamp.replace(":", "").replace("-", "")}.vsm'
    path  = os.path.join(alerts_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(vsm)

    exp_id = f'alert-{timestamp}'
    conn = _connect('s5')
    conn.execute("DELETE FROM corpus WHERE exp_id = ?", (exp_id,))
    conn.execute("DELETE FROM meta   WHERE exp_id = ?", (exp_id,))
    conn.execute(
        "INSERT INTO corpus(exp_id,verdict,spec_text,report_text,timestamp) VALUES(?,?,?,?,?)",
        (exp_id, 'alert', vsm, vsm, timestamp)
    )
    # M7: compute HMAC over VSM text for pre-storage integrity (key from S5-CA vault)
    hmac_key = _load_hmac_key()
    hmac_val = _compute_hmac(vsm, hmac_key) if hmac_key else None
    if not hmac_key:
        print('s4_store: WARN alert_hmac.key absent — HMAC not computed', file=sys.stderr)

    conn.execute(
        "INSERT INTO meta(exp_id,verdict,spec_path,report_path,indexed_at,hmac_sha256) VALUES(?,?,?,?,?,?)",
        (exp_id, 'alert', path, path, timestamp, hmac_val)
    )
    conn.commit()
    conn.close()
    return path


def verify_alert_integrity(exp_id: str, alerts_dir: str = ALERTS_DIR) -> bool:
    """Verify the stored HMAC matches the VSM file on disk.
    Returns True if valid; False if tampered or key unavailable.
    Accept criterion (M7): tampered payload detected before re-use in S4 chain."""
    hmac_key = _load_hmac_key()
    if not hmac_key:
        print('s4_store: verify_alert_integrity: HMAC key absent', file=sys.stderr)
        return False
    conn = _connect('s5')
    row = conn.execute(
        "SELECT spec_path, hmac_sha256 FROM meta WHERE exp_id = ?", (exp_id,)
    ).fetchone()
    conn.close()
    if not row or not row['hmac_sha256']:
        return False
    try:
        with open(row['spec_path'], encoding='utf-8') as fh:
            vsm_text = fh.read()
    except OSError:
        return False
    expected = _compute_hmac(vsm_text, hmac_key)
    ok = hmac.compare_digest(expected, row['hmac_sha256'])
    if not ok:
        print(f's4_store: INTEGRITY FAIL for {exp_id} — payload tampered', file=sys.stderr)
    return ok


def self_alert(label: str, evidence: str, action: str,
               alerts_dir: str = ALERTS_DIR, source: str = 'ac') -> str:
    """A monitor failure is itself an algedonic signal — class-B self-alert,
    deterministic (monitor-the-monitor, S3* pattern). Best-effort: never masks
    the original error."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    vsm = (
        f'@vsm 1.2.1\n// {source} SELF-ALERT  {now}\n\n'
        f'alert("{source}-self-{now}") {{\n'
        f'  class    = B\n'
        f'  label    = "{label}"\n'
        f'  evidence = "{evidence}"\n'
        f'  context  = "emitted by {source} about its own failure path"\n'
        f'  action   = "{action}"\n'
        f'}}\n'
    )
    try:
        path = persist_alert(vsm, now, alerts_dir)
    except Exception as e:
        print(f"{source}: self-alert persist failed: {e}", file=sys.stderr)
        return ''
    print(f"{source}: self-alert → {path}", file=sys.stderr)
    return path


def recent_alerts_from_db(db_file: str, n: int = 10) -> list:
    """Return last N alerts from a pulled s5-alerts.db file (most recent first).
    Used by SD after fetching the remote db — avoids mutating the live store."""
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT m.exp_id, m.indexed_at, c.spec_text "
            "FROM meta m, corpus c "
            "WHERE c.exp_id = m.exp_id "
            "ORDER BY m.indexed_at DESC LIMIT ?",
            (n,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def last_experiment(store: str = 'nucleus') -> dict | None:
    """Return the most recently indexed entry from the given local store (WSL-side)."""
    try:
        conn = _connect(store)
        row = conn.execute(
            "SELECT m.exp_id, m.verdict, m.indexed_at, c.spec_text, c.report_text "
            "FROM meta m, corpus c "
            "WHERE c.exp_id = m.exp_id "
            "ORDER BY m.indexed_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def stats(store: str = 'nucleus') -> int:
    conn = _connect(store)
    total = conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
    rows  = conn.execute(
        "SELECT verdict, COUNT(*) n FROM meta GROUP BY verdict ORDER BY n DESC"
    ).fetchall()
    conn.close()
    print(f"CRAG store={store}  path={db_path(store)}")
    print(f"  total: {total} experiment(s)")
    for r in rows:
        print(f"  {r['verdict']}: {r['n']}")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    cmd = argv[1]

    if cmd == 'index':
        p = argparse.ArgumentParser(prog='s4_store index')
        p.add_argument('--spec',   required=True)
        p.add_argument('--report', required=True)
        p.add_argument('--store',  default='nucleus', choices=STORES)
        a = p.parse_args(argv[2:])
        return index(a.spec, a.report, a.store)

    if cmd == 'query':
        p = argparse.ArgumentParser(prog='s4_store query')
        p.add_argument('text', nargs='+')
        p.add_argument('--k',     type=int, default=3)
        p.add_argument('--store', default='nucleus', choices=STORES)
        p.add_argument('--json',  action='store_true')
        a = p.parse_args(argv[2:])
        results = query(' '.join(a.text), a.k, a.store)
        if a.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"CRAG query  store={a.store}  k={a.k}  → {len(results)} result(s)")
            for r in results:
                print(f"  {r['exp_id']}  verdict={r['verdict']}  score={r['score']:.3f}")
        return 0

    if cmd == 'domain-query':
        p = argparse.ArgumentParser(prog='s4_store domain-query')
        p.add_argument('text', nargs='+')
        p.add_argument('--domain', required=True, choices=sorted(DOMAIN_ALIASES))
        p.add_argument('--k', type=int, default=3)
        a = p.parse_args(argv[2:])
        results = query_domain(' '.join(a.text), a.domain, a.k)
        print(f"CRAG domain-query  domain={a.domain}  k={a.k}  → {len(results)} result(s)")
        for r in results:
            print(f"  {r.get('domain')}  {r.get('ts')}  alg={r.get('algedonic_status')}  "
                  f"score={r.get('score', 0):.3f}")
        return 0

    if cmd == 'stats':
        p = argparse.ArgumentParser(prog='s4_store stats')
        p.add_argument('--store', default='nucleus', choices=STORES)
        a = p.parse_args(argv[2:])
        return stats(a.store)

    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
