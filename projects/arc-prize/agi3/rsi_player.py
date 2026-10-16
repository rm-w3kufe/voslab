#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-3 RSI Player — Recursive Self-Improvement for Interactive Games

Cycle:
  1. OBSERVE: Play game, record action→grid_diff mappings
  2. ORIENT: Analyze patterns (which actions affect which regions)
  3. DECIDE: Build strategy from learned patterns
  4. ACT: Execute strategy on new game
  5. LEARN: Update pattern database with results
"""

import requests, json, time, os, sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

# ─── Config ──────────────────────────────────────────────────────────
API_KEY = os.environ.get("ARC_API_KEY", "")
ROOT = "https://three.arcprize.org"
DATA_DIR = Path(__file__).parent / "state" / "rsi_data"
PATTERN_DB = DATA_DIR / "patterns.json"
GAME_LOG = DATA_DIR / "game_log.jsonl"

# ─── API Layer ───────────────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.headers.update({
        'X-API-Key': API_KEY,
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    })
    return s

def flatten_frame(frame):
    grid = frame
    if grid and isinstance(grid[0], list) and isinstance(grid[0][0], list):
        grid = grid[0]
    return grid

def grid_colors(grid):
    colors = {}
    for row in grid:
        for c in row:
            v = int(c)
            colors[v] = colors.get(v, 0) + 1
    return colors

def grid_diff(g0, g1):
    """Return list of (r, c, old, new) for changed cells."""
    changes = []
    for r in range(min(len(g0), len(g1))):
        for c in range(min(len(g0[0]), len(g1[0]))):
            v0, v1 = int(g0[r][c]), int(g1[r][c])
            if v0 != v1:
                changes.append((r, c, v0, v1))
    return changes

def diff_summary(changes):
    """Summarize changes: which colors appeared/disappeared, regions affected."""
    if not changes:
        return {"total": 0}
    
    disappeared = defaultdict(int)  # old_color -> count
    appeared = defaultdict(int)     # new_color -> count
    regions = defaultdict(int)      # (r//16, c//16) -> count
    
    for r, c, v0, v1 in changes:
        disappeared[v0] += 1
        appeared[v1] += 1
        regions[(r // 16, c // 16)] += 1
    
    return {
        "total": len(changes),
        "disappeared": dict(disappeared),
        "appeared": dict(appeared),
        "regions": dict(regions),
    }

# ─── Pattern Database ────────────────────────────────────────────────

class PatternDB:
    """Learned action→effect patterns from game history."""
    
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.patterns = self._load()
    
    def _load(self):
        if PATTERN_DB.exists():
            with open(PATTERN_DB) as f:
                return json.load(f)
        return {
            "action_effects": {},    # action -> {region: {color_change: count}}
            "game_results": [],      # [{game_id, levels, actions, score}]
            "action_scores": {},     # action -> avg_score_when_used
            "total_games": 0,
            "total_actions": 0,
        }
    
    def save(self):
        with open(PATTERN_DB, 'w') as f:
            json.dump(self.patterns, f, indent=2)
    
    def record_action(self, action, diff_sum, game_state):
        """Record what an action did to the grid."""
        key = str(action)
        if key not in self.patterns["action_effects"]:
            self.patterns["action_effects"][key] = {
                "uses": 0,
                "total_changed": 0,
                "regions_affected": defaultdict(int),
                "colors_disappeared": defaultdict(int),
                "colors_appeared": defaultdict(int),
            }
        
        eff = self.patterns["action_effects"][key]
        eff["uses"] += 1
        eff["total_changed"] += diff_sum.get("total", 0)
        
        for region, count in diff_sum.get("regions", {}).items():
            eff["regions_affected"][str(region)] = eff["regions_affected"].get(str(region), 0) + count
        
        for color, count in diff_sum.get("disappeared", {}).items():
            eff["colors_disappeared"][str(color)] = eff["colors_disappeared"].get(str(color), 0) + count
        
        for color, count in diff_sum.get("appeared", {}).items():
            eff["colors_appeared"][str(color)] = eff["colors_appeared"].get(str(color), 0) + count
        
        self.patterns["total_actions"] += 1
    
    def record_game(self, game_id, levels, total_actions, score):
        """Record game outcome."""
        self.patterns["game_results"].append({
            "game_id": game_id,
            "levels": levels,
            "total_actions": total_actions,
            "score": score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.patterns["total_games"] += 1
    
    def get_strategy(self, available_actions, grid_colors):
        """Generate action selection strategy from learned patterns."""
        strategy = {}
        
        for action in available_actions:
            key = str(action)
            eff = self.patterns["action_effects"].get(key)
            
            if not eff or eff["uses"] == 0:
                # Unknown action — give it a try
                strategy[action] = {"priority": "explore", "reason": "unknown, test it"}
                continue
            
            avg_change = eff["total_changed"] / eff["uses"]
            regions_hit = len(eff["regions_affected"])
            
            # Prefer actions that cause changes (more informative)
            if avg_change == 0:
                strategy[action] = {"priority": "low", "reason": "no effect observed"}
            elif avg_change < 10:
                strategy[action] = {"priority": "medium", "reason": f"small effect ({avg_change:.0f} cells)"}
            else:
                strategy[action] = {"priority": "high", "reason": f"strong effect ({avg_change:.0f} cells, {regions_hit} regions)"}
        
        return strategy
    
    def report(self):
        """Summary of learned patterns."""
        report = {
            "total_games": self.patterns["total_games"],
            "total_actions": self.patterns["total_actions"],
            "actions_learned": len(self.patterns["action_effects"]),
            "action_summary": {},
        }
        
        for action, eff in self.patterns["action_effects"].items():
            avg = eff["total_changed"] / eff["uses"] if eff["uses"] > 0 else 0
            report["action_summary"][action] = {
                "uses": eff["uses"],
                "avg_cells_changed": round(avg, 1),
                "regions_affected": len(eff["regions_affected"]),
            }
        
        return report

# ─── RSI Player ──────────────────────────────────────────────────────

class RSIPlayer:
    """ARC-AGI-3 player with RSI learning loop."""
    
    def __init__(self):
        self.session = make_session()
        self.db = PatternDB()
        self.game_log = []
    
    def get_games(self):
        """Fetch available games from API."""
        r = self.session.get(f"{ROOT}/api/games")
        if r.status_code == 200:
            return r.json()
        return []
    
    def start_game(self, game_id):
        """Start a new game."""
        r = self.session.post(f"{ROOT}/api/scorecard/open", json={'tags': ['rsi_player']})
        card_id = r.json()['card_id']
        
        r = self.session.post(f"{ROOT}/api/cmd/RESET", json={'game_id': game_id, 'card_id': card_id})
        if r.status_code != 200:
            return None
        
        data = r.json()
        data['card_id'] = card_id
        return data
    
    def execute_action(self, game_id, guid, card_id, action):
        """Execute an action and return result."""
        r = self.session.post(f"{ROOT}/api/cmd/ACTION{action}", json={
            'game_id': game_id, 'guid': guid, 'card_id': card_id
        })
        if r.status_code != 200:
            return None
        return r.json()
    
    def play_game(self, game_id, max_actions=50):
        """Play a full game with RSI learning."""
        print(f"\n{'='*60}")
        print(f"  RSI Player — Game: {game_id}")
        print(f"{'='*60}")
        
        # Start game
        state = self.start_game(game_id)
        if not state:
            print("Failed to start game")
            return None
        
        guid = state['guid']
        card_id = state['card_id']
        available = state.get('available_actions', [])
        levels = 0
        
        # Get initial grid
        grid = flatten_frame(state.get('frame', []))
        init_colors = grid_colors(grid)
        
        print(f"  GUID: {guid[:16]}...")
        print(f"  Actions: {available}")
        print(f"  Colors: {init_colors}")
        
        # Play loop
        prev_grid = grid
        actions_taken = []
        total_changes = 0
        
        for step in range(1, max_actions + 1):
            # Get strategy from learned patterns
            strategy = self.db.get_strategy(available, init_colors)
            
            # Sort by priority
            priority_order = {"high": 0, "medium": 1, "explore": 2, "low": 3}
            sorted_actions = sorted(available, key=lambda a: priority_order.get(strategy.get(a, {}).get("priority", "low"), 4))
            
            # Pick best action
            action = sorted_actions[0] if sorted_actions else available[0]
            reason = strategy.get(action, {}).get("reason", "default")
            
            # Execute
            result = self.execute_action(game_id, guid, card_id, action)
            if not result:
                print(f"  Step {step}: ACTION{action} FAILED")
                break
            
            # Analyze changes
            new_grid = flatten_frame(result.get('frame', []))
            changes = grid_diff(prev_grid, new_grid)
            dsum = diff_summary(changes)
            
            # Record in pattern DB
            self.db.record_action(action, dsum, {
                "state": result.get('state'),
                "levels": result.get('levels_completed', 0),
            })
            
            total_changes += dsum['total']
            actions_taken.append({
                "step": step,
                "action": action,
                "reason": reason,
                "cells_changed": dsum['total'],
                "state": result.get('state'),
            })
            
            # Print progress
            if dsum['total'] > 0:
                print(f"  Step {step}: ACTION{action} -> {dsum['total']} cells changed ({reason})")
                if dsum['total'] <= 20:
                    for r, c, v0, v1 in changes[:5]:
                        print(f"    ({r},{c}): {v0}->{v1}")
            else:
                print(f"  Step {step}: ACTION{action} -> no change ({reason})")
            
            # Check game state
            new_state = result.get('state')
            new_levels = result.get('levels_completed', 0)
            
            if new_levels > levels:
                print(f"  *** LEVEL UP: {levels} -> {new_levels} ***")
                levels = new_levels
            
            if new_state in ['WIN', 'GAME_OVER', 'COMPLETE']:
                print(f"  *** GAME ENDED: {new_state} ***")
                break
            
            available = result.get('available_actions', available)
            prev_grid = new_grid
            time.sleep(0.2)
        
        # Record game result
        score = levels / 7.0  # Normalize to 0-1
        self.db.record_game(game_id, levels, len(actions_taken), score)
        self.db.save()
        
        # Print summary
        print(f"\n  --- Game Summary ---")
        print(f"  Levels: {levels}/7")
        print(f"  Actions: {len(actions_taken)}")
        print(f"  Total cells changed: {total_changes}")
        print(f"  Final state: {result.get('state', '?')}")
        
        return {
            "game_id": game_id,
            "levels": levels,
            "actions": actions_taken,
            "total_changes": total_changes,
        }
    
    def run_rsi_cycle(self, num_games=3):
        """Run RSI learning cycle across multiple games."""
        print(f"\n{'='*60}")
        print(f"  RSI LEARNING CYCLE — {num_games} games")
        print(f"{'='*60}")
        
        # Get available games
        games = self.get_games()
        if not games:
            print("No games available")
            return
        
        print(f"  Available games: {len(games)}")
        for g in games[:5]:
            print(f"    {g['game_id']}: {g['title']} ({g.get('tags', ['?'])[0]})")
        
        # Play games
        results = []
        for i in range(min(num_games, len(games))):
            game = games[i % len(games)]
            result = self.play_game(game['game_id'])
            if result:
                results.append(result)
        
        # Generate RSI report
        report = self.db.report()
        print(f"\n{'='*60}")
        print(f"  RSI REPORT")
        print(f"{'='*60}")
        print(f"  Total games played: {report['total_games']}")
        print(f"  Total actions taken: {report['total_actions']}")
        print(f"  Actions learned: {report['actions_learned']}")
        
        if report['action_summary']:
            print(f"\n  Action Effectiveness:")
            for action, stats in sorted(report['action_summary'].items(), 
                                         key=lambda x: x[1]['avg_cells_changed'], reverse=True):
                print(f"    ACTION{action}: {stats['uses']} uses, "
                      f"avg {stats['avg_cells_changed']} cells changed, "
                      f"{stats['regions_affected']} regions")
        
        # Save full report
        report_path = DATA_DIR / f"rsi_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w') as f:
            json.dump({"results": results, "report": report}, f, indent=2)
        print(f"\n  Full report: {report_path}")
        
        return results

# ─── Main ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    player = RSIPlayer()
    
    num_games = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    player.run_rsi_cycle(num_games=num_games)
