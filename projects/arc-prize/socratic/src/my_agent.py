# design: projects/arc-prize/arc_prize_design.vsm
"""ARC-AGI-3 Agent v2 — Improved prompts with grid description and action semantics.
Perceive → describe grid → build context → socratic → llm → act → learn.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from typing import Any
from collections import Counter

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent

sys.path.insert(0, "/root/arc-agi-3/kaggle-starter/agent")
from socratic_agent import SocraticAgent, ActionRecord
from arc3_memory import PatternMemory
from arc3_feedback import AlgedonicFeedback, SignalType
from arc3_canon import StateCanon
from arc3_zones import ZoneDetector
from arc3_trajectories import TrajectoryMemory, Trajectory, TrajectoryStep
from arc3_pathfinding import plan_route, to_prompt_fragment


ACTION_MAP = {
    "ACTION1": GameAction.ACTION1,
    "ACTION2": GameAction.ACTION2,
    "ACTION3": GameAction.ACTION3,
    "ACTION4": GameAction.ACTION4,
    "ACTION5": GameAction.ACTION5,
    "ACTION6": GameAction.ACTION6,
    "ACTION7": GameAction.ACTION7,
}

# Action semantics per game (learned from source code)
GAME_ACTIONS = {
    "ls20": {
        "ACTION1": "move up",
        "ACTION2": "move down",
        "ACTION3": "move left",
        "ACTION4": "move right",
    },
    "ka59": {
        "ACTION1": "move up",
        "ACTION2": "move down",
        "ACTION3": "move left",
        "ACTION4": "move right",
        "ACTION6": "special action",
    },
    "sk48": {
        "ACTION1": "move up",
        "ACTION2": "move down",
        "ACTION3": "move left",
        "ACTION4": "move right",
        "ACTION6": "interact",
        "ACTION7": "special",
    },
    "vc33": {
        "ACTION6": "special action",
    },
    "r11l": {
        "ACTION6": "place/move object",
    },
}

# Color names for ARC grid cells
COLOR_NAMES = {
    0: "black", 1: "blue", 2: "red", 3: "green", 4: "yellow",
    5: "gray", 6: "magenta", 7: "orange", 8: "azure", 9: "brown",
    10: "purple", 11: "cyan", 12: "rose",
}

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3:1.7b"


def ask_llm(prompt: str) -> str:
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 150, "num_ctx": 2048}
    })
    try:
        result = subprocess.run(
            ["curl", "-s", OLLAMA_URL, "-d", payload],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        return data.get("message", {}).get("content", "")
    except Exception:
        return ""


def describe_grid_content(grid: list[list[int]]) -> str:
    """Describe what's on the grid: colors, objects, layout."""
    if not grid or not isinstance(grid[0], list):
        return "empty grid"
    
    h, w = len(grid), len(grid[0])
    
    # Count colors
    color_counts = {}
    for row in grid:
        for cell in row:
            try:
                c = int(cell)
            except:
                c = 0
            color_counts[c] = color_counts.get(c, 0) + 1
    
    total = h * w
    parts = [f"{h}x{w} grid"]
    
    # Describe dominant colors
    sorted_colors = sorted(color_counts.items(), key=lambda x: -x[1])
    color_desc = []
    for c, count in sorted_colors[:5]:
        pct = count * 100 // total
        if pct >= 5:
            color_desc.append(f"{COLOR_NAMES.get(c, f'color{c}')}({pct}%)")
    if color_desc:
        parts.append("colors: " + ", ".join(color_desc))
    
    # Find objects (connected components of non-background)
    # Simple: find bounding boxes of each color
    if h <= 16 and w <= 16:
        # Small grid - describe positions
        objects = []
        for c, count in sorted_colors:
            if c == 0 or count < 3:
                continue  # Skip background and tiny groups
            # Find bounding box
            min_r, max_r = h, 0
            min_c, max_c = w, 0
            for r in range(h):
                for col in range(w):
                    try:
                        if int(grid[r][col]) == c:
                            min_r = min(min_r, r)
                            max_r = max(max_r, r)
                            min_c = min(min_c, col)
                            max_c = max(max_c, col)
                    except:
                        pass
            if max_r >= min_r:
                name = COLOR_NAMES.get(c, f"color{c}")
                objects.append(f"{name} at ({min_r},{min_c})-({max_r},{max_c})")
        if objects:
            parts.append("objects: " + "; ".join(objects[:5]))
    
    return " | ".join(parts)


def describe_frame(frame: FrameData, game_id: str) -> str:
    parts = [f"state={frame.state}"]
    if frame.frame:
        grid = frame.frame
        if isinstance(grid, list) and len(grid) > 0:
            # Unwrap arcengine extra list
            if isinstance(grid[0], list) and len(grid[0]) == 1 and isinstance(grid[0][0], list):
                grid = grid[0]
            desc = describe_grid_content(grid)
            parts.append(desc)
    if hasattr(frame, "levels_completed"):
        parts.append(f"levels={frame.levels_completed}")
    return " | ".join(parts)


class MyAgent(Agent):
    """Improved pipeline agent with better prompts."""

    MAX_ACTIONS = 80

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._action_history: list[str] = []
        self._action_outcomes: list[tuple[str, str]] = []  # (action, result_state)
        self._step = 0
        
        self.socratic = SocraticAgent(self.game_id)
        self.memory = PatternMemory(self.game_id)
        self.feedback = AlgedonicFeedback(self.game_id)
        self.canon = StateCanon(self.game_id)
        self.zones = ZoneDetector(self.game_id)
        self.trajectories = TrajectoryMemory()
        
        self._prev_frame: FrameData | None = None
        self._prev_levels: int = 0
        self._current_trajectory_steps: list[TrajectoryStep] = []
        self._life_start: int | None = None

    @property
    def name(self) -> str:
        return f"{super().name}.socratic.v2"

    def is_done(self, frames: list[FrameData], latest_frame: FrameData) -> bool:
        return latest_frame.state is GameState.WIN

    def _get_game_actions(self) -> dict[str, str]:
        """Get action semantics for current game."""
        game = self.game_id.split("-")[0]
        return GAME_ACTIONS.get(game, {
            "ACTION1": "action 1",
            "ACTION2": "action 2",
            "ACTION3": "action 3",
            "ACTION4": "action 4",
        })

    def _build_llm_prompt(
        self,
        frames: list[FrameData],
        latest_frame: FrameData,
        socratic_hint: str | None,
        pattern_context: str,
        feedback_context: str,
        zone_context: str = "",
    ) -> str:
        game = self.game_id.split("-")[0]
        actions = self._get_game_actions()
        
        # Describe current state
        current_desc = describe_frame(latest_frame, self.game_id)
        
        # Build concise prompt focused on decision
        simple = [a.name for a in GameAction
                  if a is not GameAction.RESET and not a.is_complex()]
        
        # What was tried recently
        tried_counts = Counter(self._action_history[-15:])
        
        # Recent history pairs
        history_pairs = list(self._action_outcomes[-5:]) if self._action_outcomes else []
        
        # Build minimal prompt — just what agent needs
        life = self.zones.history[-1].life_value if self.zones.history else None
        player = self.zones.history[-1].player_pos if self.zones.history else None
        zones = self.zones.history[-1].zones if self.zones.history else {}
        
        # Key-fit status and next objective
        key_fits = "key_fits_figure" in self.zones.invariants
        if key_fits:
            objective = "Key fits! GO TO FIGURE."
        else:
            objective = "Key doesn't fit. GO TO CHECKPOINT to rotate."
        
        parts = [
            f'Step {self._step}, Life: {life}',
            f'Player: {player}',
            f'Objective: {objective}',
        ]
        
        # Pathfinding directive (PRIMARY)
        if hasattr(self, '_route') and self._route.get("next_action"):
            route = self._route
            parts.append(f'\n=== PATHFINDING DIRECTIVE ===')
            parts.append(f'Action: {route["next_action"]}')
            cp_dist = route.get("checkpoint_path")
            if cp_dist and hasattr(cp_dist, 'distance'):
                parts.append(f'Distance to checkpoint: {cp_dist.distance}')
            parts.append(f'Cost: {route.get("total_cost", "?")} life')
            parts.append(f'Budget OK: {route.get("budget_ok", "?")}')
            parts.append(f'MUST execute: {route["next_action"]}')
        
        parts.append(f'\nReply with the action name only (e.g. ACTION3)')
        
        return "\n".join(parts)

    def _parse_action(self, response: str) -> GameAction | None:
        response = response.strip().upper()
        for name, action in ACTION_MAP.items():
            if name in response:
                return action
        if "RESET" in response:
            return GameAction.RESET
        return None

    def _extract_grid_data(self, frame: FrameData) -> dict:
        data = {"state": str(frame.state), "grid": None, "levels_completed": 0}
        if frame.frame:
            data["grid"] = frame.frame
        if hasattr(frame, "levels_completed"):
            data["levels_completed"] = frame.levels_completed
        return data

    def choose_action(
        self, frames: list[FrameData], latest_frame: FrameData
    ) -> GameAction:
        if latest_frame.state in (GameState.NOT_PLAYED, GameState.GAME_OVER):
            # Store trajectory if we have steps
            if self._current_trajectory_steps and self._life_start is not None:
                life_end = self.zones.history[-1].life_value if self.zones.history else self._life_start
                result = "success" if latest_frame.state == GameState.WIN else "failure"
                traj = Trajectory(
                    game_id=self.game_id,
                    steps=self._current_trajectory_steps,
                    result=result,
                    levels_completed=self._prev_levels,
                    life_start=self._life_start,
                    life_end=life_end or self._life_start,
                    duration=0,
                )
                self.trajectories.store(traj)
            
            self._action_history.clear()
            self._action_outcomes.clear()
            self._prev_frame = None
            self._prev_levels = 0
            self._step = 0
            self._current_trajectory_steps = []
            self._life_start = None
            return GameAction.RESET

        self._step += 1
        
        # === PERCEIVE ===
        grid_data = self._extract_grid_data(latest_frame)
        state_str = str(latest_frame.state)
        
        # === ZONES (detect board regions) ===
        grid_for_zones = latest_frame.frame
        if grid_for_zones is not None:
            if hasattr(grid_for_zones, "tolist"):
                grid_for_zones = grid_for_zones.tolist()
            if isinstance(grid_for_zones, list) and len(grid_for_zones) == 1:
                grid_for_zones = grid_for_zones[0]
            if isinstance(grid_for_zones, list) and grid_for_zones and isinstance(grid_for_zones[0], list):
                if len(grid_for_zones[0]) == 1 and isinstance(grid_for_zones[0][0], list):
                    grid_for_zones = grid_for_zones[0]
            zone_data = self.zones.detect(grid_for_zones, step=self._step)
            zone_context = self.zones.to_prompt_fragment()
            
            # === PATHFINDING (plan route) ===
            player_pos = self.zones.history[-1].player_pos if self.zones.history else None
            life_val = self.zones.history[-1].life_value if self.zones.history else 0
            checkpoint_zone = zone_data.get("checkpoint")
            figure_zone = zone_data.get("figure")
            
            if player_pos and checkpoint_zone and figure_zone:
                route = plan_route(
                    grid_for_zones,
                    player_pos,
                    checkpoint_zone.to_dict() if hasattr(checkpoint_zone, 'to_dict') else checkpoint_zone,
                    figure_zone.to_dict() if hasattr(figure_zone, 'to_dict') else figure_zone,
                    life_val or 0,
                )
                pathfinding_context = to_prompt_fragment(route)
            else:
                pathfinding_context = "Pathfinding: waiting for zone data"
                route = {}
        else:
            zone_context = "No grid data"
            pathfinding_context = "No grid data"
            route = {}
        
        # Store route for prompt builder
        self._route = route
        
        # === CANON (predict vs observe) ===
        if self._prev_frame:
            declared = self.canon.predict(self._extract_grid_data(self._prev_frame))
            observed = self.canon.observe(grid_data)
            self.canon.compare(declared, observed)
        
        # === MEMORY (detect patterns) ===
        detected = self.memory.detect_patterns(grid_data)
        pattern_context = self.memory.to_prompt_fragment(detected)
        
        # === FEEDBACK (algedonic signals) ===
        feedback_context = self.feedback.to_prompt_fragment()
        
        # === SOCRATIC (suggest from memory) ===
        candidate_actions = [a.name for a in GameAction
                           if a is not GameAction.RESET and not a.is_complex()]
        socratic_hint = self.socratic.suggest_action(state_str, candidate_actions)
        
        # === LLM (propose action) ===
        memory_context = self.trajectories.to_prompt_fragment(self.game_id)
        prompt = self._build_llm_prompt(
            frames, latest_frame, socratic_hint,
            pattern_context, feedback_context, zone_context
        )
        if memory_context:
            prompt += f"\n{memory_context}"
        if pathfinding_context:
            prompt += f"\n{pathfinding_context}"
        response = ask_llm(prompt)
        action = self._parse_action(response)
        
        # Validate: if LLM response doesn't match pathfinding, use pathfinding
        if action is not None and route.get("next_action"):
            if action.name != route["next_action"]:
                # LLM deviated from pathfinding - use pathfinding instead
                action = ACTION_MAP.get(route["next_action"])
        
        # Fallback: pathfinding recommendation, then socratic, then random
        if action is None:
            if route.get("next_action") and route["next_action"] in ACTION_MAP:
                action = ACTION_MAP[route["next_action"]]
            elif socratic_hint and socratic_hint in ACTION_MAP:
                action = ACTION_MAP[socratic_hint]
            else:
                tried = set(self._action_history[-5:])
                untried = [a for a in candidate_actions if a not in tried]
                if untried:
                    action = ACTION_MAP[random.choice(untried)]
                else:
                    action = ACTION_MAP[random.choice(candidate_actions)]
        
        # Handle complex actions
        if action.is_complex():
            action.set_data({"x": random.randint(0, 63), "y": random.randint(0, 63)})

        action_name = action.name
        
        # Record for socratic memory
        state_key = state_str
        if grid_data.get("grid"):
            g = grid_data["grid"]
            if isinstance(g, list) and len(g) > 0:
                state_key = f"{state_str}_{len(g)}x{len(g[0])}"
        
        action.reasoning = {
            "method": "llm" if response else "exploration_fallback",
            "llm_raw": response[:100] if response else "",
            "socratic_hint": socratic_hint or "",
            "step": self._step,
        }
        
        # Record outcome (will be updated next step)
        record = ActionRecord(
            action=action_name,
            state_before=state_str,
            state_after=state_str,
            levels_before=self._prev_levels,
            levels_after=latest_frame.levels_completed if hasattr(latest_frame, "levels_completed") else 0,
            game_over=(latest_frame.state is GameState.GAME_OVER),
            won=(latest_frame.state is GameState.WIN),
            timestamp=time.time(),
            llm_reasoning=response[:200] if response else "",
            pattern_used=detected[0] if detected else "",
            pleasurable=(latest_frame.state is GameState.WIN),
            painful=(latest_frame.state is GameState.GAME_OVER),
        )
        self.socratic.record_action(record)
        
        # Algedonic feedback
        self.feedback.evaluate(
            state_before=self._prev_frame.state if self._prev_frame else "START",
            state_after=state_str,
            levels_before=self._prev_levels,
            levels_after=latest_frame.levels_completed if hasattr(latest_frame, "levels_completed") else 0,
            action=action_name,
        )
        
        # Record outcome for next prompt
        self._action_outcomes.append((action_name, state_str))
        if len(self._action_outcomes) > 10:
            self._action_outcomes = self._action_outcomes[-10:]
        
        self._prev_frame = latest_frame
        self._prev_levels = latest_frame.levels_completed if hasattr(latest_frame, "levels_completed") else 0
        self._action_history.append(action_name)
        
        # Track trajectory step
        life_now = self.zones.history[-1].life_value if self.zones.history else None
        if self._life_start is None and life_now is not None:
            self._life_start = life_now
        
        key_fits = "key_fits_figure" in self.zones.invariants
        player_pos = self.zones.history[-1].player_pos if self.zones.history else (0, 0)
        
        step = TrajectoryStep(
            step=self._step,
            action=action_name,
            player_pos=player_pos or (0, 0),
            life_value=life_now or 0,
            key_fits=key_fits,
            zones={n: z.to_dict() for n, z in (self.zones.history[-1].zones if self.zones.history else {}).items()},
            result_state=state_str,
        )
        self._current_trajectory_steps.append(step)
        
        # Push state for viewer
        try:
            sys.path.insert(0, "/root/arc-agi-3/kaggle-starter")
            from viewer import push_state
            grid_data_push = latest_frame.frame if hasattr(latest_frame, "frame") else None
            if grid_data_push is not None:
                if hasattr(grid_data_push, "tolist"):
                    grid_data_push = grid_data_push.tolist()
                if isinstance(grid_data_push, list) and len(grid_data_push) == 1:
                    grid_data_push = grid_data_push[0]
                if isinstance(grid_data_push, list) and grid_data_push and isinstance(grid_data_push[0], list):
                    if len(grid_data_push[0]) == 1 and isinstance(grid_data_push[0][0], list):
                        grid_data_push = grid_data_push[0]
            push_state(
                game_id=self.game_id,
                step=self._step,
                grid=grid_data_push,
                action=action_name,
                state_str=state_str,
                action_history=self._action_history[-20:],
                socratic_scores=self.socratic.action_scores,
                reward=self.feedback.get_reward(),
                recent_signals=[
                    {"type": s.signal_type.value, "intensity": s.intensity, "message": s.message}
                    for s in self.feedback.get_recent_signals(5)
                ],
                canon_accuracy=self.canon.get_accuracy(),
                canon_drift_rate=self.canon.get_drift_rate(),
                patterns_detected=detected[:5],
                llm_raw=response[:100] if response else "",
                method=action.reasoning.get("method", "") if isinstance(action.reasoning, dict) else "",
                levels=latest_frame.levels_completed if hasattr(latest_frame, "levels_completed") else 0,
                zones=self.zones.to_dict(),
                life=self.zones.history[-1].life_value if self.zones.history else None,
                player_pos=self.zones.history[-1].player_pos if self.zones.history else None,
                invariants=self.zones.invariants,
            )
        except Exception:
            pass
        
        return action
