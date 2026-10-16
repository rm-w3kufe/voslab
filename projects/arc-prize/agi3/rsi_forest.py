#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-3 RSI Forest — Multi-branch exploration + strategy elaboration

Forest = cada "árbol" es una estrategia diferente jugando el mismo juego.
Se comparan resultados, se aprende de la mejor rama.
Luego se elabora una estrategia compuesta a partir de los patrones encontrados.

Ciclo:
  1. FOREST PLAY: N estrategias × M juegos
  2. AGGREGATE: Qué estrategia ganó por tipo de juego
  3. ELABORATE: Construir meta-estrategia de los patrones ganadores
  4. VALIDATE: Probar meta-estrategia en juego nuevo
  5. RECORD: Guardar en VSM si mejora
"""

import requests, json, time, os, sys, copy, random
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

# ─── Config ──────────────────────────────────────────────────────────
API_KEY = os.environ.get("ARC_API_KEY", "")
ROOT = "https://three.arcprize.org"
DATA_DIR = Path(__file__).parent / "state" / "rsi_data"
FOREST_DB = DATA_DIR / "forest_db.json"

# ─── API ─────────────────────────────────────────────────────────────

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

def grid_diff(g0, g1):
    changes = []
    for r in range(min(len(g0), len(g1))):
        for c in range(min(len(g0[0]), len(g1[0]))):
            v0, v1 = int(g0[r][c]), int(g1[r][c])
            if v0 != v1:
                changes.append((r, c, v0, v1))
    return changes

def diff_regions(changes, block=16):
    """Which grid regions were affected."""
    regions = defaultdict(int)
    for r, c, v0, v1 in changes:
        regions[(r // block, c // block)] += 1
    return dict(regions)

def grid_signature(grid):
    """Compact signature of grid state for comparison."""
    colors = defaultdict(int)
    for row in grid:
        for c in row:
            colors[int(c)] += 1
    return dict(sorted(colors.items()))

# ─── Forest Database ─────────────────────────────────────────────────

class ForestDB:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
    
    def _load(self):
        if FOREST_DB.exists():
            with open(FOREST_DB) as f:
                return json.load(f)
        return {
            "strategies": {},      # name -> {wins, losses, avg_levels, patterns}
            "games_played": [],    # [{game_id, strategy, levels, actions, timestamp}]
            "elaborated": [],      # [{strategy_name, based_on, timestamp}]
            "validations": [],     # [{strategy, game_id, levels, improved}]
        }
    
    def save(self):
        with open(FOREST_DB, 'w') as f:
            json.dump(self.data, f, indent=2, default=str)

# ─── Strategies ──────────────────────────────────────────────────────

class Strategy:
    """Base strategy — override select_action()."""
    name = "base"
    
    def __init__(self, available_actions):
        self.available = available_actions
        self.history = []  # [(action, cells_changed, regions)]
    
    def select_action(self, grid, step):
        """Pick next action. Override in subclasses."""
        return self.available[0] if self.available else None
    
    def observe(self, action, cells_changed, regions):
        self.history.append((action, cells_changed, regions))
    
    def score(self):
        """How well did this strategy do?"""
        if not self.history:
            return 0
        total_change = sum(c for _, c, _ in self.history)
        unique_actions = len(set(a for a, _, _ in self.history))
        # Reward: changes + action diversity (exploration)
        return total_change + unique_actions * 5


class CursorStrategy(Strategy):
    """Follow the cursor pattern (ACTION5 moves right-to-left)."""
    name = "cursor"
    
    def select_action(self, grid, step):
        return 5  # Always ACTION5


class ExplorerStrategy(Strategy):
    """Try each action once, then focus on most effective."""
    name = "explorer"
    
    def __init__(self, available_actions):
        super().__init__(available_actions)
        self.tried = set()
        self.effectiveness = {}
    
    def select_action(self, grid, step):
        # Phase 1: try each action once
        for a in self.available:
            if a not in self.tried:
                return a
        # Phase 2: pick most effective
        if self.effectiveness:
            return max(self.effectiveness, key=self.effectiveness.get)
        return self.available[0] if self.available else None
    
    def observe(self, action, cells_changed, regions):
        super().observe(action, cells_changed, regions)
        self.tried.add(action)
        self.effectiveness[action] = self.effectiveness.get(action, 0) + cells_changed


class RegionHunterStrategy(Strategy):
    """Focus on unexplored grid regions."""
    name = "region_hunter"
    
    def __init__(self, available_actions):
        super().__init__(available_actions)
        self.regions_hit = set()
    
    def select_action(self, grid, step):
        # Alternate between actions, tracking which regions they affect
        if step <= len(self.available):
            return self.available[step - 1]
        # After testing, prefer actions that hit new regions
        return self.available[step % len(self.available)]
    
    def observe(self, action, cells_changed, regions):
        super().observe(action, cells_changed, regions)
        self.regions_hit.update(regions.keys())


class PatternExploitStrategy(Strategy):
    """Exploit known patterns — do what worked before."""
    name = "pattern_exploit"
    
    def __init__(self, available_actions, known_patterns=None):
        super().__init__(available_actions)
        self.known = known_patterns or {}
    
    def select_action(self, grid, step):
        # Pick action with highest known effectiveness
        if self.known:
            best = max(self.available, key=lambda a: self.known.get(str(a), {}).get("avg_change", 0))
            return best
        return self.available[0] if self.available else None


class ElaboratedStrategy(Strategy):
    """Meta-strategy built from forest learning — adapts based on game state."""
    name = "elaborated"
    
    def __init__(self, available_actions, meta_rules=None):
        super().__init__(available_actions)
        self.rules = meta_rules or []
        self.phase = "explore"  # explore -> exploit -> adapt
    
    def select_action(self, grid, step):
        total_cells = sum(len(row) for row in grid) if grid else 1
        colors = grid_signature(grid) if grid else {}
        unique_colors = len(colors)
        
        # Phase transitions
        if step <= len(self.available):
            self.phase = "explore"
        elif step <= len(self.available) * 3:
            self.phase = "exploit"
        else:
            self.phase = "adapt"
        
        # Apply meta-rules
        for rule in self.rules:
            if rule.get("phase") == self.phase or rule.get("phase") == "all":
                if rule.get("condition", True):
                    action = rule.get("action")
                    if action in self.available:
                        return action
        
        # Default: cycle through actions
        return self.available[(step - 1) % len(self.available)] if self.available else None

# ─── Forest Player ───────────────────────────────────────────────────

class ForestPlayer:
    def __init__(self):
        self.session = make_session()
        self.db = ForestDB()
    
    def get_games(self):
        r = self.session.get(f"{ROOT}/api/games")
        return r.json() if r.status_code == 200 else []
    
    def start_game(self, game_id):
        r = self.session.post(f"{ROOT}/api/scorecard/open", json={'tags': ['forest']})
        card_id = r.json()['card_id']
        r = self.session.post(f"{ROOT}/api/cmd/RESET", json={'game_id': game_id, 'card_id': card_id})
        if r.status_code != 200:
            return None
        data = r.json()
        data['card_id'] = card_id
        return data
    
    def play_with_strategy(self, game_id, strategy, max_actions=30):
        """Play a game using a specific strategy. Returns result."""
        state = self.start_game(game_id)
        if not state:
            return None
        
        guid = state['guid']
        card_id = state['card_id']
        available = state.get('available_actions', [])
        
        grid = flatten_frame(state.get('frame', []))
        levels = 0
        
        for step in range(1, max_actions + 1):
            action = strategy.select_action(grid, step)
            if action is None or action not in available:
                break
            
            r = self.session.post(f"{ROOT}/api/cmd/ACTION{action}", json={
                'game_id': game_id, 'guid': guid, 'card_id': card_id
            })
            if r.status_code != 200:
                break
            
            result = r.json()
            new_grid = flatten_frame(result.get('frame', []))
            changes = grid_diff(grid, new_grid)
            regions = diff_regions(changes)
            
            strategy.observe(action, len(changes), regions)
            
            new_levels = result.get('levels_completed', 0)
            if new_levels > levels:
                levels = new_levels
            
            if result.get('state') in ['WIN', 'GAME_OVER', 'COMPLETE']:
                break
            
            available = result.get('available_actions', available)
            grid = new_grid
            time.sleep(0.15)
        
        return {
            "levels": levels,
            "actions": len(strategy.history),
            "total_change": sum(c for _, c, _ in strategy.history),
            "score": strategy.score(),
            "state": result.get('state', '?') if 'result' in dir() else '?',
        }
    
    def forest_play(self, game_id, max_actions=30):
        """Play same game with multiple strategies, compare results."""
        print(f"\n  FOREST PLAY: {game_id}")
        
        strategies = [
            CursorStrategy([5, 6, 7]),
            ExplorerStrategy([5, 6, 7]),
            RegionHunterStrategy([5, 6, 7]),
            PatternExploitStrategy([5, 6, 7], self.db.data.get("strategies", {})),
        ]
        
        # Override available actions based on actual game
        state = self.start_game(game_id)
        if not state:
            return []
        
        actual_actions = state.get('available_actions', [5, 6, 7])
        for s in strategies:
            s.available = actual_actions
        
        results = []
        for strat in strategies:
            # Need fresh game for each strategy
            result = self.play_with_strategy(game_id, strat, max_actions)
            if result:
                result['strategy'] = strat.name
                results.append(result)
                print(f"    {strat.name}: levels={result['levels']} "
                      f"change={result['total_change']} score={result['score']}")
                
                # Record in DB
                key = strat.name
                if key not in self.db.data["strategies"]:
                    self.db.data["strategies"][key] = {
                        "wins": 0, "losses": 0,
                        "total_levels": 0, "total_games": 0,
                        "patterns": {}
                    }
                sdb = self.db.data["strategies"][key]
                sdb["total_games"] += 1
                sdb["total_levels"] += result['levels']
                if result['levels'] > 0:
                    sdb["wins"] += 1
                else:
                    sdb["losses"] += 1
        
        self.db.data["games_played"].append({
            "game_id": game_id,
            "results": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.db.save()
        
        return results
    
    def elaborate_strategy(self):
        """Build meta-strategy from forest results — THE RSI CORE."""
        print(f"\n{'='*60}")
        print(f"  ELABORATE STRATEGY — Learning from forest")
        print(f"{'='*60}")
        
        # Find best strategy per game type
        best_by_game = {}
        for game in self.db.data["games_played"]:
            gid = game["game_id"]
            best = max(game["results"], key=lambda r: r.get("score", 0))
            best_by_game[gid] = best
        
        print(f"\n  Best strategies by game:")
        for gid, best in best_by_game.items():
            print(f"    {gid}: {best['strategy']} (score={best['score']})")
        
        # Aggregate patterns
        strategy_wins = defaultdict(int)
        strategy_total = defaultdict(int)
        for gid, best in best_by_game.items():
            strategy_wins[best['strategy']] += 1
            strategy_total[best['strategy']] += 1
        
        overall_best = max(strategy_wins, key=strategy_wins.get) if strategy_wins else "explorer"
        print(f"\n  Overall best: {overall_best}")
        
        # Get actual available actions from last game
        last_game = self.db.data["games_played"][-1] if self.db.data["games_played"] else None
        actual_actions = [5, 6, 7]  # default
        if last_game:
            for r in last_game.get("results", []):
                if r.get("strategy") == overall_best:
                    # Use same actions as the winning strategy
                    break
        
        # Build meta-rules from learned patterns
        meta_rules = []
        
        # Rule 1: Always explore first
        meta_rules.append({
            "phase": "explore",
            "condition": True,
            "action": actual_actions[0],
            "reason": "explore_all_actions_first"
        })
        
        # Rule 2: If cursor pattern found, exploit it
        if "cursor" in strategy_wins and strategy_wins["cursor"] > 1:
            meta_rules.append({
                "phase": "exploit",
                "condition": True,
                "action": 5,
                "reason": "cursor_pattern_repeatable"
            })
        
        # Rule 3: After exploration, use region coverage
        meta_rules.append({
            "phase": "adapt",
            "condition": True,
            "action": None,  # Will be computed dynamically
            "reason": "region_coverage_adapt"
        })
        
        elaborated = ElaboratedStrategy(actual_actions, meta_rules)
        
        # Register elaborated strategy
        self.db.data["elaborated"].append({
            "strategy_name": "elaborated_v1",
            "based_on": list(strategy_wins.keys()),
            "meta_rules": len(meta_rules),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.db.save()
        
        print(f"\n  Elaborated strategy built:")
        for i, rule in enumerate(meta_rules):
            print(f"    Rule {i+1}: phase={rule['phase']} action={rule['action']} ({rule['reason']})")
        
        return elaborated
    
    def validate(self, game_id, strategy, max_actions=30):
        """Validate elaborated strategy on a new game."""
        print(f"\n  VALIDATE: {strategy.name} on {game_id}")
        result = self.play_with_strategy(game_id, strategy, max_actions)
        if result:
            result['strategy'] = strategy.name
            print(f"    Result: levels={result['levels']} score={result['score']}")
            
            self.db.data["validations"].append({
                "strategy": strategy.name,
                "game_id": game_id,
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.db.save()
        return result
    
    def run_forest_cycle(self, num_games=3):
        """Full forest RSI cycle."""
        print(f"\n{'#'*60}")
        print(f"  RSI FOREST CYCLE — {num_games} games")
        print(f"{'#'*60}")
        
        games = self.get_games()
        if not games:
            print("No games available")
            return
        
        # Filter to keyboard_click games (we know those work)
        kgames = [g for g in games if 'keyboard' in g.get('tags', [''])[0]]
        if not kgames:
            kgames = games[:num_games]
        
        # Phase 1: Forest play
        all_results = []
        for game in kgames[:num_games]:
            results = self.forest_play(game['game_id'])
            all_results.extend(results)
        
        # Phase 2: Elaborate strategy
        elaborated = self.elaborate_strategy()
        
        # Phase 3: Validate
        if kgames:
            validate_game = kgames[num_games % len(kgames)]
            self.validate(validate_game['game_id'], elaborated)
        
        # Summary
        print(f"\n{'#'*60}")
        print(f"  FOREST SUMMARY")
        print(f"{'#'*60}")
        print(f"  Games played: {len(self.db.data['games_played'])}")
        print(f"  Strategies tested: {len(self.db.data['strategies'])}")
        print(f"  Elaborated strategies: {len(self.db.data['elaborated'])}")
        print(f"  Validations: {len(self.db.data['validations'])}")
        
        # Strategy comparison
        print(f"\n  Strategy Performance:")
        for name, s in sorted(self.db.data['strategies'].items(), 
                              key=lambda x: x[1]['total_levels'], reverse=True):
            avg = s['total_levels'] / s['total_games'] if s['total_games'] > 0 else 0
            print(f"    {name}: {s['wins']}W/{s['losses']}L avg_levels={avg:.1f}")

# ─── Main ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    player = ForestPlayer()
    num_games = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    player.run_forest_cycle(num_games=num_games)
