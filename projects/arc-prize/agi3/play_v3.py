#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""ARC-AGI-3 PoC: integrated start + play + diff + log"""

import requests, json, time, sys, os

API_KEY = os.environ.get("ARC_API_KEY", "")
ROOT = "https://three.arcprize.org"
GAME_ID = "ls20"
MAX_ATTEMPTS = 30

def make_session():
    s = requests.Session()
    s.headers.update({
        'X-API-Key': API_KEY,
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    })
    return s

def grid_colors(grid):
    colors = {}
    for row in grid:
        for c in row:
            v = int(c)
            colors[v] = colors.get(v, 0) + 1
    return colors

def grid_diff(g0, g1):
    """Return list of (r, c, old, new) for changed cells."""
    changes = []
    for r in range(min(len(g0), len(g1))):
        for c in range(min(len(g0[0]), len(g1[0]))):
            v0, v1 = int(g0[r][c]), int(g1[r][c])
            if v0 != v1:
                changes.append((r, c, v0, v1))
    return changes

def render_grid(grid, max_rows=20, max_cols=64):
    """Compact grid render."""
    COLORS = {0: '·', 1: '#', 2: 'o', 3: 'x', 4: 'O', 5: '+', 6: '*', 7: '@', 8: '8', 9: '9', 10: 'A', 11: 'B', 12: 'C', 13: 'D', 14: 'E', 15: 'F'}
    lines = []
    cols = min(len(grid[0]), max_cols)
    header = "   " + "".join(f"{i%10}" for i in range(cols))
    lines.append(header)
    for r in range(min(len(grid), max_rows)):
        row_str = "".join(COLORS.get(int(c), f"{int(c):x}") for c in grid[r][:cols])
        lines.append(f"{r:2d} {row_str}")
    return "\n".join(lines)

def main():
    s = make_session()
    
    # START GAME
    print(f"=== Starting game {GAME_ID} ===")
    r = s.post(f"{ROOT}/api/scorecard/open", json={'tags': ['vsf_poc_v3']})
    card_id = r.json()['card_id']
    print(f"Scorecard: {card_id}")
    
    r = s.post(f"{ROOT}/api/cmd/RESET", json={'game_id': GAME_ID, 'card_id': card_id})
    if r.status_code != 200:
        print(f"RESET failed: {r.status_code} {r.text[:200]}")
        return
    
    data = r.json()
    guid = data['guid']
    state = data.get('state')
    available = data.get('available_actions', [])
    levels = data.get('levels_completed', 0)
    win_levels = data.get('win_levels', '?')
    
    print(f"Game: {GAME_ID} | GUID: {guid[:16]}...")
    print(f"State: {state} | Levels: {levels}/{win_levels}")
    print(f"Available: {available}")
    
    # Parse initial frame
    frame = data.get('frame', [])
    grid = frame
    if grid and isinstance(grid[0], list) and isinstance(grid[0][0], list):
        grid = grid[0]
    
    prev_grid = grid
    print(f"\n--- Initial grid ({len(grid)}x{len(grid[0])}) ---")
    print(render_grid(grid))
    print(f"Colors: {grid_colors(grid)}")
    
    # PLAY LOOP
    log = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n=== Attempt {attempt} ===")
        
        # Try each available action
        for action in available:
            action_name = f"ACTION{action}"
            
            r = s.post(f"{ROOT}/api/cmd/{action_name}", json={
                'game_id': GAME_ID,
                'guid': guid,
                'card_id': card_id,
            })
            
            if r.status_code != 200:
                print(f"  {action_name}: HTTP {r.status_code}")
                continue
            
            result = r.json()
            new_state = result.get('state')
            new_levels = result.get('levels_completed', 0)
            new_available = result.get('available_actions', [])
            
            # Parse frame
            new_frame = result.get('frame', [])
            new_grid = new_frame
            if new_grid and isinstance(new_grid[0], list) and isinstance(new_grid[0][0], list):
                new_grid = new_grid[0]
            
            # Diff
            changes = grid_diff(prev_grid, new_grid)
            
            entry = {
                'attempt': attempt,
                'action': action_name,
                'state': new_state,
                'levels': new_levels,
                'available': new_available,
                'cells_changed': len(changes),
                'changes_sample': changes[:20],
            }
            log.append(entry)
            
            print(f"  {action_name}: state={new_state} levels={new_levels} changed={len(changes)}")
            
            if changes:
                # Show what changed
                for (r, c, v0, v1) in changes[:10]:
                    print(f"    ({r},{c}): {v0}->{v1}")
                if len(changes) > 10:
                    print(f"    ... and {len(changes)-10} more")
            
            if new_state in ['WIN', 'GAME_OVER', 'COMPLETE']:
                print(f"  *** GAME ENDED: {new_state} ***")
                # Save final
                save_state(card_id, guid, GAME_ID, new_state, new_levels, new_available, new_grid, log)
                return
            
            if new_levels > levels:
                print(f"  *** LEVEL UP: {levels} -> {new_levels} ***")
                levels = new_levels
                # Level completed, might need RESET or continue
            
            # Update for next comparison
            if changes:
                prev_grid = new_grid
                grid = new_grid
            
            available = new_available
            time.sleep(0.3)
        
        # If no changes from any action, try simple actions
        if not any(e['cells_changed'] > 0 for e in log[-len(available):]):
            print("  No changes from any action - game might be stuck")
            break
    
    save_state(card_id, guid, GAME_ID, state, levels, available, grid, log)

def save_state(card_id, guid, game_id, state, levels, available, grid, log):
    os.makedirs('state', exist_ok=True)
    with open('state/play_v3_log.json', 'w') as f:
        json.dump({
            'card_id': card_id, 'guid': guid, 'game_id': game_id,
            'state': state, 'levels': levels, 'available_actions': available,
            'log': log,
        }, f, indent=2)
    print(f"\nLog saved to state/play_v3_log.json ({len(log)} entries)")

if __name__ == '__main__':
    main()
