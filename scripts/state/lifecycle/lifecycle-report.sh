#!/usr/bin/env bash
# lifecycle-report.sh — comprehensive lifecycle report across all projects
# Usage: bash scripts/state/lifecycle/lifecycle-report.sh [--json] [--project ID]
# Provides unified view: projects, tasks, sessions, gaps, handlers
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
JSON_OUTPUT=false
PROJECT_ID=""
for arg in "$@"; do
  case "$arg" in
    --json) JSON_OUTPUT=true ;;
    --project) shift; PROJECT_ID="${1:-}"; shift 2>/dev/null || true ;;
    -*) ;;
    *) PROJECT_ID="$arg" ;;
  esac
done

if [ "$JSON_OUTPUT" = true ]; then
  # JSON output for programmatic use
  python3 -c "
import json, subprocess, os

with open('$FOCUS') as f:
    data = json.load(f)

projects = data.get('projects', [])

# Enrich with git info
for p in projects:
    path = p.get('path', '').replace('~', os.path.expanduser('~'))
    if path and os.path.isdir(path + '/.git'):
        try:
            result = subprocess.run(
                ['git', '-C', path, 'log', '--oneline', '-3'],
                capture_output=True, text=True, timeout=5
            )
            p['recent_commits'] = result.stdout.strip().split('\n') if result.stdout.strip() else []
        except:
            p['recent_commits'] = []
    else:
        p['recent_commits'] = []

print(json.dumps(data, indent=2))
"
else
  # Human-readable output
  python3 -c "
import json, subprocess, os, sys

with open('$FOCUS') as f:
    data = json.load(f)

projects = data.get('projects', [])
pid = '$PROJECT_ID'

# Filter if specific project
if pid:
    projects = [p for p in projects if p['id'] == pid]
    if not projects:
        print(f'✗ Project {pid} not found')
        sys.exit(1)

# Header
print('=' * 70)
print('LIFECYCLE REPORT')
print(f'Updated: {data.get(\"updated\", \"unknown\")}')
print('=' * 70)

# Summary
active = [p for p in projects if p['state'] not in ('archived', 'stable')]
stable = [p for p in projects if p['state'] == 'stable']
archived = [p for p in projects if p['state'] == 'archived']

print()
print(f'Projects: {len(active)} active, {len(stable)} stable, {len(archived)} archived')
print()

# Projects by state
for state in ['draft', 'design', 'implementing', 'testing', 'consolidating']:
    state_projects = [p for p in projects if p['state'] == state]
    if state_projects:
        print(f'{state.upper()} ({len(state_projects)}):')
        for p in state_projects:
            ms = p.get('milestones', [])
            done = sum(1 for m in ms if m.get('status') == 'done')
            gaps = len([g for g in p.get('gaps', []) if 'RESUELTO' not in g.get('status', '')])
            hooks = len(p.get('active_hooks', []))
            handlers = len(p.get('handlers', []))
            
            print(f'  {p[\"id\"]:20s} milestones={done}/{len(ms)} gaps={gaps} hooks={hooks} handlers={handlers}')
            
            # Recent commits
            path = p.get('path', '').replace('~', os.path.expanduser('~'))
            if path and os.path.isdir(path + '/.git'):
                try:
                    result = subprocess.run(
                        ['git', '-C', path, 'log', '--oneline', '-2'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.stdout.strip():
                        for line in result.stdout.strip().split('\n')[:2]:
                            print(f'    {line}')
                except:
                    pass
            
            # Next action
            next_act = p.get('next_action', '')
            if next_act:
                print(f'    → {next_act[:60]}')
        print()

if stable:
    print('STABLE:')
    for p in stable:
        print(f'  {p[\"id\"]:20s} version={p.get(\"milestones\", [{}])[-1].get(\"name\", \"?\") if p.get(\"milestones\") else \"?\"}')
    print()

# Gap analysis summary
print('=' * 70)
print('GAP ANALYSIS')
print('=' * 70)
gap_file = '$REPO_ROOT/child/sandbox/lifecycle-002/gap-analysis.vsm'
if os.path.exists(gap_file):
    with open(gap_file) as f:
        content = f.read()
    import re
    
    # Split by gap blocks - each starts with { and has id field
    gap_blocks = re.split(r'\{\s*\n\s*id:', content)
    gaps = []
    
    for block in gap_blocks[1:]:  # skip first empty block
        # Extract id
        id_match = re.search(r'\"(GAP-[^\"]+)\"', block)
        if not id_match:
            continue
        gid = id_match.group(1)
        
        # Extract status - look for status field
        status_match = re.search(r'status:\s*\"([^\"]+)\"', block)
        status = status_match.group(1) if status_match else 'PENDIENTE'
        
        gaps.append((gid, status))
    
    resolved = sum(1 for _, s in gaps if 'RESUELTO' in s)
    total = len(gaps)
    print(f'Resolved: {resolved}/{total}')
    for gid, status in gaps:
        if 'RESUELTO' in status:
            print(f'  ✓ {gid}')
        elif 'N/A' in status:
            print(f'  - {gid} (N/A)')
        else:
            print(f'  ○ {gid}')
print()

# Handler status
print('=' * 70)
print('HANDLER STATUS')
print('=' * 70)
log_file = '$REPO_ROOT/logs/agent_plugin.jsonl'
if os.path.exists(log_file):
    with open(log_file) as f:
        lines = f.readlines()[-20:]
    
    from collections import Counter
    results = Counter()
    for line in lines:
        try:
            e = json.loads(line)
            inst = e.get('instrument', '')
            result = e.get('result', '')
            if inst.startswith('handler:') or inst in ['learning-cycle', 'session-hygiene', 'state-reconcile']:
                results[f'{inst}:{result}'] += 1
        except:
            pass
    
    if results:
        for k, v in results.most_common(10):
            print(f'  {k}: {v}')
    else:
        print('  No recent handler executions')
else:
    print('  No plugin log found')
print()

# Task summary
print('=' * 70)
print('TASK SUMMARY')
print('=' * 70)
tasks_file = '$REPO_ROOT/child/TASKS.vsm'
if os.path.exists(tasks_file):
    with open(tasks_file) as f:
        content = f.read()
    import re
    tasks = re.findall(r'task\([^)]+\)', content)
    sessions = re.findall(r'session\([^)]+\)', content)
    print(f'  task() blocks: {len(tasks)}')
    print(f'  session() blocks: {len(sessions)}')
print()
"
fi
