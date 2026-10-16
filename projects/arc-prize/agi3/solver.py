#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-2 Solver — VSF Agent
Loads puzzles, runs solvers, evaluates accuracy.
"""
import json
import os
import random
import copy
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

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


# ─── Solvers ───────────────────────────────────────────────────────

def solver_random(train_pairs, test_input) -> List[List[int]]:
    """Baseline: random grid of same shape."""
    rows = len(test_input)
    cols = len(test_input[0]) if rows > 0 else 0
    return [[random.randint(0, 4) for _ in range(cols)] for _ in range(rows)]


def solver_identity(train_pairs, test_input) -> List[List[int]]:
    """Trivial: output = input (works if transformation is identity)."""
    return [row[:] for row in test_input]


def solver_copy_bottom(train_pairs, test_input) -> List[List[int]]:
    """If train shows bottom row appears in output, try to replicate."""
    # Look at first train pair
    if not train_pairs:
        return solver_identity(train_pairs, test_input)
    
    inp, out = train_pairs[0]
    # Simple heuristic: if output has same shape, try to find a mapping
    rows = len(test_input)
    cols = len(test_input[0]) if rows > 0 else 0
    
    # Check if any row in input appears in output
    result = [row[:] for row in test_input]
    
    # Try color mapping from first train pair
    color_map = {}
    for r in range(len(inp)):
        for c in range(len(inp[r])):
            if r < len(out) and c < len(out[r]):
                in_val = inp[r][c]
                out_val = out[r][c]
                if in_val not in color_map:
                    color_map[in_val] = out_val
    
    # Apply mapping
    for r in range(rows):
        for c in range(cols):
            if test_input[r][c] in color_map:
                result[r][c] = color_map[test_input[r][c]]
    
    return result


def solver_find_pattern(train_pairs, test_input) -> List[List[int]]:
    """Smart solver: analyze patterns in train pairs and apply to test."""
    if not train_pairs:
        return solver_identity(train_pairs, test_input)
    
    result = [row[:] for row in test_input]
    rows = len(test_input)
    cols = len(test_input[0]) if rows > 0 else 0
    
    # Strategy 1: Color mapping (most common pattern)
    color_map = {}
    color_counts = {}
    for inp, out in train_pairs:
        for r in range(min(len(inp), len(out))):
            for c in range(min(len(inp[r]), len(out[r]))):
                key = (inp[r][c], out[r][c])
                color_counts[key] = color_counts.get(key, 0) + 1
    
    # Build mapping from most frequent transitions
    for (in_val, out_val), count in sorted(color_counts.items(), key=lambda x: -x[1]):
        if in_val not in color_map:
            color_map[in_val] = out_val
    
    # Apply mapping
    for r in range(rows):
        for c in range(cols):
            if test_input[r][c] in color_map:
                result[r][c] = color_map[test_input[r][c]]
    
    # Strategy 2: Position-based (if specific positions always change)
    pos_map = {}
    for inp, out in train_pairs:
        for r in range(min(len(inp), len(out))):
            for c in range(min(len(inp[r]), len(out[r]))):
                if inp[r][c] != out[r][c]:
                    key = (r, c, inp[r][c])
                    pos_map[key] = out[r][c]
    
    # Apply position mapping if we have enough data
    if len(train_pairs) >= 2:
        for r in range(rows):
            for c in range(cols):
                key = (r, c, test_input[r][c])
                if key in pos_map:
                    result[r][c] = pos_map[key]
    
    return result


def solver_nearest_neighbor(train_pairs, test_input) -> List[List[int]]:
    """Find most similar train input, use its output as template."""
    if not train_pairs:
        return solver_identity(train_pairs, test_input)
    
    # Calculate similarity between test input and each train input
    best_sim = -1
    best_out = None
    
    for inp, out in train_pairs:
        # Simple similarity: count matching cells
        sim = 0
        min_r = min(len(inp), len(test_input))
        min_c = min(len(inp[0]) if inp else 0, len(test_input[0]) if test_input else 0)
        for r in range(min_r):
            for c in range(min_c):
                if inp[r][c] == test_input[r][c]:
                    sim += 1
        if sim > best_sim:
            best_sim = sim
            best_out = out
    
    if best_out:
        # Adapt output to test input shape
        rows = len(test_input)
        cols = len(test_input[0]) if rows > 0 else 0
        result = [[0]*cols for _ in range(rows)]
        
        for r in range(min(rows, len(best_out))):
            for c in range(min(cols, len(best_out[r]))):
                result[r][c] = best_out[r][c]
        
        return result
    
    return solver_identity(train_pairs, test_input)


# ─── Evaluation ────────────────────────────────────────────────────

def evaluate_solver(solver_fn, puzzles: Dict, max_puzzles: int = 100) -> Dict:
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
            
            if predicted == expected:
                correct += 1
            else:
                errors.append({
                    "task_id": task_id,
                    "input_shape": (len(test_input), len(test_input[0]) if test_input else 0),
                    "output_shape": (len(expected), len(expected[0]) if expected else 0),
                    "predicted_shape": (len(predicted), len(predicted[0]) if predicted else 0),
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
        solver_random,
        solver_identity,
        solver_copy_bottom,
        solver_find_pattern,
        solver_nearest_neighbor,
    ]
    
    print("\n=== Evaluation Results ===\n")
    for solver in solvers:
        result = evaluate_solver(solver, puzzles, max_puzzles=200)
        print(f"{result['solver']:30s} | {result['correct']}/{result['total']} | accuracy: {result['accuracy']:.1%}")
        if result['sample_errors']:
            print(f"  Sample error: task {result['sample_errors'][0].get('task_id', '?')}")
        print()
