#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_master_plan.vsm
"""sft_train.py — LoRA fine-tuner for the ViArc-2 grid proposer (r2).

    SFT_BASE=/kaggle/input/qwen3-4b-instruct \
    SFT_DATA=/kaggle/working/data/sft \
    python3 sft_train.py [--config config/harness_config.json] [--out OUT]

Config-driven from harness_config.json → sft section (single source of
truth; edit there, not here):
  LoRA r/alpha/dropout, target attn q/k/v/o, seq_len, lr, epochs,
  per-device bs × grad-accum, warmup, precision auto (bf16 on Ampere+,
  fp16 on T4/Turing), seed.

Outputs (--out, default $SFT_OUT or ./adapter_r2):
  adapter_config.json + adapter_model.safetensors + TRAIN_META.json
  (provenance: base, config hash, data stats, final losses) — staged as
  the r2_sft_adapter dataset for kernel mount.

R10: fixed seed, deterministic dataloading order (sorted jsonl), no RNG
in eval; bitwise reproducibility across GPU archs is NOT claimed (tactic
layer, R10.1) — the gate is the held-out p1 benchmark, not bit equality.
Requires: torch, transformers, peft, datasets not required (stdlib jsonl).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def load_cfg(path: str) -> dict:
    with open(path) as fp:
        cfg = json.load(fp)
    sft = cfg.get("sft")
    if not sft or "lora_r" not in sft:
        raise SystemExit(f"{path}: sft.lora_r missing — extend config first")
    return sft


def load_jsonl(path: str, limit: int = 0) -> list[dict]:
    rows = []
    with open(path) as fp:
        for line in fp:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def build_dataset(rows: list[dict], tok, seq_len: int):
    """Chat template → input_ids/labels (R10: stable order as-is)."""
    out_ids, out_masks, out_labels = [], [], []
    for r in rows:
        text = tok.apply_chat_template(r["messages"], tokenize=False,
                                       add_generation_prompt=False)
        enc = tok(text, truncation=True, max_length=seq_len,
                  add_special_tokens=False)
        ids = enc["input_ids"]
        out_ids.append(ids)
        out_masks.append(enc["attention_mask"])
        out_labels.append(list(ids))          # full-sequence SFT
    return out_ids, out_masks, out_labels


class ListDataset:
    """Minimal torch-compatible dataset (no HF datasets dependency)."""

    def __init__(self, ids, masks, labels):
        self.ids, self.masks, self.labels = ids, masks, labels

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, i):
        return {"input_ids": self.ids[i], "attention_mask": self.masks[i],
                "labels": self.labels[i]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config",
                    default=os.path.join(HERE, "config", "harness_config.json"))
    ap.add_argument("--data", default=os.environ.get(
        "SFT_DATA", os.path.join(HERE, "..", "data", "sft")))
    ap.add_argument("--base", default=os.environ.get("SFT_BASE", ""))
    ap.add_argument("--out", default=os.environ.get("SFT_OUT",
                                                    os.path.join(HERE, "adapter_r2")))
    ap.add_argument("--eval-samples", type=int, default=500)
    args = ap.parse_args()

    sft = load_cfg(args.config)
    base = args.base
    if not base or not os.path.isdir(base):
        raise SystemExit(f"SFT_BASE not a directory: {base!r} "
                         "(stage the model or set env)")

    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              Trainer, TrainingArguments)
    from peft import LoraConfig, TaskType, get_peft_model

    seed = int(sft["seed"])
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    precision = sft.get("precision", "auto")
    if precision == "auto":
        bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    else:
        bf16 = precision == "bf16"
    fp16 = torch.cuda.is_available() and not bf16
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"base={base} dev={dev} bf16={bf16} fp16={fp16}", flush=True)

    tok = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        base,
        torch_dtype=(torch.bfloat16 if bf16 else torch.float16)
        if dev == "cuda" else torch.float32,
        trust_remote_code=True)
    model.config.use_cache = False

    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=int(sft["lora_r"]), lora_alpha=int(sft["lora_alpha"]),
        lora_dropout=float(sft["lora_dropout"]),
        target_modules=list(sft["target_modules"]),
        bias="none",
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    train_path = os.path.join(args.data, "train.jsonl")
    held_path = os.path.join(args.data, "heldout.jsonl")
    tr_ids, tr_m, tr_l = build_dataset(load_jsonl(train_path), tok,
                                       int(sft["seq_len"]))
    he_ids, he_m, he_l = build_dataset(load_jsonl(held_path, args.eval_samples),
                                       tok, int(sft["seq_len"]))
    print(f"train={len(tr_ids)} heldout_eval={len(he_ids)}", flush=True)

    # deterministic order (R10): jsonl is already written in sorted-tid order
    train_ds = ListDataset(tr_ids, tr_m, tr_l)
    eval_ds = ListDataset(he_ids, he_m, he_l)

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    # v5 (v4 incident): image transformers dropped `warmup_ratio` from
    # TrainingArguments. Filter kwargs by the image's real signature,
    # preserving the ratified 3% warmup as explicit warmup_steps; any
    # other removed kwarg is dropped LOUDLY (printed), never crashed.
    import inspect
    import math as _math
    t_kwargs = dict(
        output_dir=os.path.join(out_dir, "ckpt"),
        num_train_epochs=float(sft["epochs"]),
        per_device_train_batch_size=int(sft["per_device_bs"]),
        gradient_accumulation_steps=int(sft["grad_accum"]),
        learning_rate=float(sft["lr"]),
        warmup_ratio=float(sft["warmup_ratio"]),
        lr_scheduler_type="cosine",
        logging_steps=25,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        bf16=bf16, fp16=fp16,
        gradient_checkpointing=True,
        dataloader_num_workers=2,
        report_to=[],
        seed=seed, data_seed=seed,
        remove_unused_columns=False,
    )
    _params = inspect.signature(TrainingArguments.__init__).parameters
    if "warmup_ratio" not in _params:
        t_kwargs.pop("warmup_ratio")
        if "warmup_steps" in _params:
            _total = _math.ceil(
                len(tr_ids) / (int(sft["per_device_bs"])
                               * int(sft["grad_accum"]))) * int(sft["epochs"])
            t_kwargs["warmup_steps"] = max(
                1, round(_total * float(sft["warmup_ratio"])))
            print("warmup_ratio absent -> warmup_steps:",
                  t_kwargs["warmup_steps"], "of", _total)
    _dropped = [k for k in list(t_kwargs) if k not in _params]
    for k in _dropped:
        t_kwargs.pop(k)
    if _dropped:
        print("TrainingArguments dropped (absent in image):", _dropped)
    args_t = TrainingArguments(**t_kwargs)
    trainer = Trainer(model=model, args=args_t,
                      train_dataset=train_ds, eval_dataset=eval_ds,
                      processing_class=tok)
    res = trainer.train()
    held_loss = trainer.evaluate()["eval_loss"]

    trainer.model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    cfg_hash = hashlib.sha256(
        open(args.config, "rb").read()).hexdigest()[:16]
    meta = {
        "base": base, "config_hash": cfg_hash,
        "lora_r": sft["lora_r"], "lora_alpha": sft["lora_alpha"],
        "seq_len": sft["seq_len"], "epochs": sft["epochs"],
        "train_examples": len(tr_ids), "eval_samples": len(he_ids),
        "train_loss": float(res.training_loss),
        "heldout_loss": float(held_loss),
        "train_seconds": round(time.time() - t0, 1),
        "precision": "bf16" if bf16 else ("fp16" if fp16 else "fp32"),
        "gate": sft["gate"],
    }
    with open(os.path.join(out_dir, "TRAIN_META.json"), "w") as fp:
        json.dump(meta, fp, indent=2)
    print(json.dumps(meta, indent=2), flush=True)
    print(f"adapter saved: {out_dir}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
