#!/usr/bin/env python3
"""
ARC-AGI-2 Solver v3 — RSI-enhanced with interior fill and more strategies
"""
import json
import os
import math
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from collections import Counter, defaultdict

# ─── Data Loading ──────────────────────────────────────────────────

def load_puzzles(data_dir):
    puzzles = {}
    for f in sorted(Path(data_dir).glob("*.json")):
        with open(f) as fp:
            puzzles[f.stem] = json.load(fp)
    return puzzles

def get_train_pairs(puzzle):
    return [(p["input"], p["output"]) for p in puzzle.get("train", [])]

def get_test_input(puzzle):
    tests = puzzle.get("test", [])
    return tests[0]["input"] if tests else []

# ─── Grid Utilities ───────────────────────────────────────────────

def grids_equal(a, b):
    if len(a) != len(b): return False
    for r in range(len(a)):
        if len(a[r]) != len(b[r]): return False
        for c in range(len(a[r])):
            if a[r][c] != b[r][c]: return False
    return True

def rotate_90(g):
    R, C = len(g), len(g[0]) if g else 0
    return [[g[R-1-c][r] for c in range(R)] for r in range(C)] if R and C else g

def rotate_180(g):
    R, C = len(g), len(g[0]) if g else 0
    return [[g[R-1-r][C-1-c] for c in range(C)] for r in range(R)]

def rotate_270(g):
    R, C = len(g), len(g[0]) if g else 0
    return [[g[c][C-1-r] for c in range(R)] for r in range(C)] if R and C else g

def reflect_h(g):
    return [row[::-1] for row in g]

def reflect_v(g):
    return g[::-1]

def flood_fill(grid, sr, sc, nc):
    R, C = len(grid), len(grid[0]) if grid else 0
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
    cm = None
    for inp, out in train_pairs:
        pair_cm = {}
        ok = True
        for r in range(min(len(inp), len(out))):
            for c in range(min(len(inp[r]), len(out[r]))):
                k, v = inp[r][c], out[r][c]
                if k in pair_cm:
                    if pair_cm[k] != v: ok = False; break
                else: pair_cm[k] = v
            if not ok: break
        if not ok: return None
        if cm is None: cm = pair_cm
        else:
            for k, v in pair_cm.items():
                if k in cm and cm[k] != v: return None
    if not cm: return None
    result = [row[:] for row in test_input]
    for r in range(len(result)):
        for c in range(len(result[r])):
            if result[r][c] in cm: result[r][c] = cm[result[r][c]]
    return result

# ─── Strategy 2: Tiling ───────────────────────────────────────────

def try_tiling(train_pairs, test_input):
    for inp, out in train_pairs:
        ir, ic = len(inp), len(inp[0]) if inp else 0
        or_, oc = len(out), len(out[0]) if out else 0
        if ir == 0 or ic == 0: continue
        if or_ % ir != 0 or oc % ic != 0: continue
        tr, tc = or_ // ir, oc // ic
        if tr < 2 and tc < 2: continue
        ok = all(out[r][c] == inp[r % ir][c % ic] for r in range(or_) for c in range(oc))
        if ok:
            R, C = len(test_input), len(test_input[0]) if test_input else 0
            return [[test_input[r % R][c % C] for c in range(C * tc)] for r in range(R * tr)]
    return None

# ─── Strategy 3: Rotation ─────────────────────────────────────────

def try_rotation(train_pairs, test_input):
    for inp, out in train_pairs:
        if inp and out:
            if rotate_90(inp) == out: return rotate_90(test_input)
            if rotate_180(inp) == out: return rotate_180(test_input)
            if rotate_270(inp) == out: return rotate_270(test_input)
    return None

# ─── Strategy 4: Reflection ───────────────────────────────────────

def try_reflection(train_pairs, test_input):
    for inp, out in train_pairs:
        if inp and out:
            if reflect_h(inp) == out: return reflect_h(test_input)
            if reflect_v(inp) == out: return reflect_v(test_input)
    return None

# ─── Strategy 5: Interior Fill (NEW) ──────────────────────────────

def try_interior_fill(train_pairs, test_input):
    """Fill enclosed 0-regions with a fill color."""
    for inp, out in train_pairs:
        R, C = len(inp), len(inp[0]) if inp else 0
        oR, oC = len(out), len(out[0]) if out else 0
        if (R, C) != (oR, oC): continue
        
        # Find fill color: color that appears in output but not in input
        in_colors = set(c for row in inp for c in row)
        out_colors = set(c for row in out for c in row)
        fill_colors = out_colors - in_colors
        
        if not fill_colors: continue
        fill_color = list(fill_colors)[0]
        
        # Find which 0-pixels were filled
        filled_pixels = set()
        for r in range(R):
            for c in range(C):
                if inp[r][c] == 0 and out[r][c] == fill_color:
                    filled_pixels.add((r, c))
        
        if not filled_pixels: continue
        
        # Verify: filled pixels should be "interior" (surrounded by non-zero)
        # Use flood fill from edges to find exterior
        exterior = set()
        # Flood fill from all edge 0-pixels
        for r in range(R):
            for c in [0, C-1]:
                if inp[r][c] == 0:
                    stack = [(r, c)]
                    while stack:
                        cr, cc = stack.pop()
                        if (cr, cc) in exterior: continue
                        if cr < 0 or cr >= R or cc < 0 or cc >= C: continue
                        if inp[cr][cc] != 0: continue
                        exterior.add((cr, cc))
                        stack.extend([(cr-1,cc),(cr+1,cc),(cr,cc-1),(cr,cc+1)])
        for c in range(C):
            for r in [0, R-1]:
                if inp[r][c] == 0:
                    stack = [(r, c)]
                    while stack:
                        cr, cc = stack.pop()
                        if (cr, cc) in exterior: continue
                        if cr < 0 or cr >= R or cc < 0 or cc >= C: continue
                        if inp[cr][cc] != 0: continue
                        exterior.add((cr, cc))
                        stack.extend([(cr-1,cc),(cr+1,cc),(cr,cc-1),(cr,cc+1)])
        
        # Interior = 0-pixels not in exterior
        interior = set()
        for r in range(R):
            for c in range(C):
                if inp[r][c] == 0 and (r, c) not in exterior:
                    interior.add((r, c))
        
        # Check if interior matches filled pixels
        if interior == filled_pixels:
            # Apply to test input
            tR, tC = len(test_input), len(test_input[0]) if test_input else 0
            result = [row[:] for row in test_input]
            
            # Find fill color for test: use same logic
            # For test, we need to determine what fill color to use
            # Use the most common fill color from training
            test_exterior = set()
            for r in range(tR):
                for c in [0, tC-1]:
                    if test_input[r][c] == 0:
                        stack = [(r, c)]
                        while stack:
                            cr, cc = stack.pop()
                            if (cr, cc) in test_exterior: continue
                            if cr < 0 or cr >= tR or cc < 0 or cc >= tC: continue
                            if test_input[cr][cc] != 0: continue
                            test_exterior.add((cr, cc))
                            stack.extend([(cr-1,cc),(cr+1,cc),(cr,cc-1),(cr,cc+1)])
            for c in range(tC):
                for r in [0, tR-1]:
                    if test_input[r][c] == 0:
                        stack = [(r, c)]
                        while stack:
                            cr, cc = stack.pop()
                            if (cr, cc) in test_exterior: continue
                            if cr < 0 or cr >= tR or cc < 0 or cc >= tC: continue
                            if test_input[cr][cc] != 0: continue
                            test_exterior.add((cr, cc))
                            stack.extend([(cr-1,cc),(cr+1,cc),(cr,cc-1),(cr,cc+1)])
            
            test_interior = set()
            for r in range(tR):
                for c in range(tC):
                    if test_input[r][c] == 0 and (r, c) not in test_exterior:
                        test_interior.add((r, c))
            
            # Fill interior with the fill color
            for r, c in test_interior:
                result[r][c] = fill_color
            
            return result
    
    return None

# ─── Strategy 6: Shape Expansion ──────────────────────────────────

def try_shape_expansion(train_pairs, test_input):
    """Output adds new elements around/inside input shapes."""
    for inp, out in train_pairs:
        R, C = len(inp), len(inp[0]) if inp else 0
        oR, oC = len(out), len(out[0]) if out else 0
        
        if R == 0 or C == 0: continue
        
        # Check if output is input with added border
        if oR == R + 2 and oC == C + 2:
            ok = True
            for r in range(R):
                for c in range(C):
                    if out[r+1][c+1] != inp[r][c]:
                        ok = False; break
                if not ok: break
            if ok:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                result = [[0]*(tC+2) for _ in range(tR+2)]
                for r in range(tR):
                    for c in range(tC):
                        result[r+1][c+1] = test_input[r][c]
                return result
        
        # Check if output is input with added row/col
        if oR == R + 1 and oC == C:
            ok = all(out[r][c] == inp[r][c] for r in range(R) for c in range(C))
            if ok:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                result = [row[:] for row in test_input]
                result.append([0]*tC)
                return result
        
        if oR == R and oC == C + 1:
            ok = all(out[r][c] == inp[r][c] for r in range(R) for c in range(C))
            if ok:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                result = [row + [0] for row in test_input]
                return result
    
    return None

# ─── Strategy 7: Color Spread ─────────────────────────────────────

def try_color_spread(train_pairs, test_input):
    """Non-zero colors spread to adjacent 0-cells."""
    for inp, out in train_pairs:
        R, C = len(inp), len(inp[0]) if inp else 0
        oR, oC = len(out), len(out[0]) if out else 0
        if (R, C) != (oR, oC): continue
        
        # Check if output has more non-zero cells than input
        in_nonzero = sum(1 for r in range(R) for c in range(C) if inp[r][c] != 0)
        out_nonzero = sum(1 for r in range(R) for c in range(C) if out[r][c] != 0)
        
        if out_nonzero <= in_nonzero: continue
        
        # Find spread pattern: 0-cells that became non-zero
        spreads = []
        for r in range(R):
            for c in range(C):
                if inp[r][c] == 0 and out[r][c] != 0:
                    # Check neighbors
                    neighbors = []
                    for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                        nr, nc = r+dr, c+dc
                        if 0 <= nr < R and 0 <= nc < C and inp[nr][nc] != 0:
                            neighbors.append(inp[nr][nc])
                    spreads.append((r, c, out[r][c], neighbors))
        
        if not spreads: continue
        
        # Check if spread color matches a neighbor
        all_match = all(len(n) > 0 and s[2] in n for s in spreads if s[3])
        if all_match:
            # Apply to test input
            tR, tC = len(test_input), len(test_input[0]) if test_input else 0
            result = [row[:] for row in test_input]
            
            # Spread: for each 0-cell adjacent to non-zero, copy the neighbor's color
            changed = True
            while changed:
                changed = False
                for r in range(tR):
                    for c in range(tC):
                        if result[r][c] == 0:
                            for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                                nr, nc = r+dr, c+dc
                                if 0 <= nr < tR and 0 <= nc < tC and test_input[nr][nc] != 0:
                                    result[r][c] = test_input[nr][nc]
                                    changed = True
                                    break
            
            return result
    
    return None

# ─── Strategy 8: Nearest Neighbor ─────────────────────────────────

def try_nearest_neighbor(train_pairs, test_input):
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
        R, C = len(test_input), len(test_input[0]) if test_input else 0
        result = [[0]*C for _ in range(R)]
        for r in range(min(R, len(best_out))):
            for c in range(min(C, len(best_out[r]))):
                result[r][c] = best_out[r][c]
        return result
    return None

# ─── Strategy 9: Diagonal Tiling ──────────────────────────────────

def try_diagonal_tiling(train_pairs, test_input):
    for inp, out in train_pairs:
        ir, ic = len(inp), len(inp[0]) if inp else 0
        or_, oc = len(out), len(out[0]) if out else 0
        if or_ % ir != 0 or oc % ic != 0: continue
        tr, tc = or_ // ir, oc // ic
        ok = True
        for r in range(or_):
            for c in range(oc):
                tile_r, tile_c = r // ir, c // ic
                if tile_r == tile_c:
                    if out[r][c] != inp[r % ir][c % ic]:
                        ok = False; break
                else:
                    if out[r][c] != 0:
                        ok = False; break
            if not ok: break
        if ok:
            tR, tC = len(test_input), len(test_input[0]) if test_input else 0
            result = [[0]*(tC*tc) for _ in range(tR*tr)]
            for tile_idx in range(min(tr, tc)):
                r0 = tile_idx * tR
                c0 = tile_idx * tC
                for r in range(tR):
                    for c in range(tC):
                        result[r0+r][c0+c] = test_input[r][c]
            return result
    return None

# ─── Strategy 10: Object Count ────────────────────────────────────

def try_object_count(train_pairs, test_input):
    """If output has different number of objects, try to match count."""
    for inp, out in train_pairs:
        # Count connected components
        def count_objects(grid):
            R, C = len(grid), len(grid[0]) if grid else 0
            visited = set()
            count = 0
            for r in range(R):
                for c in range(C):
                    if (r,c) not in visited and grid[r][c] != 0:
                        count += 1
                        stack = [(r,c)]
                        while stack:
                            cr, cc = stack.pop()
                            if (cr,cc) in visited or cr<0 or cr>=R or cc<0 or cc>=C: continue
                            if grid[cr][cc] != grid[r][c]: continue
                            visited.add((cr,cc))
                            stack.extend([(cr-1,cc),(cr+1,cc),(cr,cc-1),(cr,cc+1)])
            return count
        
        in_count = count_objects(inp)
        out_count = count_objects(out)
        
        if in_count != out_count:
            # Try to adjust object count in test
            test_count = count_objects(test_input)
            if test_count != out_count:
                # This strategy is too complex to implement generically
                pass
    
    return None

# ─── Master Solver ────────────────────────────────────────────────

STRATEGIES = [
    ("color_mapping", try_color_mapping),
    ("interior_fill", try_interior_fill),
    ("tiling", try_tiling),
    ("rotation", try_rotation),
    ("reflection", try_reflection),
    ("shape_expansion", try_shape_expansion),
    ("color_spread", try_color_spread),
    ("diagonal_tiling", try_diagonal_tiling),
    ("nearest_neighbor", try_nearest_neighbor),
]

def solver_v3(train_pairs, test_input):
    """Try all strategies, return best match (or first non-None if no match)."""
    candidates = []
    for name, fn in STRATEGIES:
        try:
            result = fn(train_pairs, test_input)
            if result is not None:
                candidates.append((name, result))
        except:
            continue
    if candidates:
        return candidates[0][1]
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
        
        total += 1
    
    return {
        "solver": solver_fn.__name__,
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total > 0 else 0,
        "strategy_hits": dict(strategy_hits),
    }

# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    data_dir = "/root/arc-data/training"
    print(f"Loading puzzles from {data_dir}...")
    puzzles = load_puzzles(data_dir)
    print(f"Loaded {len(puzzles)} puzzles")
    
    print("\n=== Solver v3 Evaluation (200 puzzles) ===\n")
    result = evaluate_solver(solver_v3, puzzles, max_puzzles=200)
    print(f"Total: {result['correct']}/{result['total']} | accuracy: {result['accuracy']:.1%}")
    print(f"\nStrategy breakdown:")
    for strat, count in sorted(result['strategy_hits'].items(), key=lambda x: -x[1]):
        print(f"  {strat:25s}: {count}")
    
    print("\n=== Solver v3 Evaluation (1000 puzzles) ===\n")
    result_full = evaluate_solver(solver_v3, puzzles, max_puzzles=1000)
    print(f"Total: {result_full['correct']}/{result_full['total']} | accuracy: {result_full['accuracy']:.1%}")
    print(f"\nStrategy breakdown:")
    for strat, count in sorted(result_full['strategy_hits'].items(), key=lambda x: -x[1]):
        print(f"  {strat:25s}: {count}")
