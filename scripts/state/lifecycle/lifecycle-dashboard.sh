#!/usr/bin/env bash
# lifecycle-dashboard.sh — real-time lifecycle dashboard
# Usage: bash scripts/state/lifecycle/lifecycle-dashboard.sh
# Compact, always-updated view of entire system
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

python3 -c "
import json, subprocess, os, sys
from datetime import datetime

with open('$FOCUS') as f:
    data = json.load(f)

projects = data.get('projects', [])

# Clear screen (optional, works in terminal)
# print('\033[2J\033[H', end='')

print('╔' + '═' * 68 + '╗')
print('║' + ' LIFECYCLE DASHBOARD'.center(68) + '║')
print('║' + f' {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")}'.center(68) + '║')
print('╚' + '═' * 68 + '╝')
print()

# Project status matrix
print('┌─────────────────────────────────────────────────────────────────────┐')
print('│ PROJECT STATUS                                                     │')
print('├─────────────────────────────────────────────────────────────────────┤')

states = ['draft', 'design', 'implementing', 'testing', 'consolidating', 'stable', 'archived']
state_colors = {
    'draft': '░░░░░░',
    'design': '▓░░░░░',
    'implementing': '▓▓░░░░',
    'testing': '▓▓▓░░░',
    'consolidating': '▓▓▓▓░░',
    'stable': '▓▓▓▓▓▓',
    'archived': '──────'
}

for state in states:
    state_projects = [p for p in projects if p['state'] == state]
    if state_projects:
        for p in state_projects:
            ms = p.get('milestones', [])
            done = sum(1 for m in ms if m.get('status') == 'done')
            total = len(ms)
            bar = state_colors.get(state, '░░░░░░')
            progress = f'{done}/{total}' if total > 0 else '-/-'
            
            # Get recent commit
            path = p.get('path', '').replace('~', os.path.expanduser('~'))
            commit = ''
            if path and os.path.isdir(path + '/.git'):
                try:
                    result = subprocess.run(
                        ['git', '-C', path, 'log', '--oneline', '-1', '--format=%h %s'],
                        capture_output=True, text=True, timeout=3
                    )
                    if result.stdout.strip():
                        commit = result.stdout.strip()[:30]
                except:
                    pass
            
            print(f'│ [{state:13s}] {p[\"id\"]:20s} {bar} {progress:5s} {commit:30s} │')

print('└─────────────────────────────────────────────────────────────────────┘')
print()

# Gap analysis
print('┌─────────────────────────────────────────────────────────────────────┐')
print('│ GAPS                                                               │')
print('├─────────────────────────────────────────────────────────────────────┤')

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
    pending = total - resolved
    
    bar_len = 40
    filled = int(bar_len * resolved / total) if total > 0 else 0
    bar = '█' * filled + '░' * (bar_len - filled)
    
    print(f'│ Progress: {bar} {resolved}/{total} ({100*resolved//total if total else 0}%) │')
    for gid, status in gaps:
        if 'RESUELTO' in status:
            print(f'│   ✓ {gid:40s} RESUELTO          │')
        elif 'N/A' in status:
            print(f'│   - {gid:40s} N/A               │')
        else:
            print(f'│   ○ {gid:40s} PENDIENTE         │')
else:
    print('│ No gap analysis found                                             │')

print('└─────────────────────────────────────────────────────────────────────┘')
print()

# Handler status
print('┌─────────────────────────────────────────────────────────────────────┐')
print('│ HANDLERS                                                           │')
print('├─────────────────────────────────────────────────────────────────────┤')

log_file = '$REPO_ROOT/logs/agent_plugin.jsonl'
if os.path.exists(log_file):
    with open(log_file) as f:
        lines = f.readlines()[-50:]
    
    from collections import Counter, defaultdict
    handler_stats = defaultdict(lambda: {'pass': 0, 'fail': 0, 'skip': 0})
    
    for line in lines:
        try:
            e = json.loads(line)
            inst = e.get('instrument', '')
            result = e.get('result', '')
            if 'handler' in inst or inst in ['learning-cycle', 'session-hygiene', 'state-reconcile']:
                if result in handler_stats[inst]:
                    handler_stats[inst][result] += 1
        except:
            pass
    
    if handler_stats:
        for inst, stats in sorted(handler_stats.items()):
            total = stats['pass'] + stats['fail'] + stats['skip']
            status = '✓' if stats['fail'] == 0 else '✗'
            print(f'│ {status} {inst:30s} pass={stats[\"pass\"]:2d} fail={stats[\"fail\"]:2d} skip={stats[\"skip\"]:2d} │')
    else:
        print('│ No handler activity                                               │')
else:
    print('│ No plugin log found                                               │')

print('└─────────────────────────────────────────────────────────────────────┘')
print()

# Quick stats
print('┌─────────────────────────────────────────────────────────────────────┐')
print('│ QUICK STATS                                                        │')
print('├─────────────────────────────────────────────────────────────────────┤')

total_milestones = sum(len(p.get('milestones', [])) for p in projects)
done_milestones = sum(sum(1 for m in p.get('milestones', []) if m.get('status') == 'done') for p in projects)
total_hooks = sum(len(p.get('active_hooks', [])) for p in projects)
total_handlers = sum(len(p.get('handlers', [])) for p in projects)

print(f'│ Projects: {len(projects):3d}  Milestones: {done_milestones}/{total_milestones:3d}  Hooks: {total_hooks:3d}  Handlers: {total_handlers:2d} │')
print('└─────────────────────────────────────────────────────────────────────┘')
"
