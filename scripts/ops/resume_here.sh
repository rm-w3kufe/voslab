#!/usr/bin/env bash
# resume_here.sh — continue the latest session OF THIS DIRECTORY.
#
# WHY: `opencode -c` resumes the globally-most-recent session, so two
# terminals (main + scratch) steal each other's sessions. This helper
# queries the session store READ-ONLY for the latest session whose
# directory is $PWD and resumes it explicitly (-s). Fresh start when
# the directory never ran opencode. Extra args pass through.
#
# Usage: ./scripts/ops/resume_here.sh [extra opencode args...]
set -u

DB="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/opencode.db"
HERE="$(pwd)"

ID="$(python3 - "$DB" "$HERE" <<'PY'
import sqlite3, sys
db, here = sys.argv[1], sys.argv[2]
try:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = c.execute(
        "select id from session where directory = ? "
        "order by time_updated desc limit 1", (here,)).fetchone()
    print(row[0] if row else "")
except Exception:
    print("")
PY
)"

if [ -n "$ID" ]; then
  echo "resume_here: continuing $ID ($HERE)"
  exec opencode -s "$ID" "$@"
else
  echo "resume_here: no session for $HERE — fresh start"
  exec opencode "$@"
fi
