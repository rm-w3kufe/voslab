#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-3 opencode Agent — Game Loop
Connects to ARC-AGI-3 API, gets state, saves for agent review.
Agent decides action, script executes.
"""
import os
import sys
import json
import time
import requests

ROOT = "https://three.arcprize.org"
API_KEY = os.environ.get("ARC_API_KEY", "")
headers = {"X-API-Key": API_KEY, "Accept": "application/json", "Content-Type": "application/json"}

STATE_DIR = "/root/arc3_state"

# ─── API Functions ─────────────────────────────────────────────────

def api_get(path):
    r = requests.get(f"{ROOT}{path}", headers=headers)
    return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}

def api_post(path, data):
    r = requests.post(f"{ROOT}{path}", headers=headers, json=data)
    return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}

def list_games():
    return api_get("/api/games")

def get_game_meta(game_id):
    return api_get(f"/api/games/{game_id}")

def start_game(game_id, card_id=None):
    data = {"game_id": game_id}
    if card_id:
        data["card_id"] = card_id
    return api_post("/api/cmd/RESET", data)

def take_action(action, game_id, guid, x=None, y=None):
    data = {"game_id": game_id, "guid": guid}
    if x is not None and y is not None:
        data["x"] = x
        data["y"] = y
    return api_post(f"/api/cmd/{action}", data)

def open_scorecard(tags=None):
    return api_post("/api/scorecard/open", {"tags": tags or ["vsf_agent"]})

def close_scorecard(card_id):
    return api_post("/api/scorecard/close", {"card_id": card_id})

# ─── State Rendering ──────────────────────────────────────────────

def render_grid(frame_data):
    """Render grid as ASCII art."""
    if isinstance(frame_data, dict):
        grid = frame_data.get("grid", frame_data.get("frames", [[]])[0])
    elif isinstance(frame_data, list):
        grid = frame_data[0] if frame_data and isinstance(frame_data[0], list) else frame_data
    else:
        return str(frame_data)[:200]
    
    if not grid or not grid[0]:
        return "Empty grid"
    
    COLORS = {
        0: "·", 1: "#", 2: "o", 3: "x", 4: "O", 
        5: "+", 6: "*", 7: "@", 8: "8", 9: "9",
        10: "A", 11: "B", 12: "C", 13: "D", 14: "E", 15: "F"
    }
    
    # Header
    cols = len(grid[0])
    header = "   " + "".join(f"{i%10}" for i in range(cols))
    
    lines = [header]
    for r, row in enumerate(grid):
        line = f"{r:2d} " + "".join(COLORS.get(c, "?") for c in row)
        lines.append(line)
    
    return "\n".join(lines)

def save_state(state, action_history, turn):
    """Save game state for agent review."""
    os.makedirs(STATE_DIR, exist_ok=True)
    
    # Save current state
    with open(f"{STATE_DIR}/current_state.json", "w") as f:
        json.dump(state, f, indent=2, default=str)
    
    # Save action history
    with open(f"{STATE_DIR}/action_history.json", "w") as f:
        json.dump(action_history, f, indent=2)
    
    # Save rendered grid
    if "frames" in state:
        with open(f"{STATE_DIR}/grid.txt", "w") as f:
            for i, frame in enumerate(state["frames"]):
                f.write(f"=== Frame {i} ===\n")
                f.write(render_grid(frame))
                f.write("\n\n")
    
    # Save summary
    with open(f"{STATE_DIR}/summary.txt", "w") as f:
        f.write(f"Turn: {turn}\n")
        f.write(f"State: {state.get('state', '?')}\n")
        f.write(f"Levels: {state.get('levels_completed', 0)}\n")
        f.write(f"Available actions: {state.get('available_actions', [])}\n")
        f.write(f"Total actions taken: {len(action_history)}\n")
        if action_history:
            last = action_history[-1]
            f.write(f"Last action: {last.get('action')} -> {last.get('result_state')}\n")

# ─── Main Game Loop ───────────────────────────────────────────────

def run_game(game_id, max_turns=30):
    """Run a game, saving state at each turn for agent review."""
    print(f"=== ARC-AGI-3 Agent: {game_id} ===\n")
    
    # Open scorecard
    print("Opening scorecard...")
    sc = open_scorecard(["vsf_agent", game_id])
    card_id = sc.get("card_id")
    print(f"Scorecard: {card_id}")
    
    # Start game
    print("Starting game...")
    state = start_game(game_id, card_id)
    guid = state.get("guid")
    print(f"GUID: {guid}")
    print(f"State: {state.get('state')}")
    print(f"Levels: {state.get('levels_completed')}")
    
    if "error" in state:
        print(f"Error: {state}")
        return
    
    action_history = []
    
    for turn in range(1, max_turns + 1):
        current_state = state.get("state", "?")
        
        if current_state in ["WIN", "GAME_OVER"]:
            print(f"\nGame ended: {current_state}")
            break
        
        # Save state for agent
        save_state(state, action_history, turn)
        
        # Show current state
        print(f"\n--- Turn {turn} ---")
        print(f"State: {current_state}")
        print(f"Levels: {state.get('levels_completed', 0)}")
        
        if "frames" in state:
            print("Grid:")
            print(render_grid(state["frames"][-1] if isinstance(state["frames"], list) else state["frames"]))
        
        available = state.get("available_actions", [])
        print(f"Available: {available}")
        
        # Write turn info for agent
        with open(f"{STATE_DIR}/turn_{turn}.txt", "w") as f:
            f.write(f"Turn {turn}\n")
            f.write(f"State: {current_state}\n")
            f.write(f"Available actions: {available}\n")
            if "frames" in state:
                f.write("Grid:\n")
                f.write(render_grid(state["frames"][-1] if isinstance(state["frames"], list) else state["frames"]))
                f.write("\n")
        
        print(f"State saved to {STATE_DIR}/")
        print(f"Review and decide action for turn {turn}")
        
        # Wait for agent decision (file-based IPC)
        decision_file = f"{STATE_DIR}/decision.txt"
        print(f"Waiting for decision at {decision_file}...")
        
        # Check for pre-made decision or use default
        if os.path.exists(decision_file):
            with open(decision_file) as f:
                decision = f.read().strip()
            os.remove(decision_file)
        else:
            # Default: try first available simple action
            decision = "ACTION1"
            for a in available:
                if a in [1, 2, 3, 4]:
                    decision = f"ACTION{a}"
                    break
        
        # Parse decision
        action = decision.split()[0] if decision else "ACTION1"
        x, y = None, None
        if action == "ACTION6" and len(decision.split()) >= 3:
            x, y = int(decision.split()[1]), int(decision.split()[2])
        
        print(f"Executing: {action}" + (f" ({x},{y})" if x else ""))
        
        # Execute action
        result = take_action(action, game_id, guid, x, y)
        
        # Record
        action_history.append({
            "turn": turn,
            "action": action,
            "x": x,
            "y": y,
            "result_state": result.get("state", "?"),
            "levels": result.get("levels_completed", 0),
            "available": result.get("available_actions", []),
        })
        
        state = result
        print(f"Result: {result.get('state')}, Levels: {result.get('levels_completed')}")
    
    # Save final state
    save_state(state, action_history, turn)
    
    # Close scorecard
    print("\nClosing scorecard...")
    result = close_scorecard(card_id)
    print(f"Final score: {result.get('score', '?')}")
    
    # Save full results
    with open(f"{STATE_DIR}/results.json", "w") as f:
        json.dump({
            "game_id": game_id,
            "card_id": card_id,
            "final_state": state.get("state"),
            "levels_completed": state.get("levels_completed"),
            "total_actions": len(action_history),
            "score": result.get("score"),
            "action_history": action_history,
        }, f, indent=2)
    
    return result

if __name__ == "__main__":
    game_id = sys.argv[1] if len(sys.argv) > 1 else "ls20-9607627b"
    max_turns = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    run_game(game_id, max_turns)
