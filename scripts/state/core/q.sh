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
# docs/spec_revision/system/boot/hard_rules.vsm, never polled from state.db.
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
    *)          sqlite3 $FMT "$DB" "$1" ;;
esac
