#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_master_plan.vsm
"""Build the ViArc-2 SFT training kernel (Kaggle GPU, private, internet ON).

    python3 arc-solver/build_sft_kernel.py [--out sft_kernel.ipynb]

Pipeline in-kernel (offline training data via competition mount):
  1. install peft if absent (private kernel, internet allowed — this is
     a TRAINING artifact, never a competition submission)
  2. locate staged base model (qwen3-4b-instruct) under /kaggle/input
  3. extract arc-agi_training_challenges.json + solutions → per-task files
  4. sft_prepare.build() → chat jsonl (deterministic, byte-stable R10)
  5. sft_train.py LoRA it1 (config-driven from embedded harness_config.json)
  6. adapter_r2 + TRAIN_META.json → /kaggle/working (kernels output →
     staged as rmw3kufe/viarc2-sft-r2 → LLM_ADAPTER_PATH gate eval)

GPU quota est: 3-5h (sft.est_iter_hours) per calendar it1 window.
"""
from __future__ import annotations

import argparse
import json
import os
from textwrap import dedent

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ["sft_prepare.py", "sft_train.py", "llm_serialize.py"]
CONFIG = os.path.join(HERE, "config", "harness_config.json")
METADATA = {
    "id": "rmw3kufe/viarc-2-sft-it1",
    "title": "ViArc VSM AGI-2 SFT it1 (LoRA r2)",
    "code_file": "sft_kernel.ipynb",
    "language": "python",
    "kernel_type": "notebook",
    "is_private": True,
    "enable_gpu": True,
    "enable_tpu": False,
    "enable_internet": True,          # pip peft only; train data offline
    "keywords": ["arc-prize", "lora", "sft", "vsm"],
    "dataset_sources": ["rmw3kufe/qwen3-4b-instruct"],
    "kernel_sources": [],
    "competition_sources": ["arc-prize-2026-arc-agi-2"],
    "model_sources": [],
}

MD = """# ViArc VSM AGI-2 — SFT iteration 1 (LoRA r2)

**Purpose:** fine-tune the grid proposer (base: Qwen3-4B-Instruct,
Apache-2.0) on ARC-AGI-2 training pairs with D4 augmentation + per-task
leave-one-out prompts (answer-leak free), LoRA r=16 α=32 on attn q/k/v/o,
seq 768, lr 1e-4, 2 epochs — spec from `config/harness_config.json`
(single source of truth).

**Data:** competition `arc-agi_training_challenges(+solutions).json`
(train split only, by-task hash 80/20 — heldout never trained).

**Output:** `adapter_r2/` (adapter + `TRAIN_META.json` provenance) →
staged as a private dataset; gate = held-out p1 ≥ zero-shot + 2pp
(evaluated by `bench_local.py` with `LLM_ADAPTER_PATH`, separate run).

**Reproduce:** run all cells (GPU, internet ON — private training kernel,
never submitted to the competition). Deterministic seed 42 (R10).
"""

RUN = dedent('''\
    import json, os, sys, glob

    os.environ.setdefault("PYTHONHASHSEED", "0")

    # ── 1. peft (private training kernel — internet allowed) ─────────
    try:
        import peft  # noqa: F401
        print("peft ok:", peft.__version__)
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "-q", "peft"])
        import peft
        print("peft installed:", peft.__version__)

    # ── 2. modules + config (embedded) ───────────────────────────────
    MODULES = __MODULES__
    CONFIG = __CONFIG__
    for name, src in MODULES.items():
        with open(name, "w") as fp:
            fp.write(src)
    with open("harness_config.json", "w") as fp:
        fp.write(CONFIG)
    print("modules:", sorted(MODULES))

    # ── 3. locate staged base model ──────────────────────────────────
    def find_base():
        root = "/kaggle/input"
        for name in sorted(os.listdir(root)):
            d1 = os.path.join(root, name)
            for cand in [d1] + [os.path.join(d1, s) for s in
                                sorted(os.listdir(d1))
                                if os.path.isdir(os.path.join(d1, s))]:
                try:
                    files = set(os.listdir(cand))
                except OSError:
                    continue
                if "model.safetensors.index.json" in files or (
                        "config.json" in files and
                        any(f.endswith(".safetensors") for f in files)):
                    return cand
        return None

    base = find_base()
    assert base, "staged base model not found under /kaggle/input"
    print("base:", base)

    # ── 4. extract training tasks (challenges + solutions) ───────────
    COMP = [p for p in glob.glob(
        "/kaggle/input/competitions/*") if "arc-agi-2" in p]
    COMP = COMP[0] if COMP else None
    assert COMP, "competition data mount not found"
    chal = json.load(open(os.path.join(COMP,
                                       "arc-agi_training_challenges.json")))
    sols = json.load(open(os.path.join(COMP,
                                       "arc-agi_training_solutions.json")))
    tdir = "data/training"
    os.makedirs(tdir, exist_ok=True)
    for tid, task in chal.items():
        sol = sols.get(tid)
        if sol and len(sol) == len(task.get("test", [])):
            for t, s in zip(task["test"], sol):
                t["output"] = s
        with open(os.path.join(tdir, f"{tid}.json"), "w") as fp:
            json.dump(task, fp)
    print("tasks extracted:", len(chal))

    # ── 5. deterministic dataset build ───────────────────────────────
    import sft_prepare
    stats = sft_prepare.build(tdir, "data/sft", n_variants=7, seed=42)
    print("sft stats:", json.dumps(stats["examples"]))

    # ── 6. LoRA it1 ──────────────────────────────────────────────────
    os.environ["SFT_BASE"] = base
    os.environ["SFT_DATA"] = os.path.abspath("data/sft")
    os.environ["SFT_OUT"] = os.path.abspath("adapter_r2")
    sys.argv = ["sft_train.py", "--config", "harness_config.json"]
    import sft_train
    sft_train.main()
    print("DONE adapter:", os.listdir("adapter_r2"))
''')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    mods = {}
    for name in MODULES:
        with open(os.path.join(HERE, name)) as fp:
            mods[name] = fp.read()
    with open(CONFIG) as fp:
        cfg = fp.read()
    run = (RUN.replace("__MODULES__", json.dumps(mods))
              .replace("__CONFIG__", json.dumps(cfg)))
    compile(run, "<sft_run>", "exec")          # fail loud before push
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "kaggle": {"accelerator": "gpu", "isInternetEnabled": True},
        },
        "cells": [
            {"cell_type": "markdown", "metadata": {},
             "source": MD.splitlines(keepends=True)},
            {"cell_type": "code", "metadata": {}, "execution_count": None,
             "outputs": [], "source": run.splitlines(keepends=True)},
        ],
    }
    out = a.out or os.path.join(HERE, "kaggle_sft", "sft_kernel.ipynb")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fp:
        json.dump(nb, fp)
    md_out = os.path.join(HERE, "kaggle_sft", "kernel-metadata.json")
    with open(md_out, "w") as fp:
        json.dump(METADATA, fp, indent=2, ensure_ascii=False)
    print(f"notebook: {out} ({os.path.getsize(out)} bytes, "
          f"{len(mods)} modules)")
    print(f"metadata: {md_out}")


if __name__ == "__main__":
    main()
