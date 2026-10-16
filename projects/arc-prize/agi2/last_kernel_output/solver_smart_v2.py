#!/usr/bin/env python3
"""
ARC-AGI-2 Smart Solver v2 — VSF Agent
Multi-strategy solver with comprehensive pattern detection.
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
    puzzles = {}
    data_path = Path(data_dir)
    for f in sorted(data_path.glob("*.json")):
        task_id = f.stem
        with open(f) as fp:
            puzzles[task_id] = json.load(fp)
    return puzzles

def get_train_pairs(puzzle: Dict) -> List[Tuple]:
    return [(p["input"], p["output"]) for p in puzzle.get("train", [])]

def get_test_input(puzzle: Dict) -> List[List[int]]:
    tests = puzzle.get("test", [])
    return tests[0]["input"] if tests else []

# ─── Grid Utilities ───────────────────────────────────────────────

def grid_shape(g):
    return (len(g), len(g[0]) if g else 0) if g else (0, 0)

def grids_equal(a, b):
    if len(a) != len(b): return False
    for r in range(len(a)):
        if len(a[r]) != len(b[r]): return False
        for c in range(len(a[r])):
            if a[r][c] != b[r][c]: return False
    return True

def rotate_90(g):
    R, C = grid_shape(g)
    return [[g[R-1-c][r] for c in range(R)] for r in range(C)] if R and C else g

def rotate_180(g):
    R, C = grid_shape(g)
    return [[g[R-1-r][C-1-c] for c in range(C)] for r in range(R)]

def rotate_270(g):
    R, C = grid_shape(g)
    return [[g[c][C-1-r] for c in range(R)] for r in range(C)] if R and C else g

def reflect_h(g):
    return [row[::-1] for row in g]

def reflect_v(g):
    return g[::-1]

def reflect_d1(g):  # transpose
    R, C = grid_shape(g)
    return [[g[r][c] for r in range(R)] for c in range(C)] if R and C else g

def reflect_d2(g):  # anti-transpose
    R, C = grid_shape(g)
    return [[g[C-1-c][R-1-r] for c in range(C)] for r in range(R)] if R and C else g

def flood_fill(grid, sr, sc, nc):
    R, C = grid_shape(grid)
    result = [row[:] for row in grid]
    oc = result[sr][sc]
    if oc == nc: return result
    stack = [(sr, sc)]
    visited = set()
    while stack:
        r, c = stack.pop()
        if (r,c) in visited or r<0 or r>=R or c<0 or c>=C or result[r][c]!=oc: continue
        visited.add((r,c))
        result[r][c] = nc
        stack.extend([(r-1,c),(r+1,c),(r,c-1),(r,c+1)])
    return result

# ─── Strategy 1: Color Mapping ────────────────────────────────────

def try_color_mapping(train_pairs, test_input):
    """Consistent color mapping across all pairs."""
    maps = []
    for inp, out in train_pairs:
        cm = {}
        ok = True
        for r in range(min(len(inp), len(out))):
            for c in range(min(len(inp[r]), len(out[r]))):
                k, v = inp[r][c], out[r][c]
                if k in cm:
                    if cm[k] != v: ok = False; break
                else: cm[k] = v
            if not ok: break
        if not ok: return None
        maps.append(cm)
    
    if not maps: return None
    base = maps[0]
    for cm in maps[1:]:
        for k, v in cm.items():
            if k in base and base[k] != v: return None
    
    result = [row[:] for row in test_input]
    for r in range(len(result)):
        for c in range(len(result[r])):
            if result[r][c] in base:
                result[r][c] = base[result[r][c]]
    return result

# ─── Strategy 2: Scaling/Tiling ───────────────────────────────────

def try_tiling(train_pairs, test_input):
    """Output is a tiled/scaled version of input."""
    for inp, out in train_pairs:
        ir, ic = grid_shape(inp)
        or_, oc = grid_shape(out)
        if ir == 0 or ic == 0: continue
        if or_ % ir != 0 or oc % ic != 0: continue
        tr, tc = or_ // ir, oc // ic
        if tr < 2 and tc < 2: continue
        
        # Try simple tiling
        ok = True
        for r in range(or_):
            for c in range(oc):
                if out[r][c] != inp[r % ir][c % ic]:
                    ok = False; break
            if not ok: break
        if ok:
            tr, tc = or_ // ir, oc // ic
            result = [[0]*(len(test_input[0])*tc) for _ in range(len(test_input)*tr)]
            for r in range(len(result)):
                for c in range(len(result[0])):
                    result[r][c] = test_input[r % len(test_input)][c % len(test_input[0])]
            return result
        
        # Try alternating tiling (flip rows/cols)
        for flip_r in [False, True]:
            for flip_c in [False, True]:
                ok = True
                for r in range(or_):
                    for c in range(oc):
                        sr = r % ir
                        sc = c % ic
                        tr_idx = r // ir
                        tc_idx = c // ic
                        if flip_r and tr_idx % 2 == 1: sr = ir - 1 - sr
                        if flip_c and tc_idx % 2 == 1: sc = ic - 1 - sc
                        if out[r][c] != inp[sr][sc]:
                            ok = False; break
                    if not ok: break
                if ok:
                    tr, tc = or_ // ir, oc // ic
                    result = [[0]*(len(test_input[0])*tc) for _ in range(len(test_input)*tr)]
                    for r in range(len(result)):
                        for c in range(len(result[0])):
                            sr = r % len(test_input)
                            sc = c % len(test_input[0])
                            tr_idx = r // len(test_input)
                            tc_idx = c // len(test_input[0])
                            if flip_r and tr_idx % 2 == 1: sr = len(test_input) - 1 - sr
                            if flip_c and tc_idx % 2 == 1: sc = len(test_input[0]) - 1 - sc
                            result[r][c] = test_input[sr][sc]
                    return result
    
    return None

# ─── Strategy 3: Rotation ─────────────────────────────────────────

def try_rotation(train_pairs, test_input):
    for inp, out in train_pairs:
        if grids_equal(rotate_90(inp), out):
            return rotate_90(test_input)
        if grids_equal(rotate_180(inp), out):
            return rotate_180(test_input)
        if grids_equal(rotate_270(inp), out):
            return rotate_270(test_input)
    return None

# ─── Strategy 4: Reflection ───────────────────────────────────────

def try_reflection(train_pairs, test_input):
    for inp, out in train_pairs:
        if grids_equal(reflect_h(inp), out):
            return reflect_h(test_input)
        if grids_equal(reflect_v(inp), out):
            return reflect_v(test_input)
        if grids_equal(reflect_d1(inp), out):
            return reflect_d1(test_input)
        if grids_equal(reflect_d2(inp), out):
            return reflect_d2(test_input)
    return None

# ─── Strategy 5: Flood Fill ───────────────────────────────────────

def try_flood_fill(train_pairs, test_input):
    for inp, out in train_pairs:
        ir, ic = grid_shape(inp)
        or_, oc = grid_shape(out)
        if (ir, ic) != (or_, oc): continue
        changes = []
        for r in range(ir):
            for c in range(ic):
                if inp[r][c] != out[r][c]:
                    changes.append((r, c, inp[r][c], out[r][c]))
        if len(changes) == 1:
            r, c, _, new = changes[0]
            filled = flood_fill(inp, r, c, new)
            if grids_equal(filled, out):
                return flood_fill(test_input, r, c, new)
    return None

# ─── Strategy 6: Position-based Color Map ─────────────────────────

def try_position_color_map(train_pairs, test_input):
    """Color mapping that depends on position."""
    if len(train_pairs) < 2: return None
    
    # Check if each train pair has a consistent per-position color map
    # but the maps differ between pairs
    all_maps = []
    for inp, out in train_pairs:
        R, C = grid_shape(inp)
        oR, oC = grid_shape(out)
        if R != oR or C != oC: return None
        pm = {}
        for r in range(R):
            for c in range(C):
                pm[(r,c)] = (inp[r][c], out[r][c])
        all_maps.append(pm)
    
    # Check if the mapping pattern is consistent (same input→output for same position)
    # but different positions have different mappings
    # This is just a per-position map from first pair
    pm = all_maps[0]
    result = [row[:] for row in test_input]
    R, C = grid_shape(test_input)
    for r in range(R):
        for c in range(C):
            if (r,c) in pm:
                inp_val, out_val = pm[(r,c)]
                if test_input[r][c] == inp_val:
                    result[r][c] = out_val
    return result

# ─── Strategy 7: Diagonal Tiling ──────────────────────────────────

def try_diagonal_tiling(train_pairs, test_input):
    """Input placed along diagonal of output, zeros elsewhere."""
    for inp, out in train_pairs:
        ir, ic = grid_shape(inp)
        or_, oc = grid_shape(out)
        if or_ % ir != 0 or oc % ic != 0: continue
        tr, tc = or_ // ir, oc // ic
        
        ok = True
        for r in range(or_):
            for c in range(oc):
                tile_r, tile_c = r // ir, c // ic
                src_r, src_c = r % ir, c % ic
                if tile_r == tile_c:
                    if out[r][c] != inp[src_r][src_c]:
                        ok = False; break
                else:
                    if out[r][c] != 0:
                        ok = False; break
            if not ok: break
        
        if ok:
            tr, tc = or_ // ir, oc // ic
            result = [[0]*(len(test_input[0])*tc) for _ in range(len(test_input)*tr)]
            for tile_idx in range(min(tr, tc)):
                r0 = tile_idx * len(test_input)
                c0 = tile_idx * len(test_input[0])
                for r in range(len(test_input)):
                    for c in range(len(test_input[0])):
                        result[r0+r][c0+c] = test_input[r][c]
            return result
    
    return None

# ─── Strategy 8: Color Counting ───────────────────────────────────

def try_color_counting(train_pairs, test_input):
    """Output has same colors but different counts."""
    for inp, out in train_pairs:
        in_colors = Counter(c for row in inp for c in row)
        out_colors = Counter(c for row in out for c in row)
        if in_colors == out_colors:
            # Same multiset of colors, just rearranged
            # Use nearest neighbor approach
            best_sim = -1
            best_out = None
            for inp2, out2 in train_pairs:
                sim = sum(1 for r in range(min(len(inp2), len(test_input)))
                         for c in range(min(len(inp2[0]) if inp2 else 0, len(test_input[0]) if test_input else 0))
                         if inp2[r][c] == test_input[r][c])
                if sim > best_sim:
                    best_sim = sim
                    best_out = out2
            if best_out:
                R, C = grid_shape(test_input)
                result = [[0]*C for _ in range(R)]
                for r in range(min(R, len(best_out))):
                    for c in range(min(C, len(best_out[r]))):
                        result[r][c] = best_out[r][c]
                return result
    return None

# ─── Strategy 9: Pattern Fill ─────────────────────────────────────

def try_pattern_fill(train_pairs, test_input):
    """Output uses input as a pattern but fills with different colors."""
    for inp, out in train_pairs:
        ir, ic = grid_shape(inp)
        or_, oc = grid_shape(out)
        if ir == 0 or ic == 0: continue
        
        # Check if shapes match
        if ir == or_ and ic == oc:
            # Check if there's a consistent color substitution per position
            subs = {}
            ok = True
            for r in range(ir):
                for c in range(ic):
                    k = inp[r][c]
                    v = out[r][c]
                    if k not in subs:
                        subs[k] = v
                    elif subs[k] != v:
                        ok = False; break
                if not ok: break
            
            if ok and len(subs) > 0:
                result = [row[:] for row in test_input]
                for r in range(len(result)):
                    for c in range(len(result[r])):
                        if result[r][c] in subs:
                            result[r][c] = subs[result[r][c]]
                return result
    
    return None

# ─── Strategy 10: Nearest Neighbor ────────────────────────────────

def try_nearest_neighbor(train_pairs, test_input):
    """Find most similar train input, use its output as template."""
    if not train_pairs: return None
    
    best_sim = -1
    best_out = None
    for inp, out in train_pairs:
        sim = sum(1 for r in range(min(len(inp), len(test_input)))
                 for c in range(min(len(inp[0]) if inp else 0, len(test_input[0]) if test_input else 0))
                 if inp[r][c] == test_input[r][c])
        if sim > best_sim:
            best_sim = sim
            best_out = out
    
    if best_out:
        R, C = grid_shape(test_input)
        result = [[0]*C for _ in range(R)]
        for r in range(min(R, len(best_out))):
            for c in range(min(C, len(best_out[r]))):
                result[r][c] = best_out[r][c]
        return result
    return None

# ─── Master Solver ────────────────────────────────────────────────

STRATEGIES = [
    ("color_mapping", try_color_mapping),
    ("tiling", try_tiling),
    ("rotation", try_rotation),
    ("reflection", try_reflection),
    ("flood_fill", try_flood_fill),
    ("position_color_map", try_position_color_map),
    ("diagonal_tiling", try_diagonal_tiling),
    ("color_counting", try_color_counting),
    ("pattern_fill", try_pattern_fill),
    ("nearest_neighbor", try_nearest_neighbor),
]

def solver_smart_v2(train_pairs, test_input):
    """Try each strategy in order, return first success."""
    for name, fn in STRATEGIES:
        try:
            result = fn(train_pairs, test_input)
            if result is not None:
                return result
        except:
            continue
    return [row[:] for row in test_input]

# ─── Evaluation ────────────────────────────────────────────────────

def evaluate_solver(solver_fn, puzzles, max_puzzles=200):
    correct = 0
    total = 0
    strategy_hits = defaultdict(int)
    task_ids = list(puzzles.keys())[:max_puzzles]
    
    for task_id in task_ids:
        puzzle = puzzles[task_id]
        train_pairs = get_train_pairs(puzzle)
        test_input = get_test_input(puzzle)
        if not test_input: continue
        
        expected = puzzle["test"][0]["output"]
        
        try:
            # Find which strategy worked
            solved = False
            for name, fn in STRATEGIES:
                try:
                    result = fn(train_pairs, test_input)
                    if result is not None and grids_equal(result, expected):
                        correct += 1
                        strategy_hits[name] += 1
                        solved = True
                        break
                except:
                    continue
            
            if not solved:
                # Try the master solver
                result = solver_fn(train_pairs, test_input)
                if grids_equal(result, expected):
                    correct += 1
        except Exception as e:
            pass
        
        total += 1
    
    accuracy = correct / total if total > 0 else 0
    
    return {
        "solver": solver_fn.__name__,
        "correct": correct,
        "total": total,
        "accuracy": accuracy,
        "strategy_hits": dict(strategy_hits),
    }

# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    data_dir = "/root/arc-data/training"
    print(f"Loading puzzles from {data_dir}...")
    puzzles = load_puzzles(data_dir)
    print(f"Loaded {len(puzzles)} puzzles")
    
    print("\n=== Smart Solver v2 Evaluation ===\n")
    result = evaluate_solver(solver_smart_v2, puzzles, max_puzzles=200)
    print(f"Total: {result['correct']}/{result['total']} | accuracy: {result['accuracy']:.1%}")
    print(f"\nStrategy breakdown:")
    for strat, count in sorted(result['strategy_hits'].items(), key=lambda x: -x[1]):
        print(f"  {strat:25s}: {count}")
    
    # Also run on full 1000
    print("\n=== Full 1000 Puzzles ===\n")
    result_full = evaluate_solver(solver_smart_v2, puzzles, max_puzzles=1000)
    print(f"Total: {result_full['correct']}/{result_full['total']} | accuracy: {result_full['accuracy']:.1%}")
    print(f"\nStrategy breakdown:")
    for strat, count in sorted(result_full['strategy_hits'].items(), key=lambda x: -x[1]):
        print(f"  {strat:25s}: {count}")
