# design: projects/arc-prize/knowledge/viarc3_master_plan.vsm
#          + viarc_next_run_plan.vsm f5_cnn_proposer_v8 (R16: v8 CNN tier)
"""ViArc-3 CNN proposer + LLM brain + homeostat — AGI-3 agent.

    perceive (compressed frame) -> model (CNN action-effect prediction)
    -> goal (WIN) -> plan (tiered proposer) -> act

Three tiers (VSM: tactics R10.1, enforcement R10), design f5:
  * CNN — v8, derived from the official StochasticGoose sample (0.25 vs
    our 0.06): conv backbone -> 5+4096 logits (5 buttons + 64x64 coords),
    masked sample, online BCE on "did the frame change", reset per level.
    Seeded from _seed(game_id) — NO time-based entropy (R10).
  * BRAIN — small Qwen staged as competition dataset (T4, offline),
    greedy decode, deterministic budgets (early-first-N, thrash rescue
    points, hard call cap, wall-clock kill-switch). Reached only when
    the CNN tier is unavailable (v8 A/B: brain OFF while CNN runs).
  * HOMESTAT — deterministic fallback (seeded xorshift32, uniform pick
    v7 + dead-choice suppression; least-tried retired: Random 0.18 beat
    systematic 0.06 on hidden eval).
    Any tier failure (no model, parse fail, exception, over budget)
    degrades to the next silently — the harness always gets an action.

M2 adds executable world-model hypotheses + retrodiction certification
on top of the recorded effects; M3 wires python-retrieval tools.
Single-file by design: the Kaggle notebook splices this whole module.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import time
from collections import deque
from typing import Any

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent

# ── CNN tier budgets (v8 — goose parity, R10: fixed constants) ───────
CNN_TRAIN_EVERY = 5     # actions between gradient steps (goose: 5)
CNN_BATCH = 64          # experiences per step (goose: 64)
CNN_BUF_MAX = 20000     # experience cap (goose: 200000; we run 400 actions)
CNN_LR = 1e-4           # Adam lr (goose: 1e-4)
CNN_GRID = 64           # model expects 64x64 (pad/clip — NEVER assert)
CNN_CHANNELS = 16       # one-hot colours 0-15
CNN_N_ACTIONS = 5       # ACTION1-5 modeled; coords cover ACTION6

# ── brain budgets (deterministic — R10: same input, same gate) ───────
BRAIN_EARLY = 6             # first N moves of every game consult the brain
BRAIN_RESCUE = {6, 12, 24}  # thrash-count rescue points
BRAIN_MAX_CALLS = 240       # hard cap per agent instance (kernel safety)
BRAIN_DEADLINE_S = 5400     # wall kill-switch from first load (watchdog,
                            # never a preference — AGI-2 pattern)
BRAIN_MAX_NEW = 64          # tokens per answer (one line)

_BRAIN: dict[str, Any] = {"model": None, "tok": None, "calls": 0,
                          "deadline": None, "loaded": False}

_RE_ACTION = re.compile(r"ACTION\s*([1-7])", re.I)
_RE_XY = [
    re.compile(r"x\s*=\s*(-?\d{1,3})\s*[,\s]+\s*y\s*=\s*(-?\d{1,3})", re.I),
    re.compile(r"\(\s*(-?\d{1,3})\s*,\s*(-?\d{1,3})\s*\)"),
    re.compile(r"\b(-?\d{1,3})\s*,\s*(-?\d{1,3})\b"),
]

_SYS = (
    "You are an ARC-AGI-3 agent playing a 64x64 grid puzzle (colors 0-15). "
    "There are NO instructions: infer the game rules from observed action "
    "effects. Actions: ACTION1-ACTION5 are transformation buttons whose "
    "semantics are game-specific (discover them from effects); ACTION6 "
    "clicks/places at coordinate x,y (0-63); ACTION7 submits the current "
    "frame as the solution; RESET restarts the game. "
    "Reply with EXACTLY ONE line and nothing else: "
    "ACTION<n>   or, only for ACTION6,   ACTION6 x=<col> y=<row>  "
    "(both 0-63, col=x, row=y)."
)


def _seed(game_id: str) -> int:
    return int(hashlib.sha256(game_id.encode()).hexdigest()[:8], 16)


# ── brain plumbing (AGI-2 llm_harness pattern, self-contained) ───────
def model_path() -> str | None:
    """Weight location: env override first, then scan /kaggle/input.

    Datasets mount flat (slug) or nested (owner/slug); walk two levels
    looking for HF layout (config.json + safetensors), never deeper.
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


def _brain_load() -> bool:
    if _BRAIN["model"] is not None:
        return True
    if _BRAIN["loaded"]:            # failed once → don't retry per call
        return False
    path = model_path()
    if not path:
        return False
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        if not torch.cuda.is_available():
            return False            # local lab: deterministic fallback
        tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            path, torch_dtype=torch.bfloat16, device_map="cuda",
            trust_remote_code=True)
        model.eval()
        _BRAIN["tok"], _BRAIN["model"] = tok, model
        _BRAIN["deadline"] = time.time() + BRAIN_DEADLINE_S
        _BRAIN["loaded"] = True
        print(f"[viarc3-brain] loaded {path} on cuda", flush=True)
        return True
    except Exception as e:          # degrade, never crash the harness
        print(f"[viarc3-brain] load failed: {e}", flush=True)
        _BRAIN["loaded"] = True
        return False


def _brain_ok() -> bool:
    if _BRAIN["calls"] >= BRAIN_MAX_CALLS:
        return False
    if _BRAIN["deadline"] and time.time() >= _BRAIN["deadline"]:
        return False                # watchdog only, not a preference
    return _brain_load()


def _brain_line(prompt: str) -> str | None:
    try:
        import torch
        tok, model = _BRAIN["tok"], _BRAIN["model"]
        if tok is None or model is None:
            return None
        messages = [{"role": "system", "content": _SYS},
                    {"role": "user", "content": prompt}]
        text = tok.apply_chat_template(messages, tokenize=False,
                                       add_generation_prompt=True)
        inputs = tok(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=BRAIN_MAX_NEW,
                                 do_sample=False,          # greedy (R10)
                                 pad_token_id=tok.eos_token_id)
        _BRAIN["calls"] += 1
        return tok.decode(out[0][inputs["input_ids"].shape[1]:],
                          skip_special_tokens=True).strip()
    except Exception as e:
        print(f"[viarc3-brain] generate failed: {e}", flush=True)
        return None


def _parse_action(line: str, avail: list[GameAction]) -> GameAction | None:
    """Strict: one valid, available action or None (caller falls back)."""
    m = _RE_ACTION.search(line or "")
    if not m:
        return None
    name = f"ACTION{m.group(1)}"
    if not any(a.name == name for a in avail):
        return None
    action = next(a for a in avail if a.name == name)
    if action.is_complex():
        xy = None
        for rx in _RE_XY:
            mx = rx.search(line)
            if mx:
                xy = (int(mx.group(1)), int(mx.group(2)))
                break
        if xy is None:
            return None
        x, y = max(0, min(63, xy[0])), max(0, min(63, xy[1]))
        action.set_data({"x": x, "y": y})   # validated by ComplexAction
    return action


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


class MyAgent(Agent):
    """Tiered proposer (v8 CNN -> brain -> v7 homeostat baseline)."""

    MAX_ACTIONS = 400

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rng_state = _seed(self.game_id)
        # per-action effect stats: action -> [changed, tried, cells]
        self._effects: dict[str, list[int]] = {}
        self._prev_flat: tuple | None = None
        self._prev_sig: tuple | None = None
        self._thrash = 0
        self._last_action: str | None = None
        self._steps = 0            # non-reset moves this game
        self._rescue_fired: set[int] = set()
        self._history: list[str] = []   # recent "ACTIONn -> effect" lines
        # v7 dead-choice memory (cleared whenever the frame changes):
        self._dead_actions: set[str] = set()          # simple, no-change
        self._dead_xy: set[tuple[int, int]] = set()   # coords, no-change
        self._last_xy: tuple[int, int] | None = None
        self._last_simple = False
        # v8 CNN tier state (design f5):
        self._cnn = None            # ActionModel | None (lazy)
        self._cnn_torch = None
        self._cnn_F = None
        self._cnn_opt = None
        self._cnn_off = False       # permanent disable after build failure
        self._cnn_buf: deque[tuple[Any, int, float]] = deque(maxlen=CNN_BUF_MAX)
        self._cnn_hashes: set[str] = set()
        self._cnn_prev = None        # one-hot tensor of previous frame
        self._cnn_prev_idx: int | None = None
        self._cnn_prev_key: str | None = None
        self._cnn_level: int | None = None
        # instance-seeded RNG for CNN sampling/batches (R10: no global
        # random, no time-based seed — same game_id, same sequence)
        self._rand = random.Random(_seed(self.game_id) + 0xC8)

    # ── xorshift32 (R10: no wall-clock; no GLOBAL random — the CNN
    #    sampler below uses an instance-seeded random.Random instead) ──
    # v7: LCG % 64 used low bits (2^31 modulus ⇒ tiny lattice ⇒ repeated
    # coords, ft09: 150/200 clicks changed nothing). High bits instead.
    def _next(self, n: int) -> int:
        x = self._rng_state or 0x9E3779B9
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self._rng_state = x
        return (x >> 8) % n

    def _next_coord(self) -> tuple[int, int]:
        """xy draw that avoids this frame's dead (no-change) cells."""
        x, y = 0, 0
        for _ in range(24):
            x, y = self._next(64), self._next(64)
            if (x, y) not in self._dead_xy:
                break
        return x, y

    @property
    def name(self) -> str:
        return f"viarc3-brain.{self.MAX_ACTIONS}"

    # ── perceive: compressed frame signature (frame is 3D: [1][H][W]) ─
    @staticmethod
    def _flat(grid: Any) -> tuple:
        if isinstance(grid, list):
            out: list[int] = []
            for item in grid:
                if isinstance(item, list):
                    out.extend(MyAgent._flat(item))
                else:
                    out.append(int(item))
            return tuple(out)
        return tuple(int(v) for v in grid)  # numpy array

    @classmethod
    def _sig(cls, frame: FrameData) -> tuple:
        flat = cls._flat(frame.frame)
        nz = sum(1 for v in flat if v)
        h = hash(flat) & 0xFFFFFFFF  # int-tuple hash: run-stable (R10)
        return (len(flat), nz, h)

    @staticmethod
    def _to_actions(codes: list[int]) -> list[GameAction]:
        names = {0: "RESET"}
        out = []
        for c in codes:
            name = names.get(c, f"ACTION{c}" if 1 <= c <= 7 else None)
            if name and name in GameAction.__members__:
                out.append(GameAction.__members__[name])
        return out

    def is_done(self, frames: list[FrameData], latest_frame: FrameData) -> bool:
        return latest_frame.state is GameState.WIN

    # ── model: record action effects (retrodiction fodder for M2) ─────
    def _observe_effect(self, action_name: str, changed: bool,
                        cells: int) -> None:
        slot = self._effects.setdefault(action_name, [0, 0, 0])
        slot[1] += 1
        if changed:
            slot[0] += 1
            slot[2] += cells
            self._thrash = 0
            # new landscape ⇒ old dead spots may be live again (v7)
            self._dead_actions.clear()
            self._dead_xy.clear()
        else:
            self._thrash += 1
            # v7: remember the choice that wasted this step (current frame)
            if self._last_xy is not None:
                self._dead_xy.add(self._last_xy)      # complex, xy known
            elif self._last_simple:
                self._dead_actions.add(action_name)   # simple, by name
            # complex w/o known xy (brain path): skip — nothing to remember

    # ── perception summary (compact — T4 context stays tiny) ──────────
    @staticmethod
    def _grid_2d(frame: FrameData) -> list[list[int]]:
        g: Any = frame.frame
        while g and isinstance(g[0], list) and g[0] and isinstance(g[0][0], list):
            g = g[0]                     # unwrap singleton planes
        return g if g and isinstance(g[0], list) else [[]]

    @staticmethod
    def _block_map(grid: list[list[int]], h: int = 8, w: int = 8) -> str:
        """h x w dominant-nonzero-color map (hex digit, '.'=empty)."""
        rows = len(grid) or 1
        cols = len(grid[0]) if grid and grid[0] else 1
        out = []
        for by in range(h):
            line = []
            for bx in range(w):
                counts: dict[int, int] = {}
                for y in range(by * rows // h, (by + 1) * rows // h):
                    row = grid[y]
                    for x in range(bx * cols // w, (bx + 1) * cols // w):
                        v = row[x]
                        if v:
                            counts[v] = counts.get(v, 0) + 1
                line.append(format(max(counts, key=counts.get), "x")
                            if counts else ".")
            out.append("".join(line))
        return " / ".join(out)

    def _summary(self, latest: FrameData, avail: list[GameAction],
                 changed: int) -> str:
        flat = self._flat(latest.frame)
        hist: dict[int, int] = {}
        for v in flat:
            if v:
                hist[v] = hist.get(v, 0) + 1
        colors = " ".join(f"{c}:{n}" for c, n in sorted(hist.items())[:8])
        eff = " ".join(
            f"{n}: {s[0]}/{s[1]}ch" + (f"~{s[2] // s[0]}c" if s[0] else "")
            for n, s in sorted(self._effects.items()))
        avail_s = ", ".join(a.name for a in avail)
        recent = " | ".join(self._history[-6:])
        grid = self._grid_2d(latest)
        return (
            f"game={self.game_id} state={latest.state.name} "
            f"levels={latest.levels_completed} steps={self._steps} "
            f"last_change={changed}cells thrash={self._thrash}\n"
            f"available: {avail_s}\n"
            f"effects: {eff or '(none)'}\n"
            f"recent: {recent or '(none)'}\n"
            f"colors(non-zero): {colors or '(none)'}\n"
            f"frame map 8x8 dominant color: {self._block_map(grid)}\n"
            f"next action (one line):"
        )

    def _brain_act(self, summary: str,
                   avail: list[GameAction]) -> GameAction | None:
        if not _brain_ok():
            return None
        line = _brain_line(summary)
        if line:
            print(f"[viarc3-brain] #{_BRAIN['calls']} {line[:80]}",
                  flush=True)
        return _parse_action(line, avail) if line else None

    # ── v8 CNN tier (design f5: goose-derived, seeded, degrades) ─────
    def _cnn_init(self) -> bool:
        """Lazy build; failure disables the tier permanently (logged)."""
        if self._cnn_off:
            return False
        if self._cnn is not None:
            return True
        try:
            cls, torch, F = _build_cnn()
            torch.manual_seed(_seed(self.game_id))  # R10: seeded weights
            device = torch.device("cuda" if torch.cuda.is_available()
                                  else "cpu")
            self._cnn = cls().to(device)
            self._cnn_cls = cls
            self._cnn_device = device
            self._cnn_torch, self._cnn_F = torch, F
            self._cnn_opt = torch.optim.Adam(self._cnn.parameters(),
                                             lr=CNN_LR)
            self._cnn.eval()   # dropout off at inference
            n_par = sum(p.numel() for p in self._cnn.parameters())
            print(f"[viarc3-cnn] loaded device={device} params={n_par}",
                  flush=True)
            return True
        except Exception as e:
            print(f"[viarc3-cnn] disabled: {e!r}", flush=True)
            self._cnn_off = True
            return False

    def _cnn_reset_level(self, level: int) -> None:
        """Per-level reset — goose parity ('Cleared experience buffer')."""
        torch = self._cnn_torch
        self._cnn_buf.clear()
        self._cnn_hashes.clear()
        self._cnn_prev = None
        self._cnn_prev_idx = None
        self._cnn_prev_key = None
        torch.manual_seed(_seed(self.game_id) + int(level))
        self._cnn = self._cnn_cls().to(self._cnn_device)
        self._cnn_opt = torch.optim.Adam(self._cnn.parameters(), lr=CNN_LR)
        self._cnn.eval()
        print(f"[viarc3-cnn] level {level}: model+buffer reset", flush=True)

    @staticmethod
    def _cnn_tensor(grid: list, torch: Any, F: Any) -> Any:
        """one-hot [16,64,64] from a variable grid — pad/clip, NEVER
        assert (v8 lesson: asserts kill runs)."""
        h = len(grid)
        rows = []
        for i in range(CNN_GRID):
            src = grid[i][:CNN_GRID] if i < h else []
            row = [min(15, max(0, int(v))) for v in src]
            row += [0] * (CNN_GRID - len(row))
            rows.append(row)
        g = torch.tensor(rows, dtype=torch.long)
        return F.one_hot(g, num_classes=CNN_CHANNELS).permute(2, 0, 1).float()

    def _cnn_sample(self, logits: Any,
                    avail: list[GameAction]) -> tuple[int, GameAction | None]:
        """Masked sample over 5 buttons + 4096 coords (goose parity:
        sigmoid /4096 for coords, normalize, seeded choice). idx=-1 when
        everything is masked — caller degrades to the next tier."""
        p = self._cnn_torch.sigmoid(logits).detach().cpu().tolist()
        weights: list[float] = []
        for i in range(CNN_N_ACTIONS):
            code = i + 1
            ok = any(a.value == code for a in avail)
            weights.append(p[i] if ok else 0.0)
        a6 = any(a.value == 6 for a in avail)
        if a6:
            weights.extend(v / (CNN_GRID * CNN_GRID)
                           for v in p[CNN_N_ACTIONS:])
        else:
            weights.extend([0.0] * (CNN_GRID * CNN_GRID))
        total = sum(weights)
        if total <= 0:
            return -1, None
        idx = self._rand.choices(range(len(weights)), weights=weights,
                                 k=1)[0]
        if idx < CNN_N_ACTIONS:
            code = idx + 1
            return idx, next(a for a in avail if a.value == code)
        ci = idx - CNN_N_ACTIONS
        x, y = ci % CNN_GRID, ci // CNN_GRID
        action = next(a for a in avail if a.value == 6)
        action.set_data({"x": x, "y": y})
        return idx, action

    def _cnn_train(self) -> None:
        """One seeded gradient step on (frame, action, frame_changed)."""
        torch, F = self._cnn_torch, self._cnn_F
        if len(self._cnn_buf) < CNN_BATCH:
            return
        idxs = self._rand.sample(range(len(self._cnn_buf)), CNN_BATCH)
        batch = [self._cnn_buf[i] for i in idxs]
        dev = self._cnn_device
        states = torch.stack([b[0] for b in batch]).to(dev)
        actions = torch.tensor([b[1] for b in batch], dtype=torch.long,
                               device=dev)
        rewards = torch.tensor([b[2] for b in batch], dtype=torch.float32,
                               device=dev)
        self._cnn.train()
        self._cnn_opt.zero_grad()
        logits = self._cnn(states)
        sel = logits.gather(1, actions.unsqueeze(1)).squeeze(1)
        main = F.binary_cross_entropy_with_logits(sel, rewards)
        probs = torch.sigmoid(logits)
        loss = (main
                - 0.0001 * probs[:, :CNN_N_ACTIONS].mean()
                - 0.00001 * probs[:, CNN_N_ACTIONS:].mean())
        loss.backward()
        self._cnn_opt.step()
        self._cnn.eval()

    def _cnn_act(self, latest_frame: Any, avail: list[GameAction],
                 changed_cells: int) -> GameAction | None:
        """Tier 1 (v8): CNN proposer — returns None on any failure so
        brain/homeostat take over (harness never dies: v6 contract)."""
        try:
            if not self._cnn_init():
                return None
            torch = self._cnn_torch
            # per-level reset (goose: score change -> fresh model)
            lvl = getattr(latest_frame, "levels_completed", None)
            if isinstance(lvl, int) and lvl != self._cnn_level:
                first = self._cnn_level is None
                self._cnn_level = lvl
                if not first:
                    self._cnn_reset_level(lvl)
            grid = self._grid_2d(latest_frame)
            tens = self._cnn_tensor(grid, torch, self._cnn_F)
            # experience for the PREVIOUS (frame, action) pair
            if (self._cnn_prev is not None and self._cnn_prev_idx is not None
                    and self._cnn_prev_key is not None
                    and self._cnn_prev_key not in self._cnn_hashes):
                self._cnn_hashes.add(self._cnn_prev_key)
                self._cnn_buf.append((self._cnn_prev, self._cnn_prev_idx,
                                      1.0 if changed_cells else 0.0))
            with torch.no_grad():
                logits = self._cnn(tens.unsqueeze(0)).squeeze(0)
            idx, action = self._cnn_sample(logits, avail)
            if action is None:
                return None
            self._cnn_prev = tens
            self._cnn_prev_idx = idx
            self._cnn_prev_key = hashlib.md5(
                str(tens.flatten().tolist()).encode()).hexdigest()
            if self._steps % CNN_TRAIN_EVERY == 0 and \
                    len(self._cnn_buf) >= CNN_BATCH:
                try:
                    self._cnn_train()
                except Exception as e:
                    print(f"[viarc3-cnn] train skipped: {e!r}", flush=True)
            return action
        except Exception as e:
            print(f"[viarc3-cnn] act failed: {e!r}", flush=True)
            return None

    def _gate(self) -> bool:
        """Deterministic brain-consult gate (R10)."""
        if self._steps < BRAIN_EARLY:
            return True
        pending = BRAIN_RESCUE - self._rescue_fired
        if self._thrash in pending:
            return True
        return False

    def choose_action(
        self, frames: list[FrameData], latest_frame: FrameData
    ) -> GameAction:
        """v6 hardening: outer guard — no exception may kill Phase B
        (the v8 death mode). Any failure degrades to the safest
        deterministic action, never raises into the harness."""
        try:
            return self._choose_action_inner(frames, latest_frame)
        except Exception as e:
            print(f"[viarc3] choose_action fallback: {e!r}", flush=True)
            try:
                if latest_frame.state in (GameState.NOT_PLAYED,
                                          GameState.GAME_OVER):
                    return GameAction.RESET
                avail = [a for a in
                         self._to_actions(latest_frame.available_actions)
                         if a is not GameAction.RESET]
                if not avail:
                    return GameAction.RESET
                action = sorted(avail, key=lambda a: a.name)[0]
                if action.is_complex():
                    action.set_data({"x": 0, "y": 0})
                self._last_xy = None       # v7: keep dead-memory honest
                self._last_simple = action.is_simple()
                return action
            except Exception:
                return GameAction.RESET

    def _choose_action_inner(
        self, frames: list[FrameData], latest_frame: FrameData
    ) -> GameAction:
        if latest_frame.state in (GameState.NOT_PLAYED, GameState.GAME_OVER):
            self._prev_sig = None
            self._prev_flat = None
            self._dead_actions.clear()   # v7: fresh episode ⇒ fresh memory
            self._dead_xy.clear()
            return GameAction.RESET

        flat = self._flat(latest_frame.frame)
        sig = self._sig(latest_frame)
        avail = [
            a for a in self._to_actions(latest_frame.available_actions)
            if a is not GameAction.RESET
        ] or [a for a in GameAction if a is not GameAction.RESET]

        # attribute last action's effect (algedonic: waste = no change)
        changed_cells = 0
        if self._prev_flat is not None and len(self._prev_flat) == len(flat):
            changed_cells = sum(1 for a, b in zip(self._prev_flat, flat)
                                if a != b)
        if self._last_action is not None and self._prev_sig is not None:
            self._observe_effect(self._last_action, sig != self._prev_sig,
                                 changed_cells)
            self._history.append(
                f"{self._last_action}->{'%dc' % changed_cells if changed_cells else 'no change'}")
            self._history = self._history[-8:]
        self._last_xy = None        # v7: consumed by _observe_effect above
        self._last_simple = False

        self._steps += 1

        # ── v8 tiers (design f5): CNN first, brain, homeostat ─────────
        action: GameAction | None = None
        action = self._cnn_act(latest_frame, avail, changed_cells)
        if action is None and self._gate():
            if self._thrash in BRAIN_RESCUE:
                self._rescue_fired.add(self._thrash)
            try:
                summary = self._summary(latest_frame, avail, changed_cells)
                action = self._brain_act(summary, avail)
            except Exception as e:   # brain must never crash the harness
                print(f"[viarc3-brain] act failed: {e}", flush=True)
                action = None

        if action is None:
            # v7: seeded-UNIFORM pick (hidden eval: Random 0.18 beat our
            # systematic least-tried 0.06) + dead-choice suppression.
            # Thrash rescue keeps change-rate ranking as before.
            live = [a for a in avail
                    if not (a.is_simple() and a.name in self._dead_actions)]
            live = live or avail
            if self._thrash >= 6:
                scored = sorted(
                    live,
                    key=lambda a: (
                        -self._effects.get(a.name, [0, 0, 0])[0]
                        / max(1, self._effects.get(a.name, [0, 0, 0])[1]),
                        a.name,
                    ),
                )
                action = scored[0]
            else:
                action = live[self._next(len(live))]
            if action.is_complex():
                x, y = self._next_coord()
                action.set_data({"x": x, "y": y})
                self._last_xy = (x, y)
        self._last_simple = action.is_simple()

        if action.is_complex():
            action.reasoning = {"why": "viarc3 m1.5", "thrash": self._thrash,
                                "steps": self._steps}
        else:
            action.reasoning = (
                f"viarc3: tried="
                f"{self._effects.get(action.name, [0, 0, 0])[1]}")

        self._prev_sig = sig
        self._prev_flat = flat
        self._last_action = action.name
        return action
