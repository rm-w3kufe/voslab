#!/usr/bin/env bash
# q.sh — thin wrapper around `sqlite3` for vsf-state.db queries.
#
# Friendly defaults: column headers on, separator | (tab if --tsv).
#
# Usage:
#   vsf-q                       # show common verbs
#   vsf-q 'SELECT ...'          # raw query
#   vsf-q services              # active services snapshot
#   vsf-q components            # all components
#   vsf-q chains                # chain state
#   vsf-q blockers              # tasks blocking BBH
# NOTE: 'rules' verb removed 2026-08-12 — the rules table was dropped from
# state.db (R7-RULES-TABLE-CLEANUP-2026-08-11). Rules are declared in
# system/boot/hard_rules.vsm, never polled from state.db.
set -euo pipefail

DB=/var/lib/vsf-state/state.db
[[ -f "$DB" ]] || { echo "$DB not initialized — run bootstrap.sh" >&2; exit 2; }

FMT="-header -column"
if [[ "${1:-}" == "--tsv" ]]; then FMT="-tabs"; shift; fi

if [[ $# -eq 0 ]]; then
    cat <<EOF
vsf-q verbs:
  services     services snapshot (v_services_summary view)
  components   declared components (source + build + deploy mapping)
  chains       chain_state of nucleus + s3_star
  blockers     open tasks with blocks_bbh=1
  topology     lxcs
  specs        declared spec docs
  queue        algedonic NATS queue view (TELEMETRY-01 P4): live ledger_A
               vs retired ledger_B + operator_inbox freshness + verdict

Or pass a raw SQL string:
  vsf-q "SELECT name, deploy_target_lxc FROM components WHERE source_dir IS NOT NULL"
EOF
    exit 0
fi

case "$1" in
    services)   sqlite3 $FMT "$DB" 'SELECT * FROM v_services_summary' ;;
    components) sqlite3 $FMT "$DB" 'SELECT name, source_dir, build_lxc, deploy_target_lxc FROM components ORDER BY deploy_target_lxc, name' ;;
    chains)     sqlite3 $FMT "$DB" 'SELECT chain_id, lxc, line_count, substr(head_hash,1,16) AS head, last_event_ts, refreshed_at FROM chain_state' ;;
    blockers)   sqlite3 $FMT "$DB" 'SELECT * FROM v_open_blockers' ;;
    topology)   sqlite3 $FMT "$DB" 'SELECT id, role, ip FROM lxcs ORDER BY id' ;;
    specs)      sqlite3 $FMT "$DB" 'SELECT path, status, last_updated FROM specs' ;;
    queue)
        # TELEMETRY-01 P4 — vista de cola NATS para rmw3 (orden S5
        # post-propuesta: "ver la cola antes de alimentarla").
        #   LIVE    ledger_A = LXC104 /root/algedonic/ledger.db — vsf_s5_ledger.py
        #           subscribes vsf.<id>.algedonic.>, writes rows continuously.
        #   RETIRED ledger_B = $DB.algedonic_ledger — orphan history (q17.phase_3,
        #           2026-07-26: preserved, NO writers, frozen by design).
        #   INBOX   /alerts/operator_inbox.log @104 — dual-channel file copy.
        # max_age estricto (ronda-2): channel fresh iff newest ledger_A write
        # (any status) <= 15 min old; else STALE (feeder must fall back
        # visibly — R9, nunca silencio). Exit 1 iff the LIVE section fails.
        python3 - "$DB" <<'PYEOF'
import datetime as dt
import subprocess
import sys

DB = sys.argv[1]
MAX_AGE_S = 15 * 60
NOW = dt.datetime.now(dt.timezone.utc)
LIVE = "/root/algedonic/ledger.db"
LXC = "104"


def parse(ts):
    if not ts or ts == "-":
        return None
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(ts)
    except ValueError:
        return None


def age_str(when):
    if when is None:
        return "?"
    d = NOW - when
    s = int(d.total_seconds())
    if s < 0:
        return "0s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // 86400}d{(s % 86400) // 3600:02d}h"


def pct_sqlite(db, sql):
    """Run one sqlite3 inside LXC; return (ok, out, err)."""
    p = subprocess.run(
        ["pct", "exec", LXC, "--", "sqlite3", "-cmd", ".timeout 3000",
         "-separator", "|", db, sql],
        capture_output=True, text=True, timeout=30,
    )
    return p.returncode == 0, p.stdout.strip(), p.stderr.strip()


rc = 0
fresh = False
print(f"=== algedonic queue view (TELEMETRY-01 P4) — {NOW.strftime('%Y-%m-%dT%H:%M:%SZ')} ===")
print(f"max_age: {MAX_AGE_S // 60} min (strict, ronda-2) on ledger_A newest write\n")

# ── LIVE: ledger_A ───────────────────────────────────────────────────────
SQL = (
    "SELECT COUNT(*) FROM algedonic_ledger WHERE status='pending_human';"
    "SELECT COALESCE(MAX(ts),'-') FROM algedonic_ledger WHERE status='pending_human';"
    "SELECT COALESCE(MAX(ts),'-') FROM algedonic_ledger;"
    "SELECT type||'='||COUNT(*) FROM algedonic_ledger "
    "WHERE status='pending_human' GROUP BY type ORDER BY COUNT(*) DESC;"
    "SELECT group_concat(status||'='||n,' ') FROM "
    "(SELECT status, COUNT(*) n FROM algedonic_ledger GROUP BY status);"
)
ok, out, err = pct_sqlite(LIVE, SQL)
if not ok:
    print(f"[LIVE] FAIL — pct exec {LXC} sqlite: {err or out}", file=sys.stderr)
    rc = 1
else:
    lines = out.splitlines()
    pending = lines[0] if lines else "?"
    newest_p = parse(lines[1]) if len(lines) > 1 else None
    newest_a = parse(lines[2]) if len(lines) > 2 else None
    types = lines[3:-1] if len(lines) > 3 else []
    statuses = lines[-1] if len(lines) > 4 else "?"
    ch_age = age_str(newest_a)
    fresh = newest_a is not None and (NOW - newest_a).total_seconds() <= MAX_AGE_S
    verdict = "FRESH" if fresh else "STALE"
    print(f"[LIVE] ledger_A {LXC}:{LIVE}  (NATS vsf.<id>.algedonic.> → vsf_s5_ledger.py)")
    print(f"  pending_human : {pending}   newest pending: "
          f"{lines[1] if len(lines) > 1 else '?'} (age {age_str(newest_p)})")
    print(f"  channel write : {lines[2] if len(lines) > 2 else '?'} (age {ch_age}) → {verdict}")
    print(f"  by type       : {' '.join(types) if types else '(none)'}")
    print(f"  statuses      : {statuses}")

# ── RETIRED: ledger_B ────────────────────────────────────────────────────
try:
    p = subprocess.run(
        ["sqlite3", "-cmd", ".timeout 3000", "-separator", "|", DB,
         "SELECT COUNT(*) FROM algedonic_ledger WHERE status='pending_human';"
         "SELECT COALESCE(MAX(ts),'-') FROM algedonic_ledger;"
         "SELECT COUNT(*) FROM algedonic_ledger;"],
        capture_output=True, text=True, timeout=30,
    )
    lines = p.stdout.splitlines()
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    print(f"\n[RETIRED] ledger_B {DB}.algedonic_ledger (q17.phase_3, preservada sin escritores)")
    print(f"  pending_human : {lines[0]}   frozen since "
          f"{lines[1]} (age {age_str(parse(lines[1]))})   rows={lines[2] if len(lines) > 2 else '?'}")
    print("  NOTE: P1 StateDbFeeder lee ESTA tabla → queue_up=1.0 pinneado (divergencia declarada P4)")
except Exception as e:  # noqa: BLE001 — the view reports, never hides
    print(f"[RETIRED] ERROR — {e}", file=sys.stderr)

# ── INBOX: dual-channel file ─────────────────────────────────────────────
p = subprocess.run(
    ["pct", "exec", LXC, "--", "bash", "-c",
     "stat -c %Y /alerts/operator_inbox.log; tail -n 1 /alerts/operator_inbox.log | cut -c1-60"],
    capture_output=True, text=True, timeout=30,
)
if p.returncode == 0:
    parts = p.stdout.splitlines()
    mtime = dt.datetime.fromtimestamp(int(parts[0]), dt.timezone.utc)
    head = parts[1] if len(parts) > 1 else "?"
    print(f"\n[INBOX] operator_inbox.log @{LXC}  mtime {mtime.strftime('%Y-%m-%dT%H:%M:%SZ')} "
          f"(age {age_str(mtime)})  last: {head}")
else:
    print(f"\n[INBOX] ERROR — {p.stderr.strip()}", file=sys.stderr)

# ── verdict ──────────────────────────────────────────────────────────────
if rc != 0:
    verdict = "LIVE section FAILED — no se pudo leer ledger_A (ver ERROR arriba)"
elif fresh:
    verdict = ("channel FRESH (write <= 15m) — cola lista para alimentar "
               "(fuente definitiva = ledger_A + operator_inbox, D9)")
else:
    verdict = ("channel STALE (> 15m sin escritura) — feeder debe caer a "
               "fallback VISIBLE (feeder_stale, ronda-2) — R9, nunca silencio")
print("\nVERDICT: " + verdict)
sys.exit(rc)
PYEOF
        ;;
    *)          sqlite3 $FMT "$DB" "$1" ;;
esac
