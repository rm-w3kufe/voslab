# design: projects/arc-prize/arc_prize_design.vsm
"""Algedonic Feedback — Pain/pleasure signals from game outcomes.

Named after Stafford Beer's concept: signals of pain or pleasure
travel directly to S5 (identity/policy) without going through hierarchy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time


class SignalType(Enum):
    PAIN = "pain"
    PLEASURE = "pleasure"
    NEUTRAL = "neutral"


@dataclass
class AlgedonicSignal:
    """A pain/pleasure signal from a game action."""
    signal_type: SignalType
    intensity: float       # 0.0 to 1.0
    source: str            # What triggered it (e.g., "game_over", "level_progress")
    message: str           # Human-readable explanation
    timestamp: float = field(default_factory=time.time)
    action: str = ""
    pattern_used: str = ""


class AlgedonicFeedback:
    """Pain/pleasure feedback system for game learning.
    
    Generates signals from game state transitions:
    - WIN → strong pleasure
    - GAME_OVER → pain
    - Level progress → mild pleasure
    - Stuck (no progress) → mild pain
    - Repeated action → pain
    """
    
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.signals: list[AlgedonicSignal] = []
        self.cumulative_pleasure: float = 0.0
        self.cumulative_pain: float = 0.0
        self._last_levels: int = 0
        self._last_action: str = ""
        self._repeat_count: int = 0
    
    def evaluate(
        self,
        state_before: str,
        state_after: str,
        levels_before: int,
        levels_after: int,
        action: str,
        pattern_used: str = "",
    ) -> AlgedonicSignal:
        """Evaluate transition and generate signal."""
        signal = None
        
        # WIN → strong pleasure
        if state_after == "WIN":
            signal = AlgedonicSignal(
                signal_type=SignalType.PLEASURE,
                intensity=1.0,
                source="win",
                message="Game won!",
                action=action,
                pattern_used=pattern_used,
            )
        
        # GAME_OVER → pain
        elif state_after == "GAME_OVER":
            signal = AlgedonicSignal(
                signal_type=SignalType.PAIN,
                intensity=0.8,
                source="game_over",
                message="Died - action was harmful",
                action=action,
                pattern_used=pattern_used,
            )
        
        # Level progress → mild pleasure
        elif levels_after > levels_before:
            signal = AlgedonicSignal(
                signal_type=SignalType.PLEASURE,
                intensity=0.5,
                source="level_progress",
                message=f"Progress: levels {levels_before} → {levels_after}",
                action=action,
                pattern_used=pattern_used,
            )
        
        # Stuck → mild pain
        elif state_after == state_before and levels_after == levels_before:
            self._repeat_count += 1
            intensity = min(0.3, 0.1 * self._repeat_count)
            signal = AlgedonicSignal(
                signal_type=SignalType.PAIN,
                intensity=intensity,
                source="stuck",
                message=f"No progress ({self._repeat_count}x stuck)",
                action=action,
                pattern_used=pattern_used,
            )
        else:
            self._repeat_count = 0
            signal = AlgedonicSignal(
                signal_type=SignalType.NEUTRAL,
                intensity=0.0,
                source="transition",
                message=f"State: {state_before} → {state_after}",
                action=action,
                pattern_used=pattern_used,
            )
        
        # Track cumulative
        if signal.signal_type == SignalType.PLEASURE:
            self.cumulative_pleasure += signal.intensity
        elif signal.signal_type == SignalType.PAIN:
            self.cumulative_pain += signal.intensity
        
        self.signals.append(signal)
        self._last_levels = levels_after
        self._last_action = action
        return signal
    
    def get_reward(self) -> float:
        """Net reward: pleasure minus pain."""
        return self.cumulative_pleasure - self.cumulative_pain
    
    def get_recent_signals(self, n: int = 5) -> list[AlgedonicSignal]:
        """Get last n signals."""
        return self.signals[-n:]
    
    def to_prompt_fragment(self) -> str:
        """Generate prompt fragment from recent feedback."""
        recent = self.get_recent_signals(5)
        if not recent:
            return "No feedback yet."
        
        lines = [f"Cumulative reward: {self.get_reward():.2f}"]
        for s in recent:
            emoji = "✓" if s.signal_type == SignalType.PLEASURE else ("✗" if s.signal_type == SignalType.PAIN else "→")
            lines.append(f"  {emoji} {s.message} (intensity: {s.intensity:.1f})")
        return "\n".join(lines)
    
    def should_explore(self) -> bool:
        """Should we explore more? (High pain = explore, High pleasure = exploit)."""
        if self.cumulative_pain > self.cumulative_pleasure * 2:
            return True  # In pain, try new things
        if self.cumulative_pleasure > 5:
            return False  # Doing well, keep going
        return True  # Default to exploration
