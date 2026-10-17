# design: projects/arc-prize/knowledge/viarc3_master_plan.vsm
"""ViArc-3 homeostat skeleton (M1 stub) — AGI-3 agent.

    perceive (compressed frame diff) -> model (action-effect stats)
    -> goal (WIN) -> plan (systematic novelty + undo rollback) -> act

Deterministic (R10): seeded per game_id; no wall-clock in decisions.
Drop-in compatible with the ARC-AGI-3-Agents framework (MyAgent contract).
M2 replaces `model` with executable world-model hypotheses + retrodiction
certifier; M2 also adds python-retrieval history tools (Duke pattern).
"""
from __future__ import annotations

import hashlib
from typing import Any

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent


def _seed(game_id: str) -> int:
    return int(hashlib.sha256(game_id.encode()).hexdigest()[:8], 16)


class MyAgent(Agent):
    """Systematic-exploration homeostat baseline (M1)."""

    MAX_ACTIONS = 400

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rng_state = _seed(self.game_id)
        # per-action effect stats: action -> (changed, tried)
        self._effects: dict[str, list[int]] = {}
        self._prev_sig: tuple | None = None
        self._thrash = 0
        self._last_action: str | None = None

    # ── deterministic LCG (R10: no wall-clock, no `random` module) ────
    def _next(self, n: int) -> int:
        self._rng_state = (1103515245 * self._rng_state + 12345) % 2**31
        return self._rng_state % n

    @property
    def name(self) -> str:
        return f"viarc3-homeostat.{self.MAX_ACTIONS}"

    # ── perceive: compressed frame signature (frame is 3D: list of 2D) ─
    @staticmethod
    def _flat(grid: Any) -> tuple:
        if isinstance(grid, list):
            out: list[int] = []
            for item in grid:
                if isinstance(item, list):
                    out.extend(MyAgent._flat(item))
                else:
                    out.append(int(item))
            return tuple(out)
        return tuple(int(v) for v in grid)  # numpy array

    @classmethod
    def _sig(cls, frame: FrameData) -> tuple:
        flat = cls._flat(frame.frame)
        nz = sum(1 for v in flat if v)
        h = hash(flat) & 0xFFFFFFFF  # int-tuple hash: run-stable (R10)
        return (len(flat), nz, h)

    @staticmethod
    def _to_actions(codes: list[int]) -> list[GameAction]:
        names = {0: "RESET"}
        out = []
        for c in codes:
            name = names.get(c, f"ACTION{c}" if 1 <= c <= 7 else None)
            if name and name in GameAction.__members__:
                out.append(GameAction.__members__[name])
        return out

    def is_done(self, frames: list[FrameData], latest_frame: FrameData) -> bool:
        return latest_frame.state is GameState.WIN

    # ── model: record action effects (retrodiction fodder for M2) ─────
    def _observe_effect(self, action_name: str, changed: bool) -> None:
        slot = self._effects.setdefault(action_name, [0, 0])
        slot[1] += 1
        if changed:
            slot[0] += 1
            self._thrash = 0
        else:
            self._thrash += 1

    def choose_action(
        self, frames: list[FrameData], latest_frame: FrameData
    ) -> GameAction:
        if latest_frame.state in (GameState.NOT_PLAYED, GameState.GAME_OVER):
            self._prev_sig = None
            return GameAction.RESET

        sig = self._sig(latest_frame)
        avail = [
            a for a in self._to_actions(latest_frame.available_actions)
            if a is not GameAction.RESET
        ] or [a for a in GameAction if a is not GameAction.RESET]

        # attribute last action's effect (algedonic: waste = no change)
        if self._prev_sig is not None and self._last_action is not None:
            self._observe_effect(self._last_action, sig != self._prev_sig)

        # plan: least-tried action first (systematic coverage); if thrash
        # (no-change streak), prefer actions with high historical change rate
        if self._thrash >= 6:
            scored = sorted(
                avail,
                key=lambda a: (
                    -self._effects.get(a.name, [0, 0])[0]
                    / max(1, self._effects.get(a.name, [0, 0])[1]),
                    a.name,
                ),
            )
            action = scored[0]
        else:
            tried = sorted(
                avail,
                key=lambda a: (self._effects.get(a.name, [0, 0])[1], a.name),
            )
            action = tried[0]

        if action.is_complex():
            action.set_data({"x": self._next(64), "y": self._next(64)})
            action.reasoning = {"why": "homeostat systematic", "thrash": self._thrash}
        else:
            action.reasoning = f"homeostat: tried={self._effects.get(action.name, [0, 0])[1]}"

        self._prev_sig = sig
        self._last_action = action.name
        return action
