# design: projects/arc-prize/arc_prize_design.vsm
"""Socratic Decision Agent — Memory scaffold for ARC-AGI-3.
With exploration bonus to avoid getting stuck.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field


@dataclass
class ActionRecord:
    action: str
    state_before: str
    state_after: str
    levels_before: int
    levels_after: int
    game_over: bool
    won: bool
    timestamp: float
    llm_reasoning: str = ""
    pattern_used: str = ""
    pleasurable: bool = False
    painful: bool = False


@dataclass
class DecisionNode:
    state_key: str
    action: str
    visits: int = 0
    wins: int = 0
    losses: int = 0
    children: dict[str, "DecisionNode"] = field(default_factory=dict)


class SocraticAgent:
    """Decision memory with socratic evaluation.
    
    Uses UCB1 with exploration bonus to avoid local optima.
    """
    
    def __init__(self, game_id: str, max_memory: int = 200):
        self.game_id = game_id
        self.max_memory = max_memory
        self.history: list[ActionRecord] = []
        self.root = DecisionNode(state_key="root", action="START")
        self.action_scores: dict[str, float] = {}
        self._sequence: list[str] = []
        self._total_actions: int = 0
    
    def _state_key(self, state: str, grid_shape: tuple[int, int] | None = None) -> str:
        if grid_shape:
            return f"{state}_{grid_shape[0]}x{grid_shape[1]}"
        return state
    
    def record_action(self, record: ActionRecord) -> None:
        self.history.append(record)
        if len(self.history) > self.max_memory:
            self.history = self.history[-self.max_memory:]
        
        state_key = self._state_key(record.state_before)
        node = self._find_or_create_node(state_key, record.action)
        node.visits += 1
        self._total_actions += 1
        if record.won:
            node.wins += 1
        elif record.game_over:
            node.losses += 1
        
        # Update global action scores
        action = record.action
        if action not in self.action_scores:
            self.action_scores[action] = 0.0
        if record.pleasurable:
            self.action_scores[action] += 1.0
        if record.painful:
            self.action_scores[action] -= 1.0
        
        self._sequence.append(record.action)
        if len(self._sequence) > 10:
            self._sequence = self._sequence[-10:]
    
    def _find_or_create_node(self, state_key: str, action: str) -> DecisionNode:
        if state_key not in self.root.children:
            self.root.children[state_key] = DecisionNode(state_key=state_key, action="")
        node = self.root.children[state_key]
        if action not in node.children:
            node.children[action] = DecisionNode(state_key=state_key, action=action)
        return node.children[action]
    
    def suggest_action(self, state: str, available: list[str]) -> str | None:
        """Suggest best action using UCB1 with exploration bonus."""
        state_key = self._state_key(state)
        
        if state_key not in self.root.children:
            # No data yet — suggest random to explore
            return random.choice(available) if available else None
        
        node = self.root.children[state_key]
        
        # If any action has 0 visits, prefer it (pure exploration)
        unvisited = [a for a in available if a not in node.children or node.children[a].visits == 0]
        if unvisited:
            return random.choice(unvisited)
        
        # UCB1 selection with exploration bonus
        best_action = None
        best_score = float("-inf")
        total_visits = sum(c.visits for c in node.children.values()) or 1
        
        for action in available:
            if action not in node.children:
                return action  # Unexplored
            
            child = node.children[action]
            if child.visits == 0:
                return action
            
            # UCB1 formula
            exploit = child.wins / child.visits
            explore = (2 * total_visits ** 0.5) / child.visits
            
            # Add small random factor for diversity
            noise = random.uniform(-0.05, 0.05)
            
            # Bonus for actions not tried recently
            recency_bonus = 0.0
            if self._sequence and self._sequence[-1] != action:
                recency_bonus = 0.1
            
            score = exploit + explore + noise + recency_bonus
            
            if score > best_score:
                best_score = score
                best_action = action
        
        return best_action
    
    def get_context_summary(self) -> str:
        if not self.history:
            return "No prior experience."
        
        recent = self.history[-5:]
        lines = ["Recent experience:"]
        for r in recent:
            emoji = "✓" if r.won else ("✗" if r.game_over else "→")
            lines.append(f"  {emoji} {r.state_before} → {r.action} → {r.state_after}")
        
        if self.action_scores:
            top = sorted(self.action_scores.items(), key=lambda x: -x[1])[:3]
            lines.append(f"Best actions: {', '.join(a for a,_ in top)}")
        
        if self._sequence:
            lines.append(f"Recent: {' → '.join(self._sequence[-5:])}")
        
        return "\n".join(lines)
    
    def to_json(self) -> str:
        return json.dumps({
            "game_id": self.game_id,
            "action_scores": self.action_scores,
            "total_actions": self._total_actions,
            "sequence": self._sequence,
        }, indent=2)
