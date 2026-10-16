#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Try different game_id formats."""
import requests, json, os

ROOT = "https://three.arcprize.org"
KEY = os.environ.get("ARC_API_KEY", "")
h = {"X-API-Key": KEY, "Accept": "application/json", "Content-Type": "application/json"}

# Try the exact example from docs
test_ids = [
    "ls20-016295f7601e",  # doc example
    "ls20",               # short name
    "ka59",               # short name
    "ft09",               # short name
    "vc33",               # short name
]

# Open scorecard first
sc = requests.post(f"{ROOT}/api/scorecard/open", headers=h, json={"tags": ["debug"]}).json()
card_id = sc.get("card_id")
print(f"Scorecard: {card_id}")

for gid in test_ids:
    print(f"\n--- Trying {gid} ---")
    r = requests.post(f"{ROOT}/api/cmd/RESET", headers=h, json={"game_id": gid, "card_id": card_id})
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        print(f"  GUID: {data.get('guid')}")
        print(f"  State: {data.get('state')}")
        break

# Close scorecard
requests.post(f"{ROOT}/api/scorecard/close", headers=h, json={"card_id": card_id})
