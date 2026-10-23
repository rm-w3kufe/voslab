#!/usr/bin/env python3
# auto-generado: build_pretrain_kernel.py (R10 — no edit in kernel copy)
# prereg: docs/plans/agi_prereg_bfull_r1_2026_10_23.vsm (S5 'Go+')
# design: same embedding source — R16 zero-drift hash printed below
"""Pretrain GUI of the AGI-3 CNN (B full 12x101k): GPU schema v4 holds
the same eval schema AND the new prereg field coverage_out_of_sample.

Local smoke: pretrain_kernel.py --limit 500 --epochs 1  (CORPUS=local
data/cnn_corpus, OUT=/tmp — same code path & same report fields)
"""
import argparse, glob, hashlib, json, os, sys, time
import numpy as np

DRIFT_SHA = "46c92baf7fa9ad44"
GRID, NCH, NACT = 64, 16, 5
EPOCHS, BATCH, LR, SEED = 12, 64, 0.0001, 42

# ── ActionModel — fábrica v8 R16 (VERBATIM, module-level) ────────
from typing import Any

CNN_TRAIN_EVERY = 5     # actions between gradient steps (goose: 5)
CNN_BATCH = 64          # experiences per step (goose: 64)
CNN_BUF_MAX = 20000     # experience cap (goose: 200000; uint8 grids = 80MB)
CNN_LR = 1e-4           # Adam lr (goose: 1e-4)
CNN_GRID = 64           # model expects 64x64 (pad/clip — NEVER assert)
CNN_CHANNELS = 16       # one-hot colours 0-15
CNN_N_ACTIONS = 5       # ACTION1-5 modeled; coords cover ACTION6

def _build_cnn() -> tuple[Any, Any, Any]:
    """v8: build the goose-derived ActionModel (design f5).

    Returns (model_class, torch, torch.nn.functional) — or raises. Called
    lazily once per agent; any failure disables the tier (homeostat/brain
    keep the run alive). Attribution: derived from the official
    StochasticGoose sample kernel (DriesSmit / Tufa Labs) distributed by
    ARC Prize as reference material.
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ActionModel(nn.Module):
        """CNN predicting which actions change the frame (5 + 64x64)."""

        def __init__(self, input_channels: int = CNN_CHANNELS,
                     grid_size: int = CNN_GRID) -> None:
            super().__init__()
            self.num_action_types = CNN_N_ACTIONS
            self.conv1 = nn.Conv2d(input_channels, 32, 3, padding=1)
            self.conv2 = nn.Conv2d(32, 64, 3, padding=1)
            self.conv3 = nn.Conv2d(64, 128, 3, padding=1)
            self.conv4 = nn.Conv2d(128, 256, 3, padding=1)
            self.action_pool = nn.MaxPool2d(4, 4)          # 64 -> 16
            self.action_fc = nn.Linear(256 * (grid_size // 4) ** 2, 512)
            self.action_head = nn.Linear(512, self.num_action_types)
            self.coord_conv1 = nn.Conv2d(256, 128, 3, padding=1)
            self.coord_conv2 = nn.Conv2d(128, 64, 3, padding=1)
            self.coord_conv3 = nn.Conv2d(64, 32, 1)
            self.coord_conv4 = nn.Conv2d(32, 1, 1)
            self.dropout = nn.Dropout(0.2)

        def forward(self, x: Any) -> Any:
            x = F.relu(self.conv1(x))
            x = F.relu(self.conv2(x))
            x = F.relu(self.conv3(x))
            feats = F.relu(self.conv4(x))
            a = self.action_pool(feats).flatten(1)
            a = self.dropout(F.relu(self.action_fc(a)))
            action_logits = self.action_head(a)
            c = F.relu(self.coord_conv1(feats))
            c = F.relu(self.coord_conv2(c))
            c = F.relu(self.coord_conv3(c))
            coord_logits = self.coord_conv4(c).flatten(1)
            return torch.cat([action_logits, coord_logits], dim=1)

    return ActionModel, torch, F

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--epochs", type=int, default=EPOCHS)
    p.add_argument("--batch", type=int, default=BATCH)
    p.add_argument("--lr", type=float, default=LR)
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args()
    # RUN-scope: los usos del bloque usan le nombres EPOCHS/BATCH/LR/SEED
    epochs, batch, lr, seed = args.epochs, args.batch, args.lr, args.seed
    globals().update(epochs=epochs, batch=batch, lr=lr, seed=seed,
                     EPOCHS=epochs, BATCH=batch, LR=lr, SEED=seed)
    os.environ.setdefault("PYTHONHASHSEED", "0")
    import torch

    # ── corpus mount (kaggle dataset or local dev) ───────────────────
    CORPUS = None
    for dp, dns, fns in os.walk("/kaggle/input"):
        if any(f.endswith(".npz") for f in fns):
            CORPUS = dp
            break
    OUT = "/kaggle/working"
    TRAIN_LIMIT = args.limit
    if CORPUS is None:
        # dev mode: entorno local del training (env override o layout repo)
        for cand in (
            os.environ.get("PTK_CORPUS"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "data", "cnn_corpus"),
        ):
            if cand:
                r2 = os.path.abspath(cand)
                if os.path.isdir(r2) and glob.glob(os.path.join(r2, "*.npz")):
                    CORPUS = r2
                    OUT = "/tmp/pretrain_smoke"
                    break
        if CORPUS is None:
            raise AssertionError("corpus npz no montado (o archivo local)")

    print(f"CORPUS={CORPUS} OUT={OUT} LIMIT={TRAIN_LIMIT}", flush=True)
    print(f"DRIFT_SHA={DRIFT_SHA}", flush=True)

    ActionModel, torch, F = _build_cnn()
    torch.manual_seed(SEED)

    # ── corpus loader (schema v4: drop7 + every-5th holdout) ────────
    def load_corpus(holdout):
        frames, idxs, rews = [], [], []
        n_drop7, n_hold = 0, 0
        for f in sorted(glob.glob(os.path.join(CORPUS, "*.npz"))):
            game = os.path.basename(f).split(".")[0]
            z = np.load(f)
            a = z["action"].astype(np.int64)
            keep = a != 7
            n_drop7 += int((~keep).sum())
            if game in holdout:
                n_hold += int(keep.sum())
                continue
            a = a[keep]
            x, y = z["x"][keep], z["y"][keep]
            idx = np.where(a <= 5, a - 1,
                           NACT - 1 + y.astype(np.int64) * GRID + x)
            frames.append(z["frames"][keep])
            idxs.append(idx)
            rews.append(z["changed"][keep].astype(np.float32))
        return (np.concatenate(frames), np.concatenate(idxs),
                np.concatenate(rews), n_drop7, n_hold)

    def eval_bce(model, frames, idxs, rews, batch=128):
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

    # ── holdout split (schema v4) ────────────────────────────────────
    games = sorted({os.path.basename(f).split(".")[0]
                  for f in glob.glob(os.path.join(CORPUS, "*.npz"))})
    holdout = set(games[::5])
    tr_frames, tr_idxs, tr_rews, n7, nh = load_corpus(holdout)
    if TRAIN_LIMIT:
        tr_frames, tr_idxs, tr_rews = (tr_frames[:TRAIN_LIMIT],
                                       tr_idxs[:TRAIN_LIMIT],
                                       tr_rews[:TRAIN_LIMIT])
    print(f"train rows={len(tr_rews)} (drop7={n7} "
          f"holdout_rows_skipped={nh})", flush=True)
    print(f"holdout games ({len(holdout)}): {sorted(holdout)}",
          flush=True)
    ho_f, ho_i, ho_r = [], [], []
    for f in sorted(glob.glob(os.path.join(CORPUS, "*.npz"))):
        game = os.path.basename(f).split(".")[0]
        if game not in holdout:
            continue
        z = np.load(f)
        a = z["action"].astype(np.int64)
        keep = a != 7
        a = a[keep]
        x, y = z["x"][keep], z["y"][keep]
        idx = np.where(a <= 5, a - 1, NACT - 1 + y.astype(np.int64) * GRID + x)
        ho_f.append(z["frames"][keep])
        ho_i.append(idx)
        ho_r.append(z["changed"][keep].astype(np.float32))
    H_F = np.concatenate(ho_f)
    H_I = np.concatenate(ho_i)
    H_R = np.concatenate(ho_r)
    if TRAIN_LIMIT:
        H_F, H_I, H_R = H_F[:TRAIN_LIMIT], H_I[:TRAIN_LIMIT], H_R[:TRAIN_LIMIT]
        print("SMOKE slice holdout rows", flush=True)
    print(f"holdout rows={len(H_R)}", flush=True)

    # ── baseline random init (protocol agente: seeded) ──────────────
    torch.manual_seed(SEED)
    base = ActionModel()
    base_bce = eval_bce(base, H_F, H_I, H_R)
    print(f"baseline random-init heldout BCE: {base_bce:.5f}", flush=True)
    del base

    # ── train B full ────────────────────────────────────────────────
    torch.manual_seed(SEED)
    model = ActionModel()
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    n_par = sum(q.numel() for q in model.parameters())
    print(f"params={n_par}", flush=True)
    g_all = torch.from_numpy(tr_frames.astype(np.int64))
    idx_t = torch.from_numpy(tr_idxs)
    rew_t = torch.from_numpy(tr_rews)
    order = torch.Generator().manual_seed(SEED)
    t0 = time.time()
    n = len(tr_rews)
    for ep in range(EPOCHS):
        model.train()
        perm = torch.randperm(n, generator=order)
        tot, nb = 0.0, 0
        for i in range(0, n, BATCH):
            b = perm[i:i + BATCH]
            oh = F.one_hot(g_all[b], num_classes=NCH).permute(0, 3, 1, 2).float()
            logits = model(oh)
            sel = logits.gather(1, idx_t[b].unsqueeze(1)).squeeze(1)
            main = F.binary_cross_entropy_with_logits(sel, rew_t[b])
            probs = torch.sigmoid(logits)
            loss = (main - 0.0001 * probs[:, :NACT].mean()
                    - 0.00001 * probs[:, NACT:].mean())
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(main)
            nb += 1
        model.eval()
        hb = eval_bce(model, H_F, H_I, H_R)
        print(f"epoch {ep + 1}/{EPOCHS} train_bce={tot / nb:.5f} "
              f"holdout_bce={hb:.5f} ({time.time() - t0:.0f}s)",
              flush=True)

    final_bce = eval_bce(model, H_F, H_I, H_R)

    # ── coverage_out_of_sample (PREREG: frac top-1 hits label==1) ────
    model.eval()
    pos = np.where(H_R == 1.0)[0]
    hits, n_pos = 0, int(len(pos))
    if n_pos:
        with torch.no_grad():
            for i0 in range(0, n_pos, 128):
                ii = pos[i0:i0 + 128]
                oh = F.one_hot(
                    torch.from_numpy(H_F[ii].astype(np.int64)),
                    num_classes=NCH).permute(0, 3, 1, 2).float()
                logits = model(oh)
                am = torch.argmax(logits, dim=1).numpy()
                hits += int((am == H_I[ii]).sum())
    cov = hits / max(n_pos, 1)
    print(f"coverage_out_of_sample={hits}/{n_pos}={cov:.4f}", flush=True)

    # ── report (schema v4 + prereg fields) ──────────────────────────
    os.makedirs(OUT, exist_ok=True)
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": SEED, "epochs": EPOCHS, "batch": BATCH, "lr": LR,
        "params": n_par, "drift_sha": DRIFT_SHA,
        "train_rows": int(n), "holdout_rows": int(len(H_R)),
        "holdout_games": sorted(holdout),
        "dropped_action7": int(n7),
        "baseline_random_init_bce": round(base_bce, 5),
        "trained_holdout_bce": round(final_bce, 5),
        "coverage_out_of_sample": round(cov, 5),
        "coverage_hits": hits, "coverage_pos": n_pos,
        "delta_vs_baseline": round(base_bce - final_bce, 5),
        "improves": bool(final_bce < base_bce),
        "seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(OUT, "pretrain_report.json"), "w") as fh:
        fh.write(json.dumps(report, indent=1))
    print("REPORT " + json.dumps(report), flush=True)


if __name__ == "__main__":
    sys.exit(main())
