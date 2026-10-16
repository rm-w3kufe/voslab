#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-3 Agent — Full game loop with session cookies.
"""
import requests, json, os, sys, time

ROOT = "https://three.arcprize.org"
KEY = os.environ.get("ARC_API_KEY", "")
STATE_DIR = os.path.expanduser("~/vsf/child/arc-agi3/state")
os.makedirs(STATE_DIR, exist_ok=True)

def create_session():
    s = requests.Session()
    s.headers.update({"X-API-Key": KEY, "Accept": "application/json", "Content-Type": "application/json"})
    return s

def render_grid(frame):
    if not frame or not isinstance(frame, list):
        return str(frame)[:500]
    
    # Handle nested lists
    grid = frame
    if grid and isinstance(grid[0], list) and isinstance(grid[0][0], list):
        grid = grid[0]
    
    if not grid or not isinstance(grid[0], list):
        return str(frame)[:500]
    
    COLORS = {0: "·", 1: "#", 2: "o", 3: "x", 4: "O", 5: "+", 6: "*", 7: "@", 8: "8", 9: "9"}
    cols = len(grid[0])
    header = "   " + "".join(f"{i%10}" for i in range(cols))
    lines = [header]
    for r, row in enumerate(grid):
        lines.append(f"{r:2d} " + "".join(COLORS.get(int(c), "?") for c in row))
    return "\n".join(lines)

def analyze_grid(frame):
    """Analyze grid to extract useful info for agent."""
    if not frame or not isinstance(frame, list):
        return {}
    
    # Handle nested lists (frame might be list of lists of lists)
    grid = frame
    if grid and isinstance(grid[0], list) and isinstance(grid[0][0], list):
        grid = grid[0]  # Take first frame if multiple
    
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0
    if rows == 0 or cols == 0:
        return {"shape": "0x0", "colors": {}, "objects": [], "nonzero_cells": 0}
    
    colors = {}
    for r in range(rows):
        for c in range(cols):
            v = int(grid[r][c])  # Ensure int
            colors[v] = colors.get(v, 0) + 1
    
    # Find non-zero objects
    objects = []
    visited = set()
    for r in range(rows):
        for c in range(cols):
            if (r,c) not in visited and grid[r][c] != 0:
                color = int(grid[r][c])
                obj = []
                stack = [(r,c)]
                while stack:
                    cr, cc = stack.pop()
                    if (cr,cc) in visited or cr<0 or cr>=rows or cc<0 or cc>=cols:
                        continue
                    if int(grid[cr][cc]) != color:
                        continue
                    visited.add((cr,cc))
                    obj.append((cr,cc))
                    stack.extend([(cr-1,cc),(cr+1,cc),(cr,cc-1),(cr,cc+1)])
                objects.append({"color": color, "cells": len(obj), "pos": (r,c)})
    
    return {
        "shape": f"{rows}x{cols}",
        "colors": colors,
        "objects": objects,
        "nonzero_cells": sum(colors.get(k,0) for k in colors if k != 0),
    }

def play_game(s, game_id, max_turns=50):
    """Play a game, printing state and waiting for decisions."""
    print(f"\n{'='*60}")
    print(f"GAME: {game_id}")
    print(f"{'='*60}")
    
    # Open scorecard
    r = s.post(f"{ROOT}/api/scorecard/open", json={"tags": ["vsf_agent", game_id]})
    sc = r.json()
    card_id = sc.get("card_id")
    print(f"Scorecard: {card_id}")
    
    # Start game
    r = s.post(f"{ROOT}/api/cmd/RESET", json={"game_id": game_id, "card_id": card_id})
    if r.status_code != 200:
        print(f"Failed to start: {r.text[:200]}")
        return None
    
    data = r.json()
    guid = data.get("guid")
    print(f"GUID: {guid}")
    
    history = []
    prev_grid = None
    
    for turn in range(1, max_turns + 1):
        state = data.get("state", "?")
        
        if state in ["WIN", "GAME_OVER"]:
            print(f"\n*** GAME ENDED: {state} ***")
            print(f"Levels completed: {data.get('levels_completed', 0)}")
            break
        
        frame = data.get("frame", [])
        available = data.get("available_actions", [])
        levels = data.get("levels_completed", 0)
        win_levels = data.get("win_levels", "?")
        
        # Analyze
        analysis = analyze_grid(frame)
        
        print(f"\n--- Turn {turn} | State: {state} | Levels: {levels}/{win_levels} ---")
        print(render_grid(frame))
        print(f"  Objects: {analysis.get('objects', [])}")
        print(f"  Available: {available}")
        
        # Save state for agent
        state_info = {
            "turn": turn,
            "game_id": game_id,
            "state": state,
            "frame": frame,
            "available_actions": available,
            "levels": levels,
            "analysis": analysis,
            "history": history[-5:],  # last 5 actions
        }
        
        with open(f"{STATE_DIR}/turn_{turn}.json", "w") as f:
            json.dump(state_info, f, indent=2)
        
        # LLM-powered agent with heuristic fallback
        action = decide_action(analysis, available, history, frame, prev_grid)
        
        print(f"  Decision: {action}")
        
        # Execute
        payload = {"game_id": game_id, "guid": guid}
        if action.startswith("ACTION6"):
            parts = action.split()
            payload["x"] = int(parts[1])
            payload["y"] = int(parts[2])
            action_name = "ACTION6"
        else:
            action_name = action
        
        r = s.post(f"{ROOT}/api/cmd/{action_name}", json=payload)
        
        if r.status_code != 200:
            print(f"  Error: {r.text[:200]}")
            break
        
        data = r.json()
        new_state = data.get("state", "?")
        new_levels = data.get("levels_completed", 0)
        
        history.append({
            "turn": turn,
            "action": action,
            "state_before": state,
            "state_after": new_state,
            "levels_before": levels,
            "levels_after": new_levels,
        })
        
        print(f"  Result: {state} -> {new_state} | Levels: {levels} -> {new_levels}")
        
        # Save current grid as prev for next iteration
        prev_grid = frame
    
    # Close scorecard
    r = s.post(f"{ROOT}/api/scorecard/close", json={"card_id": card_id})
    score = r.json().get("score", "?")
    print(f"\nFinal score: {score}")
    
    # Save results
    results = {
        "game_id": game_id,
        "card_id": card_id,
        "final_state": data.get("state"),
        "levels_completed": data.get("levels_completed", 0),
        "total_turns": len(history),
        "score": score,
        "history": history,
    }
    with open(f"{STATE_DIR}/results_{game_id.replace('/', '_')}.json", "w") as f:
        json.dump(results, f, indent=2)
    
    return results

def decide_action(analysis, available, history, frame=None, prev_grid=None):
    """Use LLM to decide action, with heuristic fallback."""
    try:
        from ollama_reason import decide_move, grid_to_text
        
        # Extract grid from frame
        grid = frame
        if grid and isinstance(grid[0], list) and isinstance(grid[0][0], list):
            grid = grid[0]
        
        # Extract prev_grid from prev_grid if it's also nested
        prev = prev_grid
        if prev and isinstance(prev[0], list) and isinstance(prev[0][0], list):
            prev = prev[0]
        
        if grid and len(grid) > 0:
            game_state = {
                "levels": history[-1]["levels_after"] if history else 0,
                "max_levels": 6,
            }
            
            action = decide_move(grid, available, game_state, history, prev)
            if action:
                # Validate action is in available
                if action.startswith("ACTION6"):
                    if 6 not in available:
                        action = None
                elif action.startswith("ACTION"):
                    num = int(action.replace("ACTION", ""))
                    if num not in available:
                        action = None
            
            if action:
                return action
    except Exception as e:
        print(f"[LLM fallback] {e}")
    
    # Heuristic fallback
    objects = analysis.get("objects", [])
    
    if 6 in available and objects:
        clicked = set()
        for h in history:
            if "ACTION6" in h.get("action", ""):
                parts = h["action"].split()
                if len(parts) == 3:
                    clicked.add((int(parts[1]), int(parts[2])))
        
        for obj in objects:
            color = obj["color"]
            if color == 5:
                continue
            r, c = obj["pos"]
            center_r = r + int(obj["cells"]**0.5) // 2
            center_c = c + int(obj["cells"]**0.5) // 2
            if (center_c, center_r) not in clicked:
                return f"ACTION6 {center_c} {center_r}"
        
        import random
        return f"ACTION6 {random.randint(5, 60)} {random.randint(5, 60)}"
    
    for a in [1, 2, 3, 4, 5]:
        if a in available:
            return f"ACTION{a}"
    
    return "ACTION1"

if __name__ == "__main__":
    s = create_session()
    
    # Try a few games
    games = ["sp80-589a99af", "ka59-38d34dbb", "ft09-0d8bbf25"]
    
    for gid in games:
        try:
            result = play_game(s, gid, max_turns=20)
            if result and result.get("levels_completed", 0) > 0:
                print(f"\n*** Progress on {gid}! ***")
                break
        except Exception as e:
            print(f"Error on {gid}: {e}")
