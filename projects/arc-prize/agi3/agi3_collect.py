#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""
AGI-3 Environment Collector — hypothesis test + viable-space embedding.

Hypothesis: running games even at 0 levels yields the robust floor:
an action->effect model per game plus a milestone signal from diffs.

Each grid is embedded as a vector in R^n (viable space):
  dims 0-15 : color histogram (normalized cell counts, 16 colors)
  dim 16    : non-background mass fraction
  dim 17    : object count (connected components, normalized)
  dim 18    : symmetry flag (0/1)
  dims 19-22: content bbox (r0, r1, c0, c1, normalized)
A game run becomes a TRAJECTORY in R^n. From it:
  - milestone = displacement magnitude above threshold (or level change)
  - novelty   = grid hash unseen in this run (tabu foundation)
  - floor     = per-action effect stats (cells changed, regions, colors)

Probe suite per game: each available ACTION xK + ACTION6 clicks at a
small coordinate grid. Polite pacing (0.2s).
"""
import requests, json, os, sys, time, hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

API_KEY = os.environ.get("ARC_API_KEY", "")
ROOT = "https://three.arcprize.org"
OUT_DIR = Path(__file__).parent / "state" / "rsi_data" / "transitions"

EMB_DIM = 23


def make_session():
    s = requests.Session()
    s.headers.update({"X-API-Key": API_KEY, "Accept": "application/json",
                      "Content-Type": "application/json"})
    return s


def flatten_frame(frame):
    grid = frame
    if grid and isinstance(grid[0], list) and isinstance(grid[0][0], list):
        grid = grid[0]
    return grid


def grid_hash(grid):
    h = hashlib.sha256()
    for row in grid:
        h.update(bytes(int(c) & 0xF for c in row))
    return h.hexdigest()[:16]


def components(g, bg):
    R, C = (len(g), len(g[0]) if g else 0)
    seen, n = set(), 0
    for r in range(R):
        for c in range(C):
            if (r, c) in seen or g[r][c] == bg:
                continue
            n += 1
            stack = [(r, c)]
            while stack:
                cr, cc = stack.pop()
                if ((cr, cc) in seen or cr < 0 or cr >= R or cc < 0 or
                        cc >= C or g[cr][cc] == bg):
                    continue
                seen.add((cr, cc))
                stack.extend([(cr - 1, cc), (cr + 1, cc),
                              (cr, cc - 1), (cr, cc + 1)])
    return n


def embed(grid):
    """Grid -> R^23 viable-space vector (list of floats)."""
    R = len(grid)
    C = len(grid[0]) if R else 1
    N = R * C
    hist = [0] * 16
    for row in grid:
        for c in row:
            v = int(c)
            if 0 <= v < 16:
                hist[v] += 1
    vec = [h / N for h in hist]
    bg = max(range(16), key=lambda i: hist[i])
    mass = (N - hist[bg]) / N
    vec.append(mass)
    vec.append(min(components(grid, bg) / 50.0, 1.0))
    sym_h = all(grid[r] == grid[R - 1 - r] for r in range(R // 2))
    sym_v = all(grid[r][c] == grid[r][C - 1 - c]
                for r in range(R) for c in range(C // 2))
    vec.append(1.0 if (sym_h or sym_v) else 0.0)
    cells = [(r, c) for r in range(R) for c in range(C)
             if int(grid[r][c]) != bg]
    if cells:
        r0 = min(r for r, c in cells) / R
        r1 = max(r for r, c in cells) / R
        c0 = min(c for r, c in cells) / C
        c1 = max(c for r, c in cells) / C
    else:
        r0 = r1 = c0 = c1 = 0.0
    vec.extend([r0, r1, c0, c1])
    assert len(vec) == EMB_DIM, len(vec)
    return vec


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def diff_summary(g0, g1):
    changes = 0
    gained_colors = set()
    regions = defaultdict(int)
    R = min(len(g0), len(g1))
    for r in range(R):
        C = min(len(g0[r]), len(g1[r]))
        for c in range(C):
            v0, v1 = int(g0[r][c]), int(g1[r][c])
            if v0 != v1:
                changes += 1
                gained_colors.add(v1)
                regions[(r // 16, c // 16)] += 1
    return {"cells": changes, "new_colors": sorted(gained_colors),
            "regions": {f"{k}": v for k, v in regions.items()}}


class Collector:
    def __init__(self, tag="collect"):
        self.s = make_session()
        self.tag = tag
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    def start(self, game_id):
        r = self.s.post(f"{ROOT}/api/scorecard/open",
                        json={"tags": [self.tag]})
        card_id = r.json()["card_id"]
        r = self.s.post(f"{ROOT}/api/cmd/RESET",
                        json={"game_id": game_id, "card_id": card_id})
        if r.status_code != 200:
            return None
        d = r.json()
        d["card_id"] = card_id
        return d

    def act(self, game_id, guid, card_id, action, x=None, y=None):
        body = {"game_id": game_id, "guid": guid, "card_id": card_id}
        if x is not None:
            body.update({"x": x, "y": y})
        r = self.s.post(f"{ROOT}/api/cmd/ACTION{action}", json=body)
        if r.status_code != 200:
            return None
        return r.json()

    def close(self, card_id):
        try:
            self.s.post(f"{ROOT}/api/scorecard/close",
                        json={"card_id": card_id}, timeout=15)
        except Exception:
            pass

    def probe(self, game_id, repeats=2, clicks=((32, 32), (0, 0),
                                               (63, 63), (32, 0), (0, 32))):
        """Fixed probe suite. Returns run record (trajectory in R^n)."""
        st = self.start(game_id)
        if not st:
            return None
        guid, card_id = st["guid"], st["card_id"]
        grid = flatten_frame(st.get("frame", []))
        steps = []
        visited = {grid_hash(grid)}
        prev_vec = embed(grid)
        prev_levels = st.get("levels_completed", 0)

        def fire(action, x=None, y=None):
            nonlocal grid, prev_vec, prev_levels
            res = self.act(game_id, guid, card_id, action, x, y)
            if res is None:
                return
            new_grid = flatten_frame(res.get("frame", []))
            ds = diff_summary(grid, new_grid)
            vec = embed(new_grid)
            displacement = dist(prev_vec, vec)
            levels = res.get("levels_completed", 0)
            h = grid_hash(new_grid)
            novel = h not in visited
            visited.add(h)
            # raw milestone: level change always counts; the displacement
            # band is calibrated at summarize time (adaptive threshold).
            milestone = levels > prev_levels
            steps.append({
                "action": action, "x": x, "y": y,
                "cells_changed": ds["cells"],
                "new_colors": ds["new_colors"],
                "regions": ds["regions"],
                "displacement": round(displacement, 4),
                "novel": novel, "milestone": milestone,
                "levels": levels, "state": res.get("state"),
                "hash": h,
            })
            grid, prev_vec, prev_levels = new_grid, vec, levels
            time.sleep(0.2)

        avail = st.get("available_actions", [])
        for _ in range(repeats):
            for a in avail:
                if a == 6:
                    for (x, y) in clicks:
                        fire(a, x, y)
                else:
                    fire(a)
        self.close(card_id)
        return {"game_id": game_id, "levels": prev_levels,
                "states_visited": len(visited), "steps": steps,
                "ts": datetime.now(timezone.utc).isoformat()}

    def summarize(self, run):
        """Per-action effect model = the robust floor for this game.

        Milestones (adaptive): a step counts iff level-up, or its
        displacement >= 5x the run median displacement. This separates
        micro (cursor), medium (pulse) and large (bulk transform) bands
        without per-game tuning. Observed bands, 64x64:
          micro  ~0.0004 (1-cell cursor) | medium ~0.0007 (ls20 pulse)
          large  0.006+ (bulk) / 0.017 (click-fill).
        """
        import statistics
        disps = sorted(s["displacement"] for s in run["steps"])
        med = statistics.median(disps) if disps else 0.0
        thr = 5 * med if med > 0 else 0.003
        for s in run["steps"]:
            if s["levels"] > 0 or s["displacement"] >= thr:
                s["milestone"] = True
        by_action = defaultdict(
            lambda: {"n": 0, "cells": 0, "milestones": 0, "novel": 0,
                     "max_disp": 0.0})
        for s in run["steps"]:
            a = by_action[str(s["action"])]
            a["n"] += 1
            a["cells"] += s["cells_changed"]
            a["milestones"] += int(s["milestone"])
            a["novel"] += int(s["novel"])
            a["max_disp"] = max(a["max_disp"], s["displacement"])
        floor = {}
        for k, a in by_action.items():
            floor[k] = {"uses": a["n"],
                        "avg_cells": round(a["cells"] / a["n"], 1),
                        "milestones": a["milestones"],
                        "novel_rate": round(a["novel"] / a["n"], 2),
                        "max_disp": a["max_disp"]}
        return {"game_id": run["game_id"], "levels": run["levels"],
                "states_visited": run["states_visited"],
                "n_steps": len(run["steps"]),
                "milestones": sum(1 for s in run["steps"] if s["milestone"]),
                "milestone_thr": round(thr, 4),
                "median_disp": round(med, 4),
                "floor": floor}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("games", nargs="*", default=["cd82-fb555c5d"])
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--tag", default="collect")
    args = ap.parse_args()
    col = Collector(tag=args.tag)
    for gid in args.games:
        print(f"probing {gid} ...")
        run = col.probe(gid, repeats=args.repeats)
        if not run:
            print("  FAILED to start")
            continue
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = OUT_DIR / f"{gid.split('-')[0]}_{stamp}.json"
        with open(path, "w") as f:
            json.dump(run, f, indent=1)
        s = col.summarize(run)
        with open(path, "w") as f:  # re-save: summarize calibrates milestones
            json.dump(run, f, indent=1)
        print(f"  levels={s['levels']} states={s['states_visited']} "
              f"steps={s['n_steps']} milestones={s['milestones']} "
              f"(thr={s['milestone_thr']}, med={s['median_disp']})")
        for a in sorted(s["floor"]):
            print(f"    ACTION{a}: {s['floor'][a]}")
        print(f"  saved {path}")


if __name__ == "__main__":
    main()
