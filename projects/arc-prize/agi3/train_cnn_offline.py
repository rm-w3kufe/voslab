#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc3_master_plan.vsm
#         + docs/spec_revision/design-sources/shadow-inventory-2026-10.vsm (P1)
"""Offline pretrain of the AGI-3 CNN action-effect proposer (v8 model).

Trains the EXACT ActionModel from viarc3_agent._build_cnn (import, no
reimplementation — zero architecture drift) on the collect_cnn_v2 corpus,
then evaluates against a random-init baseline on a GAME-level holdout
(eval generalizes to unseen games; row-level splits would leak).

Loss = the agent's own (_cnn_train): BCE on chosen-action change +
its light entropy regularizers. Labels: action 1-5 -> logit idx
code-1; action 6 -> 5 + y*64 + x (agent _cnn_sample contract).
ACTION7 (undo) dropped — not in the competition action space.

Determinism (R10): fixed seeds + explicit holdout list (every 5th
sorted game short id). Same input -> same weights/report.

Run (arc3-lab root, venv has torch CPU):
  .venv/bin/python ~/vOSlab/projects/arc-prize/agi3/train_cnn_offline.py
Output:
  data/cnn_corpus/pretrain/cnn_pretrained.pt + pretrain_report.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

VLAB = Path.home() / "vOSlab" / "projects" / "arc-prize" / "agi3"
LAB = Path("/tmp/opencode/arc3-lab")
VENDOR = LAB / "vendor" / "ARC-AGI-3-Agents"
CORPUS = VLAB / "data" / "cnn_corpus"
OUT = CORPUS / "pretrain"
GRID, NCH, NACT = 64, 16, 5  # CNN_CHANNELS / CNN_N_ACTIONS (viarc3)


def load_agent_module():
    """Import viarc3_agent with vendor+arcengine paths (play_local contract)."""
    for p in (str(VENDOR), str(VLAB / "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "viarc3_agent", VLAB / "agent" / "viarc3_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_corpus(holdout: set[str]):
    frames, idxs, rews = [], [], []
    n_drop7 = n_hold = 0
    for f in sorted(CORPUS.glob("*.npz")):
        game = f.name.split(".")[0]
        z = np.load(f)
        a = z["action"].astype(np.int64)
        keep = a != 7  # undo: not in competition space
        n_drop7 += int((~keep).sum())
        if game in holdout:
            n_hold += int(keep.sum())
            continue
        a = a[keep]
        x, y = z["x"][keep], z["y"][keep]
        idx = np.where(a <= 5, a - 1, NACT - 1 + y.astype(np.int64) * GRID + x)
        frames.append(z["frames"][keep])
        idxs.append(idx)
        rews.append(z["changed"][keep].astype(np.float32))
    return (np.concatenate(frames), np.concatenate(idxs),
            np.concatenate(rews), n_drop7, n_hold)


def eval_bce(model, torch, F, frames, idxs, rews, batch=128):
    model.eval()
    tot, n = 0.0, 0
    with torch.no_grad():
        for i in range(0, len(rews), batch):
            g = torch.from_numpy(frames[i:i + batch].astype(np.int64))
            oh = F.one_hot(g, num_classes=NCH).permute(0, 3, 1, 2).float()
            t = torch.from_numpy(idxs[i:i + batch])
            r = torch.from_numpy(rews[i:i + batch])
            logits = model(oh)
            sel = logits.gather(1, t.unsqueeze(1)).squeeze(1)
            tot += float(F.binary_cross_entropy_with_logits(
                sel, r, reduction="sum"))
            n += len(r)
    return tot / max(n, 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-4)  # CNN_LR (agent)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--limit", type=int, default=0,
                   help="debug: cap train rows")
    args = p.parse_args()

    mod = load_agent_module()
    cls, torch, F = mod._build_cnn()
    torch.manual_seed(args.seed)

    games = sorted({f.name.split(".")[0] for f in CORPUS.glob("*.npz")})
    holdout = set(games[::5])  # every 5th short id — explicit, fixed
    tr_frames, tr_idxs, tr_rews, n7, nh = load_corpus(holdout)
    if args.limit:
        tr_frames, tr_idxs, tr_rews = (tr_frames[:args.limit],
                                       tr_idxs[:args.limit],
                                       tr_rews[:args.limit])
    print(f"train rows={len(tr_rews)} (drop7={n7} holdout_rows_skipped={nh})",
          flush=True)
    print(f"holdout games ({len(holdout)}): {sorted(holdout)}", flush=True)

    # holdout eval data (for BOTH baseline and trained)
    ho_f, ho_i, ho_r, _, _ = [], [], [], 0, 0
    frames_h, idxs_h, rews_h = [], [], []
    for f in sorted(CORPUS.glob("*.npz")):
        if f.name.split(".")[0] not in holdout:
            continue
        z = np.load(f)
        a = z["action"].astype(np.int64)
        keep = a != 7
        a = a[keep]
        x, y = z["x"][keep], z["y"][keep]
        idx = np.where(a <= 5, a - 1, NACT - 1 + y.astype(np.int64) * GRID + x)
        frames_h.append(z["frames"][keep])
        idxs_h.append(idx)
        rews_h.append(z["changed"][keep].astype(np.float32))
    H_F = np.concatenate(frames_h)
    H_I = np.concatenate(idxs_h)
    H_R = np.concatenate(rews_h)
    print(f"holdout rows={len(H_R)}", flush=True)

    # baseline: random init (seed protocol mirrors agent: seeded random)
    torch.manual_seed(args.seed)
    base = cls()
    base_bce = eval_bce(base, torch, F, H_F, H_I, H_R)
    print(f"baseline random-init heldout BCE: {base_bce:.5f}", flush=True)
    del base

    # train (agent contract: Adam CNN_LR, same loss w/ entropy regs)
    torch.manual_seed(args.seed)
    model = cls()
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    n_par = sum(q.numel() for q in model.parameters())
    print(f"params={n_par}", flush=True)
    g_all = torch.from_numpy(tr_frames.astype(np.int64))
    idx_t = torch.from_numpy(tr_idxs)
    rew_t = torch.from_numpy(tr_rews)
    order = torch.Generator().manual_seed(args.seed)
    t0 = time.time()
    n = len(tr_rews)
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n, generator=order)
        tot, nb = 0.0, 0
        for i in range(0, n, args.batch):
            b = perm[i:i + args.batch]
            oh = F.one_hot(g_all[b], num_classes=NCH).permute(
                0, 3, 1, 2).float()
            logits = model(oh)
            sel = logits.gather(1, idx_t[b].unsqueeze(1)).squeeze(1)
            main = F.binary_cross_entropy_with_logits(sel, rew_t[b])
            probs = torch.sigmoid(logits)
            loss = (main
                    - 0.0001 * probs[:, :NACT].mean()
                    - 0.00001 * probs[:, NACT:].mean())
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(main)
            nb += 1
        model.eval()
        ho_bce = eval_bce(model, torch, F, H_F, H_I, H_R)
        print(f"epoch {ep + 1}/{args.epochs} train_bce={tot / nb:.5f} "
              f"holdout_bce={ho_bce:.5f} "
              f"({time.time() - t0:.0f}s)", flush=True)

    final_bce = eval_bce(model, torch, F, H_F, H_I, H_R)
    OUT.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), OUT / "cnn_pretrained.pt")
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": args.seed, "epochs": args.epochs, "batch": args.batch,
        "lr": args.lr, "params": n_par,
        "train_rows": int(n), "holdout_rows": int(len(H_R)),
        "holdout_games": sorted(holdout),
        "dropped_action7": n7,
        "baseline_random_init_bce": round(base_bce, 5),
        "trained_holdout_bce": round(final_bce, 5),
        "delta_vs_baseline": round(base_bce - final_bce, 5),
        "improves": bool(final_bce < base_bce),
        "seconds": round(time.time() - t0, 1),
    }
    (OUT / "pretrain_report.json").write_text(json.dumps(report, indent=1))
    print("REPORT " + json.dumps(report), flush=True)


if __name__ == "__main__":
    sys.exit(main())
