#!/usr/bin/env python3
"""
S5 Digest (SD) — periodic synthesis for the policy layer (§2.5).

Reads last N alerts from s5-alerts.db (pulled from LXC 101) + last experiment
from rag-nucleus.db (local WSL) → calls Qwen with SD primer → writes digest.vsm.

You are operating as S5 Digest. Retrieval scope: s5-alerts.db only.
No cross-writes to rag-nucleus.db (store isolation rule).
LLM only at the human-interface boundary (D6', R10): advisory output only.

Usage:
    python3 scripts/shared/sd_digest.py [--n 10] [--out DIR] [--dry-run]
"""

import sys, os, subprocess, datetime, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s4_store
import qwen_client
from s4_store import ALERTS_DIR

# Resolve LXC IDs from topology.json (clone-portable)
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from topology_resolve import resolve_lxc

VSF_N02 = os.environ.get('VSF_N02', 'n02')

DIGESTS_DIR  = os.path.join(os.path.expanduser('~'), '.vsf', 'digests')
REMOTE_S5_DB = '/root/.vsf/s4/s5-alerts.db'
_NUCLEUS_LXC = resolve_lxc("nucleus")
_STAR_LXC = resolve_lxc("s3star")
KPI_DB_STAR  = '/var/lib/vsf/s3_star/kpi.db'

# EXP-TRUST-01 phase A start — keep in sync with docs/experiments/EXP-TRUST-01/spec.vsm
_TRUST01_START = datetime.datetime(2026, 6, 11, 19, 0, 0, tzinfo=datetime.timezone.utc)

_SD_PRIMER = """\
You are a VSF system monitor (S5 Digest). Your retrieval scope is s5-alerts.db only.
Review the algedonic alerts below (most recent first). Also review the S3* KPI TREND
and EXP-TRUST-01 STATUS sections provided. Identify:
(1) recurring patterns across alerts;
(2) any escalating trend (class A or multiple class B in sequence);
(3) open conditions that have not resolved;
(4) whether the S3* KPI trend corroborates or contradicts the alert pattern;
(5) EXP-TRUST-01 phase A progress relative to the 7-day window.
Output a SINGLE digest block in VSL v1.0 format with a plain-language summary
and one recommended action, or advisory = "no action" if the system is nominal.
Do NOT recommend actions that modify L0/L1 directly — monitoring and experiment
proposals only. Do not invent metrics or alert content not present in the input.

Output format (fill in all fields):
digest("{date}") {
  period   = "{period}"
  alerts   = {n_alerts}
  pattern  = "..."
  trend    = "..."
  kpi_status = "..."
  open     = [...]
  advisory = "..."
}
"""


# ── Remote fetch ───────────────────────────────────────────────────────────────

def _pull_s5_db() -> str | None:
    """Pull s5-alerts.db from LXC 101 via pct pull → scp. Returns local path or None."""
    r = subprocess.run(
        ['ssh', f'root@{VSF_N02}', f'pct pull {_NUCLEUS_LXC} {REMOTE_S5_DB} /tmp/sd_s5_alerts.db'],
        capture_output=True, timeout=30
    )
    if r.returncode != 0:
        print(f"SD: pct pull failed: {r.stderr.decode().strip()[:120]}", file=sys.stderr)
        return None
    r2 = subprocess.run(
        ['scp', '-q', f'root@{VSF_N02}:/tmp/sd_s5_alerts.db', '/tmp/sd_s5_alerts.db'],
        capture_output=True, timeout=30
    )
    if r2.returncode != 0:
        print(f"SD: scp failed: {r2.stderr.decode().strip()[:120]}", file=sys.stderr)
        return None
    return '/tmp/sd_s5_alerts.db'


# ── S3* KPI trend (LXC 107) ───────────────────────────────────────────────────

def _fetch_kpi_trend(hours: int = 24) -> str:
    """24h KPI trend from LXC 107 kpi.db — first/last stasis + exceptions."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
    q_kpi = (f"SELECT ts_poll,stasis_cos,trust,viable,regime FROM kpi "
             f"WHERE ts_poll >= '{cutoff}' ORDER BY id")
    q_exc = (f"SELECT ts_poll,kind,detail FROM exceptions "
             f"WHERE ts_poll >= '{cutoff}' ORDER BY id DESC LIMIT 5")
    try:
        def _run(query: str) -> str:
            r = subprocess.run(
                ['ssh', f'root@{VSF_N02}',
                 f"pct exec {_STAR_LXC} -- sqlite3 -separator '|' {KPI_DB_STAR} \"{query}\""],
                capture_output=True, text=True, timeout=20,
            )
            return r.stdout.strip() if r.returncode == 0 else ''

        kpi_lines = [l for l in _run(q_kpi).splitlines() if '|' in l]
        exc_lines = [l for l in _run(q_exc).splitlines() if '|' in l]
    except Exception as exc:
        return f'  (kpi fetch error: {exc})'

    if not kpi_lines:
        return '  (no KPI rows in last 24h — S3* poller may be down)'

    try:
        first = kpi_lines[0].split('|')
        last  = kpi_lines[-1].split('|')
        first_sc = float(first[1]); last_sc = float(last[1])
        last_trust = float(last[2]); last_viable = last[3]; last_regime = last[4]
        delta = last_sc - first_sc
        trend = 'stable' if abs(delta) < 0.0001 else ('improving' if delta > 0 else 'declining')
        summary = (
            f"  rows={len(kpi_lines)} ({hours}h window)\n"
            f"  stasis_cos: first={first_sc:.4f} last={last_sc:.4f} "
            f"  trend={trend} (Δ={delta:+.6f})\n"
            f"  trust={last_trust:.3f} viable={last_viable} regime={last_regime}"
        )
        if exc_lines:
            summary += f"\n  S3* exceptions ({len(exc_lines)}):\n"
            for line in exc_lines:
                summary += f"    {line}\n"
        else:
            summary += "\n  S3* exceptions=0 (nominal)"
        return summary
    except (IndexError, ValueError) as exc:
        return f'  (kpi parse error: {exc})'


def _trust01_status() -> str:
    """EXP-TRUST-01 phase A elapsed time and gate status."""
    now     = datetime.datetime.now(datetime.timezone.utc)
    elapsed = (now - _TRUST01_START).total_seconds() / 86400
    remaining = max(0.0, 7.0 - elapsed)
    status  = 'COMPLETE — CHECO-PROJ calibration C1-C4 ready to run' if elapsed >= 7 else (
              f'IN PROGRESS — {remaining:.1f}d until phase A complete (gate: CHECO-PROJ)')
    return (
        f"  started=2026-06-11T19:00Z  elapsed={elapsed:.2f}d\n"
        f"  status={status}"
    )


# ── Prompt ─────────────────────────────────────────────────────────────────────

def _build_prompt(alerts: list, last_exp: dict | None,
                  kpi_trend: str = '', trust01: str = '') -> str:
    today = datetime.date.today().isoformat()
    if alerts:
        first_ts = alerts[-1].get('indexed_at', '')[:10]
        last_ts  = alerts[0].get('indexed_at',  '')[:10]
        period   = f'{first_ts} → {last_ts}'
    else:
        period = today

    alert_text = ''
    for a in alerts:
        alert_text += f'\n--- {a["exp_id"]} ({a["indexed_at"]}) ---\n'
        alert_text += a['spec_text'][:300].strip()
        alert_text += '\n'
    if not alert_text:
        alert_text = '\n(no alerts found in s5-alerts.db)\n'

    exp_text = ''
    if last_exp:
        exp_text = (
            f'\n--- LAST NUCLEUS EXPERIMENT ({last_exp["exp_id"]}, '
            f'verdict={last_exp["verdict"]}, {last_exp["indexed_at"][:10]}) ---\n'
            + last_exp['report_text'][:400].strip()
        )

    primer = (_SD_PRIMER
              .replace('{date}',    today)
              .replace('{period}',  period)
              .replace('{n_alerts}', str(len(alerts))))
    return (
        primer
        + f'\nALERTS (last {len(alerts)}, most recent first):\n'
        + alert_text
        + (f'\nLAST NUCLEUS EXPERIMENT CONTEXT:\n{exp_text}\n' if exp_text else '')
        + f'\nS3* KPI TREND (LXC 107, last 24h):\n{kpi_trend}\n'
        + f'\nEXP-TRUST-01 STATUS (phase A baseline):\n{trust01}\n'
    )


# ── Output ─────────────────────────────────────────────────────────────────────

def _wrap_digest(text: str, n_alerts: int, timestamp: str) -> str:
    """Return valid VSL 1.2.1 — use Qwen's block if present, else wrap raw text."""
    header = f'@vsm 1.2.1\n// sd_digest.py  {timestamp}\n\n'
    if 'digest(' in text:
        return header + text.strip() + '\n'
    safe = text[:300].replace('\n', ' ').replace('"', "'")
    return (
        header
        + f'digest("vsf-{timestamp[:10]}") {{\n'
        + f'  alerts   = {n_alerts}\n'
        + f'  raw      = "{safe}"\n'
        + f'}}\n'
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def run(n: int = 10, digests_dir: str = DIGESTS_DIR, dry_run: bool = False) -> int:
    print(f"SD: pulling s5-alerts.db from LXC {_NUCLEUS_LXC} ...")
    local_db = _pull_s5_db()
    if local_db is None:
        s4_store.self_alert(
            'SD pull failure',
            f'pct pull {_NUCLEUS_LXC} s5-alerts.db / scp failed',
            f'check LXC {_NUCLEUS_LXC} up + {VSF_N02} tunnel (R8)',
            ALERTS_DIR, source='sd'
        )
        return 1

    alerts  = s4_store.recent_alerts_from_db(local_db, n)
    print(f"SD: {len(alerts)} alert(s) retrieved from s5-alerts.db")

    last_exp = s4_store.last_experiment('nucleus')
    if last_exp:
        print(f"SD: last experiment = {last_exp['exp_id']} (verdict={last_exp['verdict']})")
    else:
        print("SD: no indexed experiments in rag-nucleus.db (cross-read empty)")

    print("SD: fetching S3* KPI trend from LXC 107 ...")
    kpi_trend = _fetch_kpi_trend()
    trust01   = _trust01_status()
    print(f"SD: KPI trend fetched; TRUST-01 elapsed={trust01.split('elapsed=')[1].split()[0] if 'elapsed=' in trust01 else '?'}")

    prompt = _build_prompt(alerts, last_exp, kpi_trend, trust01)

    if dry_run:
        print("SD: dry-run — prompt preview (first 800 chars):")
        print(prompt[:800])
        return 0

    print("SD: calling Qwen (sd) ...")
    response = qwen_client.generate('sd', prompt, num_predict=250, max_time=600)
    if not response:
        print("SD: Qwen call failed — self-alert already emitted by qwen_client", file=sys.stderr)
        return 1

    now  = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    vsm  = _wrap_digest(response, len(alerts), now)

    os.makedirs(digests_dir, exist_ok=True)
    fname = f'digest-{now.replace(":", "").replace("-", "")}.vsm'
    path  = os.path.join(digests_dir, fname)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(vsm)

    print(f"SD: digest → {path}")
    print('\n' + vsm)
    return 0


def main(argv: list) -> int:
    p = argparse.ArgumentParser(description='CRAG S5 Digest (SD)')
    p.add_argument('--n',       type=int, default=10,    help='alerts to read (default 10)')
    p.add_argument('--out',     default=DIGESTS_DIR,     help='digests output directory')
    p.add_argument('--dry-run', action='store_true',     help='build prompt, no Qwen call')
    a = p.parse_args(argv[1:])
    return run(a.n, a.out, a.dry_run)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
