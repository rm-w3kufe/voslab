#!/usr/bin/env bash
# design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
# event-log — compact event logging for VSF plugin system.
#
# AGENT-CYCLE-OBSERVABILITY (directiva S5 rmw3): every event fires a
# compact log line. No agent code writes this — only scripts/plugins.
# Format: pipe-separated tuple, one record per line.
#
# Usage:
#   event-log summary <ts> <event_id> <hook> <handlers_total> <handlers_ok> <handlers_skip> <duration_ms> <summary>
#   event-log trace   <ts> <event_id> <hook> <handler> <result> <duration_ms> <detail>
#   event-log event   <ts> <event_id> <hook> <instrument> <action> <result> [<detail>]
#
# Files:
#   logs/events.jsonl         — summary (1 line per event)
#   logs/events_verbose.jsonl — trace (1 line per handler, optional)
#   logs/agent_plugin.jsonl   — backward compat (JSON, existing)
#
# Modes:
#   summary  — one line per event: who, what, how many handlers, total duration
#   trace    — one line per handler: detailed breakdown within an event
#   event    — legacy compat: one line per activation (replaces agent-plugin-log)
#
# CWD-independent: derives ROOT from the script location.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

SUMMARY_LOG="$LOG_DIR/events.jsonl"
TRACE_LOG="$LOG_DIR/events_verbose.jsonl"
LEGACY_LOG="$LOG_DIR/agent_plugin.jsonl"

MODE="${1:-}"
shift || { echo "Usage: event-log <summary|trace|event> <args...>" >&2; exit 2; }

# Generate event_id if not provided (8 char hex from timestamp + random)
gen_event_id() {
  local ts="$1"
  local rand
  rand=$(od -An -tx1 -N4 /dev/random 2>/dev/null | tr -d ' ')
  echo "${ts:0:10}-${rand:0:8}"
}

case "$MODE" in
  summary)
    # event-log summary <ts> <event_id> <hook> <total> <ok> <skip> <duration_ms> <summary>
    [ $# -ge 7 ] || { echo "Usage: event-log summary <ts> <event_id> <hook> <total> <ok> <skip> <duration_ms> [<summary>]" >&2; exit 2; }
    TS="$1"
    EVENT_ID="$2"
    HOOK="$3"
    TOTAL="$4"
    OK="$5"
    SKIP="$6"
    DURATION="$7"
    SUMMARY="${8:-}"
    echo "${TS}|${EVENT_ID}|${HOOK}|${TOTAL}|${OK}|${SKIP}|${DURATION}|${SUMMARY}" >> "$SUMMARY_LOG"
    ;;

  trace)
    # event-log trace <ts> <event_id> <hook> <handler> <result> <duration_ms> <detail>
    [ $# -ge 6 ] || { echo "Usage: event-log trace <ts> <event_id> <hook> <handler> <result> <duration_ms> [<detail>]" >&2; exit 2; }
    TS="$1"
    EVENT_ID="$2"
    HOOK="$3"
    HANDLER="$4"
    RESULT="$5"
    DURATION="$6"
    DETAIL="${7:-}"
    echo "${TS}|${EVENT_ID}|${HOOK}|${HANDLER}|${RESULT}|${DURATION}|${DETAIL}" >> "$TRACE_LOG"
    ;;

  event)
    # event-log event <ts> <event_id> <hook> <instrument> <action> <result> [<detail>]
    # Legacy compat: writes to agent_plugin.jsonl in JSON format
    [ $# -ge 5 ] || { echo "Usage: event-log event <ts> <event_id> <hook> <instrument> <action> <result> [<detail>]" >&2; exit 2; }
    TS="$1"
    EVENT_ID="$2"
    HOOK="$3"
    INSTRUMENT="$4"
    ACTION="$5"
    RESULT="$6"
    DETAIL="${7:-}"
    # Write JSON for backward compat
    printf '{"ts":"%s","event_id":"%s","hook":"%s","instrument":"%s","action":"%s","result":"%s","detail":"%s","pid":%d}\n' \
      "$TS" "$EVENT_ID" "$HOOK" "$INSTRUMENT" "$ACTION" "$RESULT" "$DETAIL" "$$" >> "$LEGACY_LOG"
    ;;

  *)
    echo "Unknown mode: $MODE (use summary|trace|event)" >&2
    exit 2
    ;;
esac
