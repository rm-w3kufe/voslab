#!/usr/bin/env bash
# lifecycle-init.sh — manually register a project in current_focus.json
# Usage: bash scripts/state/lifecycle/lifecycle-init.sh <project-id> <name> <path> [mission]
# Note: the plugin auto-detects projects with git repos. This script is for
# projects without standard markers or for manual override.
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

if [ -z "${1:-}" ] || [ -z "${2:-}" ] || [ -z "${3:-}" ]; then
  echo "Usage: lifecycle-init.sh <project-id> <name> <path> [mission]"
  echo "Example: lifecycle-init.sh my-app 'My App' ~/projects/my-app 'Build a thing'"
  exit 1
fi

PROJECT_ID="$1"
NAME="$2"
PATH_DIR="$3"
MISSION="${4:-Define mission}"

python3 -c "
import json, sys, os
from datetime import date

with open('$FOCUS') as f:
    data = json.load(f)

# Check if project already exists
for p in data.get('projects', []):
    if p['id'] == '$PROJECT_ID':
        print(f'✗ Project $PROJECT_ID already exists (state: {p[\"state\"]})')
        sys.exit(1)

# Detect marker
path = os.path.expanduser('$PATH_DIR')
marker = 'manual'
for m in ['.git', 'package.json', 'Cargo.toml', 'pyproject.toml', 'go.mod']:
    if os.path.exists(os.path.join(path, m)):
        marker = m
        break

project = {
    'id': '$PROJECT_ID',
    'name': '$NAME',
    'path': path,
    'state': 'draft',
    'mission': '$MISSION',
    'marker': marker,
    'created': str(date.today()),
    'updated': str(date.today()),
    'milestones': [],
    'next_action': 'Define first milestone',
    'auto_detected': False,
}

data['projects'] = data.get('projects', [])
data['projects'].append(project)

with open('$FOCUS', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')

print(f'✓ Created project $PROJECT_ID (state: draft, marker: {marker})')
"
