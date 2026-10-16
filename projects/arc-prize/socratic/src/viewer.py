#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""ARC-AGI-3 Game Viewer — Terminal visualization for game runs.

Features:
  - Live game grid with colors
  - Action history bar
  - Socratic memory scores
  - Algedonic feedback signals
  - Watch mode (poll JSON state file)

Uso:
  python3 viewer.py --watch                  # live: poll state/arc3_state.json
  python3 viewer.py --watch my_state.json    # live: custom file
  python3 viewer.py --snap state.json        # render once
  python3 viewer.py --demo                   # demo with fake data

Agent writes state:
  from viewer import push_state
  push_state(game_id, step, grid, action, state, ...)
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATE = os.path.join(HERE, "state", "arc3_state.json")

# ─── Colors ────────────────────────────────────────────────────────
ANSI_BG = {0: 238, 1: 21, 2: 196, 3: 46, 4: 226, 5: 244,
           6: 201, 7: 208, 8: 39, 9: 124}
for i in range(10, 256):
    ANSI_BG[i] = i % 256

RESET = "\x1b[0m"
CLEAR = "\x1b[2J\x1b[H"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
WHITE = "\x1b[37m"
MAGENTA = "\x1b[35m"

# ─── Grid rendering ───────────────────────────────────────────────

def _cell(v, numbers=False):
    # Handle nested arrays (arcengine sometimes returns list cells)
    if isinstance(v, list):
        v = v[0] if v else 0
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = 0
    bg = ANSI_BG.get(v, v % 256)
    if numbers:
        fg = 16 if v in (3, 4, 5, 8) else 231
        return "\x1b[48;5;%dm\x1b[38;5;%dm%2d%s" % (bg, fg, v, RESET)
    return "\x1b[48;5;%dm  %s" % (bg, RESET)

def render_grid(g, numbers=False):
    if not g:
        return "(empty)"
    h = len(g)
    w = len(g[0]) if g else 0
    
    # Auto-compact for large grids
    if w > 40 or h > 30:
        return render_grid_compact(g)
    
    return "\n".join(
        "".join(_cell(v, numbers) for v in row)
        for row in g)

def render_grid_compact(g):
    """Compact mode: 2 chars per cell, fg=bg for solid blocks with visible char."""
    if not g:
        return "(empty)"
    
    chars = {0: "·", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5",
             6: "6", 7: "7", 8: "8", 9: "9", 10: "A", 11: "B", 12: "C"}
    
    lines = []
    for row in g:
        line = ""
        for v in row:
            try:
                v = int(v)
            except:
                v = 0
            bg = ANSI_BG.get(v, v % 256)
            ch = chars.get(v, hex(v)[-1])
            # fg slightly lighter than bg for visible character
            fg = min(bg + 15, 255) if bg < 240 else max(bg - 15, 0)
            line += "\x1b[48;5;%dm\x1b[38;5;%dm%s%s" % (bg, fg, ch * 2, RESET)
        lines.append(line)
    
    # Add row numbers
    result = []
    for i, line in enumerate(lines):
        result.append("\x1b[2m%2d\x1b[0m %s" % (i, line))
    return "\n".join(result)

def _dims(g):
    if not g:
        return "0x0"
    return "%dx%d" % (len(g), len(g[0]) if g else 0)

# ─── Bar chart ────────────────────────────────────────────────────

def bar(values, labels, width=30, color_pos=CYAN, color_neg=RED):
    """Horizontal bar chart as string."""
    if not values:
        return ""
    max_val = max(abs(v) for v in values) or 1
    lines = []
    for val, label in zip(values, labels):
        bar_len = int(abs(val) / max_val * width)
        if val >= 0:
            bar_str = color_pos + "█" * bar_len + RESET
        else:
            bar_str = color_neg + "█" * bar_len + RESET
        lines.append("  %-8s %s %s" % (label, bar_str, "%.1f" % val))
    return "\n".join(lines)

# ─── State rendering ──────────────────────────────────────────────

def render_state(state):
    """Render full game state to terminal string."""
    parts = []
    
    # Header
    game_id = state.get("game_id", "?")
    step = state.get("step", 0)
    game_state = state.get("state", "?")
    levels = state.get("levels", 0)
    
    state_color = GREEN if game_state == "WIN" else (RED if game_state == "GAME_OVER" else WHITE)
    
    parts.append("=" * 60)
    parts.append(BOLD + "ARC-AGI-3: %s" % game_id + RESET)
    parts.append("Step: %d  │  State: %s%s%s  │  Levels: %d" % (
        step, state_color, game_state, RESET, levels))
    parts.append("=" * 60)
    
    # Grid
    grid = state.get("grid")
    if grid:
        parts.append("")
        parts.append(BOLD + "[game grid]" + RESET)
        parts.append(render_grid(grid))
        parts.append("  shape: %s" % _dims(grid))
    
    # Current action
    action = state.get("action", "")
    llm_raw = state.get("llm_raw", "")
    method = state.get("method", "")
    
    if action:
        parts.append("")
        parts.append(BOLD + "[action]" + RESET)
        parts.append("  %s%s%s" % (YELLOW, action, RESET))
        if method:
            parts.append("  method: %s" % method)
        if llm_raw:
            parts.append("  llm: %s" % llm_raw[:80])
    
    # Action history
    history = state.get("action_history", [])
    if history:
        parts.append("")
        parts.append(BOLD + "[action history] (%d total)" % len(history) + RESET)
        from collections import Counter
        counts = Counter(history)
        labels = list(counts.keys())
        values = list(counts.values())
        max_val = max(values) or 1
        for label, val in zip(labels, values):
            bar_len = int(val / max_val * 20)
            is_last = (label == action)
            color = YELLOW if is_last else CYAN
            parts.append("  %s%-8s%s %s%s%s %d" % (
                YELLOW if is_last else "", label, RESET,
                color, "█" * bar_len, RESET, val))
    
    # Socratic scores
    scores = state.get("socratic_scores", {})
    if scores:
        parts.append("")
        parts.append(BOLD + "[socratic scores]" + RESET)
        labels = list(scores.keys())
        values = list(scores.values())
        parts.append(bar(values, labels, width=20))
    
    # Feedback
    reward = state.get("reward", 0)
    signals = state.get("recent_signals", [])
    if signals:
        parts.append("")
        parts.append(BOLD + "[feedback] reward: %.2f" % reward + RESET)
        for sig in signals[-5:]:
            sig_type = sig.get("type", "?")
            intensity = sig.get("intensity", 0)
            msg = sig.get("message", "")
            if sig_type == "pleasure":
                emoji = GREEN + "✓" + RESET
            elif sig_type == "pain":
                emoji = RED + "✗" + RESET
            else:
                emoji = DIM + "→" + RESET
            parts.append("  %s %.1f %s" % (emoji, intensity, msg))
    
    # Canon
    accuracy = state.get("canon_accuracy", -1)
    drift_rate = state.get("canon_drift_rate", -1)
    if accuracy >= 0:
        parts.append("")
        parts.append(BOLD + "[canon]" + RESET)
        parts.append("  accuracy: %.0f%%  │  drift: %.0f%%" % (accuracy * 100, drift_rate * 100))
    
    # Patterns
    patterns = state.get("patterns_detected", [])
    if patterns:
        parts.append("")
        parts.append(BOLD + "[patterns detected]" + RESET)
        parts.append("  " + ", ".join(patterns[:5]))
    
    # Timestamp
    ts = state.get("ts", "")
    if ts:
        parts.append("")
        parts.append(DIM + "ts: %s" % ts + RESET)
    
    return "\n".join(parts)

# ─── API ──────────────────────────────────────────────────────────

def push_state(game_id, step, grid, action, state_str,
               action_history=None, socratic_scores=None,
               reward=0, recent_signals=None, canon_accuracy=-1,
               canon_drift_rate=-1, patterns_detected=None,
               llm_raw="", method="", levels=0,
               zones=None, life=None, player_pos=None, invariants=None,
               path=DEFAULT_STATE):
    """Write state for viewer to poll."""
    data = {
        "game_id": game_id,
        "step": step,
        "grid": grid,
        "action": action,
        "state": state_str,
        "action_history": action_history or [],
        "socratic_scores": socratic_scores or {},
        "reward": reward,
        "recent_signals": recent_signals or [],
        "canon_accuracy": canon_accuracy,
        "canon_drift_rate": canon_drift_rate,
        "patterns_detected": patterns_detected or [],
        "llm_raw": llm_raw,
        "method": method,
        "levels": levels,
        "zones": zones or {},
        "life": life,
        "player_pos": player_pos,
        "invariants": invariants or [],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    return path

# ─── Watch mode ───────────────────────────────────────────────────

def watch(path=DEFAULT_STATE, interval=0.3):
    last = None
    print("👁  watching %s  (Ctrl-C to quit)" % path)
    try:
        while True:
            try:
                mt = os.path.getmtime(path)
            except OSError:
                if last != "missing":
                    sys.stdout.write(CLEAR + "waiting for state in %s ...\n" % path)
                    sys.stdout.flush()
                    last = "missing"
                time.sleep(interval)
                continue
            if mt != last:
                last = mt
                try:
                    with open(path) as f:
                        state = json.load(f)
                    sys.stdout.write(CLEAR + render_state(state) + "\n")
                except (OSError, ValueError) as e:
                    sys.stdout.write(CLEAR + "state unreadable: %s\n" % e)
                sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nviewer closed.")

# ─── Demo ─────────────────────────────────────────────────────────

def demo():
    """Show demo state."""
    state = {
        "game_id": "ls20",
        "step": 5,
        "grid": [
            [0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 2, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 3, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ],
        "action": "ACTION3",
        "state": "PLAYING",
        "action_history": ["ACTION1", "ACTION4", "ACTION2", "ACTION3", "ACTION3"],
        "socratic_scores": {
            "ACTION1": 0.2,
            "ACTION2": -0.1,
            "ACTION3": 0.5,
            "ACTION4": 0.0,
            "ACTION5": -0.3,
        },
        "reward": 0.2,
        "recent_signals": [
            {"type": "neutral", "intensity": 0, "message": "State: PLAYING → PLAYING"},
            {"type": "pleasure", "intensity": 0.5, "message": "Level progress"},
            {"type": "neutral", "intensity": 0, "message": "State: PLAYING → PLAYING"},
            {"type": "pain", "intensity": 0.2, "message": "No progress (2x stuck)"},
            {"type": "pleasure", "intensity": 0.5, "message": "Level progress"},
        ],
        "canon_accuracy": 0.6,
        "canon_drift_rate": 0.4,
        "patterns_detected": ["try_all_actions", "fill_solid", "mirror_horizontal"],
        "llm_raw": "ACTION3",
        "method": "llm",
        "levels": 1,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(render_state(state))

# ─── CLI ──────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="arc3-viewer",
        description="ARC-AGI-3 Game Viewer — terminal visualization")
    ap.add_argument("--snap", metavar="FILE",
                    help="render state file once and exit")
    ap.add_argument("--watch", nargs="?", const=DEFAULT_STATE, metavar="FILE",
                    help="watch state file, re-render on change")
    ap.add_argument("--demo", action="store_true",
                    help="show demo state")
    a = ap.parse_args(argv)

    if a.demo:
        demo()
    elif a.watch:
        watch(a.watch)
    elif a.snap:
        with open(a.snap) as f:
            print(render_state(json.load(f)))
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
