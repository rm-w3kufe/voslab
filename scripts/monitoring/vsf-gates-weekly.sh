#!/bin/bash
# vsf-gates-weekly.sh — weekly gate-suite run, alert-on-fail only.
# S5 approved 2026-10-12 (Sunday 04:00 UTC window, Persistent=true for
# WSL sleep). Passes are silent (no spam); failures append ONE algedonic
# alert to state/rsi/alerts.jsonl, surfaced at next session.created.
# Pair: vsf-gates-weekly.service + vsf-gates-weekly.timer (user units).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ALERTS="$REPO_ROOT/state/rsi/alerts.jsonl"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

OUT=$(python3 "$REPO_ROOT/packages/framework/run_gates.py" 2>&1)
RC=$?

if [ "$RC" -eq 0 ]; then
  echo "[$TS] gates weekly: PASS"
  exit 0
fi

DETAIL=$(printf '%s' "$OUT" | tail -5 | tr '\n' ';' | cut -c1-300)
ALERT_ID="alert-$(date +%s)000-$$"
python3 - "$ALERTS" "$ALERT_ID" "$TS" "$DETAIL" "$RC" <<'EOF'
import json, sys
path, aid, ts, detail, rc = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
rec = {"alert_id": aid, "ts": ts, "level": "error",
       "alert_type": "gates_weekly_fail",
       "source": "vsf-gates-weekly.timer",
       "detail": f"weekly gate-suite failed rc={rc}: {detail}",
       "evidence": {"rc": int(rc)}, "trace_id": None, "session_id": None}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
print(f"alerted: {aid}")
EOF
echo "[$TS] gates weekly: FAIL rc=$RC (alert appended)"
exit "$RC"
