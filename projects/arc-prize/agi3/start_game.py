#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-3 Agent Loop — runs from opencode workspace (has internet).
"""
import requests, os, json, sys

ROOT = "https://three.arcprize.org"
KEY = os.environ.get("ARC_API_KEY", "")
h = {"X-API-Key": KEY, "Accept": "application/json", "Content-Type": "application/json"}

STATE_DIR = os.path.expanduser("~/vsf/child/arc-agi3/state")
os.makedirs(STATE_DIR, exist_ok=True)

def api_get(path):
    r = requests.get(f"{ROOT}{path}", headers=h)
    return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}

def api_post(path, data):
    r = requests.post(f"{ROOT}{path}", headers=h, json=data)
    return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}

def render_grid(frame):
    if isinstance(frame, dict) and "grid" in frame:
        grid = frame["grid"]
    elif isinstance(frame, list) and frame and isinstance(frame[0], list):
        grid = frame
    else:
        return str(frame)[:500]
    
    COLORS = {0: "·", 1: "#", 2: "o", 3: "x", 4: "O", 5: "+", 6: "*", 7: "@", 8: "8", 9: "9"}
    cols = len(grid[0]) if grid else 0
    header = "   " + "".join(f"{i%10}" for i in range(cols))
    lines = [header]
    for r, row in enumerate(grid):
        lines.append(f"{r:2d} " + "".join(COLORS.get(c, "?") for c in row))
    return "\n".join(lines)

# Step 1: List games
print("=== Listing games ===")
games = api_get("/api/games")
if "error" in games:
    print(f"Error: {games}")
    sys.exit(1)

print(f"Found {len(games)} games")

# Step 2: Try to start each game
for game in games[:3]:
    gid = game["game_id"]
    print(f"\n--- Trying {gid} ---")
    
    # Try RESET with card_id
    sc = api_post("/api/scorecard/open", {"tags": ["vsf_test", gid]})
    card_id = sc.get("card_id")
    print(f"  Scorecard: {card_id}")
    
    result = api_post("/api/cmd/RESET", {"game_id": gid, "card_id": card_id})
    
    if "error" in result:
        print(f"  Error: {result.get('error', '')[:200]}")
        continue
    
    guid = result.get("guid")
    state = result.get("state")
    levels = result.get("levels_completed", 0)
    available = result.get("available_actions", [])
    
    print(f"  GUID: {guid}")
    print(f"  State: {state}")
    print(f"  Levels: {levels}")
    print(f"  Available: {available}")
    
    if "frames" in result:
        print(f"\n  Grid:")
        frame = result["frames"][-1] if isinstance(result["frames"], list) else result["frames"]
        print(f"  {render_grid(frame)}")
    
    # Save state
    with open(f"{STATE_DIR}/game_{gid.replace('/', '_')}.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    
    print(f"\n  Scorecard closed: {card_id}")
    api_post("/api/scorecard/close", {"card_id": card_id})
    
    break  # Found a working game
