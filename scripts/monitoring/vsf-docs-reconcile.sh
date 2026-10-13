#!/usr/bin/env bash
# vsf-docs-reconcile.sh — daily docs inventory drift check, alert-on-fail only.
# design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm
# Runs docs_reconcile.py --check (model≡reality for the doc tree). Passes are
# silent; drift appends ONE algedonic alert to state/rsi/alerts.jsonl,
# surfaced at next session.created.
# Pair: vsf-docs-reconcile.service + vsf-docs-reconcile.timer (user units).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ALERTS="$REPO_ROOT/state/rsi/alerts.jsonl"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

OUT=$(python3 "$REPO_ROOT/scripts/shared/docs_reconcile.py" --check 2>&1)
RC=$?

if [ "$RC" -eq 0 ]; then
  echo "[$TS] docs reconcile: PASS"
  exit 0
fi

DETAIL=$(printf '%s' "$OUT" | tail -5 | tr '\n' ';' | cut -c1-300)
ALERT_ID="alert-$(date +%s)000-$$"
python3 - "$ALERTS" "$ALERT_ID" "$TS" "$DETAIL" "$RC" <<'EOF'
import json, sys
path, aid, ts, detail, rc = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
rec = {"alert_id": aid, "ts": ts, "level": "error",
       "alert_type": "docs_reconcile_fail",
       "source": "vsf-docs-reconcile.timer",
       "detail": f"docs inventory drift rc={rc}: {detail}",
       "evidence": {"rc": int(rc)}, "trace_id": None, "session_id": None}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
print(f"alerted: {aid}")
EOF
echo "[$TS] docs reconcile: FAIL rc=$RC (alert appended)"
exit "$RC"
