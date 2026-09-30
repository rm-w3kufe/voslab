#!/usr/bin/env bash
# lifecycle-promote.sh — promote a project to next state
# Usage: bash scripts/state/lifecycle/lifecycle-promote.sh <project-id> [target-state]
# Works with any project type.
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

if [ -z "${1:-}" ]; then
  echo "Usage: lifecycle-promote.sh <project-id> [target-state]"
  echo "States: draft → design → implementing → testing → consolidating → stable → archived"
  exit 1
fi

PROJECT_ID="$1"
TARGET="${2:-auto}"

python3 -c "
import json, sys
from datetime import date

TRANSITIONS = {
    'draft': ['design', 'archived'],
    'design': ['implementing', 'draft', 'archived'],
    'implementing': ['testing', 'design'],
    'testing': ['consolidating', 'implementing'],
    'consolidating': ['stable', 'testing'],
    'stable': ['archived'],
    'archived': [],
}

with open('$FOCUS') as f:
    data = json.load(f)

project = None
for p in data.get('projects', []):
    if p['id'] == '$PROJECT_ID':
        project = p
        break

if not project:
    print(f'✗ Project $PROJECT_ID not found')
    sys.exit(1)

current = project['state']
allowed = TRANSITIONS.get(current, [])

target = '$TARGET'
if target == 'auto':
    ms = project.get('milestones', [])
    all_done = len(ms) > 0 and all(m.get('status') == 'done' for m in ms)
    if all_done and 'consolidating' in allowed:
        target = 'consolidating'
    elif all_done and 'stable' in allowed:
        target = 'stable'
    else:
        print(f'✗ Cannot auto-promote: not all milestones done or no valid transition')
        sys.exit(1)

if target not in allowed:
    print(f'✗ Cannot promote from {current} to {target}. Allowed: {allowed}')
    sys.exit(1)

project['state'] = target
project['updated'] = str(date.today())

with open('$FOCUS', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')

print(f'✓ {\"$PROJECT_ID\"}: {current} → {target}')
"
