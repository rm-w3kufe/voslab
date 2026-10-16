#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Run ARC-AGI-3 agent with live viewer.

Agent runs until game over or WIN. No step limit.
Usage:
  python3 run.py --game ls20
  python3 run.py --game ls20 --max 500  # safety limit only
"""
import argparse
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agent"))
sys.path.insert(0, os.path.join(ROOT, "vendor", "ARC-AGI-3-Agents"))

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", default="ls20", help="Game ID")
    ap.add_argument("--max", type=int, default=500, help="Safety limit (default 500)")
    a = ap.parse_args()

    # Import
    import arc_agi
    from arc_agi import OperationMode
    import agents.agent as agt
    from agent.my_agent import MyAgent

    # Set safety limit only (game ends on WIN or GAME_OVER)
    MyAgent.MAX_ACTIONS = a.max

    # Create game
    arc = arc_agi.Arcade(operation_mode=OperationMode.NORMAL)
    env = arc.make(a.game)
    if env is None:
        print(f"Could not create env for {a.game}")
        return

    # Create and run agent
    agent = MyAgent(
        card_id="local-dev",
        game_id=a.game,
        agent_name=f"MyAgent.{a.game}",
        ROOT_URL="http://localhost",
        record=False,
        arc_env=env,
        tags=["local-dev"],
    )
    agent.main()

    # Summary
    final = agent.frames[-1]
    print(f"\n→ state={final.state}, levels={final.levels_completed}, actions={agent.action_counter}")

if __name__ == "__main__":
    main()
