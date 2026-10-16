#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-2 Smart Solver — VSF Agent
Multi-strategy solver with pattern detection.
"""
import json
import os
import random
import copy
import math
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any, Callable
from collections import Counter, defaultdict

# ─── Data Loading ──────────────────────────────────────────────────

def load_puzzles(data_dir: str) -> Dict[str, Any]:
    """Load all puzzles from a directory of JSON files."""
    puzzles = {}
    data_path = Path(data_dir)
    for f in sorted(data_path.glob("*.json")):
        task_id = f.stem
        with open(f) as fp:
            puzzles[task_id] = json.load(fp)
    return puzzles


def get_train_pairs(puzzle: Dict) -> List[Tuple[List[List[int]], List[List[int]]]]:
    """Extract train input→output pairs."""
    return [(p["input"], p["output"]) for p in puzzle.get("train", [])]


def get_test_input(puzzle: Dict) -> List[List[int]]:
    """Extract test input (what we need to solve)."""
    tests = puzzle.get("test", [])
    if tests:
        return tests[0]["input"]
    return []


# ─── Grid Utilities ───────────────────────────────────────────────

def grid_shape(grid: List[List[int]]) -> Tuple[int, int]:
    """Get (rows, cols) of a grid."""
    if not grid or not grid[0]:
        return (0, 0)
    return (len(grid), len(grid[0]))


def grids_equal(a: List[List[int]], b: List[List[int]]) -> bool:
    """Check if two grids are equal."""
    if len(a) != len(b):
        return False
    for r in range(len(a)):
        if len(a[r]) != len(b[r]):
            return False
        for c in range(len(a[r])):
            if a[r][c] != b[r][c]:
                return False
    return True


def rotate_90(grid: List[List[int]]) -> List[List[int]]:
    """Rotate grid 90° clockwise."""
    rows, cols = grid_shape(grid)
    result = [[0] * rows for _ in range(cols)]
    for r in range(rows):
        for c in range(cols):
            result[c][rows - 1 - r] = grid[r][c]
    return result


def rotate_180(grid: List[List[int]]) -> List[List[int]]:
    """Rotate grid 180°."""
    rows, cols = grid_shape(grid)
    result = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            result[rows - 1 - r][cols - 1 - c] = grid[r][c]
    return result


def rotate_270(grid: List[List[int]]) -> List[List[int]]:
    """Rotate grid 270° clockwise."""
    rows, cols = grid_shape(grid)
    result = [[0] * rows for _ in range(cols)]
    for r in range(rows):
        for c in range(cols):
            result[cols - 1 - c][r] = grid[r][c]
    return result


def reflect_h(grid: List[List[int]]) -> List[List[int]]:
    """Reflect horizontally (flip left-right)."""
    return [row[::-1] for row in grid]


def reflect_v(grid: List[List[int]]) -> List[List[int]]:
    """Reflect vertically (flip up-down)."""
    return grid[::-1]


def reflect_d1(grid: List[List[int]]) -> List[List[int]]:
    """Reflect across main diagonal (transpose)."""
    rows, cols = grid_shape(grid)
    result = [[0] * rows for _ in range(cols)]
    for r in range(rows):
        for c in range(cols):
            result[c][r] = grid[r][c]
    return result


def reflect_d2(grid: List[List[int]]) -> List[List[int]]:
    """Reflect across anti-diagonal."""
    rows, cols = grid_shape(grid)
    result = [[0] * rows for _ in range(cols)]
    for r in range(rows):
        for c in range(cols):
            result[cols - 1 - c][rows - 1 - r] = grid[r][c]
    return result


def flood_fill(grid: List[List[int]], start_r: int, start_c: int, new_color: int) -> List[List[int]]:
    """Flood fill from (start_r, start_c) with new_color."""
    rows, cols = grid_shape(grid)
    result = [row[:] for row in grid]
    old_color = result[start_r][start_c]
    if old_color == new_color:
        return result
    
    stack = [(start_r, start_c)]
    visited = set()
    while stack:
        r, c = stack.pop()
        if (r, c) in visited:
            continue
        if r < 0 or r >= rows or c < 0 or c >= cols:
            continue
        if result[r][c] != old_color:
            continue
        visited.add((r, c))
        result[r][c] = new_color
        stack.extend([(r-1, c), (r+1, c), (r, c-1), (r, c+1)])
    
    return result


# ─── Strategy Detection ────────────────────────────────────────────

def detect_color_mapping(train_pairs: List[Tuple]) -> Optional[Dict[int, int]]:
    """Detect if there's a consistent color mapping across all train pairs."""
    color_maps = []
    
    for inp, out in train_pairs:
        cm = {}
        valid = True
        for r in range(min(len(inp), len(out))):
            for c in range(min(len(inp[r]), len(out[r]))):
                k = inp[r][c]
                v = out[r][c]
                if k in cm:
                    if cm[k] != v:
                        valid = False
                        break
                else:
                    cm[k] = v
            if not valid:
                break
        if valid:
            color_maps.append(cm)
        else:
            return None
    
    if not color_maps:
        return None
    
    # Check all mappings are consistent
    base = color_maps[0]
    for cm in color_maps[1:]:
        for k, v in cm.items():
            if k in base and base[k] != v:
                return None
    
    return base


def detect_rotation(train_pairs: List[Tuple]) -> Optional[str]:
    """Detect if output is a rotation of input."""
    for inp, out in train_pairs:
        if grids_equal(rotate_90(inp), out):
            return "90"
        if grids_equal(rotate_180(inp), out):
            return "180"
        if grids_equal(rotate_270(inp), out):
            return "270"
    return None


def detect_reflection(train_pairs: List[Tuple]) -> Optional[str]:
    """Detect if output is a reflection of input."""
    for inp, out in train_pairs:
        if grids_equal(reflect_h(inp), out):
            return "h"
        if grids_equal(reflect_v(inp), out):
            return "v"
        if grids_equal(reflect_d1(inp), out):
            return "d1"
        if grids_equal(reflect_d2(inp), out):
            return "d2"
    return None


def detect_tiling(train_pairs: List[Tuple]) -> Optional[Tuple[int, int]]:
    """Detect if output is a tiled version of input."""
    for inp, out in train_pairs:
        in_rows, in_cols = grid_shape(inp)
        out_rows, out_cols = grid_shape(out)
        
        if in_rows == 0 or in_cols == 0:
            continue
        
        if out_rows % in_rows == 0 and out_cols % in_cols == 0:
            tile_r = out_rows // in_rows
            tile_c = out_cols // in_cols
            
            if tile_r > 1 or tile_c > 1:
                # Verify tiling
                match = True
                for r in range(out_rows):
                    for c in range(out_cols):
                        if out[r][c] != inp[r % in_rows][c % in_cols]:
                            match = False
                            break
                    if not match:
                        break
                
                if match:
                    return (tile_r, tile_c)
    
    return None


def detect_flood_fill(train_pairs: List[Tuple]) -> Optional[Dict]:
    """Detect if output is a flood fill of input."""
    for inp, out in train_pairs:
        in_rows, in_cols = grid_shape(inp)
        out_rows, out_cols = grid_shape(out)
        
        if (in_rows, in_cols) != (out_rows, out_cols):
            continue
        
        # Find where color changed
        changes = []
        for r in range(in_rows):
            for c in range(in_cols):
                if inp[r][c] != out[r][c]:
                    changes.append((r, c, inp[r][c], out[r][c]))
        
        if len(changes) == 1:
            r, c, old, new = changes[0]
            # Verify it's a flood fill
            filled = flood_fill(inp, r, c, new)
            if grids_equal(filled, out):
                return {"start": (r, c), "new_color": new}
    
    return None


# ─── Smart Solver ──────────────────────────────────────────────────

def solver_smart(train_pairs: List[Tuple], test_input: List[List[int]]) -> List[List[int]]:
    """Smart solver that detects pattern and applies it."""
    if not train_pairs:
        return [row[:] for row in test_input]
    
    # Strategy 1: Color mapping
    cm = detect_color_mapping(train_pairs)
    if cm:
        result = [row[:] for row in test_input]
        for r in range(len(result)):
            for c in range(len(result[r])):
                if result[r][c] in cm:
                    result[r][c] = cm[result[r][c]]
        return result
    
    # Strategy 2: Rotation
    rot = detect_rotation(train_pairs)
    if rot:
        result = [row[:] for row in test_input]
        if rot == "90":
            result = rotate_90(result)
        elif rot == "180":
            result = rotate_180(result)
        elif rot == "270":
            result = rotate_270(result)
        return result
    
    # Strategy 3: Reflection
    ref = detect_reflection(train_pairs)
    if ref:
        result = [row[:] for row in test_input]
        if ref == "h":
            result = reflect_h(result)
        elif ref == "v":
            result = reflect_v(result)
        elif ref == "d1":
            result = reflect_d1(result)
        elif ref == "d2":
            result = reflect_d2(result)
        return result
    
    # Strategy 4: Tiling
    tile = detect_tiling(train_pairs)
    if tile:
        tile_r, tile_c = tile
        in_rows, in_cols = grid_shape(test_input)
        out_rows = in_rows * tile_r
        out_cols = in_cols * tile_c
        result = [[0] * out_cols for _ in range(out_rows)]
        for r in range(out_rows):
            for c in range(out_cols):
                result[r][c] = test_input[r % in_rows][c % in_cols]
        return result
    
    # Strategy 5: Flood fill
    ff = detect_flood_fill(train_pairs)
    if ff:
        result = flood_fill(test_input, ff["start"][0], ff["start"][1], ff["new_color"])
        return result
    
    # Strategy 6: Nearest neighbor with color mapping
    # Find most similar train input, get its color map, apply to test
    best_sim = -1
    best_cm = None
    for inp, out in train_pairs:
        sim = 0
        min_r = min(len(inp), len(test_input))
        min_c = min(len(inp[0]) if inp else 0, len(test_input[0]) if test_input else 0)
        for r in range(min_r):
            for c in range(min_c):
                if inp[r][c] == test_input[r][c]:
                    sim += 1
        if sim > best_sim:
            best_sim = sim
            # Build color map for this pair
            cm = {}
            for r in range(min(len(inp), len(out))):
                for c in range(min(len(inp[r]), len(out[r]))):
                    k = inp[r][c]
                    v = out[r][c]
                    if k not in cm:
                        cm[k] = v
            best_cm = cm
    
    if best_cm:
        result = [row[:] for row in test_input]
        for r in range(len(result)):
            for c in range(len(result[r])):
                if result[r][c] in best_cm:
                    result[r][c] = best_cm[result[r][c]]
        return result
    
    # Fallback: identity
    return [row[:] for row in test_input]


# ─── Evaluation ────────────────────────────────────────────────────

def evaluate_solver(solver_fn, puzzles: Dict, max_puzzles: int = 200) -> Dict:
    """Evaluate a solver on puzzles."""
    correct = 0
    total = 0
    errors = []
    
    task_ids = list(puzzles.keys())[:max_puzzles]
    
    for task_id in task_ids:
        puzzle = puzzles[task_id]
        train_pairs = get_train_pairs(puzzle)
        test_input = get_test_input(puzzle)
        
        if not test_input:
            continue
        
        expected = puzzle["test"][0]["output"]
        
        try:
            predicted = solver_fn(train_pairs, test_input)
            
            if grids_equal(predicted, expected):
                correct += 1
            else:
                errors.append({
                    "task_id": task_id,
                    "input_shape": grid_shape(test_input),
                    "output_shape": grid_shape(expected),
                    "predicted_shape": grid_shape(predicted),
                })
        except Exception as e:
            errors.append({"task_id": task_id, "error": str(e)})
        
        total += 1
    
    accuracy = correct / total if total > 0 else 0
    
    return {
        "solver": solver_fn.__name__,
        "correct": correct,
        "total": total,
        "accuracy": accuracy,
        "error_count": len(errors),
        "sample_errors": errors[:5],
    }


# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    data_dir = "/root/arc-data/training"
    print(f"Loading puzzles from {data_dir}...")
    puzzles = load_puzzles(data_dir)
    print(f"Loaded {len(puzzles)} puzzles")
    
    solvers = [
        solver_smart,
    ]
    
    print("\n=== Smart Solver Evaluation ===\n")
    for solver in solvers:
        result = evaluate_solver(solver, puzzles, max_puzzles=200)
        print(f"{result['solver']:30s} | {result['correct']}/{result['total']} | accuracy: {result['accuracy']:.1%}")
        if result['sample_errors']:
            print(f"  Sample error: task {result['sample_errors'][0].get('task_id', '?')}")
        print()
