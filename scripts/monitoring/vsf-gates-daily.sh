#!/bin/bash
# vsf-gates-daily.sh — daily doc-consistency trio, alert-on-fail only.
# design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm
# Runs the three fast local checks that drifted twice this session
# (plan-tree, dir-schema, classification) — weekly full suite stays Sunday.
# Passes are silent (no spam); failures append ONE algedonic alert to
# state/rsi/alerts.jsonl, surfaced at next session.created.
# Pair: vsf-gates-daily.service + vsf-gates-daily.timer (user units).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHECKS="$REPO_ROOT/packages/public/vsf-checks/checks"
ALERTS="$REPO_ROOT/state/rsi/alerts.jsonl"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

FAIL=""
for check in plan-tree-valid dir-schema-valid classification-valid; do
  OUT_ONE=$("$CHECKS/$check" pass 2>&1)
  RC_ONE=$?
  if [ "$RC_ONE" -ne 0 ]; then
    FAIL="$FAIL $check($RC_ONE):$(printf '%s' "$OUT_ONE" | tail -2 | tr '\n' ';' | cut -c1-150)"
  fi
done

if [ -z "$FAIL" ]; then
  echo "[$TS] gates daily: PASS (plan-tree, dir-schema, classification)"
  exit 0
fi

DETAIL=$(printf '%s' "$FAIL" | cut -c1-300)
ALERT_ID="alert-$(date +%s)000-$$"
python3 - "$ALERTS" "$ALERT_ID" "$TS" "$DETAIL" <<'EOF'
import json, sys
path, aid, ts, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
rec = {"alert_id": aid, "ts": ts, "level": "error",
       "alert_type": "gates_daily_fail",
       "source": "vsf-gates-daily.timer",
       "detail": f"daily doc-consistency failed:{detail}",
       "evidence": {}, "trace_id": None, "session_id": None}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
print(f"alerted: {aid}")
EOF
echo "[$TS] gates daily: FAIL (alert appended)"
exit 1
