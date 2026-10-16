#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Evaluate socratic agent vs random baseline on multiple games."""
import subprocess
import json
import sys
from pathlib import Path

GAMES = ["ls20", "vc33", "ka59", "sk48", "r11l"]
STEPS = 20

def run_agent(agent_file: str, game: str, steps: int) -> dict:
    """Run agent on a game and return results."""
    script = f"""
import sys
sys.path.insert(0, "/root/arc-agi-3/kaggle-starter/vendor/ARC-AGI-3-Agents")
sys.path.insert(0, "/root/arc-agi-3/kaggle-starter/agent")

import arc_agi
from arc_agi import OperationMode
import agents.agent as agt

# Load agent
import importlib.util
spec = importlib.util.spec_from_file_location("agent_mod", "{agent_file}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

agt.MAX_STEPS = {steps}
agt.MyAgentCls = mod.MyAgent

arc = arc_agi.Arcade(operation_mode=OperationMode.NORMAL)
scorecard = arc_agi.ScorecardManager()
arc.play(environment_ids=["{game}"], agent_cls=mod.MyAgent, scorecard_manager=scorecard)
"""
    result = subprocess.run(
        ["ssh", "n02", "pct", "exec", "114", "--", 
         "/root/arc-agi-3/kaggle-starter/.venv/bin/python", "-c", script],
        capture_output=True, text=True, timeout=600
    )
    
    # Parse output
    output = result.stdout + result.stderr
    stats = {"game": game, "agent": Path(agent_file).stem}
    
    for line in output.split("\n"):
        if "levels=" in line:
            stats["raw"] = line.strip()
        if "Aggregate scorecard score:" in line:
            try:
                stats["score"] = float(line.split(":")[-1].strip())
            except:
                stats["score"] = 0.0
        if "fps" in line and "avg" in line:
            try:
                fps_str = line.split("avg fps ")[-1].split(")")[0]
                stats["fps"] = float(fps_str)
            except:
                pass
    
    return stats

def main():
    print("=== ARC-AGI-3 Socratic Agent Evaluation ===\n")
    
    agents = [
        "/root/arc-agi-3/kaggle-starter/agent/my_agent_socratic.py",
        "/root/arc-agi-3/kaggle-starter/agent/my_agent_random.py",
    ]
    
    results = []
    for agent in agents:
        print(f"\n--- {Path(agent).stem} ---")
        for game in GAMES:
            print(f"  {game}...", end=" ", flush=True)
            try:
                stats = run_agent(agent, game, STEPS)
                results.append(stats)
                print(f"fps={stats.get('fps', '?')}, score={stats.get('score', '?')}")
            except Exception as e:
                print(f"ERROR: {e}")
    
    # Save results
    output_file = Path("/root/arc-agi-3/kaggle-starter/results/evaluation.json")
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n=== Results saved to {output_file} ===")
    
    # Print summary table
    print("\n=== Summary ===")
    print(f"{'Agent':<20} {'Game':<8} {'FPS':<8} {'Score':<8}")
    print("-" * 44)
    for r in results:
        print(f"{r.get('agent', '?'):<20} {r.get('game', '?'):<8} {r.get('fps', '?'):<8} {r.get('score', '?'):<8}")

if __name__ == "__main__":
    main()
