#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Visor terminal ARC-AGI — rewrite v2 (2026-09-12).

Mejoras vs v1:
  - Auto-width: grids grandes se comprimen automáticamente
  - Indicador ✓/✗ de un vistazo
  - Stats por puzzle (n_colors, objects, shape mismatch)
  - Modo --compact para grids muy grandes
  - Side-by-side alineado incluso con shapes distintos
  - Color 0 visible (gris oscuro en vez de negro)
  - Resumen rápido antes de los grids

Uso:
  python3 arc-agi3/viewer.py fafffa47              # trains + test
  python3 arc-agi3/viewer.py --snap snap.json       # render una vez
  python3 arc-agi3/viewer.py --watch [snap]         # live polling
  python3 arc-agi3/viewer.py --compact fafffa47     # grids grandes
  python3 arc-agi3/viewer.py --solve fafffa47       # resolver + mostrar
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DEFAULT_SNAP = os.path.join(HERE, "state", "view_current.json")

# ─── Colors ────────────────────────────────────────────────────────
# ARC palette → ANSI 256. Color 0 = gris oscuro (no negro invisible).
ANSI_BG = {0: 238, 1: 21, 2: 196, 3: 46, 4: 226, 5: 244,
           6: 201, 7: 208, 8: 39, 9: 124}
# Extended colors (10+) for ARC-AGI-3
for i in range(10, 256):
    ANSI_BG[i] = i % 256  # passthrough para colores no mapeados

NAMES = {0: "bg", 1: "blue", 2: "red", 3: "green", 4: "yellow",
         5: "gray", 6: "magenta", 7: "orange", 8: "cyan", 9: "brown"}
RESET = "\x1b[0m"
CLEAR = "\x1b[2J\x1b[H"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
WHITE = "\x1b[37m"

def _term_width():
    """Try to get terminal width; default 120."""
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 120

# ─── Grid rendering ───────────────────────────────────────────────

def _cell(v, numbers=False, mark=False):
    """Single cell with optional digit overlay and diff mark."""
    bg = ANSI_BG.get(v, v % 256)
    if mark:
        return "\x1b[48;5;%dm\x1b[97m\xd7\xd7%s" % (bg, RESET)
    if numbers:
        fg = 16 if v in (3, 4, 5, 8) else 231
        return "\x1b[48;5;%dm\x1b[38;5;%dm%2d%s" % (bg, fg, v, RESET)
    return "\x1b[48;5;%dm  %s" % (bg, RESET)

def _cell_compact(v, marks=None, r=0, c=0):
    """Single char cell for compact mode."""
    if marks and (r, c) in marks:
        return "\x1b[91m×%s" % RESET
    if v == 0:
        return "\x1b[38;5;238m·%s" % RESET
    return "\x1b[48;5;%dm %s" % (ANSI_BG.get(v, v % 256), RESET)

def render_grid(g, numbers=False, marks=None, compact=False):
    """Render grid. compact=True for single-char cells."""
    if not g:
        return "(empty)"
    marks = marks or set()
    if compact:
        return "\n".join(
            "".join(_cell_compact(v, marks, r, c)
                    for c, v in enumerate(row))
            for r, row in enumerate(g))
    return "\n".join(
        "".join(_cell(v, numbers, (r, c) in marks)
                for c, v in enumerate(row))
        for r, row in enumerate(g))

def _dims(g):
    return "%dx%d" % (len(g), len(g[0]) if g else 0)

def diff_marks(a, b):
    """Cells where a differs from b."""
    if a is None or b is None:
        return set()
    if len(a) != len(b) or any(len(r1) != len(r2)
                               for r1, r2 in zip(a, b)):
        return {(r, c) for r in range(len(a))
                for c in range(len(a[r]))}
    return {(r, c) for r in range(len(a)) for c in range(len(a[r]))
            if a[r][c] != b[r][c]}

# ─── Grid analysis ────────────────────────────────────────────────

def _grid_stats(g):
    """Quick stats about a grid."""
    if not g:
        return {"h": 0, "w": 0, "colors": 0, "non_bg": 0, "objects": 0}
    h, w = len(g), len(g[0])
    bg = 0
    colors = set()
    non_bg = 0
    for row in g:
        for v in row:
            colors.add(v)
            if v != bg:
                non_bg += 1
    # Simple connected-component count
    visited = set()
    objs = 0
    for r in range(h):
        for c in range(w):
            if g[r][c] != bg and (r, c) not in visited:
                objs += 1
                # BFS
                stack = [(r, c)]
                while stack:
                    cr, cc = stack.pop()
                    if (cr, cc) in visited:
                        continue
                    if 0 <= cr < h and 0 <= cc < w and g[cr][cc] == g[r][c]:
                        visited.add((cr, cc))
                        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                            stack.append((cr+dr, cc+dc))
    return {"h": h, "w": w, "colors": len(colors), "non_bg": non_bg,
            "objects": objs}

# ─── Side-by-side rendering ──────────────────────────────────────

def render_pair(inp, out, numbers=False, label_in="IN", label_out="OUT",
                compact=False):
    """Side-by-side with aligned rows."""
    li = render_grid(inp, numbers, compact=compact).split("\n")
    lo = render_grid(out, numbers, compact=compact).split("\n")
    head = "%s %s  →  %s %s" % (label_in, _dims(inp), label_out, _dims(out))
    n = max(len(li), len(lo))
    li += [""] * (n - len(li))
    lo += [""] * (n - len(lo))
    return "\n".join([head] + ["%s   %s" % (a, b) for a, b in zip(li, lo)])

# ─── Summary line ─────────────────────────────────────────────────

def _summary_line(snap, numbers=False):
    """One-line summary: puzzle ID, dims, pass/fail."""
    title = snap.get("title", "?")
    parts = [BOLD + title + RESET]

    trains = snap.get("trains", [])
    if trains:
        parts.append("%d trains" % len(trains))

    test_in = snap.get("test_in")
    pred = snap.get("pred")
    expected = snap.get("expected")

    if test_in:
        parts.append("test: %s" % _dims(test_in))

    if pred is not None and expected is not None:
        marks = diff_marks(pred, expected)
        n_diff = len(marks)
        total = len(expected) * len(expected[0]) if expected else 0
        if n_diff == 0:
            parts.append(GREEN + "✓ CORRECT" + RESET)
        else:
            parts.append(RED + "✗ %d/%d differ" % (n_diff, total) + RESET)

        # Quick stats
        ps = _grid_stats(pred)
        es = _grid_stats(expected)
        if ps["h"] != es["h"] or ps["w"] != es["w"]:
            parts.append(YELLOW + "shape mismatch %s→%s" %
                         (_dims(pred), _dims(expected)) + RESET)
        parts.append("pred: %d colors, %d obj" % (ps["colors"], ps["objects"]))
    elif pred is not None:
        parts.append("pred: %s" % _dims(pred))

    note = snap.get("note", "")
    if note:
        parts.append(DIM + note + RESET)

    return " │ ".join(parts)

# ─── Full snapshot rendering ─────────────────────────────────────

def render_snapshot(snap, numbers=False, compact=False):
    """Full snapshot with summary, trains, test, diff."""
    parts = []
    title = snap.get("title", "snapshot")

    # Header
    parts.append("=" * 60)
    parts.append(_summary_line(snap, numbers))
    parts.append("=" * 60)

    # Trains
    for i, tr in enumerate(snap.get("trains", [])):
        parts.append("")
        parts.append(BOLD + "[train%d]" % i + RESET)
        inp, out = tr["in"], tr["out"]
        # Auto-decide compact mode for large grids
        use_compact = compact or max(len(inp), len(inp[0]) if inp else 0,
                                     len(out), len(out[0]) if out else 0) > 20
        parts.append(render_pair(inp, out, numbers, compact=use_compact))

    # Test
    if snap.get("test_in") is not None:
        parts.append("")
        parts.append(BOLD + "[test]" + RESET)
        test_in = snap["test_in"]
        pred = snap.get("pred") or test_in
        expected = snap.get("expected")

        use_compact = compact or max(
            len(test_in), len(test_in[0]) if test_in else 0,
            len(pred), len(pred[0]) if pred else 0) > 20

        parts.append(render_pair(test_in, pred, numbers,
                                 label_in="IN ", label_out="PRED",
                                 compact=use_compact))

        if expected is not None:
            marks = diff_marks(pred, expected)
            n_diff = len(marks)
            total = len(expected) * len(expected[0]) if expected else 0

            if n_diff == 0:
                parts.append(GREEN + "  ✓ PRED == EXPECTED (%s)" %
                             _dims(expected) + RESET)
            else:
                parts.append(RED + "  ✗ %d/%d cells differ" %
                             (n_diff, total) + RESET)

            if _dims(pred) != _dims(expected):
                parts.append(YELLOW + "  ⚠ SHAPE MISMATCH: pred=%s expected=%s" %
                             (_dims(pred), _dims(expected)) + RESET)

            use_compact2 = compact or max(
                len(expected), len(expected[0]) if expected else 0) > 20
            parts.append(render_grid(expected, numbers, marks,
                                     compact=use_compact2))
    elif snap.get("expected") is not None:
        # Expected without pred — just show it
        parts.append("")
        parts.append(BOLD + "[expected only]" + RESET)
        parts.append(render_grid(snap["expected"], numbers))

    # Timestamp
    if snap.get("ts"):
        parts.append("")
        parts.append(DIM + "snapshot: %s" % snap["ts"] + RESET)

    # Agent trace (if present)
    trace = snap.get("trace")
    if trace:
        parts.append("")
        parts.append(BOLD + "[trace]" + RESET)
        if isinstance(trace, dict):
            for k, v in trace.items():
                parts.append("  %s: %s" % (k, v))
        elif isinstance(trace, str):
            parts.append("  " + trace)

    return "\n".join(parts)

# ─── API para probes ──────────────────────────────────────────────
def push(title, trains=None, test_in=None, pred=None, expected=None,
         note="", trace=None, path=DEFAULT_SNAP):
    """Escribe snapshot atomico (tmp+rename) para que --watch lo tome."""
    snap = {"title": title, "note": note,
            "trains": [{"in": i, "out": o} for i, o in (trains or [])],
            "test_in": test_in, "pred": pred, "expected": expected,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if trace:
        snap["trace"] = trace
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f)
    os.replace(tmp, path)
    return path

def push_puzzle(pid, pred=None, note="", trains_dir="data/training",
                path=DEFAULT_SNAP):
    """Atajo: snapshot de un puzzle del training + pred opcional."""
    import solver_smart_v2 as v2
    base = os.path.dirname(path)
    root = HERE if os.path.isabs(trains_dir) else os.getcwd()
    p = v2.load_puzzles(os.path.join(root, trains_dir))[pid]
    t = v2.get_train_pairs(p)
    return push(pid if not note else "%s - %s" % (pid, note),
                trains=t, test_in=v2.get_test_input(p), pred=pred,
                expected=p["test"][0]["output"], note=note, path=path)

def push_solve(pid, trains_dir="data/training", path=DEFAULT_SNAP):
    """Solve a puzzle and push the result with trace."""
    import solver_smart_v2 as v2
    import solver_v3 as v3
    import recognizer as R
    root = HERE if os.path.isabs(trains_dir) else os.getcwd()
    p = v2.load_puzzles(os.path.join(root, trains_dir))[pid]
    trains = v2.get_train_pairs(p)
    test_in = v2.get_test_input(p)
    expected = p["test"][0]["output"]

    t0 = time.time()
    pred, trace = _solve_with_trace(pid, trains, test_in, expected)
    elapsed = time.time() - t0

    correct = False
    if pred is not None:
        try:
            correct = v3.grids_equal(pred, expected)
        except Exception:
            pass

    trace["elapsed_ms"] = "%d" % (elapsed * 1000)
    trace["correct"] = correct

    return push(pid, trains=trains, test_in=test_in, pred=pred,
                expected=expected, note=trace.get("strategy", ""),
                trace=trace, path=path)

def _solve_with_trace(pid, trains, test_in, expected):
    """Solve with strategy trace."""
    import recognizer as R
    import solver_v3 as v3
    import solver_smart_v2 as v2

    trace = {"pid": pid, "trains": len(trains)}

    # Try each dynamic
    for name, det, fns, family in R.DYNAMICS:
        try:
            if not det(trains):
                continue
        except Exception:
            continue

        trace["detected"] = name
        trace["family"] = family

        fns_r = R.composed_fns_for(trains) if fns is None else fns
        if not fns_r:
            continue

        for i, fn in enumerate(fns_r):
            try:
                pred = R.safe_apply(fn, trains, test_in)
                if pred is not None:
                    correct = v3.grids_equal(pred, expected)
                    trace["strategy"] = "%s.fn%d" % (name, i)
                    trace["fn"] = fn.__name__
                    if correct:
                        return pred, trace
            except Exception as e:
                trace["error_%s_%d" % (name, i)] = str(e)[:100]

    # Fallbacks
    for fname, fn in R.FALLBACK:
        try:
            pred = R.safe_apply(fn, trains, test_in)
            if pred is not None:
                correct = v3.grids_equal(pred, expected)
                trace["strategy"] = "fallback.%s" % fname
                trace["fn"] = fn.__name__
                if correct:
                    return pred, trace
        except Exception:
            pass

    trace["strategy"] = "none"
    return None, trace

# ─── Watch mode ───────────────────────────────────────────────────

def watch(path=DEFAULT_SNAP, interval=0.5, numbers=False, compact=False):
    last = None
    print("👁  watching %s  (Ctrl-C to quit)" % path)
    try:
        while True:
            try:
                mt = os.path.getmtime(path)
            except OSError:
                if last != "missing":
                    sys.stdout.write(CLEAR + "waiting for snapshot in %s ...\n"
                                     % path)
                    sys.stdout.flush()
                    last = "missing"
                time.sleep(interval)
                continue
            if mt != last:
                last = mt
                try:
                    with open(path) as f:
                        snap = json.load(f)
                    sys.stdout.write(CLEAR + render_snapshot(snap, numbers,
                                                             compact) + "\n")
                except (OSError, ValueError) as e:
                    sys.stdout.write(CLEAR + "snapshot unreadable: %s\n" % e)
                sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nviewer closed.")

# ─── CLI ──────────────────────────────────────────────────────────
EPILOG = """\
examples:
  %(prog)s fafffa47              show trains + test for puzzle
  %(prog)s --solve fafffa47      solve puzzle, show result + trace
  %(prog)s --compact fafffa47    compact mode (1 char/cell) for big grids
  %(prog)s --snap snap.json      render a snapshot file once
  %(prog)s --watch               live: poll view_current.json, re-render
  %(prog)s --watch my.json       live: poll custom file
  %(prog)s --numbers fafffa47    overlay digit on each cell

api (from python):
  from viewer import push, push_puzzle, push_solve
  push("title", trains=..., test_in=..., pred=..., expected=...)
  push_puzzle("fafffa47", pred=[[1,2],[3,4]])
  push_solve("fafffa47")   # solve + push + trace
"""

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="viewer",
        description="ARC-AGI terminal viewer v2 — visualize puzzles & solutions",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("puzzle", nargs="?",
                    help="puzzle ID (e.g. fafffa47)")
    ap.add_argument("--snap", metavar="FILE",
                    help="render snapshot file once and exit")
    ap.add_argument("--watch", nargs="?", const=DEFAULT_SNAP, metavar="FILE",
                    help="watch snapshot file, re-render on change "
                         "(default: state/view_current.json)")
    ap.add_argument("--solve", action="store_true",
                    help="solve puzzle with engine, show result + trace")
    ap.add_argument("--compact", action="store_true",
                    help="compact mode: 1 char/cell for grids > 20")
    ap.add_argument("--numbers", action="store_true",
                    help="overlay digit value on each cell")
    ap.add_argument("--data", default="data/training",
                    help="training data directory (default: data/training)")
    a = ap.parse_args(argv)

    if a.watch:
        watch(a.watch, numbers=a.numbers, compact=a.compact)
    elif a.snap:
        with open(a.snap) as f:
            print(render_snapshot(json.load(f), a.numbers, a.compact))
    elif a.solve and a.puzzle:
        push_solve(a.puzzle, trains_dir=a.data)
        with open(DEFAULT_SNAP) as f:
            print(render_snapshot(json.load(f), a.numbers, a.compact))
    elif a.puzzle:
        import solver_smart_v2 as v2
        p = v2.load_puzzles(a.data)[a.puzzle]
        snap = {"title": a.puzzle,
                "trains": [{"in": i, "out": o}
                           for i, o in v2.get_train_pairs(p)],
                "test_in": v2.get_test_input(p),
                "expected": p["test"][0]["output"]}
        print(render_snapshot(snap, a.numbers, a.compact))
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
