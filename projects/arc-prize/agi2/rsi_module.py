#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
ARC-AGI-2 RSI Module — Recursive Self-Improvement for ARC Solvers
Analyzes failures, generates hypotheses, implements new strategies.
"""
import json
import os
import math
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Callable
from collections import Counter, defaultdict

# ─── RSI Core ──────────────────────────────────────────────────────

class ARC_RSI:
    """Compressed RSI cycle for ARC puzzle solving."""
    
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.puzzles = self._load_puzzles()
        self.failures = []
        self.strategies = []
        self.solved = []
        self.hypotheses = []
    
    def _load_puzzles(self) -> Dict:
        puzzles = {}
        for f in sorted(Path(self.data_dir).glob("*.json")):
            with open(f) as fp:
                puzzles[f.stem] = json.load(fp)
        return puzzles
    
    # ─── OBSERVE: Analyze failures ────────────────────────────────
    
    def observe(self, solver_fn, max_puzzles=200):
        """Run solver, collect failures, categorize."""
        self.failures = []
        self.solved = []
        
        task_ids = list(self.puzzles.keys())[:max_puzzles]
        
        for task_id in task_ids:
            puzzle = self.puzzles[task_id]
            trains = [(p["input"], p["output"]) for p in puzzle.get("train", [])]
            tests = puzzle.get("test", [])
            if not tests: continue
            
            test_input = tests[0]["input"]
            expected = tests[0]["output"]
            
            try:
                result = solver_fn(trains, test_input)
                if result == expected:
                    self.solved.append(task_id)
                    continue
            except:
                pass
            
            # Analyze failure
            failure = self._analyze_failure(task_id, trains, test_input, expected)
            self.failures.append(failure)
        
        return {
            "solved": len(self.solved),
            "failed": len(self.failures),
            "total": len(task_ids),
        }
    
    def _analyze_failure(self, task_id, trains, test_input, expected):
        """Deep analysis of why a puzzle failed."""
        analysis = {"task_id": task_id}
        
        # Shape analysis
        in_shapes = [(len(p[0]), len(p[0][0]) if p[0] else 0) for p in trains]
        out_shapes = [(len(p[1]), len(p[1][0]) if p[1] else 0) for p in trains]
        test_shape = (len(test_input), len(test_input[0]) if test_input else 0)
        expected_shape = (len(expected), len(expected[0]) if expected else 0)
        
        analysis["input_shapes"] = in_shapes
        analysis["output_shapes"] = out_shapes
        analysis["test_shape"] = test_shape
        analysis["expected_shape"] = expected_shape
        analysis["shape_change"] = in_shapes != out_shapes
        
        # Scale factor
        if in_shapes and out_shapes:
            avg_in_area = sum(r*c for r,c in in_shapes) / len(in_shapes)
            avg_out_area = sum(r*c for r,c in out_shapes) / len(out_shapes)
            analysis["scale_factor"] = avg_out_area / avg_in_area if avg_in_area > 0 else 1
        
        # Color analysis
        all_colors = set()
        for inp, out in trains:
            all_colors.update(c for row in inp for c in row)
            all_colors.update(c for row in out for c in row)
        analysis["n_colors"] = len(all_colors)
        
        # Color map consistency
        cm = self._find_color_map(trains)
        analysis["consistent_color_map"] = cm is not None
        if cm:
            analysis["color_map"] = cm
        
        # Spatial pattern detection
        analysis["has_symmetry"] = self._detect_symmetry(trains)
        analysis["has_progression"] = self._detect_progression(trains)
        analysis["has_object_movement"] = self._detect_object_movement(trains)
        
        return analysis
    
    def _find_color_map(self, trains):
        """Find consistent color mapping."""
        cm = None
        for inp, out in trains:
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
        return cm
    
    def _detect_symmetry(self, trains):
        """Detect if output has symmetry patterns."""
        for inp, out in trains:
            R, C = len(out), len(out[0]) if out else 0
            if R == 0 or C == 0: continue
            
            # Check horizontal symmetry
            h_sym = all(out[r] == out[R-1-r] for r in range(R//2))
            # Check vertical symmetry
            v_sym = all(out[r][c] == out[r][C-1-c] for r in range(R) for c in range(C//2))
            
            if h_sym or v_sym:
                return {"horizontal": h_sym, "vertical": v_sym}
        return None
    
    def _detect_progression(self, trains):
        """Detect if there's a progression pattern (e.g., color changes incrementally)."""
        if len(trains) < 2: return None
        
        # Check if color counts change progressively
        color_counts = []
        for inp, out in trains:
            cc = Counter(c for row in out for c in row)
            color_counts.append(cc)
        
        # Check if any color count changes linearly
        for color in set(c for cc in color_counts for c in cc):
            counts = [cc.get(color, 0) for cc in color_counts]
            if len(counts) >= 2:
                diffs = [counts[i+1] - counts[i] for i in range(len(counts)-1)]
                if len(set(diffs)) == 1:  # constant difference
                    return {"color": color, "counts": counts, "diff": diffs[0]}
        return None
    
    def _detect_object_movement(self, trains):
        """Detect if objects (connected components) move between input and output."""
        for inp, out in trains[:1]:  # Check first pair
            # Find connected components in input
            in_objects = self._find_objects(inp)
            out_objects = self._find_objects(out)
            
            if len(in_objects) > 0 and len(out_objects) > 0:
                # Check if object count changes
                if len(in_objects) != len(out_objects):
                    return {"in_count": len(in_objects), "out_count": len(out_objects)}
        return None
    
    def _find_objects(self, grid):
        """Find connected components (objects) in a grid."""
        R, C = len(grid), len(grid[0]) if grid else 0
        visited = set()
        objects = []
        
        for r in range(R):
            for c in range(C):
                if (r,c) not in visited and grid[r][c] != 0:
                    # BFS
                    obj = []
                    stack = [(r,c)]
                    while stack:
                        cr, cc = stack.pop()
                        if (cr,cc) in visited or cr<0 or cr>=R or cc<0 or cc>=C:
                            continue
                        if grid[cr][cc] != grid[r][c]:
                            continue
                        visited.add((cr,cc))
                        obj.append((cr,cc))
                        stack.extend([(cr-1,cc),(cr+1,cc),(cr,cc-1),(cr,cc+1)])
                    objects.append(obj)
        
        return objects
    
    # ─── ORIENT: Generate hypotheses ──────────────────────────────
    
    def orient(self):
        """Analyze failure patterns, generate strategy hypotheses."""
        self.hypotheses = []
        
        # Pattern 1: Shape changes with scaling
        shape_changes = [f for f in self.failures if f.get("shape_change")]
        if shape_changes:
            scales = [f.get("scale_factor", 1) for f in shape_changes]
            avg_scale = sum(scales) / len(scales)
            self.hypotheses.append({
                "type": "scaling",
                "description": f"Average scale factor: {avg_scale:.1f}x",
                "count": len(shape_changes),
                "strategy": "adaptive_tiling",
            })
        
        # Pattern 2: Symmetry in output
        symmetries = [f for f in self.failures if f.get("has_symmetry")]
        if symmetries:
            self.hypotheses.append({
                "type": "symmetry",
                "description": f"{len(symmetries)} puzzles have symmetry in output",
                "count": len(symmetries),
                "strategy": "symmetry_generation",
            })
        
        # Pattern 3: Progression patterns
        progressions = [f for f in self.failures if f.get("has_progression")]
        if progressions:
            self.hypotheses.append({
                "type": "progression",
                "description": f"{len(progressions)} puzzles have progression patterns",
                "count": len(progressions),
                "strategy": "progression_solver",
            })
        
        # Pattern 4: Object movement
        movements = [f for f in self.failures if f.get("has_object_movement")]
        if movements:
            self.hypotheses.append({
                "type": "movement",
                "description": f"{len(movements)} puzzles have object count changes",
                "count": len(movements),
                "strategy": "object_manipulation",
            })
        
        # Pattern 5: Many colors, no shape change
        complex_same_shape = [f for f in self.failures 
                             if not f.get("shape_change") and f.get("n_colors", 0) >= 6]
        if complex_same_shape:
            self.hypotheses.append({
                "type": "complex_mapping",
                "description": f"{len(complex_same_shape)} puzzles with many colors, same shape",
                "count": len(complex_same_shape),
                "strategy": "context_aware_color_map",
            })
        
        return self.hypotheses
    
    # ─── DECIDE: Select strategies to implement ───────────────────
    
    def decide(self):
        """Prioritize hypotheses by potential impact."""
        # Sort by count (most common pattern first)
        self.hypotheses.sort(key=lambda h: -h.get("count", 0))
        return self.hypotheses
    
    # ─── REPORT ───────────────────────────────────────────────────
    
    def report(self):
        """Generate RSI report."""
        return {
            "observed": {
                "solved": len(self.solved),
                "failed": len(self.failures),
            },
            "hypotheses": self.hypotheses,
            "top_strategies": [h["strategy"] for h in self.hypotheses[:3]],
        }


# ─── New Strategies from RSI ──────────────────────────────────────

def try_adaptive_tiling(train_pairs, test_input):
    """Tiling that adapts based on scale factor."""
    for inp, out in train_pairs:
        ir, ic = len(inp), len(inp[0]) if inp else 0
        or_, oc = len(out), len(out[0]) if out else 0
        if ir == 0 or ic == 0: continue
        if or_ % ir != 0 or oc % ic != 0: continue
        tr, tc = or_ // ir, oc // ic
        
        # Try multiple tiling patterns
        # 1. Simple repeat
        ok = all(out[r][c] == inp[r % ir][c % ic] for r in range(or_) for c in range(oc))
        if ok:
            R, C = len(test_input), len(test_input[0]) if test_input else 0
            return [[test_input[r % R][c % C] for c in range(C * tc)] for r in range(R * tr)]
        
        # 2. Alternating flip (checkerboard)
        for flip_axis in ['row', 'col', 'both']:
            ok = True
            for r in range(or_):
                for c in range(oc):
                    sr, sc = r % ir, c % ic
                    tr_i, tc_i = r // ir, c // ic
                    if flip_axis in ['row', 'both'] and tr_i % 2 == 1:
                        sr = ir - 1 - sr
                    if flip_axis in ['col', 'both'] and tc_i % 2 == 1:
                        sc = ic - 1 - sc
                    if out[r][c] != inp[sr][sc]:
                        ok = False; break
                if not ok: break
            if ok:
                R, C = len(test_input), len(test_input[0]) if test_input else 0
                result = [[0]*(C*tc) for _ in range(R*tr)]
                for r in range(R*tr):
                    for c in range(C*tc):
                        sr, sc = r % R, c % C
                        tr_i, tc_i = r // R, c // C
                        if flip_axis in ['row', 'both'] and tr_i % 2 == 1:
                            sr = R - 1 - sr
                        if flip_axis in ['col', 'both'] and tc_i % 2 == 1:
                            sc = C - 1 - sc
                        result[r][c] = test_input[sr][sc]
                return result
        
        # 3. Rotation tiling
        rotations = [lambda g: g, 
                     lambda g: [list(reversed(row)) for row in g],  # flip_h
                     lambda g: list(reversed(g)),  # flip_v
                     lambda g: list(zip(*reversed(g)))]  # rotate_90 approx
        for rot_fn in rotations:
            try:
                rotated = rot_fn(inp)
                if len(rotated) != ir or (rotated and len(rotated[0]) != ic):
                    continue
                ok = all(out[r][c] == rotated[r % ir][c % ic] for r in range(or_) for c in range(oc))
                if ok:
                    R, C = len(test_input), len(test_input[0]) if test_input else 0
                    rot_test = rot_fn(test_input)
                    return [[rot_test[r % R][c % C] for c in range(C * tc)] for r in range(R * tr)]
            except:
                continue
    
    return None


def try_symmetry_generation(train_pairs, test_input):
    """Generate symmetric output from input."""
    for inp, out in train_pairs:
        R, C = len(out), len(out[0]) if out else 0
        iR, iC = len(inp), len(inp[0]) if inp else 0
        
        if iR == 0 or iC == 0: continue
        
        # Check if output is input reflected horizontally
        if R == iR and C == iC * 2:
            ok = all(out[r][c] == inp[r][c % iC] for r in range(R) for c in range(C))
            if ok:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                return [[test_input[r][c % tC] for c in range(tC * 2)] for r in range(tR)]
        
        # Check if output is input reflected vertically
        if R == iR * 2 and C == iC:
            ok = all(out[r][c] == inp[r % iR][c] for r in range(R) for c in range(C))
            if ok:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                return [[test_input[r % tR][c] for c in range(tC)] for r in range(tR * 2)]
        
        # Check if output is 4-way symmetry
        if R == iR * 2 and C == iC * 2:
            ok = True
            for r in range(R):
                for c in range(C):
                    sr, sc = r % iR, c % iC
                    if r >= iR: sr = iR - 1 - sr
                    if c >= iC: sc = iC - 1 - sc
                    if out[r][c] != inp[sr][sc]:
                        ok = False; break
                if not ok: break
            if ok:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                result = [[0]*(tC*2) for _ in range(tR*2)]
                for r in range(tR*2):
                    for c in range(tC*2):
                        sr, sc = r % tR, c % tC
                        if r >= tR: sr = tR - 1 - sr
                        if c >= tC: sc = tC - 1 - sc
                        result[r][c] = test_input[sr][sc]
                return result
    
    return None


def try_context_aware_color_map(train_pairs, test_input):
    """Color mapping that considers spatial context."""
    if len(train_pairs) < 2: return None
    
    # Build position-dependent color map
    R, C = len(test_input), len(test_input[0]) if test_input else 0
    
    # For each position, collect all input→output mappings
    pos_maps = defaultdict(lambda: defaultdict(int))
    for inp, out in train_pairs:
        for r in range(min(len(inp), len(out))):
            for c in range(min(len(inp[r]), len(out[r]))):
                key = (inp[r][c], r, c)
                pos_maps[(r,c)][inp[r][c]] = out[r][c]
    
    # Apply: for each position, use the most common mapping
    result = [row[:] for row in test_input]
    for r in range(R):
        for c in range(C):
            if (r,c) in pos_maps and test_input[r][c] in pos_maps[(r,c)]:
                result[r][c] = pos_maps[(r,c)][test_input[r][c]]
    
    return result


def try_shape_change_solver(train_pairs, test_input):
    """Handle puzzles where output is a different shape than input."""
    for inp, out in train_pairs:
        ir, ic = len(inp), len(inp[0]) if inp else 0
        or_, oc = len(out), len(out[0]) if out else 0
        
        if ir == 0 or ic == 0: continue
        
        # Case 1: Output is taller (add rows)
        if or_ > ir and oc == ic:
            # Find what rows are added
            row_pattern = []
            for r in range(or_):
                src_r = r % ir
                if out[r] == inp[src_r]:
                    row_pattern.append("same")
                elif r > 0 and out[r] == out[r-1]:
                    row_pattern.append("repeat")
                else:
                    row_pattern.append("new")
            
            if "repeat" in row_pattern or "same" in row_pattern:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                result = []
                for r in range(or_):
                    src_r = r % tR
                    result.append(test_input[src_r][:])
                return result
        
        # Case 2: Output is wider (add columns)
        if or_ == ir and oc > ic:
            col_pattern = []
            for c in range(oc):
                src_c = c % ic
                col_match = all(out[r][c] == inp[r][src_c] for r in range(ir))
                if col_match:
                    col_pattern.append("same")
                else:
                    col_pattern.append("new")
            
            if "same" in col_pattern:
                tR, tC = len(test_input), len(test_input[0]) if test_input else 0
                result = []
                for r in range(or_):
                    src_r = r % tR
                    row = []
                    for c in range(oc):
                        src_c = c % tC
                        row.append(test_input[src_r][src_c])
                    result.append(row)
                return result
        
        # Case 3: Both taller and wider
        if or_ > ir and oc > ic:
            tR, tC = len(test_input), len(test_input[0]) if test_input else 0
            result = []
            for r in range(or_):
                src_r = r % tR
                row = []
                for c in range(oc):
                    src_c = c % tC
                    row.append(test_input[src_r][src_c])
                result.append(row)
            return result
    
    return None


# ─── Combined Smart Solver with RSI ───────────────────────────────

def solver_rsi(train_pairs, test_input):
    """Solver enhanced with RSI-generated strategies."""
    strategies = [
        # Original strategies
        ("color_mapping", _try_color_mapping),
        ("tiling", _try_tiling),
        ("rotation", _try_rotation),
        ("reflection", _try_reflection),
        ("flood_fill", _try_flood_fill),
        # RSI-generated strategies
        ("adaptive_tiling", try_adaptive_tiling),
        ("symmetry_generation", try_symmetry_generation),
        ("context_aware_color_map", try_context_aware_color_map),
        ("shape_change_solver", try_shape_change_solver),
    ]
    
    for name, fn in strategies:
        try:
            result = fn(train_pairs, test_input)
            if result is not None:
                return result
        except:
            continue
    
    return [row[:] for row in test_input]


# ─── Helper functions (copied from solver_smart_v2) ───────────────

def _try_color_mapping(train_pairs, test_input):
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
            if result[r][c] in cm:
                result[r][c] = cm[result[r][c]]
    return result

def _try_tiling(train_pairs, test_input):
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

def _try_rotation(train_pairs, test_input):
    def rot90(g):
        R, C = len(g), len(g[0]) if g else 0
        return [[g[R-1-c][r] for c in range(R)] for r in range(C)] if R and C else g
    def rot180(g):
        R, C = len(g), len(g[0]) if g else 0
        return [[g[R-1-r][C-1-c] for c in range(C)] for r in range(R)]
    def rot270(g):
        R, C = len(g), len(g[0]) if g else 0
        return [[g[c][C-1-r] for c in range(R)] for r in range(C)] if R and C else g
    
    for inp, out in train_pairs:
        if inp and out:
            if rot90(inp) == out: return rot90(test_input)
            if rot180(inp) == out: return rot180(test_input)
            if rot270(inp) == out: return rot270(test_input)
    return None

def _try_reflection(train_pairs, test_input):
    for inp, out in train_pairs:
        if inp and out:
            if [row[::-1] for row in inp] == out: return [row[::-1] for row in test_input]
            if inp[::-1] == out: return test_input[::-1]
    return None

def _try_flood_fill(train_pairs, test_input):
    def ff(grid, sr, sc, nc):
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
    
    for inp, out in train_pairs:
        R, C = len(inp), len(inp[0]) if inp else 0
        oR, oC = len(out), len(out[0]) if out else 0
        if (R, C) != (oR, oC): continue
        changes = [(r,c,inp[r][c],out[r][c]) for r in range(R) for c in range(C) if inp[r][c]!=out[r][c]]
        if len(changes) == 1:
            r, c, _, new = changes[0]
            if ff(inp, r, c, new) == out:
                return ff(test_input, r, c, new)
    return None


# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    data_dir = "/root/arc-data/training"
    
    print("=== ARC RSI Cycle ===\n")
    
    # Initialize RSI
    rsi = ARC_RSI(data_dir)
    
    # Import the solver for observation
    from solver_smart_v2 import solver_smart_v2
    
    # OBSERVE
    print("1. OBSERVE: Analyzing failures...")
    obs = rsi.observe(solver_smart_v2, max_puzzles=200)
    print(f"   Solved: {obs['solved']}, Failed: {obs['failed']}")
    
    # ORIENT
    print("\n2. ORIENT: Generating hypotheses...")
    hyps = rsi.orient()
    for h in hyps:
        print(f"   - {h['type']}: {h['description']}")
    
    # DECIDE
    print("\n3. DECIDE: Prioritizing strategies...")
    strategies = rsi.decide()
    for i, s in enumerate(strategies[:3]):
        print(f"   {i+1}. {s['strategy']} (impact: {s['count']} puzzles)")
    
    # Test RSI-enhanced solver
    print("\n4. ACT: Testing RSI-enhanced solver...")
    from solver_smart_v2 import load_puzzles, evaluate_solver
    
    puzzles = load_puzzles(data_dir)
    result = evaluate_solver(solver_rsi, puzzles, max_puzzles=200)
    print(f"   RSI Solver: {result['correct']}/{result['total']} | accuracy: {result['accuracy']:.1%}")
    
    # Compare with v2
    result_v2 = evaluate_solver(solver_smart_v2, puzzles, max_puzzles=200)
    print(f"   V2 Solver:  {result_v2['correct']}/{result_v2['total']} | accuracy: {result_v2['accuracy']:.1%}")
    
    improvement = result['accuracy'] - result_v2['accuracy']
    print(f"\n   Improvement: {improvement:+.1%}")
    
    # Save RSI report
    report = rsi.report()
    with open("/root/rsi_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\n   RSI report saved to /root/rsi_report.json")
