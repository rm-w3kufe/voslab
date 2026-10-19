#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""llm_harness — M1: LLM proposals certified before they compete.

S5 hypothesis (2026-10-16): a local LLM (pre-trained models allowed,
no internet during eval) proposes candidates; OUR verifier filters
hallucinations. Two certify layers, deterministic where possible:

V1 self-consistency: K samples -> majority grid + unanimity ratio
   (greedy/seeded sampling; the same trick as consensus decoding).
V2 LOO-understanding: leave-one-train-out prompts — the model must
   reproduce held-out train outputs before its test prediction is
   trusted (budget-gated: only when V1 is not unanimous).

Ensemble with the symbolic solver: a LOO-verified symbolic PROGRAM
always outranks an LLM guess (certified > fluent); the LLM only takes
attempt_1 when the symbolic side is unverified. attempt_2 stays the
best distinct-family candidate from either side.

Runtime budget is enforced by the caller (kernel watchdog); this
module only counts calls. Model loading is lazy + path-gated so the
local/symbolic pipeline keeps working with no torch installed.
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Callable, List, Optional, Tuple

import llm_serialize as S

Grid = List[List[int]]
Trains = List[Tuple[Grid, Grid]]

K_SAMPLES = int(os.environ.get("LLM_K_SAMPLES", "4"))
LOO_MAX = int(os.environ.get("LLM_LOO_MAX", "2"))
UNANIMOUS = float(os.environ.get("LLM_UNANIMOUS", "0.75"))

_MODEL = None
_TOKENIZER = None
_DEADLINE = None


def set_deadline(epoch_seconds: float) -> None:
    """Hard wall for LLM calls (kernel watchdog lives in the notebook)."""
    global _DEADLINE
    _DEADLINE = float(epoch_seconds)


def _past_deadline() -> bool:
    if _DEADLINE is None:
        return False
    import time
    return time.time() >= _DEADLINE


def model_path() -> Optional[str]:
    """Weight location: env override first, then scan /kaggle/input.

    Datasets mount flat (slug) or nested (owner/slug) depending on
    Kaggle's mounting — walk two levels looking for HF layout
    (config.json + safetensors), never deeper (the eval set is huge).
    """
    env = os.environ.get("LLM_MODEL_PATH", "")
    if env and os.path.isdir(env):
        return env
    root = "/kaggle/input"
    if not os.path.isdir(root):
        return None
    try:
        for name in sorted(os.listdir(root)):
            d1 = os.path.join(root, name)
            cands = [d1]
            try:
                cands += [os.path.join(d1, s) for s in sorted(os.listdir(d1))
                          if os.path.isdir(os.path.join(d1, s))]
            except OSError:
                pass
            for cand in cands:
                try:
                    files = set(os.listdir(cand))
                except OSError:
                    continue
                if "model.safetensors.index.json" in files or (
                        "config.json" in files and
                        any(f.endswith(".safetensors") for f in files)):
                    return cand
    except OSError:
        return None
    return None


def _load():
    global _MODEL, _TOKENIZER
    if _MODEL is not None:
        return True
    path = model_path()
    if not path:
        return False
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            path, torch_dtype=torch.bfloat16, device_map="cuda",
            trust_remote_code=True)
        # r2 adapter (SFT gate): mount/stage then set LLM_ADAPTER_PATH
        adapter = os.environ.get("LLM_ADAPTER_PATH", "")
        if adapter and os.path.isdir(adapter) and os.path.exists(
                os.path.join(adapter, "adapter_config.json")):
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter)
            model = model.merge_and_unload()
            print(f"llm_harness: adapter merged from {adapter}", flush=True)
        model.eval()
        _TOKENIZER, _MODEL = tok, model
        return True
    except Exception:
        _MODEL = None
        return False


def _generate(prompt: str, max_new_tokens: int = 512,
              temperature: float = 0.7) -> str:
    import torch
    tok, model = _TOKENIZER, _MODEL
    messages = [{"role": "system", "content": S.SYSTEM},
                {"role": "user", "content": prompt}]
    text = tok.apply_chat_template(messages, tokenize=False,
                                   add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=max_new_tokens,
            do_sample=temperature > 0, temperature=max(temperature, 1e-5),
            top_p=0.95, pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:],
                      skip_special_tokens=True)


def propose(trains: Trains, test: Grid) -> Optional[dict]:
    """K sampled candidates -> V1 majority certify. Returns dict or None.

    {grid, key, agreement, n_unique, loo_llm} — loo_llm filled by v2
    only when the caller asks (certify_understanding).
    """
    if not _load() or _past_deadline():
        return None
    prompt = S.build_prompt(trains, test)
    grids = []
    for _ in range(K_SAMPLES):
        raw = _generate(prompt, temperature=0.7)
        g = S.grid_from_text(raw)
        if g is not None and S.sanity_shape(g, trains):
            grids.append(g)
    if not grids:
        return None
    keys = Counter(S.grid_to_text(g) for g in grids)
    best_text, votes = keys.most_common(1)[0]
    best = next(g for g in grids if S.grid_to_text(g) == best_text)
    return {"grid": best, "key": tuple(tuple(r) for r in best),
            "agreement": votes / K_SAMPLES,
            "n_unique": len(keys), "loo_llm": None}


def propose_tool_code(trains: Trains, test: Grid) -> Optional[str]:
    """RSI-M2: ask the model for a solve() PROGRAM (tool mode).

    Budget-gated by the caller (covenant decide_budget). Deterministic
    (temperature=0); code goes through rsi_bridge sandbox+LOO certify
    before it may compete — certify-first applies to the toolbox.
    """
    if not _load() or _past_deadline():
        return None
    prompt = S.build_tool_prompt(trains, test)
    raw = _generate(prompt, max_new_tokens=768, temperature=0.0)
    return S.parse_tool_code(raw)


def certify_understanding(trains: Trains, test: Grid,
                          candidate: Grid) -> float:
    """V2 LOO: how many left-out train outputs the model reproduces.

    A fluent hallucinator fails V2; a model that 'got' the rule passes.
    Fraction in [0,1]; caller treats >= 0.5 as understanding.
    """
    if not _load() or _past_deadline() or len(trains) < 2:
        return 0.0
    budget = min(LOO_MAX, len(trains))
    ok = 0
    for i in range(budget):
        others = trains[:i] + trains[i + 1:]
        held_in, held_out = trains[i]
        prompt = S.build_prompt(others, held_in)
        raw = _generate(prompt, max_new_tokens=512, temperature=0.0)
        g = S.grid_from_text(raw)
        if g is not None and g == held_out:
            ok += 1
    return ok / budget


def ensemble_decide(trains: Trains, test: Grid,
                    symbolic: Callable[[Trains, Grid], dict],
                    budget: Optional[dict] = None,
                    ) -> dict:
    """Combine certified LLM with the symbolic propose().

    symbolic(trains, test) -> {"a1": grid|None, "a2": grid|None, "loo": f}
    budget (optional, from covenant.decide_budget): when the symbolic side
    is UNVERIFIED (the tasks that decide the score), we spend slack on the
    RSI-M2 program path — the model proposes solve() CODE, rsi_bridge
    sandbox+LOO-certifies it (certify-first, I1), a certified program
    leads, and it is written back to pattern memory (cross-run growth).
    Grid-LLM remains the fallback within the same gate.
    Returns {"a1", "a2", "source", "llm_meta", "sym_loo"}.
    """
    sym = symbolic(trains, test)
    sym_verified = (sym.get("loo") or 0.0) >= 0.5
    budget = budget or {}
    slack_s = float(budget.get("slack_s", 0.0))

    # RSI-M2 program path: fires only when the symbolic side is unverified
    # (the score-deciding tasks) and there is deadline slack (A0.1: never
    # under pressure). A certified PROGRAM outranks a symbolic guess and a
    # fluent grid guess — certify-first applies to the toolbox (I1).
    if not sym_verified and slack_s > 0:
        program = propose_program(trains, test)
        if program is not None:
            a1 = program["grid"]
            sym_key = (tuple(map(tuple, sym.get("a1")))
                       if sym.get("a1") is not None else None)
            a2 = sym.get("a1") if sym_key != program["key"] else sym.get("a2")
            if a2 is None and sym.get("a1") is not None:
                a2 = sym.get("a1")
            meta = {"program_loo": program["loo"]}
            # write-back: a certified program that generalizes on LOO
            # survives the run and seeds later tasks (and later versions).
            _remember_program(program, trains)
            return {"a1": a1, "a2": a2, "source": "rsi-tool",
                    "llm_meta": meta, "sym_loo": sym.get("loo")}

    llm = propose(trains, test)

    if llm is not None and llm["agreement"] >= UNANIMOUS and not sym_verified:
        loo_llm = certify_understanding(trains, test, llm["grid"])
        llm["loo_llm"] = loo_llm
        if loo_llm >= 0.5:
            a1 = llm["grid"]
            a2 = sym.get("a1") if (sym.get("a1") is not None
                                   and tuple(map(tuple, sym["a1"])) !=
                                   llm["key"]) else sym.get("a2")
            return {"a1": a1, "a2": a2, "source": "llm-certified",
                    "llm_meta": {k: llm[k] for k in
                                 ("agreement", "n_unique", "loo_llm")},
                    "sym_loo": sym.get("loo")}
    # symbolic verified (or no usable LLM): symbolic leads
    a1 = sym.get("a1")
    a2 = sym.get("a2")
    if llm is not None and llm["key"] != tuple(map(tuple, a1 or [])):
        if a2 is None:
            a2 = llm["grid"]
    return {"a1": a1, "a2": a2, "source": "symbolic",
            "llm_meta": ({k: llm[k] for k in ("agreement", "n_unique")}
                         if llm else None),
            "sym_loo": sym.get("loo")}


# ── RSI-M2: program path (LLM decodes CODE, our verifier certifies) ─────

def propose_program(trains: Trains, test: Grid) -> Optional[dict]:
    """Ask the model for a solve() PROGRAM; sandbox+LOO-certify it.

    Returns {"grid", "key", "loo", "code"} only when the tool LOO >= 0.5
    (covenant certify_threshold) — uncertified code never competes (I1).
    Budget-gated by the caller (this is only reached under slack).
    Deterministic decode (temperature=0) per the tool-mode contract.
    """
    if not _load() or _past_deadline():
        return None
    try:
        import rsi_bridge as RSI
    except Exception:
        return None
    code = propose_tool_code(trains, test)
    if not code:
        return None
    try:
        tools = RSI.propose_tools(trains, test, [code])
    except Exception:
        return None
    if not tools:
        return None
    best = tools[0]
    return {"grid": best["grid"], "key": best["key"],
            "loo": float(best["loo_frac"]), "code": code}


def _remember_program(program: dict, trains: Trains) -> bool:
    """Write a certified program back to pattern memory (cross-run, I1).

    Never raises. The program is stored under a hash of its code so
    identical decodes do not duplicate entries.
    """
    try:
        import rsi_bridge as RSI
    except Exception:
        return False
    try:
        name = f"tool_{abs(hash(program['code'])) % 10**8:08d}"
        return bool(RSI.append_pattern(
            name, program["code"], extra={"loo_frac": program["loo"],
                                          "n_trains": len(trains)}))
    except Exception:
        return False
