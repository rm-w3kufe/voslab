#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Try with session cookies."""
import requests, json, os

ROOT = "https://three.arcprize.org"
KEY = os.environ.get("ARC_API_KEY", "")

# Use session for cookie persistence
s = requests.Session()
s.headers.update({"X-API-Key": KEY, "Accept": "application/json", "Content-Type": "application/json"})

# List games
r = s.get(f"{ROOT}/api/games")
games = r.json()
print(f"Games: {len(games)}")

# Open scorecard
r = s.post(f"{ROOT}/api/scorecard/open", json={"tags": ["debug2"]})
sc = r.json()
card_id = sc.get("card_id")
print(f"Scorecard: {card_id}")
print(f"Cookies after scorecard: {dict(s.cookies)}")

# Try each game
for game in games[:5]:
    gid = game["game_id"]
    print(f"\n--- {gid} ---")
    
    r = s.post(f"{ROOT}/api/cmd/RESET", json={"game_id": gid, "card_id": card_id})
    print(f"  Status: {r.status_code}")
    print(f"  Cookies: {dict(s.cookies)}")
    
    if r.status_code == 200:
        data = r.json()
        print(f"  GUID: {data.get('guid')}")
        print(f"  State: {data.get('state')}")
        print(f"  Levels: {data.get('levels_completed')}")
        
        if "frame" in data:
            print(f"  Frame: {len(data['frame'])}x{len(data['frame'][0]) if data['frame'] else 0}")
        break
    else:
        print(f"  Body: {r.text[:200]}")

s.post(f"{ROOT}/api/scorecard/close", json={"card_id": card_id})
