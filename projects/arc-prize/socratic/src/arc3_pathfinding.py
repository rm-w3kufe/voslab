# design: projects/arc-prize/arc_prize_design.vsm
"""
arc3_pathfinding.py — Pathfinding for ARC-AGI-3 Agent

BFS-based pathfinding to navigate the game grid.
Identifies walkable cells, calculates shortest paths, verifies budget.
"""

from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class PathResult:
    """Result of pathfinding."""
    found: bool
    path: list[tuple[int, int]]
    distance: int
    directions: list[str]  # ACTION1=up, ACTION2=down, ACTION3=left, ACTION4=right
    cost: int  # life cost (distance * 2)


# Direction deltas: up, down, left, right
DIRECTIONS = {
    "ACTION1": (-1, 0),  # up
    "ACTION2": (1, 0),   # down
    "ACTION3": (0, -1),  # left
    "ACTION4": (0, 1),   # right
}

OPPOSITE = {
    "ACTION1": "ACTION2",
    "ACTION2": "ACTION1",
    "ACTION3": "ACTION4",
    "ACTION4": "ACTION3",
}


def get_direction(from_pos: tuple[int, int], to_pos: tuple[int, int]) -> str:
    """Get the action to move from one position to adjacent position."""
    dr = to_pos[0] - from_pos[0]
    dc = to_pos[1] - from_pos[1]
    
    if dr == -1:
        return "ACTION1"  # up
    elif dr == 1:
        return "ACTION2"  # down
    elif dc == -1:
        return "ACTION3"  # left
    elif dc == 1:
        return "ACTION4"  # right
    return "ACTION1"  # default


def identify_walkable(grid: list[list[int]], zones: dict) -> set[tuple[int, int]]:
    """
    Identify walkable cells on the grid.
    
    In ARC games:
    - Color 0 (black) = background, walkable
    - Color 4 (yellow) = walls, NOT walkable (solid barriers)
    - Color 3 (green) = figure/lock area, walkable (destination)
    - Colors 5,9 (gray,brown) = model/key area, walkable
    - Colors 8,11 (azure,cyan) = life bar, NOT walkable
    - Colors 12,9 (rose,brown) = player sprite, walkable
    - Other colors = walkable (floor)
    """
    if not grid or not isinstance(grid[0], list):
        return set()
    
    h, w = len(grid), len(grid[0])
    walkable = set()
    
    for r in range(h):
        for c in range(w):
            try:
                v = int(grid[r][c])
                # Yellow (4) = walls, NOT walkable
                if v == 4:
                    continue
                # Life bar (8,11) in rows 60-62 = NOT walkable
                if v in (8, 11) and 60 <= r <= 62:
                    continue
                # Everything else is walkable
                walkable.add((r, c))
            except:
                walkable.add((r, c))
    
    return walkable


def bfs(grid: list[list[int]], start: tuple[int, int], goal: tuple[int, int],
        walkable: Optional[set[tuple[int, int]]] = None) -> PathResult:
    """
    BFS shortest path from start to goal.
    
    Returns PathResult with path, distance, and directions.
    """
    if walkable is None:
        walkable = identify_walkable(grid, {})
    
    if start not in walkable or goal not in walkable:
        return PathResult(found=False, path=[], distance=0, directions=[], cost=0)
    
    if start == goal:
        return PathResult(found=True, path=[start], distance=0, directions=[], cost=0)
    
    h, w = len(grid), len(grid[0])
    visited = {start}
    queue = deque([(start, [start])])
    
    while queue:
        current, path = queue.popleft()
        
        for action, (dr, dc) in DIRECTIONS.items():
            nr, nc = current[0] + dr, current[1] + dc
            next_pos = (nr, nc)
            
            if (0 <= nr < h and 0 <= nc < w and 
                next_pos in walkable and next_pos not in visited):
                
                new_path = path + [next_pos]
                
                if next_pos == goal:
                    # Build directions
                    directions = []
                    for i in range(len(new_path) - 1):
                        directions.append(get_direction(new_path[i], new_path[i + 1]))
                    return PathResult(
                        found=True,
                        path=new_path,
                        distance=len(new_path) - 1,
                        directions=directions,
                        cost=(len(new_path) - 1) * 2,
                    )
                
                visited.add(next_pos)
                queue.append((next_pos, new_path))
    
    return PathResult(found=False, path=[], distance=0, directions=[], cost=0)


def find_nearest(grid: list[list[int]], start: tuple[int, int],
                 targets: set[tuple[int, int]], walkable: Optional[set[tuple[int, int]]] = None) -> PathResult:
    """Find nearest target from start."""
    if walkable is None:
        walkable = identify_walkable(grid, {})
    
    if not targets:
        return PathResult(found=False, path=[], distance=0, directions=[], cost=0)
    
    # BFS from start, stop at first target found
    if start not in walkable:
        return PathResult(found=False, path=[], distance=0, directions=[], cost=0)
    
    h, w = len(grid), len(grid[0])
    visited = {start}
    queue = deque([(start, [start])])
    
    while queue:
        current, path = queue.popleft()
        
        for action, (dr, dc) in DIRECTIONS.items():
            nr, nc = current[0] + dr, current[1] + dc
            next_pos = (nr, nc)
            
            if (0 <= nr < h and 0 <= nc < w and 
                next_pos in walkable and next_pos not in visited):
                
                new_path = path + [next_pos]
                
                if next_pos in targets:
                    directions = []
                    for i in range(len(new_path) - 1):
                        directions.append(get_direction(new_path[i], new_path[i + 1]))
                    return PathResult(
                        found=True,
                        path=new_path,
                        distance=len(new_path) - 1,
                        directions=directions,
                        cost=(len(new_path) - 1) * 2,
                    )
                
                visited.add(next_pos)
                queue.append((next_pos, new_path))
    
    return PathResult(found=False, path=[], distance=0, directions=[], cost=0)


def get_zone_cells(zone: dict) -> set[tuple[int, int]]:
    """Convert zone dict to set of cells."""
    rows = zone.get("rows", "0-0")
    cols = zone.get("cols", "0-0")
    
    row_start, row_end = map(int, rows.split("-"))
    col_start, col_end = map(int, cols.split("-"))
    
    cells = set()
    for r in range(row_start, row_end + 1):
        for c in range(col_start, col_end + 1):
            cells.add((r, c))
    
    return cells


def plan_route(grid: list[list[int]], player_pos: tuple[int, int],
               checkpoint_zone: Optional[dict] = None,
               figure_zone: Optional[dict] = None,
               life_value: int = 0) -> dict:
    """
    Plan route from player to checkpoint to figure.
    
    Returns:
        {
            "checkpoint_path": PathResult,
            "figure_path": PathResult,
            "total_distance": int,
            "total_cost": int,
            "budget_ok": bool,
            "next_action": str or None,
            "objective": str,
        }
    """
    walkable = identify_walkable(grid, {})
    
    result = {
        "checkpoint_path": None,
        "figure_path": None,
        "total_distance": 0,
        "total_cost": 0,
        "budget_ok": False,
        "next_action": None,
        "objective": "explore",
    }
    
    # Find path to checkpoint
    if checkpoint_zone:
        checkpoint_cells = get_zone_cells(checkpoint_zone)
        cp_path = find_nearest(grid, player_pos, checkpoint_cells, walkable)
        result["checkpoint_path"] = cp_path
        
        if cp_path.found:
            # Find path from checkpoint to figure
            if figure_zone:
                figure_cells = get_zone_cells(figure_zone)
                # Start from center of checkpoint
                cp_center = checkpoint_zone.get("center", (0, 0))
                if isinstance(cp_center, str):
                    cp_center = tuple(map(int, cp_center.split(",")))
                fig_path = find_nearest(grid, cp_center, figure_cells, walkable)
                result["figure_path"] = fig_path
                
                if fig_path.found:
                    result["total_distance"] = cp_path.distance + fig_path.distance
                    result["total_cost"] = result["total_distance"] * 2
                    result["budget_ok"] = life_value >= result["total_cost"]
    
    # Determine objective and next action
    if result["checkpoint_path"] and result["checkpoint_path"].found:
        result["objective"] = "go_to_checkpoint"
        result["next_action"] = result["checkpoint_path"].directions[0] if result["checkpoint_path"].directions else None
    elif result["figure_path"] and result["figure_path"].found:
        result["objective"] = "go_to_figure"
        result["next_action"] = result["figure_path"].directions[0] if result["figure_path"].directions else None
    
    return result


def to_prompt_fragment(route: dict) -> str:
    """Generate prompt fragment from route plan."""
    parts = []
    
    if route["next_action"]:
        parts.append(f"Pathfinding: {route['objective']}")
        parts.append(f"Next action: {route['next_action']}")
        
        if route["checkpoint_path"]:
            parts.append(f"Distance to checkpoint: {route['checkpoint_path'].distance}")
        
        if route["figure_path"]:
            parts.append(f"Distance to figure: {route['figure_path'].distance}")
        
        parts.append(f"Total cost: {route['total_cost']} life")
        parts.append(f"Budget OK: {route['budget_ok']}")
    else:
        parts.append("Pathfinding: no path found")
    
    return "\n".join(parts)
