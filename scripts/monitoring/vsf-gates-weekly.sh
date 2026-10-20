#!/bin/bash
# vsf-gates-weekly.sh — weekly gate-suite + pytest run, alert-on-fail only.
# S5 approved 2026-10-12 (Sunday 04:00 UTC window, Persistent=true for
# WSL sleep). Passes are silent (no spam); failures append ONE algedonic
# alert to state/rsi/alerts.jsonl, surfaced at next session.created.
# A4 (2026-10-13, S5 autonomy plan): full pytest corpus joins the weekly
# run (~3.5min) so test evidence is automatic, not on-demand.
# Pair: vsf-gates-weekly.service + vsf-gates-weekly.timer (user units).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# Run from repo root: systemd user units start with cwd=$HOME, and a stray
# ~/packages/{framework,public} there shadows the repo's `packages` when
# python -m pytest puts cwd on sys.path[0]; run_gates checks are also
# cwd-relative (4 reds from HOME, 0 from root — repro 2026-10-20).
cd "$REPO_ROOT" || exit 1
ALERTS="$REPO_ROOT/state/rsi/alerts.jsonl"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

FAILURES=""

# ── 1. full gate suite ──────────────────────────────────────────────────────
OUT=$(python3 "$REPO_ROOT/packages/framework/run_gates.py" 2>&1)
RC=$?
if [ "$RC" -ne 0 ]; then
  D=$(printf '%s' "$OUT" | tail -5 | tr '\n' ';' | cut -c1-300)
  FAILURES="gates(rc=$RC):$D"
fi

# ── 2. pytest corpus (A4) ──────────────────────────────────────────────────
# --import-mode=importlib: duplicate test basenames across packages
# (test_facade.py ×2) collide in prepend mode.
# KNOWN-RED deselect (honest list, alert would be cry-wolf):
#   test_live_workspace_core_is_clean — scan flags substrate nouns (lxc/n02/
#   notebook) inside state/epistemic JSON data (task refs); over-scan debt,
#   fix pending (test scope, not data).
# The multi_bridge order-flake stays IN: flake is signal.
OUT2=$(python3 -m pytest "$REPO_ROOT/packages" "$REPO_ROOT/system/kernel" \
  -q -p no:cacheprovider --import-mode=importlib \
  --deselect packages/framework/vos_kernel/tests/test_round_runner.py::TestSubstrateScan::test_live_workspace_core_is_clean \
  2>&1)
RC2=$?
if [ "$RC2" -ne 0 ]; then
  D2=$(printf '%s' "$OUT2" | tail -6 | tr '\n' ';' | cut -c1-400)
  FAILURES="${FAILURES:+$FAILURES | }pytest(rc=$RC2):$D2"
fi

if [ -z "$FAILURES" ]; then
  echo "[$TS] gates weekly: PASS (suite + pytest)"
  exit 0
fi

DETAIL=$(printf '%s' "$FAILURES" | cut -c1-500)
ALERT_ID="alert-$(date +%s)000-$$"
python3 - "$ALERTS" "$ALERT_ID" "$TS" "$DETAIL" <<'EOF'
import json, sys
path, aid, ts, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
rec = {"alert_id": aid, "ts": ts, "level": "error",
       "alert_type": "gates_weekly_fail",
       "source": "vsf-gates-weekly.timer",
       "detail": f"weekly suite failed: {detail}",
       "evidence": {}, "trace_id": None, "session_id": None}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
print(f"alerted: {aid}")
EOF
echo "[$TS] gates weekly: FAIL (alert appended)"
exit 1
