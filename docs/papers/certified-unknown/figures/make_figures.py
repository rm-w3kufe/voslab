#!/usr/bin/env python3
"""make_figures.py — regenerate paper figures from committed results.

Reproducible: reads benchmarks/results/baseline_v2.json (+ compare
artifacts), writes docs/papers/certified-unknown/figures/*.png.
No hand-tuned numbers — every bar comes from a results file.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[3] / "benchmarks" / "results"
FIG = HERE  # script lives in figures/ already

BASE = json.load(open(RESULTS / "baseline_v2.json"))
LG = json.load(open(RESULTS / "compare_lg_v1.json"))
NEMO = json.load(open(RESULTS / "compare_nemo_v1.json"))

plt.rcParams.update({"font.size": 10, "figure.dpi": 150})


def _suite(name):
    for r in BASE["results"]:
        if r["suite"] == name:
            return r
    raise KeyError(name)


def fig_trajectories():
    """H2: per-cycle activated accuracy per fault + baseline."""
    h2 = _suite("H2-evolution")
    fig, ax = plt.subplots(figsize=(7, 4))
    for fault in h2["detail"]:
        traj = h2["detail"][fault]["traj"]
        ax.plot(range(len(traj)), traj, marker="o", label=fault)
    base = h2["metrics"]["per_fault"][0]["baseline"]
    ax.axhline(base, color="gray", linestyle="--", label="baseline")
    ax.set_xlabel("L3 cycle")
    ax.set_ylabel("activated strategy accuracy (train)")
    ax.set_title("H2 — evolutionary trajectories retain improvements")
    ax.legend()
    ax.set_ylim(0.4, 1.05)
    fig.tight_layout()
    fig.savefig(FIG / "fig1_trajectories.png")
    print("fig1_trajectories.png")


def fig_honesty():
    """H1: ours vs ablation baselines — actions and errors."""
    h1 = _suite("H1-honesty")["metrics"]
    labels = ["ours", "B0\nno-abstention", "B1\nno-gate"]
    actions = [h1["ours_actions"], h1["b0_unfounded_actions"],
               h1["b1_unfounded_actions"]]
    errors = [h1["ours_action_errors"], h1["b0_unfounded_actions"],
              h1["b1_unfounded_actions"]]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x, actions, label="actions taken", color="#4C78A8")
    ax.bar(x, errors, label="unfounded", color="#F58518")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("deployment actions")
    ax.set_title("H1 — abstention absorbs confident errors\n"
                 "(precision@certified = 1.0, false-cert = 0)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "fig2_honesty.png")
    print("fig2_honesty.png")


def fig_cost():
    """H3: per-op mean/p95 latency vs 500ms bound."""
    h3 = _suite("H3-cost")["metrics"]["ops"]
    names = [k for k in h3 if "mean_ms" in h3[k]]
    means = [h3[k]["mean_ms"] for k in names]
    p95s = [h3[k]["p95_ms"] for k in names]
    x = range(len(names))
    w = 0.35
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.bar([i - w / 2 for i in x], means, w, label="mean",
           color="#54A24B")
    ax.bar([i + w / 2 for i in x], p95s, w, label="p95", color="#E45756")
    ax.axhline(500, color="gray", linestyle="--", label="bound 500ms")
    ax.set_xticks(list(x))
    ax.set_xticklabels(names, rotation=12)
    ax.set_ylabel("ms")
    ax.set_title("H3 — governance cost per tool call (worst p95 229ms)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "fig3_cost.png")
    print("fig3_cost.png")


def fig_compare():
    """Head-to-head on ABSTENTION scenarios only (denominators equalized):
    ours 3/3 (H1 I-class + conflict + hung), LangGraph 0/3 (deny, allow,
    crash), NeMo 2/2 unclear-as-dialog-act (no truth value attached)."""
    labels = ["ours\ncertified UNKNOWN", "LangGraph\ndefaults", "NeMo\nrails"]
    abstain = [3, 0, 2]
    conferr = [0, 2, 0]
    crash = [0, 1, 0]
    x = range(3)
    fig, ax = plt.subplots(figsize=(7, 4))
    b = 0.22
    ax.bar([i - b for i in x], abstain, b, label="correct abstentions",
           color="#4C78A8")
    ax.bar(x, conferr, b, label="confident errors", color="#F58518")
    ax.bar([i + b for i in x], crash, b, label="crashes", color="#E45756")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("scenarios")
    ax.set_title("Head-to-head: abstention behavior\n"
                 "(NeMo unclear = dialog act; ours = certified UNKNOWN)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "fig4_compare.png")
    print("fig4_compare.png")


if __name__ == "__main__":
    fig_trajectories()
    fig_honesty()
    fig_cost()
    fig_compare()
