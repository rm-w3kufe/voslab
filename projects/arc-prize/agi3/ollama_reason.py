#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
LLM Reasoning Module for ARC-AGI-3
Uses Qwen 2.5-coder 1.5B via Ollama API on LXC 108.
"""
import requests
import json
import re
import sys

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5-coder:1.5b"


def ask_qwen(prompt: str, timeout: int = 60) -> str:
    """Send prompt to Qwen and return response text."""
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 300,
            }
        }, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"[LLM ERROR] {e}", file=sys.stderr)
        return ""


def parse_action(response: str) -> str | None:
    """Extract an action from LLM response."""
    match = re.search(r'ACTION(\d+)(?:\s+(\d+)\s+(\d+))?', response)
    if match:
        action_num = match.group(1)
        if action_num == '6' and match.group(2) and match.group(3):
            x = int(match.group(2))
            y = int(match.group(3))
            # Clamp to valid range
            x = max(0, min(63, x))
            y = max(0, min(63, y))
            return f"ACTION6 {x} {y}"
        elif action_num in ['1', '2', '3', '4', '5']:
            return f"ACTION{action_num}"
    
    if 'RESET' in response.upper():
        return 'RESET'
    
    return None


def grid_to_text(grid: list, max_rows: int = 20, max_cols: int = 32) -> str:
    """Convert grid to compact text representation for LLM."""
    if not grid or not grid[0]:
        return "(empty grid)"
    
    h = len(grid)
    w = len(grid[0])
    
    colors = {
        0: '·', 1: '1', 2: '2', 3: '3', 4: '4',
        5: '+', 6: 'x', 7: '7', 8: '8', 9: '9',
        10: 'A', 11: 'B', 12: 'C', 13: 'D', 14: 'E', 15: 'F'
    }
    
    lines = []
    for r in range(min(h, max_rows)):
        row = ''
        for c in range(min(w, max_cols)):
            cell = grid[r][c] if r < len(grid) and c < len(grid[r]) else 0
            row += colors.get(cell, '?')
        lines.append(f"{r:2d} {row}")
    
    return '\n'.join(lines)


def compute_diff(prev_grid: list, curr_grid: list) -> str:
    """Show what changed between two grids."""
    if not prev_grid or not curr_grid:
        return "(no previous grid)"
    
    changes = []
    for r in range(min(len(prev_grid), len(curr_grid))):
        for c in range(min(len(prev_grid[r]), len(curr_grid[r]))):
            if prev_grid[r][c] != curr_grid[r][c]:
                changes.append(f"  ({c},{r}): {prev_grid[r][c]}->{curr_grid[r][c]}")
    
    if not changes:
        return "(no changes)"
    
    return f"{len(changes)} cells changed:\n" + '\n'.join(changes[:20])


def decide_move(grid: list, available_actions: list, 
                game_state: dict, history: list, prev_grid: list = None) -> str | None:
    """Use LLM to decide the next action based on grid state."""
    
    grid_text = grid_to_text(grid)
    levels = game_state.get('levels', 0)
    max_levels = game_state.get('max_levels', 6)
    
    # Compute diff if we have previous grid
    diff_text = ""
    if prev_grid:
        diff_text = f"\nChanges since last move:\n{compute_diff(prev_grid, grid)}"
    
    # Build action history
    hist_text = ""
    if history:
        recent = history[-3:]
        hist_text = "\n".join([
            f"  Turn {h.get('turn', '?')}: {h.get('action', '?')} -> "
            f"levels={h.get('levels_after', '?')}, state={h.get('state_after', '?')}"
            for h in recent
        ])
    
    prompt = f"""You are playing an ARC-AGI-3 game. Analyze the grid and decide your next action.

Grid (showing top {min(20, len(grid))} rows, {min(32, len(grid[0]) if grid else 0)} cols):
{grid_text}

Game: {levels}/{max_levels} levels done | Available: {available_actions}
{diff_text}

Recent moves:
{hist_text or '  (none)'}

RULES:
- Find objects on the grid and interact with them
- ACTION6 x y = click at position (x,y) 
- Try clicking on DIFFERENT positions each time
- If nothing works, try ACTION1-5 (special abilities)
- RESET = restart if stuck

Think: What objects do I see? What changed last time? Where should I click next?

Respond with ONE action:"""

    response = ask_qwen(prompt)
    action = parse_action(response)
    
    print(f"[LLM] Response: {response[:150]}...")
    print(f"[LLM] Action: {action}")
    
    return action


if __name__ == "__main__":
    test_grid = [[5]*64 for _ in range(64)]
    for r in range(10, 15):
        for c in range(10, 15):
            test_grid[r][c] = 9
    action = decide_move(test_grid, [1, 2, 3, 4, 5, 6], 
                        {"levels": 0, "max_levels": 6}, [])
    print(f"\nTest action: {action}")
