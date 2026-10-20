#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc3_master_plan.vsm
#         + docs/spec_revision/design-sources/shadow-inventory-2026-10.vsm (P1)
"""CNN offline corpus collector v2 — (frame, action, effect) transitions.

Purpose: collect the training corpus for OFFLINE pretraining of the AGI-3
CNN action-effect proposer (viarc3_agent._cnn). The CNN currently learns
online with RANDOM init for its first CNN_BATCH actions and re-inits on
every level; pretraining gives it priors from action 1 and a pretrained
reset target (mechanics-first per S5 2026-10-20).

Engine: local `arc-agi` (same game engine as the Kaggle gateway) — NO
API key, NO Kaggle, runs in WSL. Must run with CWD = arc3-lab root so
`environment_files/` resolves (play_local.py contract).

Signal per the agent's own training (viarc3_agent._cnn_train):
  reward = 1.0 if the action changed ANY cell else 0.0 (BCE target).
We also log cells_changed count, levels_completed and milestone
(level-up) — future progress-head labels (richer than change-only).

Determinism (R10): all probe order / click coords / walk choices derive
from a fixed seed = f(game_id, episode). Same input → same corpus.

Output: <out>/<game_id>.npz (compressed shards) + manifest.json.

Run (from arc3-lab root):
  /tmp/opencode/arc3-lab/.venv/bin/python \
      ~/vOSlab/projects/arc-prize/agi3/collect_cnn_v2.py \
      --episodes 40 --steps 150
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

GRID = 64  # CNN expects 64x64 (pad/clip — NEVER assert, agent contract)

# ACTION6 probe clicks: systematic 4x4 lattice + center (covers coord
# logits' coarse structure; seeded uniform clicks add fine coverage).
LATTICE = [0, 21, 42, 63]


def _seed(game_id: str, episode: int) -> int:
    h = hashlib.sha256(f"{game_id}:ep{episode}:v2".encode()).hexdigest()
    return int(h[:8], 16)


def _to_grid(frame) -> np.ndarray:
    """FrameDataRaw.frame -> (64,64) uint8, values clipped to 0..15."""
    a = np.asarray(frame)
    while a.ndim > 2 and a.shape[0] == 1:
        a = a[0]
    if a.ndim != 2:
        # list-of-lists fallback
        a = np.asarray(frame, dtype=np.int64)
        while a.ndim > 2:
            a = a[0]
    a = a.astype(np.int64)
    h, w = a.shape
    out = np.zeros((GRID, GRID), dtype=np.uint8)
    hh, ww = min(h, GRID), min(w, GRID)
    out[:hh, :ww] = np.clip(a[:hh, :ww], 0, 15).astype(np.uint8)
    return out


def _pick_action(avail: list, rng: np.random.Generator, mode: str,
                 step: int) -> tuple[int, dict | None]:
    """Deterministic-by-seed action choice.

    mode 'probe': round-robin over available actions; when ACTION6 is
    available, sweep a lattice coordinate each time it recurs, else a
    seeded uniform click. mode 'walk': uniform random over available.
    Returns (action_code 1..6, step_data or None).
    """
    if not avail:
        return 0, None
    if mode == "walk":
        a = int(rng.choice(avail))
        if a == 6:
            return 6, {"x": int(rng.integers(0, GRID)),
                       "y": int(rng.integers(0, GRID))}
        return a, None
    # probe: round-robin by step over sorted avail
    a = int(sorted(avail)[step % len(avail)])
    if a == 6:
        k = step // max(len(avail), 1)
        if k % 3 < 2:  # lattice 2/3 of the clicks
            lx = LATTICE[(k // len(LATTICE)) % len(LATTICE)]
            ly = LATTICE[k % len(LATTICE)]
            return 6, {"x": lx, "y": ly}
        return 6, {"x": int(rng.integers(0, GRID)),
                   "y": int(rng.integers(0, GRID))}
    return a, None


def collect_game(arc, short_id: str, episodes: int, steps: int,
                 mode: str) -> dict | None:
    from arcengine.enums import GameAction, GameState
    env = arc.make(short_id)
    if env is None:
        print(f"  [{short_id}] could not create env, skipping", flush=True)
        return None

    rows = {k: [] for k in ("frame", "action", "x", "y", "changed",
                            "cells", "level", "milestone", "ep", "step")}
    total_changed = 0
    t0 = time.time()
    for ep in range(episodes):
        rng = np.random.default_rng(_seed(short_id, ep))
        fd = env.reset()
        if fd is None:
            break
        for st in range(steps):
            g0 = _to_grid(fd.frame)
            lvl0 = int(fd.levels_completed)
            a, data = _pick_action(fd.available_actions, rng, mode, st)
            if a == 0:
                break
            # Custom enum: value-map holds tuples; NAME subscript is the
            # only valid construction (GameAction["ACTION1"]).
            # No try/except — invalid action must crash loud (R9).
            fd2 = env.step(GameAction[f"ACTION{a}"], data)
            if fd2 is None:
                break
            g1 = _to_grid(fd2.frame)
            lvl1 = int(fd2.levels_completed)
            cells = int(np.count_nonzero(g0 != g1))
            rows["frame"].append(g0)
            rows["action"].append(a)
            rows["x"].append(int(data["x"]) if data else -1)
            rows["y"].append(int(data["y"]) if data else -1)
            rows["changed"].append(1 if cells else 0)
            rows["cells"].append(min(cells, 65535))
            rows["level"].append(lvl1)
            rows["milestone"].append(1 if lvl1 > lvl0 else 0)
            rows["ep"].append(ep)
            rows["step"].append(st)
            total_changed += 1 if cells else 0
            fd = fd2
            if fd2.state != GameState.NOT_FINISHED:
                break

    n = len(rows["frame"])
    if n == 0:
        print(f"  [{short_id}] 0 transitions", flush=True)
        return None
    arrs = {
        "frames": np.stack(rows["frame"]).astype(np.uint8),
        "action": np.asarray(rows["action"], dtype=np.int8),
        "x": np.asarray(rows["x"], dtype=np.int16),
        "y": np.asarray(rows["y"], dtype=np.int16),
        "changed": np.asarray(rows["changed"], dtype=np.uint8),
        "cells": np.asarray(rows["cells"], dtype=np.uint16),
        "level": np.asarray(rows["level"], dtype=np.int8),
        "milestone": np.asarray(rows["milestone"], dtype=np.uint8),
        "ep": np.asarray(rows["ep"], dtype=np.int16),
        "step": np.asarray(rows["step"], dtype=np.int16),
    }
    return {"game": short_id, "n": n, "changed_frac":
            round(total_changed / n, 4), "seconds":
            round(time.time() - t0, 1), "arrays": arrs}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--episodes", type=int, default=40)
    p.add_argument("--steps", type=int, default=150,
                   help="max steps per episode")
    p.add_argument("--modes", default="probe,walk",
                   help="comma list: probe|walk (walk episodes interleave)")
    p.add_argument("--games", default=None,
                   help="comma list of short ids (default: all)")
    p.add_argument("--out", default=str(
        Path.home() / "vOSlab" / "projects" / "arc-prize" / "agi3"
        / "data" / "cnn_corpus"))
    args = p.parse_args()

    import arc_agi
    from arc_agi import OperationMode

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    arc = arc_agi.Arcade(operation_mode=OperationMode.NORMAL)
    envs = arc.get_environments()
    wanted = ({g.strip().split("-")[0] for g in args.games.split(",")}
              if args.games else None)
    game_ids = [e.game_id.split("-")[0] for e in envs
                if wanted is None or e.game_id.split("-")[0] in wanted]
    print(f"collect_cnn_v2: {len(game_ids)} games, episodes={args.episodes}"
          f" steps={args.steps} modes={modes}", flush=True)

    manifest = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "episodes": args.episodes, "steps": args.steps,
                "modes": modes, "games": []}
    for i, gid in enumerate(game_ids, 1):
        # alternate modes across episodes by running one pass per mode
        # (deterministic split: even episodes -> first mode, odd -> second)
        mode = modes[(i - 1) % len(modes)] if len(modes) > 1 else modes[0]
        res = None
        for m in (modes if len(modes) > 1 else [modes[0]]):
            # split episodes between modes deterministically
            eps = args.episodes // len(modes) + (
                1 if (i - 1) % len(modes) == modes.index(m) else 0)
            if eps <= 0:
                continue
            r = collect_game(arc, gid, eps, args.steps, m)
            if r is None:
                continue
            tag = f"{gid}.{m}" if len(modes) > 1 else gid
            np.savez_compressed(out_dir / f"{tag}.npz", **r["arrays"])
            manifest["games"].append({"game": tag, "n": r["n"],
                                      "changed_frac": r["changed_frac"],
                                      "seconds": r["seconds"]})
            res = r
        if res:
            print(f"  [{i}/{len(game_ids)}] {gid}: n={res['n']} "
                  f"changed={res['changed_frac']} ({res['seconds']}s)",
                  flush=True)

    total = sum(g["n"] for g in manifest["games"])
    manifest["total_transitions"] = total
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"DONE: {total} transitions across {len(manifest['games'])} "
          f"shards -> {out_dir}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
