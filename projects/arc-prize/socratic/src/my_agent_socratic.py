# design: projects/arc-prize/arc_prize_design.vsm
"""ARC-AGI-3 Agent — Full pipeline with exploration.
Perceive → socratic → llm → act → learn.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from typing import Any

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent

sys.path.insert(0, "/root/arc-agi-3/kaggle-starter/agent")
from socratic_agent import SocraticAgent, ActionRecord
from arc3_memory import PatternMemory
from arc3_feedback import AlgedonicFeedback, SignalType
from arc3_canon import StateCanon


ACTION_MAP = {
    "ACTION1": GameAction.ACTION1,
    "ACTION2": GameAction.ACTION2,
    "ACTION3": GameAction.ACTION3,
    "ACTION4": GameAction.ACTION4,
    "ACTION5": GameAction.ACTION5,
    "ACTION6": GameAction.ACTION6,
    "ACTION7": GameAction.ACTION7,
}

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3:1.7b"


def ask_llm(prompt: str) -> str:
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 200, "num_ctx": 2048}
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


def describe_frame(frame: FrameData) -> str:
    parts = [f"state={frame.state}"]
    if frame.frame:
        grid = frame.frame
        if isinstance(grid, list) and len(grid) > 0:
            rows = len(grid)
            cols = len(grid[0]) if isinstance(grid[0], list) else 0
            parts.append(f"grid={rows}x{cols}")
            if rows <= 8 and cols <= 8:
                flat = [cell for row in grid for cell in row]
                parts.append(f"grid_flat={flat}")
    if hasattr(frame, "levels_completed"):
        parts.append(f"levels={frame.levels_completed}")
    return ", ".join(parts)


class MyAgent(Agent):
    """Full pipeline agent with exploration."""

    MAX_ACTIONS = 80

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._action_history: list[str] = []
        self._step = 0
        
        self.socratic = SocraticAgent(self.game_id)
        self.memory = PatternMemory(self.game_id)
        self.feedback = AlgedonicFeedback(self.game_id)
        self.canon = StateCanon(self.game_id)
        
        self._prev_frame: FrameData | None = None
        self._prev_levels: int = 0

    @property
    def name(self) -> str:
        return f"{super().name}.socratic"

    def is_done(self, frames: list[FrameData], latest_frame: FrameData) -> bool:
        return latest_frame.state is GameState.WIN

    def _build_llm_prompt(
        self,
        frames: list[FrameData],
        latest_frame: FrameData,
        socratic_hint: str | None,
        pattern_context: str,
        feedback_context: str,
        canon_context: str,
    ) -> str:
        game = self.game_id.split("-")[0]
        recent = frames[-3:] if len(frames) > 3 else frames
        frame_desc = " | ".join(describe_frame(f) for f in recent)
        
        simple = [a.name for a in GameAction
                  if a is not GameAction.RESET and not a.is_complex()]
        
        # Tell LLM what actions were tried and their results
        tried_summary = ""
        if self._action_history:
            from collections import Counter
            counts = Counter(self._action_history[-20:])
            tried_summary = f"Recently tried: {dict(counts)}"
        
        parts = [
            f'Game "{game}" — Step {self._step}',
            f"Current: {frame_desc}",
            f"Available: {', '.join(simple)}",
            "",
        ]
        
        if tried_summary:
            parts.append(tried_summary)
            parts.append("TRY A DIFFERENT ACTION if possible.")
            parts.append("")
        
        if socratic_hint:
            parts.append(f"Suggestion: {socratic_hint}")
        
        if pattern_context and "No patterns" not in pattern_context:
            parts.append(pattern_context)
        
        if feedback_context and "No feedback" not in feedback_context:
            parts.append(feedback_context)
        
        parts.append(f"\nChoose ONE action ({', '.join(simple)}). Reply ONLY with action name.")
        
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
            self._action_history.clear()
            self._prev_frame = None
            self._prev_levels = 0
            self._step = 0
            return GameAction.RESET

        self._step += 1
        
        # === PERCEIVE ===
        grid_data = self._extract_grid_data(latest_frame)
        state_str = str(latest_frame.state)
        
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
        
        # === CANON (state drift) ===
        canon_context = self.canon.to_prompt_fragment()
        
        # === SOCRATIC (suggest from memory) ===
        candidate_actions = [a.name for a in GameAction
                           if a is not GameAction.RESET and not a.is_complex()]
        socratic_hint = self.socratic.suggest_action(state_str, candidate_actions)
        
        # === LLM (propose action) ===
        prompt = self._build_llm_prompt(
            frames, latest_frame, socratic_hint,
            pattern_context, feedback_context, canon_context
        )
        response = ask_llm(prompt)
        action = self._parse_action(response)
        
        # Fallback: socratic hint, then random with bias toward untried
        if action is None:
            if socratic_hint and socratic_hint in ACTION_MAP:
                action = ACTION_MAP[socratic_hint]
            else:
                # Prefer actions not tried recently
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
        
        # Record outcome
        record = ActionRecord(
            action=action_name,
            state_before=state_str,
            state_after=state_str,  # Will be updated next step
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
        
        self._prev_frame = latest_frame
        self._prev_levels = latest_frame.levels_completed if hasattr(latest_frame, "levels_completed") else 0
        self._action_history.append(action_name)
        
        return action
