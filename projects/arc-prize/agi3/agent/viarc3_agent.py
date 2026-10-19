# design: projects/arc-prize/knowledge/viarc3_master_plan.vsm
"""ViArc-3 homeostat + LLM brain (M1.5) — AGI-3 agent.

    perceive (compressed frame) -> model (action-effect stats + history)
    -> goal (WIN) -> plan (systematic novelty / rescue) -> act

Two layers (VSM: tactics R10.1, enforcement R10):
  * BRRAIN — small Qwen staged as competition dataset (T4, offline),
    greedy decode, deterministic budgets (early-first-N, thrash rescue
    points, hard call cap, wall-clock kill-switch). Chooses actions from
    a compressed perception (8x8 dominant-color map + color histogram +
    effect stats + recent history).
  * HOMESTAT — deterministic fallback (seeded xorshift32, uniform pick
    v7 + dead-choice suppression; least-tried retired: Random 0.18 beat
    systematic 0.06 on hidden eval).
    Any brain failure (no model, parse fail, exception, over budget)
    degrades here silently — the harness always gets an action.

M2 adds executable world-model hypotheses + retrodiction certification
on top of the recorded effects; M3 wires python-retrieval tools.
Single-file by design: the Kaggle notebook splices this whole module.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Any

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent

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


class MyAgent(Agent):
    """Homeostat baseline + staged-Qwen brain (M1.5)."""

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

    # ── xorshift32 (R10: no wall-clock, no `random` module) ──────────
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

        # ── brain first (tactics R10.1), homeostat fallback ───────────
        action: GameAction | None = None
        if self._gate():
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
