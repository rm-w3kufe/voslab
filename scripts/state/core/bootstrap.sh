#!/usr/bin/env bash
# bootstrap.sh — one-time install of vsf-state.db on n02.
#
# Run AS ROOT ON n02:
#   bash bootstrap.sh
#
# Idempotent: re-running it re-applies schema (CREATE IF NOT EXISTS) and
# re-seeds (INSERT OR REPLACE). Does NOT clobber the live tables
# (services, chain_state, deploys) — those are managed by populate.sh.

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "must run as root" >&2; exit 1
fi

if ! command -v sqlite3 >/dev/null; then
    echo "installing sqlite3..."
    apt-get update -qq && apt-get install -y -qq sqlite3
fi

DIR=/var/lib/vsf-state
DB="$DIR/state.db"
mkdir -p "$DIR"
chmod 0750 "$DIR"

HERE="$(cd "$(dirname "$0")" && pwd)"

sqlite3 "$DB" < "$HERE/../sql/schema.sql"
sqlite3 "$DB" < "$HERE/../sql/seed.sql"

install -m 0755 "$HERE/populate.sh" /usr/local/bin/vsf-state-populate
install -m 0755 "$HERE/q.sh"        /usr/local/bin/vsf-q

echo "## bootstrap ok"
echo "  db:        $DB ($(stat -c %s "$DB") bytes)"
echo "  populate:  /usr/local/bin/vsf-state-populate"
echo "  query:     /usr/local/bin/vsf-q"
echo
echo "## first refresh:"
/usr/local/bin/vsf-state-populate

echo
echo "## sanity:"
/usr/local/bin/vsf-q 'SELECT id, role FROM lxcs'
/usr/local/bin/vsf-q "SELECT count(*) || ' components' FROM components"
# note: rules table dropped 2026-08-12 (R7-RULES-TABLE-CLEANUP-2026-08-11) —
# rules are declared in docs/spec_revision/system/boot/hard_rules.vsm, never
# mirrored in state.db.
