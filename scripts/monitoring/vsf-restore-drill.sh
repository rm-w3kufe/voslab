#!/bin/bash
# design: docs/spec_revision/design-sources/pattern-runner-v1/pattern_runner.vsm
# (PATTERN-RUNNER-v1 era — automation-from-manual A5 follow-up)
# vsf-restore-drill.sh — weekly G-07 restoration drill, alert-on-fail only.
# S5 autonomy plan (2026-10-13, "continua con los pendientes"): restore_drill.
# py was one of the 3 dormant scripts found in A5 recon; the drill rehearses
# RSI-state restore from the daily snapshot (NEVER touches live sources —
# copies go to a drill destination only; design G-07). Fires Sunday 05:00
# LOCAL (timer convention = bare OnCalendar; 1h after gates-weekly).
# Destination: /tmp/vsf-restore-drill/<ts>/ — ephemeral by design: no rm -rf
# needed (R17: cleanup is the OS's tmpfiles, not ours), drill output is
# derived data regenerated every run.
# Passes are silent; failures (rc!=0 incl. rc=2 no-snapshot blindness) append
# ONE algedonic alert to state/rsi/alerts.jsonl.
# Pair: vsf-restore-drill.service + vsf-restore-drill.timer (user units).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ALERTS="$REPO_ROOT/state/rsi/alerts.jsonl"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DEST="/tmp/vsf-restore-drill/$(date -u +%Y-%m-%dT%H-%M-%S)"

OUT=$(python3 "$REPO_ROOT/scripts/state/monitoring/restore_drill.py" \
  --dest "$DEST" 2>&1)
RC=$?

if [ "$RC" -eq 0 ]; then
  RTO=$(printf '%s' "$OUT" | grep -iE "rto|restored" | tail -1 | cut -c1-120)
  echo "[$TS] restore drill: PASS — ${RTO:-verified}"
  exit 0
fi

DETAIL=$(printf '%s' "$OUT" | tail -5 | tr '\n' ';' | cut -c1-400)
ALERT_ID="alert-$(date +%s)000-$$"
python3 - "$ALERTS" "$ALERT_ID" "$TS" "$RC" "$DETAIL" <<'EOF'
import json, sys
path, aid, ts, rc, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
rec = {"alert_id": aid, "ts": ts, "level": "error",
       "alert_type": "restore_drill_fail",
       "source": "vsf-restore-drill.timer",
       "detail": f"restore drill failed (rc={rc}): {detail}",
       "evidence": {}, "trace_id": None, "session_id": None}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
print(f"alerted: {aid}")
EOF
echo "[$TS] restore drill: FAIL rc=$RC (alert appended)"
exit 1
