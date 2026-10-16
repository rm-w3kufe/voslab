#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-3 Interactive Agent — Play a game via REST API.
Demonstrates the concept: agent observes state, decides action, executes.
"""
import os
import requests
import json
import random
import time

ROOT = "https://three.arcprize.org"
API_KEY = os.environ.get("ARC_API_KEY", "")
headers = {"X-API-Key": API_KEY, "Accept": "application/json", "Content-Type": "application/json"}

def list_games():
    r = requests.get(f"{ROOT}/api/games", headers=headers)
    return r.json() if r.status_code == 200 else []

def get_game_meta(game_id):
    r = requests.get(f"{ROOT}/api/games/{game_id}", headers=headers)
    return r.json() if r.status_code == 200 else {}

def start_game(game_id, card_id=None):
    data = {"game_id": game_id}
    if card_id:
        data["card_id"] = card_id
    r = requests.post(f"{ROOT}/api/cmd/RESET", headers=headers, json=data)
    return r.json() if r.status_code == 200 else {"error": r.text}

def take_action(action, game_id, guid, x=None, y=None):
    data = {"game_id": game_id, "guid": guid}
    if x is not None and y is not None:
        data["x"] = x
        data["y"] = y
    r = requests.post(f"{ROOT}/api/cmd/{action}", headers=headers, json=data)
    return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}

def render_grid(frames):
    """Render the latest frame as ASCII art."""
    if not frames:
        return "No frames"
    frame = frames[-1] if isinstance(frames, list) else frames
    if isinstance(frame, dict) and "grid" in frame:
        grid = frame["grid"]
    elif isinstance(frame, list):
        grid = frame
    else:
        return str(frame)[:200]
    
    COLORS = {0: ".", 1: "#", 2: "o", 3: "x", 4: "O", 5: "+", 6: "*", 7: "@", 8: "8", 9: "9"}
    lines = []
    for row in grid:
        lines.append("".join(COLORS.get(c, str(c)) for c in row))
    return "\n".join(lines)

def open_scorecard(tags=None):
    data = {"tags": tags or ["vsf_agent"]}
    r = requests.post(f"{ROOT}/api/scorecard/open", headers=headers, json=data)
    return r.json() if r.status_code == 200 else {"error": r.text}

def close_scorecard(card_id):
    r = requests.post(f"{ROOT}/api/scorecard/close", headers=headers, json={"card_id": card_id})
    return r.json() if r.status_code == 200 else {"error": r.text}

# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== ARC-AGI-3 VSF Agent ===\n")
    
    # List games
    games = list_games()
    print(f"Available games: {len(games)}")
    
    # Pick a simple game to start
    game_id = "ls20-9607627b"  # Agent reasoning (from docs)
    print(f"\nSelected game: {game_id}")
    
    # Get metadata
    meta = get_game_meta(game_id)
    print(f"Title: {meta.get('title', '?')}")
    print(f"FPS: {meta.get('default_fps', '?')}")
    print(f"Baseline actions: {meta.get('baseline_actions', [])}")
    
    # Open scorecard
    print("\nOpening scorecard...")
    sc = open_scorecard(["vsf_test", game_id])
    card_id = sc.get("card_id")
    print(f"Scorecard: {card_id}")
    
    # Start game
    print("\nStarting game...")
    state = start_game(game_id, card_id)
    print(f"State: {state.get('state', '?')}")
    print(f"Levels completed: {state.get('levels_completed', 0)}")
    
    guid = state.get("guid")
    available = state.get("available_actions", [])
    print(f"Available actions: {available}")
    
    # Render initial state
    if "frames" in state:
        print(f"\nInitial state:")
        print(render_grid(state["frames"]))
    
    # Play up to 20 actions
    print("\n--- Playing ---")
    for i in range(20):
        if state.get("state") in ["WIN", "GAME_OVER"]:
            print(f"\nGame ended: {state['state']}")
            break
        
        # Simple strategy: try actions in order
        action_choices = [f"ACTION{a}" for a in available if a != 7]  # skip undo
        if not action_choices:
            action_choices = ["ACTION1", "ACTION2", "ACTION3", "ACTION4"]
        
        action = random.choice(action_choices)
        
        # For ACTION6, pick a random coordinate
        x, y = None, None
        if action == "ACTION6":
            x, y = random.randint(0, 10), random.randint(0, 10)
        
        print(f"  Turn {i+1}: {action}" + (f" ({x},{y})" if x else ""), end=" -> ")
        
        state = take_action(action, game_id, guid, x, y)
        new_state = state.get("state", "?")
        levels = state.get("levels_completed", 0)
        available = state.get("available_actions", [])
        
        print(f"State: {new_state}, Levels: {levels}, Actions: {available}")
        
        if "frames" in state and i < 5:
            print(f"\n  Frame:")
            print(f"  {render_grid(state['frames'])}")
    
    # Close scorecard
    print("\nClosing scorecard...")
    result = close_scorecard(card_id)
    print(f"Final score: {result.get('score', '?')}")
    print(f"Details: {json.dumps(result, indent=2)[:500]}")
