# design: projects/arc-prize/arc_prize_design.vsm
"""ARC-AGI-3 Pattern Memory — Knowledge base of discovered patterns.

Patterns are extracted from VSM-ARC-RSI (59 patterns) and adapted
for ARC-AGI-3 game contexts. Each pattern is a (condition, action) pair.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Pattern:
    """A discovered pattern with context."""
    name: str
    description: str
    condition: str      # When to apply (e.g., "grid_symmetric", "object_moving")
    action_hint: str    # Suggested action (e.g., "mirror_x", "follow_object")
    confidence: float   # 0.0 to 1.0
    times_used: int = 0
    times_succeeded: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.times_used == 0:
            return 0.0
        return self.times_succeeded / self.times_used
    
    def to_prompt_fragment(self) -> str:
        return f"- {self.name}: {self.description} → {self.action_hint} (confidence: {self.confidence:.0%})"


# Pre-loaded patterns from VSM-ARC-RSI + ARC-AGI-3 observations
BASE_PATTERNS: list[Pattern] = [
    # Movement patterns
    Pattern("move_toward_goal", "Player should move toward the goal position",
            "goal_visible", "move_closer_to_goal", 0.7),
    Pattern("avoid_walls", "Don't move into walls or boundaries",
            "wall_ahead", "turn_or_reverse", 0.8),
    Pattern("follow_path", "Follow a clear path when one exists",
            "path_visible", "follow_path", 0.6),
    
    # Symmetry patterns
    Pattern("mirror_horizontal", "Grid has horizontal symmetry",
            "grid_symmetric_h", "mirror_action_h", 0.5),
    Pattern("mirror_vertical", "Grid has vertical symmetry",
            "grid_symmetric_v", "mirror_action_v", 0.5),
    Pattern("rotate_90", "Pattern rotates 90 degrees each step",
            "rotation_detected", "rotate_action", 0.4),
    
    # Object interaction
    Pattern("pick_up_nearby", "Pick up objects when nearby",
            "object_nearby", "interact", 0.6),
    Pattern("push_to_corner", "Push objects toward corners",
            "pushable_object", "push_toward_corner", 0.3),
    Pattern("collect_all", "Collect all scattered objects",
            "objects_scattered", "move_to_nearest_object", 0.5),
    
    # Timing patterns
    Pattern("wait_for_cycle", "Wait for cyclic pattern to align",
            "cyclic_pattern", "wait", 0.4),
    Pattern("act_on_beat", "Act when objects are in sync",
            "objects_in_sync", "interact_now", 0.5),
    
    # Color/shape patterns
    Pattern("match_color", "Match color of target",
            "color_target_visible", "match_color_action", 0.5),
    Pattern("complete_shape", "Complete an incomplete shape",
            "incomplete_shape", "fill_gap", 0.6),
    
    # Grid transformation
    Pattern("shift_row", "Shift a row left or right",
            "row_offset", "shift_row_action", 0.4),
    Pattern("flip_column", "Flip a column vertically",
            "column_flip", "flip_column_action", 0.4),
    Pattern("fill_solid", "Fill an area with solid color",
            "empty_area", "fill_area", 0.3),
    
    # Exploration patterns
    Pattern("try_all_actions", "Systematically try each action",
            "unknown_state", "sequential_action", 0.2),
    Pattern("random_walk", "Random walk to discover structure",
            "no_pattern_found", "random_action", 0.1),
    Pattern("repeat_successful", "Repeat actions that worked before",
            "similar_state", "repeat_last_good", 0.5),
    
    # ARC-specific
    Pattern("count_objects", "Count objects to determine action",
            "countable_objects", "count_based_action", 0.4),
    Pattern("trace_path", "Trace the path of a moving object",
            "moving_object", "follow_trace", 0.5),
    Pattern("connect_dots", "Connect dots or endpoints",
            "endpoints_visible", "connect_path", 0.4),
]


class PatternMemory:
    """Memory of discovered patterns for a game.
    
    Combines base patterns with game-specific learned patterns.
    """
    
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.patterns = {p.name: p for p in BASE_PATTERNS}
        self.game_specific: list[Pattern] = []
    
    def detect_patterns(self, frame_data: dict) -> list[str]:
        """Detect which patterns apply to current game state.
        Returns list of matching pattern names.
        """
        matches = []
        
        # Simple heuristic detection
        import numpy as np
        grid = frame_data.get("grid")
        if grid is not None:
            # Convert numpy array to list if needed
            if isinstance(grid, np.ndarray):
                grid = grid.tolist()
            if isinstance(grid, list) and len(grid) > 0:
                rows = len(grid)
                cols = len(grid[0]) if isinstance(grid[0], list) else 0
                
                if cols > 0:
                    # Check for empty areas
                    has_zero = False
                    for row in grid:
                        if isinstance(row, list):
                            for cell in row:
                                try:
                                    if int(cell) == 0:
                                        has_zero = True
                                        break
                                except (TypeError, ValueError):
                                    pass
                            if has_zero:
                                break
                    if has_zero:
                        matches.append("fill_solid")
                    
                    # Check for scattered objects
                    nonzero = 0
                    for row in grid:
                        if isinstance(row, list):
                            for cell in row:
                                try:
                                    if int(cell) != 0:
                                        nonzero += 1
                                except (TypeError, ValueError):
                                    pass
                    if 0 < nonzero < rows * cols * 0.3:
                        matches.append("collect_all")
                    
                    # Check for symmetry
                    if rows == cols:
                        matches.append("mirror_horizontal")
        
        # Always suggest exploration
        matches.append("try_all_actions")
        
        return matches
    
    def get_relevant_patterns(self, detected: list[str], top_k: int = 5) -> list[Pattern]:
        """Get top patterns for detected context."""
        scored = []
        for name in detected:
            if name in self.patterns:
                p = self.patterns[name]
                score = p.confidence * (1 + p.success_rate)
                scored.append((score, p))
        
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:top_k]]
    
    def record_outcome(self, pattern_name: str, succeeded: bool) -> None:
        """Record pattern outcome."""
        if pattern_name in self.patterns:
            p = self.patterns[pattern_name]
            p.times_used += 1
            if succeeded:
                p.times_succeeded += 1
            # Update confidence
            p.confidence = p.confidence * 0.9 + (1.0 if succeeded else 0.0) * 0.1
    
    def learn_pattern(self, name: str, description: str, condition: str, action_hint: str) -> Pattern:
        """Learn a new game-specific pattern."""
        p = Pattern(
            name=name,
            description=description,
            condition=condition,
            action_hint=action_hint,
            confidence=0.3,
        )
        self.game_specific.append(p)
        self.patterns[name] = p
        return p
    
    def to_prompt_fragment(self, detected: list[str]) -> str:
        """Generate prompt fragment with relevant patterns."""
        relevant = self.get_relevant_patterns(detected)
        if not relevant:
            return "No patterns detected yet."
        
        lines = ["Relevant patterns:"]
        for p in relevant:
            lines.append(f"  {p.to_prompt_fragment()}")
        return "\n".join(lines)
    
    def to_json(self) -> str:
        return json.dumps({
            "game_id": self.game_id,
            "total_patterns": len(self.patterns),
            "game_specific": len(self.game_specific),
            "top_confidence": sorted(
                [(p.name, p.confidence) for p in self.patterns.values()],
                key=lambda x: -x[1]
            )[:5],
        }, indent=2)
