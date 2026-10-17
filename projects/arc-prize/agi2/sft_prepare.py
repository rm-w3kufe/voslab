#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_master_plan.vsm
"""sft_prepare.py — deterministic SFT dataset builder (D4 augment).

    python3 sft_prepare.py [--data DIR] [--out DIR] [--n-variants 7] [--seed 42]

Builds chat-format jsonl for LoRA fine-tuning of the grid proposer:
  {"messages": [
      {"role": "user",      "content": <grid prompt>},
      {"role": "assistant", "content": <output grid text>} ]}

Augment: D4 group (identity, flip_h, flip_v, rot90, rot180, rot270,
transpose) + deterministic recolor per variant. Split is BY TASK hash
(80/20, no pair-level leakage). Stdlib-only (pure python transforms),
deterministic (R10): same seed+data -> byte-identical output.

Runs on LXC 114 (CPU lab) and inside the Kaggle kernel (in-kernel prep
is possible but unnecessary — generated artifact is small text jsonl).
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from llm_serialize import build_prompt, grid_to_text  # noqa: E402


# ── D4 transforms (pure python, list-of-lists) ─────────────────────────

def flip_h(g):
    return [row[::-1] for row in g]


def flip_v(g):
    return g[::-1]


def rot90(g):
    return [list(r) for r in zip(*g[::-1])]


def rot180(g):
    return [row[::-1] for row in g[::-1]]


def rot270(g):
    return [list(r) for r in zip(*g)][::-1]


def transpose(g):
    return [list(r) for r in zip(*g)]


VARIANTS = [
    ("id", lambda g: [row[:] for row in g]),
    ("fh", flip_h), ("fv", flip_v),
    ("r90", rot90), ("r180", rot180), ("r270", rot270),
    ("t", transpose),
]


def recolor(g, perm):
    return [[perm[v] for v in row] for row in g]


def make_perm(seed: int):
    rng = random.Random(seed)
    digits = list(range(10))
    rng.shuffle(digits)
    return digits


# ── Task iteration + split ─────────────────────────────────────────────

def task_split(task_id: str, seed: int) -> str:
    h = int(hashlib.sha256(f"{seed}:{task_id}".encode()).hexdigest(), 16)
    return "train" if (h % 10) < 8 else "heldout"


def build(data_dir: str, out_dir: str, n_variants: int, seed: int) -> dict:
    paths = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    if not paths:
        raise SystemExit(f"no puzzles under {data_dir}")
    os.makedirs(out_dir, exist_ok=True)
    writers = {
        "train": open(os.path.join(out_dir, "train.jsonl"), "w"),
        "heldout": open(os.path.join(out_dir, "heldout.jsonl"), "w"),
    }
    stats = {"examples": {}, "tasks": {}}
    try:
        for pi, path in enumerate(paths):
            tid = os.path.splitext(os.path.basename(path))[0]
            split = task_split(tid, seed)
            stats["tasks"][split] = stats["tasks"].get(split, 0) + 1
            with open(path) as f:
                task = json.load(f)
            pairs = [(p["input"], p["output"])
                     for p in task.get("train", [])]
            pairs += [(p["input"], p["output"])
                      for p in task.get("test", []) if "output" in p]
            if not pairs:
                continue
            for vi, (vname, fn) in enumerate(VARIANTS[:n_variants]):
                # deterministic per-task, per-variant recolor
                perm = make_perm(seed ^ (pi * 131) ^ (vi * 17))
                aug = []
                for inp, out in pairs:
                    ti, to = fn(inp), fn(out)
                    if vname != "id":
                        ti, to = recolor(ti, perm), recolor(to, perm)
                    aug.append((ti, to))
                # leave-one-out per pair: the shown train examples never
                # include the pair being predicted (no answer leak)
                for idx, (ti, to) in enumerate(aug):
                    shown = aug[:idx] + aug[idx + 1:]
                    rec = {
                        "messages": [
                            {"role": "user",
                             "content": build_prompt(shown, ti)},
                            {"role": "assistant",
                             "content": grid_to_text(to)},
                        ],
                        "task": tid, "variant": vname,
                    }
                    writers[split].write(json.dumps(rec) + "\n")
                    stats["examples"][split] = \
                        stats["examples"].get(split, 0) + 1
    finally:
        for w in writers.values():
            w.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "..", "data",
                                                   "training"))
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "sft"))
    ap.add_argument("--n-variants", type=int, default=7)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    stats = build(args.data, args.out, args.n_variants, args.seed)
    print(json.dumps(stats, indent=2))
    print("wrote:", os.path.join(args.out, "train.jsonl"),
          "+ heldout.jsonl")


if __name__ == "__main__":
    main()
