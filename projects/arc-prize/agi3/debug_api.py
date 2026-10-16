#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Debug ARC-AGI-3 API."""
import requests, json, os

ROOT = "https://three.arcprize.org"
KEY = os.environ.get("ARC_API_KEY", "")
h = {"X-API-Key": KEY, "Accept": "application/json", "Content-Type": "application/json"}

# Health check
print("=== Health ===")
r = requests.get(f"{ROOT}/api/health", headers=h)
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:200]}")

# Games with full detail
print("\n=== Games (full) ===")
r = requests.get(f"{ROOT}/api/games", headers=h)
games = r.json()
print(json.dumps(games[:3], indent=2))

# Try game metadata for first game
if games:
    gid = games[0]["game_id"]
    print(f"\n=== Metadata for {gid} ===")
    r = requests.get(f"{ROOT}/api/games/{gid}", headers=h)
    print(f"Status: {r.status_code}")
    print(json.dumps(r.json(), indent=2))
    
    # Try starting with different payload
    print(f"\n=== Start attempt ===")
    payloads = [
        {"game_id": gid},
        {"game_id": gid, "card_id": None},
        {"environment_id": gid},
    ]
    for payload in payloads:
        print(f"\n  Payload: {json.dumps(payload)}")
        r = requests.post(f"{ROOT}/api/cmd/RESET", headers=h, json=payload)
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.text[:300]}")
