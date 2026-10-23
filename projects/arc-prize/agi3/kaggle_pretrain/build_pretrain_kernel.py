#!/usr/bin/env python3
# design: docs/plans/agi_prereg_bfull_r1_2026_10_23.vsm (prereg S5 'Go+' 2026-10-23)
#         projects/arc-prize/agi2/build_sft_kernel.py (patrón kernel-mount)
"""build_pretrain_kernel.py — kernel GPU OFFLINE del pretrain CNN AGI-3
(B full 12x101k, secuencia ratificada para la cuota 2026-10-24T00:00Z).

Genera (R10, determinístico — mismo árbol → mismo kernel.py byte a byte):
  * pretrain_kernel.py   — script self-contained para Kaggle GPU:
      + ActionModel EXACTO del viarc3_agent._build_cnn (embedding VERBATIM
        vía ast — zero architecture drift R16; el hash del extracto va
        impreso y el builder lo compara contra el árbol fuente)
      + mismo schema v4 (load_corpus-drop7 / holdout every-5th / eval_bce /
        Adam CNN_LR / entropy regs del propio agent)
      + NUEVO campo exigido por el prereg: coverage_out_of_sample =
        fracción de filas label==1 del holdout donde argmax(logits) ==
        idx verdadero (top-1 exact over 4101 logits; random ~1/4101)
      + trained_holdout_bce por epoch + REPORT json a /kaggle/working
  * kernel-metadata.json  — private, enable_gpu, internet OFF (v1
    incident agi2: net-ON vacía monturas), dataset
    rmw3kufe/agi3-cnn-corpus-v1 (ready, verificado kaggle CLI)

Smoke local (antes del push, sin GPU):
  python3 kaggle_pretrain/pretrain_kernel.py --limit 500 --epochs 1
   (el kernel detecta modo local: CORPUS=../data/cnn_corpus,
    OUT=/tmp — mismo código, mismos campos prereg)

PUSH (mañana 00:00Z, de-ratificado si S5 mocha):
  kaggle kernels push -p projects/arc-prize/agi3/kaggle_pretrain
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGI3 = HERE.parent
AGENT = AGI3 / "agent" / "viarc3_agent.py"
CORPUS = AGI3 / "data" / "cnn_corpus"

METADATA = {
    "id": "rmw3kufe/viarc-vsm-agi-3-pretrain-bfull",
    "title": "ViArc VSM AGI-3 pretrain B full 12x101k",
    "code_file": "pretrain_kernel.py",
    "language": "python",
    "kernel_type": "script",
    "is_private": True,
    "enable_gpu": True,
    "enable_tpu": False,
    "enable_internet": False,
    "dataset_sources": ["rmw3kufe/agi3-cnn-corpus-v1"],
    "kernel_sources": [],
    "competition_sources": [],
    "model_sources": [],
}

# defaults del script local (train_cnn_offline.py argparse) — B full
EPOCHS, BATCH, LR, SEED = 12, 64, 1e-4, 42


def _extract_cnn() -> str:
    """Extract VERBATIM el bloque _build_cnn() + constantes CNN_* del
    viarc3_agent.py (zero-drift — el embedding sale del texto real)."""
    src = AGENT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    target = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_build_cnn":
            target = (node.lineno, node.end_lineno)
            break
    assert target, "_build_cnn no encontrado"
    a, b = target
    consts = [l for l in lines[:a] if re.match(r"^CNN_\w+ = ", l)]
    block = "\n".join(lines[a - 1:b])
    header = "from typing import Any\n\n"
    return header + "\n".join(consts) + "\n\n" + block


def _drift_sha() -> str:
    return hashlib.sha256(_extract_cnn().encode()).hexdigest()[:16]


def build(out_dir: Path, epochs=EPOCHS, batch=BATCH, lr=LR, seed=SEED) -> None:
    cnn_code = _extract_cnn()
    drift = _drift_sha()
    compile(cnn_code, "<cnn_extract>", "exec")  # syntax-safe fail-loud
    kernel = _render_run(cnn_code, drift, epochs, batch, lr, seed)
    compile(kernel, "<kernel_run>", "exec")
    (out_dir / "pretrain_kernel.py").write_text(kernel, encoding="utf-8")
    (out_dir / "kernel-metadata.json").write_text(
        json.dumps(METADATA, indent=2), encoding="utf-8")
    print(f"kernel:      {out_dir / 'pretrain_kernel.py'} "
          f"({len(kernel.splitlines())} lines)")
    print(f"metadata:    {out_dir / 'kernel-metadata.json'}")
    print(f"drift_sha:   {drift}")


def _render_run(cnn_code, drift, epochs, batch, lr, seed) -> str:
    templ = r'''#!/usr/bin/env python3
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

DRIFT_SHA = "{drift_sha}"
GRID, NCH, NACT = 64, 16, 5
EPOCHS, BATCH, LR, SEED = {epochs}, {batch}, {lr}, {seed}

# ── ActionModel — fábrica v8 R16 (VERBATIM, module-level) ────────
{cnn_code}

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

    print(f"CORPUS={{CORPUS}} OUT={{OUT}} LIMIT={{TRAIN_LIMIT}}", flush=True)
    print(f"DRIFT_SHA={{DRIFT_SHA}}", flush=True)

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
    games = sorted({{os.path.basename(f).split(".")[0]
                  for f in glob.glob(os.path.join(CORPUS, "*.npz"))}})
    holdout = set(games[::5])
    tr_frames, tr_idxs, tr_rews, n7, nh = load_corpus(holdout)
    if TRAIN_LIMIT:
        tr_frames, tr_idxs, tr_rews = (tr_frames[:TRAIN_LIMIT],
                                       tr_idxs[:TRAIN_LIMIT],
                                       tr_rews[:TRAIN_LIMIT])
    print(f"train rows={{len(tr_rews)}} (drop7={{n7}} "
          f"holdout_rows_skipped={{nh}})", flush=True)
    print(f"holdout games ({{len(holdout)}}): {{sorted(holdout)}}",
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
    print(f"holdout rows={{len(H_R)}}", flush=True)

    # ── baseline random init (protocol agente: seeded) ──────────────
    torch.manual_seed(SEED)
    base = ActionModel()
    base_bce = eval_bce(base, H_F, H_I, H_R)
    print(f"baseline random-init heldout BCE: {{base_bce:.5f}}", flush=True)
    del base

    # ── train B full ────────────────────────────────────────────────
    torch.manual_seed(SEED)
    model = ActionModel()
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    n_par = sum(q.numel() for q in model.parameters())
    print(f"params={{n_par}}", flush=True)
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
        print(f"epoch {{ep + 1}}/{{EPOCHS}} train_bce={{tot / nb:.5f}} "
              f"holdout_bce={{hb:.5f}} ({{time.time() - t0:.0f}}s)",
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
    print(f"coverage_out_of_sample={{hits}}/{{n_pos}}={{cov:.4f}}", flush=True)

    # ── report (schema v4 + prereg fields) ──────────────────────────
    os.makedirs(OUT, exist_ok=True)
    report = {{
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
    }}
    with open(os.path.join(OUT, "pretrain_report.json"), "w") as fh:
        fh.write(json.dumps(report, indent=1))
    print("REPORT " + json.dumps(report), flush=True)


if __name__ == "__main__":
    sys.exit(main())
'''
    subst = {
        "drift_sha": drift,
        "cnn_code": cnn_code,
        "epochs": epochs, "batch": batch, "lr": lr, "seed": seed,
    }
    out = templ.format(**subst)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--lr", type=float, default=LR)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = Path(args.out) if args.out else HERE
    build(out, epochs=args.epochs, batch=args.batch, lr=args.lr,
          seed=args.seed)


if __name__ == "__main__":
    main()
