# design: projects/arc-prize/arc_prize_design.vsm
"""
arc3_trajectories.py — Trajectory Memory for ARC-AGI-3 Agent

Stores, retrieves, and learns from successful/failed paths.
Enables experience replay and strategy transfer.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class TrajectoryStep:
    """Single step in a trajectory."""
    step: int
    action: str
    player_pos: tuple[int, int]
    life_value: int
    key_fits: bool
    zones: dict
    result_state: str  # NOT_PLAYED, NOT_FINISHED, GAME_OVER, LEVEL_COMPLETE


@dataclass
class Trajectory:
    """Complete trajectory (one attempt at a game)."""
    game_id: str
    steps: list[TrajectoryStep]
    result: str  # success, failure, timeout
    levels_completed: int
    life_start: int
    life_end: int
    duration: float
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    
    @property
    def total_steps(self) -> int:
        return len(self.steps)
    
    @property
    def life_cost(self) -> int:
        return self.life_start - self.life_end
    
    @property
    def actions(self) -> list[str]:
        return [s.action for s in self.steps]
    
    @property
    def player_path(self) -> list[tuple[int, int]]:
        return [s.player_pos for s in self.steps]
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['actions'] = self.actions
        d['player_path'] = self.player_path
        d['total_steps'] = self.total_steps
        d['life_cost'] = self.life_cost
        return d


class TrajectoryMemory:
    """Store and query trajectories."""
    
    def __init__(self, memory_dir: str | Path = "state/trajectories"):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.trajectories: list[Trajectory] = []
        self._load()
    
    def _load(self):
        """Load trajectories from disk."""
        for f in self.memory_dir.glob("*.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                    traj = Trajectory(
                        game_id=data['game_id'],
                        steps=[TrajectoryStep(**s) for s in data['steps']],
                        result=data['result'],
                        levels_completed=data['levels_completed'],
                        life_start=data['life_start'],
                        life_end=data['life_end'],
                        duration=data['duration'],
                        timestamp=data.get('timestamp', 0),
                        tags=data.get('tags', []),
                    )
                    self.trajectories.append(traj)
            except Exception:
                pass
    
    def _save(self, traj: Trajectory):
        """Save trajectory to disk."""
        filename = f"{traj.game_id}_{int(traj.timestamp)}.json"
        filepath = self.memory_dir / filename
        with open(filepath, 'w') as f:
            json.dump(traj.to_dict(), f, indent=2)
    
    def store(self, traj: Trajectory):
        """Store a new trajectory."""
        self.trajectories.append(traj)
        self._save(traj)
    
    def get_game_trajectories(self, game_id: str) -> list[Trajectory]:
        """Get all trajectories for a game."""
        return [t for t in self.trajectories if t.game_id == game_id]
    
    def get_successful(self, game_id: str) -> list[Trajectory]:
        """Get successful trajectories for a game."""
        return [t for t in self.trajectories 
                if t.game_id == game_id and t.result == "success"]
    
    def get_failed(self, game_id: str) -> list[Trajectory]:
        """Get failed trajectories for a game."""
        return [t for t in self.trajectories 
                if t.game_id == game_id and t.result == "failure"]
    
    def get_best(self, game_id: str) -> Optional[Trajectory]:
        """Get best trajectory (most levels completed, then fewest steps)."""
        traj = self.get_game_trajectories(game_id)
        if not traj:
            return None
        return max(traj, key=lambda t: (t.levels_completed, -t.total_steps))
    
    def get_action_stats(self, game_id: str) -> dict[str, dict]:
        """Get action statistics for a game."""
        from collections import Counter
        
        successful = self.get_successful(game_id)
        failed = self.get_failed(game_id)
        
        stats = {}
        all_actions = ["ACTION1", "ACTION2", "ACTION3", "ACTION4"]
        
        for action in all_actions:
            suc_count = sum(1 for t in successful for a in t.actions if a == action)
            fail_count = sum(1 for t in failed for a in t.actions if a == action)
            total = suc_count + fail_count
            
            stats[action] = {
                "success": suc_count,
                "failure": fail_count,
                "total": total,
                "success_rate": suc_count / total if total > 0 else 0,
            }
        
        return stats
    
    def get_position_stats(self, game_id: str) -> dict[tuple[int, int], dict]:
        """Get position visit statistics."""
        from collections import Counter
        
        traj = self.get_game_trajectories(game_id)
        if not traj:
            return {}
        
        # Count visits to each position
        visit_counts = Counter()
        success_from = Counter()
        
        for t in traj:
            for step in t.steps:
                pos = step.player_pos
                visit_counts[pos] += 1
                if t.result == "success":
                    success_from[pos] += 1
        
        stats = {}
        for pos, count in visit_counts.items():
            stats[pos] = {
                "visits": count,
                "success_from": success_from.get(pos, 0),
                "success_rate": success_from.get(pos, 0) / count if count > 0 else 0,
            }
        
        return stats
    
    def find_similar_trajectories(self, game_id: str, current_zones: dict) -> list[Trajectory]:
        """Find trajectories with similar zone configurations."""
        traj = self.get_game_trajectories(game_id)
        if not traj:
            return []
        
        # Simple similarity: same zones present
        current_zone_names = set(current_zones.keys())
        
        similar = []
        for t in traj:
            if t.steps:
                step_zones = set(t.steps[0].zones.keys())
                if step_zones == current_zone_names:
                    similar.append(t)
        
        return similar
    
    def get_summary(self) -> dict:
        """Get overall memory summary."""
        from collections import Counter
        
        games = Counter(t.game_id for t in self.trajectories)
        results = Counter(t.result for t in self.trajectories)
        
        return {
            "total_trajectories": len(self.trajectories),
            "games": dict(games),
            "results": dict(results),
            "avg_steps": sum(t.total_steps for t in self.trajectories) / len(self.trajectories) if self.trajectories else 0,
            "success_rate": results.get("success", 0) / len(self.trajectories) if self.trajectories else 0,
        }
    
    def to_prompt_fragment(self, game_id: str) -> str:
        """Generate prompt fragment from memory."""
        stats = self.get_action_stats(game_id)
        best = self.get_best(game_id)
        
        parts = [f"Memory for {game_id}:"]
        
        if best:
            parts.append(f"  Best: {best.result}, {best.total_steps} steps, "
                        f"life {best.life_start}→{best.life_end}")
        
        # Recommend actions with high success rate
        recommended = []
        for action, s in stats.items():
            if s["total"] >= 3 and s["success_rate"] > 0.6:
                recommended.append(f"{action} ({s['success_rate']:.0%})")
        
        if recommended:
            parts.append(f"  Recommended: {', '.join(recommended)}")
        
        return "\n".join(parts)
