# design: projects/arc-prize/arc_prize_design.vsm
"""ARC-AGI-3 Zone Detection — Identify game board regions and track changes.

Zones detected:
- model: the "key" shape (rows 53-62, left side)
- figure: the "lock" shape (rows 9-15, center)
- checkpoint: refill cross (rows 31-33, left)
- life_bar: health display (rows 60-62)
- player: green sprite position

Invariants tracked:
- life decreases with each move
- model must match figure shape
- checkpoints refill life
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


def _to_list(grid: Any) -> list[list[int]]:
    """Convert numpy array to list if needed."""
    import numpy as np
    if isinstance(grid, np.ndarray):
        grid = grid.tolist()
    if isinstance(grid, list) and len(grid) > 0:
        if isinstance(grid[0], list) and len(grid[0]) == 1 and isinstance(grid[0][0], list):
            grid = grid[0]
    return grid


@dataclass
class Zone:
    name: str
    row_start: int
    row_end: int
    col_start: int
    col_end: int
    colors: dict[int, int]  # color → count
    confidence: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        return ((self.row_start + self.row_end) // 2,
                (self.col_start + self.col_end) // 2)

    @property
    def height(self) -> int:
        return self.row_end - self.row_start + 1

    @property
    def width(self) -> int:
        return self.col_end - self.col_start + 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rows": f"{self.row_start}-{self.row_end}",
            "cols": f"{self.col_start}-{self.col_end}",
            "center": self.center,
            "colors": self.colors,
            "confidence": self.confidence,
        }


@dataclass
class ZoneSnapshot:
    timestamp: float
    zones: dict[str, Zone]
    life_value: int | None = None
    player_pos: tuple[int, int] | None = None
    step: int = 0


class ZoneDetector:
    """Detect and track zones on the game board."""

    def __init__(self, game_id: str):
        self.game_id = game_id
        self.history: list[ZoneSnapshot] = []
        self.invariants: list[str] = []
        self._prev_life: int | None = None

    def detect(self, grid: list[list[int]], step: int = 0) -> dict[str, Zone]:
        """Detect all zones on the current grid."""
        grid = _to_list(grid)
        if not grid or not isinstance(grid[0], list):
            return {}

        h, w = len(grid), len(grid[0])
        zones = {}

        # Detect life bar (rows 60-62, cyan/azure)
        life_zone = self._detect_life_bar(grid, h, w)
        if life_zone:
            zones["life_bar"] = life_zone

        # Detect model (rows 53-59, gray+brown shape)
        model_zone = self._detect_model(grid, h, w)
        if model_zone:
            zones["model"] = model_zone

        # Detect figure (rows 9-15, gray+green+brown shape)
        figure_zone = self._detect_figure(grid, h, w)
        if figure_zone:
            zones["figure"] = figure_zone

        # Detect checkpoint (rows 31-33, cross shape)
        checkpoint_zone = self._detect_checkpoint(grid, h, w)
        if checkpoint_zone:
            zones["checkpoint"] = checkpoint_zone

        # Detect player (single green cell, not in figure zone)
        player_pos = self._detect_player(grid, h, w, figure_zone)

        # Calculate life value from life bar
        life_value = None
        if life_zone:
            life_value = self._calculate_life(grid, life_zone)

        # Create snapshot
        snapshot = ZoneSnapshot(
            timestamp=time.time(),
            zones=zones,
            life_value=life_value,
            player_pos=player_pos,
            step=step,
        )
        self.history.append(snapshot)

        # Check invariants
        self._check_invariants(snapshot)

        return zones

    def _detect_life_bar(self, grid: list[list[int]], h: int, w: int) -> Zone | None:
        """Detect life bar in rows 60-62."""
        if h < 63:
            return None

        colors = {}
        for r in range(60, 63):
            for c in range(w):
                try:
                    v = int(grid[r][c])
                    colors[v] = colors.get(v, 0) + 1
                except:
                    pass

        # Life bar should have cyan (11) and azure (8)
        if 11 in colors or 8 in colors:
            return Zone(
                name="life_bar",
                row_start=60, row_end=62,
                col_start=0, col_end=w - 1,
                colors=colors,
            )
        return None

    def _detect_model(self, grid: list[list[int]], h: int, w: int) -> Zone | None:
        """Detect model/key shape in rows 53-59."""
        if h < 60:
            return None

        # Find the shape in rows 53-59 (gray + brown)
        shape_colors = {5, 9}  # gray, brown
        min_r, max_r = 59, 53
        min_c, max_c = w, 0

        for r in range(53, 60):
            for c in range(w):
                try:
                    v = int(grid[r][c])
                    if v in shape_colors:
                        min_r = min(min_r, r)
                        max_r = max(max_r, r)
                        min_c = min(min_c, c)
                        max_c = max(max_c, c)
                except:
                    pass

        if max_r < min_r:
            return None

        colors = {}
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                try:
                    v = int(grid[r][c])
                    colors[v] = colors.get(v, 0) + 1
                except:
                    pass

        return Zone(
            name="model",
            row_start=min_r, row_end=max_r,
            col_start=min_c, col_end=max_c,
            colors=colors,
        )

    def _detect_figure(self, grid: list[list[int]], h: int, w: int) -> Zone | None:
        """Detect figure/lock shape in rows 9-15."""
        if h < 16:
            return None

        # Find the shape in rows 9-15 (gray + green + brown)
        shape_colors = {3, 5, 9}  # green, gray, brown
        min_r, max_r = 15, 9
        min_c, max_c = w, 0

        for r in range(9, 16):
            for c in range(w):
                try:
                    v = int(grid[r][c])
                    if v in shape_colors:
                        min_r = min(min_r, r)
                        max_r = max(max_r, r)
                        min_c = min(min_c, c)
                        max_c = max(max_c, c)
                except:
                    pass

        if max_r < min_r:
            return None

        colors = {}
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                try:
                    v = int(grid[r][c])
                    colors[v] = colors.get(v, 0) + 1
                except:
                    pass

        return Zone(
            name="figure",
            row_start=min_r, row_end=max_r,
            col_start=min_c, col_end=max_c,
            colors=colors,
        )

    def _detect_checkpoint(self, grid: list[list[int]], h: int, w: int) -> Zone | None:
        """Detect checkpoint cross in rows 31-33."""
        if h < 34:
            return None

        colors = {}
        for r in range(31, 34):
            for c in range(w):
                try:
                    v = int(grid[r][c])
                    colors[v] = colors.get(v, 0) + 1
                except:
                    pass

        # Checkpoint has green (3) and gray (5)
        if 3 in colors and 5 in colors:
            return Zone(
                name="checkpoint",
                row_start=31, row_end=33,
                col_start=0, col_end=w - 1,
                colors=colors,
            )
        return None

    def _detect_player(
        self,
        grid: list[list[int]],
        h: int,
        w: int,
        figure_zone: Zone | None,
    ) -> tuple[int, int] | None:
        """Detect player position (5x5 sprite with 2 colors, unique on grid)."""
        # First pass: find all 5x5 blocks with exactly 2 colors
        candidates = []
        for r in range(h - 4):
            for c in range(w - 4):
                try:
                    colors = set()
                    for dr in range(5):
                        for dc in range(5):
                            colors.add(int(grid[r+dr][c+dc]))
                    if len(colors) == 2:
                        # Check it's not part of a larger pattern (unique 5x5)
                        # The player sprite is unique — other 5x5 blocks have more colors
                        candidates.append((r + 2, c + 2, colors))
                except:
                    pass
        
        # The player is the 5x5 block that appears ONLY ONCE
        if candidates:
            from collections import Counter
            color_pairs = [tuple(sorted(c)) for _, _, c in candidates]
            counts = Counter(color_pairs)
            for pos_r, pos_c, colors in candidates:
                pair = tuple(sorted(colors))
                if counts[pair] == 1:  # unique = player
                    return (pos_r, pos_c)
            # If no unique pair, return first candidate
            return (candidates[0][0], candidates[0][1])
        
        return None

    def _calculate_life(self, grid: list[list[int]], zone: Zone) -> int:
        """Calculate life value from life bar (count of cyan/azure cells)."""
        life = 0
        for r in range(zone.row_start, zone.row_end + 1):
            for c in range(zone.col_start, zone.col_end + 1):
                try:
                    v = int(grid[r][c])
                    if v in (8, 11):  # azure, cyan
                        life += 1
                except:
                    pass
        return life

    def _check_invariants(self, snapshot: ZoneSnapshot) -> None:
        """Check for invariants across snapshots."""
        if len(self.history) < 2:
            return

        prev = self.history[-2]

        # Invariant 1: Life decreases with moves
        if prev.life_value is not None and snapshot.life_value is not None:
            if snapshot.life_value < prev.life_value:
                delta = prev.life_value - snapshot.life_value
                inv = f"life_decreases_by_{delta}"
                if inv not in self.invariants:
                    self.invariants.append(inv)
            elif snapshot.life_value > prev.life_value:
                inv = "life_refills"
                if inv not in self.invariants:
                    self.invariants.append(inv)

        # Invariant 2: Model shape stays consistent
        if "model" in prev.zones and "model" in snapshot.zones:
            prev_model = prev.zones["model"]
            curr_model = snapshot.zones["model"]
            if prev_model.colors == curr_model.colors:
                inv = "model_shape_constant"
                if inv not in self.invariants:
                    self.invariants.append(inv)

        # Invariant 3: Figure shape stays consistent
        if "figure" in prev.zones and "figure" in snapshot.zones:
            prev_fig = prev.zones["figure"]
            curr_fig = snapshot.zones["figure"]
            if prev_fig.colors == curr_fig.colors:
                inv = "figure_shape_constant"
                if inv not in self.invariants:
                    self.invariants.append(inv)

        # Invariant 4: Check if key fits figure (shapes match)
        if "model" in snapshot.zones and "figure" in snapshot.zones:
            model = snapshot.zones["model"]
            figure = snapshot.zones["figure"]
            # Compare color distributions (normalized)
            if model.colors and figure.colors:
                m_norm = {k: v for k, v in sorted(model.colors.items())}
                f_norm = {k: v for k, v in sorted(figure.colors.items())}
                if m_norm == f_norm:
                    inv = "key_fits_figure"
                    if inv not in self.invariants:
                        self.invariants.append(inv)

    def get_life_history(self) -> list[int | None]:
        """Return life values over time."""
        return [s.life_value for s in self.history]

    def get_player_history(self) -> list[tuple[int, int] | None]:
        """Return player positions over time."""
        return [s.player_pos for s in self.history]

    def to_prompt_fragment(self) -> str:
        """Generate prompt fragment describing current zones."""
        if not self.history:
            return "No zone data yet."

        latest = self.history[-1]
        parts = [f"Zones detected (step {latest.step}):"]

        for name, zone in latest.zones.items():
            parts.append(f"  {name}: rows {zone.row_start}-{zone.row_end}, "
                        f"cols {zone.col_start}-{zone.col_end}, "
                        f"center={zone.center}")

        if latest.life_value is not None:
            parts.append(f"  Life: {latest.life_value}")

        if latest.player_pos:
            parts.append(f"  Player: {latest.player_pos}")

        if self.invariants:
            parts.append(f"Invariants: {', '.join(self.invariants)}")

        return "\n".join(parts)

    def to_dict(self) -> dict:
        """Serialize detector state."""
        return {
            "game_id": self.game_id,
            "history_len": len(self.history),
            "invariants": self.invariants,
            "latest": {
                "step": self.history[-1].step if self.history else 0,
                "zones": {n: z.to_dict() for n, z in self.history[-1].zones.items()}
                if self.history else {},
                "life": self.history[-1].life_value if self.history else None,
                "player": self.history[-1].player_pos if self.history else None,
            },
        }
