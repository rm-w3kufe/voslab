#!/usr/bin/env bash
# lifecycle-status.sh — report status of all focus entries in current_focus.json
# Usage: bash scripts/state/lifecycle/lifecycle-status.sh [focus-ref] [--extended]
#
# CC-2 (CYCLE-CLOSE-001): schema adapted to the current focus format —
# current_focus.json is an ARRAY of {ref,status,note,started_at,updated_at},
# not the retired {projects:[{id,state,milestones,...}]} model (the old
# parser crashed with AttributeError: 'list' object has no attribute 'get').
set -u
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Find focus file
FOCUS=""
if [ -f "$REPO_ROOT/child/current_focus.json" ]; then
  FOCUS="$REPO_ROOT/child/current_focus.json"
elif [ -f "$REPO_ROOT/current_focus.json" ]; then
  FOCUS="$REPO_ROOT/current_focus.json"
else
  echo "✗ No current_focus.json found"; exit 1
fi

# Parse args
EXTENDED=false
FOCUS_REF=""
for arg in "$@"; do
  case "$arg" in
    --extended|-x) EXTENDED=true ;;
    *) FOCUS_REF="$arg" ;;
  esac
done

if [ -n "$FOCUS_REF" ]; then
  # Show single focus entry detail
  python3 -c "
import json, sys

with open('$FOCUS') as f:
    data = json.load(f)

entries = data if isinstance(data, list) else data.get('entries', data.get('projects', []))
ref = '$FOCUS_REF'
for e in entries:
    if e.get('ref') == ref:
        print(f\"Focus: {e.get('ref')}\")
        print(f\"  Status: {e.get('status', '?')}\")
        print(f\"  Note: {e.get('note', 'N/A')}\")
        print(f\"  Started: {e.get('started_at', 'N/A')}\")
        print(f\"  Updated: {e.get('updated_at', 'N/A')}\")
        sys.exit(0)

print(f'✗ Focus ref {ref} not found'); sys.exit(1)
"
else
  # Show all focus entries summary
  python3 -c "
import json, os

with open('$FOCUS') as f:
    data = json.load(f)

entries = data if isinstance(data, list) else data.get('entries', data.get('projects', []))
active = [e for e in entries if e.get('status') == 'active']
paused = [e for e in entries if e.get('status') == 'paused']
done = [e for e in entries if e.get('status') == 'done']

print(f'Focus: {len(active)} active, {len(paused)} paused, {len(done)} done')
print()

if active:
    print('Active:')
    for e in active:
        updated = e.get('updated_at', e.get('started_at', '?'))
        note = (e.get('note') or '')[:60]
        print(f\"  [active]        {e.get('ref', '?'):34s} updated={updated} {note}\")

if paused:
    print()
    print('Paused:')
    for e in paused:
        print(f\"  [paused]        {e.get('ref', '?')}\")

if done:
    print()
    print('Done (recent first):')
    for e in sorted(done, key=lambda x: x.get('updated_at') or '', reverse=True)[:5]:
        print(f\"  [done]          {e.get('ref', '?'):34s} {e.get('updated_at', '?')}\")

# Extended info
if '$EXTENDED' == 'true':
    print()
    print('=' * 60)
    print('EXTENDED STATUS')
    print('=' * 60)

    # Recent handler executions (log field is 'source'; older lines used
    # 'instrument' — accept both)
    log_file = '$REPO_ROOT/logs/agent_plugin.jsonl'
    if os.path.exists(log_file):
        print()
        print('Recent handler executions:')
        with open(log_file) as f:
            lines = f.readlines()[-10:]
        for line in lines:
            try:
                e = json.loads(line)
                ts = e.get('ts', '?')[:19]
                inst = e.get('source', e.get('instrument', '?'))
                result = e.get('result', '?')
                if inst in ['event-router', 'learning-cycle', 'session-hygiene',
                            'state-reconcile', 'governance', 'attestation',
                            'tasks-maintenance', 'core-scripts', 'cyberfilter',
                            'services', 'shared', 'lifecycle-reporting',
                            'scripts-automation', 'hook-analytics']:
                    status = '✓' if result in ('ok', 'pass') else ('✗' if result in ('fail', 'error') else '?')
                    print(f\"  {status} {ts} {inst}: {result}\")
            except Exception:
                pass

    # TASKS.vsm summary (at repo root)
    tasks_file = '$REPO_ROOT/TASKS.vsm'
    if os.path.exists(tasks_file):
        print()
        print('Open tasks:')
        with open(tasks_file) as f:
            content = f.read()
        import re
        tasks = re.findall(r'task\([^)]+\)', content)
        sessions = re.findall(r'session\([^)]+\)', content)
        print(f\"  task() blocks: {len(tasks)}\")
        print(f\"  session() blocks: {len(sessions)}\")
"
fi
