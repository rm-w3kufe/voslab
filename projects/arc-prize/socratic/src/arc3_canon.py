# design: projects/arc-prize/arc_prize_design.vsm
"""State Canon — Declared vs Observed game state drift detection.

Tracks what we THINK should happen vs what ACTUALLY happens.
When drift is detected, triggers re-evaluation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StateSnapshot:
    """A snapshot of declared vs observed state."""
    declared: dict[str, Any]   # What we think should happen
    observed: dict[str, Any]   # What actually happened
    drift_detected: bool = False
    drift_fields: list[str] = field(default_factory=list)


class StateCanon:
    """Declared vs observed state tracking.
    
    For ARC-AGI-3:
    - Declared: our prediction of what the next state will be
    - Observed: what the game engine actually returns
    - Drift: difference between declared and observed
    
    When drift is high, we know our model of the game is wrong.
    """
    
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.snapshots: list[StateSnapshot] = []
        self.drift_count: int = 0
        self.total_predictions: int = 0
        self.correct_predictions: int = 0
    
    def predict(self, frame_data: dict) -> dict[str, Any]:
        """Make a prediction about next state.
        
        Simple heuristics based on current state.
        """
        state = frame_data.get("state", "UNKNOWN")
        grid = frame_data.get("grid")
        levels = frame_data.get("levels_completed", 0)
        
        prediction = {
            "predicted_state": state,  # Default: state stays same
            "predicted_levels": levels,
            "grid_changed": False,
        }
        
        # Simple prediction rules
        if state == "NOT_PLAYED":
            prediction["predicted_state"] = "PLAYING"
        elif state == "PLAYING":
            # Can't predict much without game knowledge
            prediction["predicted_state"] = "PLAYING"
        
        return prediction
    
    def observe(self, frame_data: dict) -> dict[str, Any]:
        """Extract observed state from game frame."""
        return {
            "observed_state": frame_data.get("state", "UNKNOWN"),
            "observed_levels": frame_data.get("levels_completed", 0),
            "grid_changed": True,  # Always assume grid changes
        }
    
    def compare(self, declared: dict, observed: dict) -> StateSnapshot:
        """Compare declared vs observed, detect drift."""
        drift_fields = []
        
        # Check state
        d_state = declared.get("predicted_state", "")
        o_state = observed.get("observed_state", "")
        if d_state != o_state:
            drift_fields.append(f"state: {d_state} → {o_state}")
        
        # Check levels
        d_levels = declared.get("predicted_levels", 0)
        o_levels = observed.get("observed_levels", 0)
        if d_levels != o_levels:
            drift_fields.append(f"levels: {d_levels} → {o_levels}")
        
        # Check grid
        d_grid = declared.get("grid_changed", False)
        o_grid = observed.get("grid_changed", True)
        if d_grid != o_grid:
            drift_fields.append(f"grid_changed: {d_grid} → {o_grid}")
        
        self.total_predictions += 1
        if not drift_fields:
            self.correct_predictions += 1
        else:
            self.drift_count += 1
        
        snapshot = StateSnapshot(
            declared=declared,
            observed=observed,
            drift_detected=len(drift_fields) > 0,
            drift_fields=drift_fields,
        )
        self.snapshots.append(snapshot)
        if len(self.snapshots) > 100:
            self.snapshots = self.snapshots[-100:]
        
        return snapshot
    
    def get_accuracy(self) -> float:
        """Prediction accuracy."""
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions
    
    def get_drift_rate(self) -> float:
        """Drift rate (higher = less predictable)."""
        if self.total_predictions == 0:
            return 0.0
        return self.drift_count / self.total_predictions
    
    def to_prompt_fragment(self) -> str:
        """Generate prompt fragment from canon state."""
        if not self.snapshots:
            return "No predictions yet."
        
        recent = self.snapshots[-3:]
        lines = [
            f"Prediction accuracy: {self.get_accuracy():.0%}",
            f"Drift rate: {self.get_drift_rate():.0%}",
        ]
        for s in recent:
            if s.drift_detected:
                lines.append(f"  ⚠ Drift: {', '.join(s.drift_fields)}")
            else:
                lines.append(f"  ✓ Prediction correct")
        return "\n".join(lines)
    
    def should_replan(self) -> bool:
        """Should we replan? (High drift = yes)."""
        return self.get_drift_rate() > 0.5
    
    def to_json(self) -> str:
        return json.dumps({
            "game_id": self.game_id,
            "total_predictions": self.total_predictions,
            "correct_predictions": self.correct_predictions,
            "drift_count": self.drift_count,
            "accuracy": self.get_accuracy(),
            "drift_rate": self.get_drift_rate(),
        }, indent=2)
