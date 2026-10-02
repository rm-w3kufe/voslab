#!/usr/bin/env python3
"""
Semantic Auditor (SA) — S3* semantic coherence layer (§2.4).

Reads coupling_registry + state.db component census (pulled from n02) plus
recent experiment reports from rag-nucleus.db → calls Qwen with SA primer →
writes audit_flag.vsm to ~/.vsf/audit-flags/ and indexes into sa-audit.db.

You are operating as Semantic Auditor. Retrieval scope: sa-audit.db only.
No cross-writes to rag-nucleus.db or s5-alerts.db (store isolation rule).
LLM only at the human-interface boundary (D6', R10): O1 advisory only.
SA never triggers automated action — findings go to vsf-s3-star output.

Usage:
    python3 scripts/audit/sa_auditor.py [--subject EXP-ID] [--out DIR] [--dry-run]
    (no --subject = audit all recent experiments in rag-nucleus.db)
"""

import sys, os, subprocess, datetime, json, sqlite3, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s4_store
import qwen_client
from s4_store import ALERTS_DIR

STATE_DB_REMOTE = os.environ.get('VSF_STATE_DB', '/var/lib/vsf-state/state.db')
KPI_DB          = os.environ.get('VSF_KPI_DB', '/var/lib/vsf/s3_star/kpi.db')


def _fetch_kpi_exceptions(hours: int = 24, k: int = 20) -> list:
    """S3*.c — last exceptions from the KPI poller (local on LXC 107).
    Variety reduction BEFORE the LLM boundary: SA audits exceptions, not raw dumps."""
    if not os.path.exists(KPI_DB):
        return []
    try:
        from datetime import timedelta, timezone as _tz
        cutoff = (datetime.datetime.now(_tz.utc)
                  - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        conn = sqlite3.connect(KPI_DB)
        rows = conn.execute(
            'SELECT id, ts_poll, kind, detail, ref FROM exceptions '
            'WHERE ts_poll >= ? ORDER BY id DESC LIMIT ?', (cutoff, k)).fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f'SA: kpi exceptions fetch error: {e}', file=sys.stderr)
        return []


def _is_caution_active() -> bool:
    """Check s5.caution_mode in state.db (via SSH to n02 or local path)."""
    db = STATE_DB_REMOTE
    # Local path (running on n02 host directly)
    if os.path.exists(db):
        try:
            conn = sqlite3.connect(db)
            row  = conn.execute("SELECT value FROM s5_policy WHERE key='s5.caution_mode'").fetchone()
            exp  = conn.execute("SELECT value FROM s5_policy WHERE key='s5.caution_expires'").fetchone()
            conn.close()
            if not row or row[0] != 'true':
                return False
            if exp:
                from datetime import timezone
                expires = datetime.datetime.fromisoformat(exp[0].replace('Z', '+00:00'))
                return datetime.datetime.now(timezone.utc) <= expires
            return True
        except Exception:
            return False
    # Remote path (running from WSL or LXC)
    try:
        r = subprocess.run(
            ['ssh', 'root@n02',
             f"sqlite3 {db} \"SELECT key||'='||value FROM s5_policy "
             f"WHERE key IN ('s5.caution_mode','s5.caution_expires')\""],
            capture_output=True, timeout=10, text=True
        )
        if r.returncode != 0:
            return False
        kv = dict(line.split('=', 1) for line in r.stdout.strip().splitlines() if '=' in line)
        if kv.get('s5.caution_mode') != 'true':
            return False
        exp = kv.get('s5.caution_expires')
        if exp:
            from datetime import timezone
            expires = datetime.datetime.fromisoformat(exp.replace('Z', '+00:00'))
            return datetime.datetime.now(timezone.utc) <= expires
        return True
    except Exception:
        return False  # fail-open: caution check failure must not block audits

AUDIT_FLAGS_DIR = os.path.join(os.path.expanduser('~'), '.vsf', 'audit-flags')

_SA_PRIMER = """\
You are a VSF semantic auditor (S3* Semantic Auditor). Your retrieval scope is \
sa-audit.db only.
Review the artifacts below and flag logical inconsistencies. Report ONLY what you \
observe in the provided text — do not infer or speculate beyond the artifacts.

Flag if you detect any of:
(1) A report.vsm verdict that contradicts the metric values recorded in the run
    (e.g. verdict=PASS but stasis_cos < 0.80 throughout).
(2) A coupling_registry entry whose declared dependency has no matching row in
    the state.db components table.
(3) An experiment with verdict=PASS where no supporting metric evidence appears
    in the report.
(4) An S3* KPI exception (listed under KPI_EXCEPTIONS, if any) that contradicts
    an experiment verdict or a coupling_registry claim — reference the exception
    id in your evidence field.

Output one audit_flag block per anomaly found. If no anomalies: output nothing.

Output format (VSL v1.0):
audit_flag("SUBJECT-TIMESTAMP") {
  class    = C
  subject  = "EXP-XX-NN or coupling-resource-id"
  anomaly  = "one sentence describing the inconsistency"
  evidence = "which artifact / line / field shows it"
  action   = "human review recommended before acting on this artifact"
}
"""


# ── Remote fetch: coupling_registry + components ───────────────────────────────

def _fetch_registry_and_components() -> tuple[str, str]:
    """Return (coupling_registry_json, components_json) from n02 state.db."""
    query = (
        "SELECT resource, kind, endpoint, protocol, capabilities, "
        "       access_model, governance, status "
        "FROM coupling_registry WHERE status='active' ORDER BY resource;"
    )
    query2 = (
        "SELECT name, deploy_target_lxc, deploy_path, notes "
        "FROM components ORDER BY name;"
    )
    try:
        r = subprocess.run(
            ['ssh', 'root@n02',
             f'sqlite3 -json /var/lib/vsf-state/state.db "{query}"'],
            capture_output=True, timeout=30, text=True
        )
        reg = r.stdout.strip() if r.returncode == 0 else '[]'

        r2 = subprocess.run(
            ['ssh', 'root@n02',
             f'sqlite3 -json /var/lib/vsf-state/state.db "{query2}"'],
            capture_output=True, timeout=30, text=True
        )
        comp = r2.stdout.strip() if r2.returncode == 0 else '[]'
    except Exception as e:
        print(f"SA: registry/components fetch error: {e}", file=sys.stderr)
        return '[]', '[]'
    return reg, comp


# ── Prompt ─────────────────────────────────────────────────────────────────────

def _build_prompt(registry_json: str, components_json: str,
                  experiments: list, subject: str | None,
                  kpi_exceptions: list | None = None) -> str:
    # Compact registry
    try:
        reg = json.loads(registry_json)
        reg_text = '\n'.join(
            f"  {r['resource']} [{r['kind']}] → {r.get('endpoint','?')} "
            f"(status={r.get('status','?')})"
            for r in reg
        ) or '  (empty)'
    except Exception:
        reg_text = registry_json[:800]

    # Compact components
    try:
        comps = json.loads(components_json)
        comp_set = {c['name'] for c in comps}
        comp_text = '\n'.join(
            f"  {c['name']} → lxc={c.get('deploy_target_lxc','?')} "
            f"path={c.get('deploy_path','?')}"
            for c in comps
        ) or '  (empty)'
    except Exception:
        comp_set  = set()
        comp_text = components_json[:600]

    # Experiments block
    exp_text = ''
    for e in experiments:
        ts = (e.get('indexed_at') or e.get('timestamp') or '')[:10]
        exp_text += (
            f"\n--- {e['exp_id']}  verdict={e['verdict']} ({ts}) ---\n"
        )
        exp_text += e['report_text'][:600].strip() + '\n'
    if not exp_text:
        exp_text = '\n(no indexed experiments)\n'

    subject_hint = f'\nAuditing subject: {subject}\n' if subject else ''

    # S3*.c — exception block (management by exception: only deviations reach the LLM)
    if kpi_exceptions:
        kpi_text = '\n'.join(
            f'  [#{r[0]}] {r[1]} {r[2]}: {r[3]} ({r[4]})' for r in kpi_exceptions)
    else:
        kpi_text = '  (none in the last 24h — KPI stream nominal)'

    return (
        _SA_PRIMER
        + subject_hint
        + '\nCOUPLING_REGISTRY (active entries):\n' + reg_text
        + '\n\nCOMPONENTS (state.db):\n' + comp_text
        + '\n\nKPI_EXCEPTIONS (S3* poller, last 24h):\n' + kpi_text
        + '\n\nEXPERIMENT REPORTS (from rag-nucleus.db):\n' + exp_text
    )


# ── Output ─────────────────────────────────────────────────────────────────────

def _parse_flags(text: str) -> list[str]:
    """Extract audit_flag(...) { ... } blocks from Qwen response."""
    flags, depth, current = [], 0, []
    for line in text.splitlines():
        if 'audit_flag(' in line and depth == 0:
            current = [line]
            depth = line.count('{') - line.count('}')
        elif current:
            current.append(line)
            depth += line.count('{') - line.count('}')
            if depth <= 0:
                flags.append('\n'.join(current))
                current, depth = [], 0
    return flags


def _write_flag(flag_vsm: str, timestamp: str, flags_dir: str) -> str:
    os.makedirs(flags_dir, exist_ok=True)
    fname = f'audit-flag-{timestamp.replace(":", "").replace("-", "")}.vsm'
    path  = os.path.join(flags_dir, fname)
    full  = f'@vsm 1.2.1\n// sa_auditor.py  {timestamp}\n\n' + flag_vsm.strip() + '\n'
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(full)
    # Index into sa-audit.db (SA store — never writes to nucleus or s5)
    s4_store.index(path, path, store='audit')
    return path


# ── Main ───────────────────────────────────────────────────────────────────────

def run(subject: str | None = None, flags_dir: str = AUDIT_FLAGS_DIR,
        dry_run: bool = False) -> int:
    print("SA: fetching coupling_registry + components from n02 ...")
    reg_json, comp_json = _fetch_registry_and_components()

    # Get experiment reports — subject-filtered or last 5
    if subject:
        experiments = s4_store.query(subject, k=3, store='nucleus')
    else:
        experiments = s4_store.query('experiment viability stasis', k=5, store='nucleus')
    print(f"SA: {len(experiments)} experiment(s) in audit scope")

    kpi_exceptions = _fetch_kpi_exceptions()
    print(f"SA: {len(kpi_exceptions)} KPI exception(s) in window (S3*.c)")

    prompt = _build_prompt(reg_json, comp_json, experiments, subject, kpi_exceptions)

    if dry_run:
        print("SA: dry-run — prompt preview (first 800 chars):")
        print(prompt[:800])
        return 0

    if _is_caution_active():
        print("SA: S5 caution mode ACTIVE — skipping Qwen call (M3); data fetched and logged only")
        return 0

    print("SA: calling Qwen (sa) ...")
    response = qwen_client.generate('sa', prompt, num_predict=500)
    if not response:
        print("SA: Qwen call failed — self-alert already emitted by qwen_client",
              file=sys.stderr)
        return 1

    now   = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    flags = _parse_flags(response)

    if not flags:
        print(f"SA: no anomalies detected (Qwen response: {response[:120]!r})")
        return 0

    print(f"SA: {len(flags)} audit flag(s) found")
    for flag in flags:
        path = _write_flag(flag, now, flags_dir)
        print(f"SA: flag → {path}")
        print(flag[:300])
    return 0


def main(argv: list) -> int:
    p = argparse.ArgumentParser(description='CRAG Semantic Auditor (SA)')
    p.add_argument('--subject', default=None, help='experiment id to audit (default: recent)')
    p.add_argument('--out',     default=AUDIT_FLAGS_DIR, help='audit flags output directory')
    p.add_argument('--dry-run', action='store_true',     help='build prompt, no Qwen call')
    a = p.parse_args(argv[1:])
    return run(a.subject, a.out, a.dry_run)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
