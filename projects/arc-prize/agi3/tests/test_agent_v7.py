"""Agent unit suite — v7 homeostat + v8 CNN tier (design f5) — deterministic, no network.

Run from anywhere (needs the lab venv: arc-engine + torch CPU for v8):
    ARCLAB=/tmp/opencode/arc3-lab /tmp/opencode/arc3-lab/.venv/bin/python \
        ~/vOSlab/projects/arc-prize/agi3/tests/test_agent_v7.py

v7: xorshift distribution, dead-choice memory (ACTION/coords),
complex action_data x/y, rescue ranking, brain/outer degradation,
episode-reset hygiene. v8: one-hot pad/clip (no assert), masked seeded
sampling, per-step experience, train-step CPU, tier fallback.
R10: no randomness — everything seeded/fixed. v8 torch tests SKIP when
torch is absent (tier must degrade, never crash).
"""
from __future__ import annotations

import importlib.util
import os
import random
import sys
import types
from collections import deque
from pathlib import Path

LAB = Path(os.environ.get("ARCLAB", "/tmp/opencode/arc3-lab"))
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(LAB / "vendor" / "ARC-AGI-3-Agents"))
if not (LAB / "vendor" / "ARC-AGI-3-Agents").exists():
    raise SystemExit(f"lab framework missing at {LAB}/vendor — run make setup")

from arcengine import GameAction, GameState  # noqa: E402

spec = importlib.util.spec_from_file_location("ma", LAB / "agent" / "my_agent.py")
ma = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ma)
MyAgent = ma.MyAgent

PASS: list[tuple[str, bool]] = []


def ok(name: str, cond: bool) -> None:
    PASS.append((name, cond))
    print(("  ✓ " if cond else "  ✗ FAIL ") + name)


def fresh(game_id: str = "t", cnn: bool = False) -> MyAgent:
    a = object.__new__(MyAgent)
    a.game_id = game_id          # Agent.__init__ normally sets this
    a._rng_state = ma._seed(game_id)
    a._effects, a._prev_flat, a._prev_sig = {}, None, None
    a._thrash, a._last_action, a._steps = 0, None, 0
    a._rescue_fired, a._history = set(), []
    a._dead_actions, a._dead_xy = set(), set()
    a._last_xy, a._last_simple = None, False
    # v8 CNN tier (default OFF — v7 tests exercise homeostat/brain only)
    a._cnn, a._cnn_torch, a._cnn_F = None, None, None
    a._cnn_opt, a._cnn_cls, a._cnn_device = None, None, None
    a._cnn_off = not cnn
    a._cnn_buf, a._cnn_hashes = deque(maxlen=20000), set()
    a._cnn_prev, a._cnn_prev_idx, a._cnn_prev_key = None, None, None
    a._cnn_level = None
    a._rand = random.Random(ma._seed(game_id) + 0xC8)
    return a


def frame(state=GameState.NOT_FINISHED, avail=(1, 6), grid=None):
    g = grid if grid is not None else [[(i * 7 + j) % 5 for j in range(8)]
                                       for i in range(8)]
    return types.SimpleNamespace(frame=g, state=state,
                                 available_actions=list(avail))


# ── _parse_action (strict brain I/O) ─────────────────────────────────
avail36 = [GameAction.__members__["ACTION3"], GameAction.__members__["ACTION6"]]
ok("parse valid", ma._parse_action('{"action": "ACTION3"}', avail36)
   is GameAction.ACTION3)
ok("parse invalid→None", ma._parse_action('{"action": "NOPE"}', avail36)
   is None)
ok("parse unavailable→None", ma._parse_action('{"action": "ACTION2"}', avail36)
   is None)

# ── xorshift32 (_next): coverage + uniform repeats ───────────────────
a = fresh()
vals = [a._next(64) for _ in range(4096)]
ok("_next mod64 coverage ≥55/64", len(set(vals)) >= 55)
rep = sum(1 for i in range(len(vals) - 1) if vals[i] == vals[i + 1])
ok("_next consecutive repeats ≤5% (uniform ≈1/64)", rep <= 0.05 * len(vals))

# ── _next_coord avoids dead cells ────────────────────────────────────
a = fresh()
coords = {(x, y) for x in range(64) for y in range(64)}
a._dead_xy = set(sorted(coords)[:1000])
viol = sum(1 for _ in range(200) if a._next_coord() in a._dead_xy)
ok("_next_coord never dead (200 draws)", viol == 0)

# ── dead-choice bookkeeping in _observe_effect ───────────────────────
a = fresh()
a._last_xy, a._last_simple = (3, 4), False
a._observe_effect("ACTION6", False, 0)
ok("complex no-change → dead_xy", (3, 4) in a._dead_xy and not a._dead_actions)
ok("thrash counted", a._thrash == 1)
a._observe_effect("ACTION6", True, 5)
ok("change clears dead + thrash", not a._dead_xy and a._thrash == 0)
a2 = fresh()
a2._last_xy, a2._last_simple = None, True
a2._observe_effect("ACTION1", False, 0)
ok("simple no-change → dead_actions", "ACTION1" in a2._dead_actions)
a3 = fresh()
a3._last_xy, a3._last_simple = None, False
a3._observe_effect("ACTION6", False, 0)
ok("complex-unknown-xy not recorded", not a3._dead_xy and not a3._dead_actions)

# ── is_done: WIN stops the run (Random-parity) ───────────────────────
a = fresh()
ok("is_done WIN→True", a.is_done([], frame(GameState.WIN)) is True)
ok("is_done NOT_FINISHED→False", a.is_done([], frame()) is False)

# ── choose_action happy path ─────────────────────────────────────────
a = fresh()
a._gate = lambda: False
act = a.choose_action([], frame())
ok("returns non-RESET", act is not GameAction.RESET)
ok("complex has x/y via action_data",
   (not act.is_complex())
   or (hasattr(act.action_data, "x") and hasattr(act.action_data, "y")))

# ── changing frames never crash the loop ─────────────────────────────
a = fresh()
a._gate = lambda: False
picks = []
for i in range(60):
    act = a.choose_action([], frame(grid=[[i % 3] * 8 for _ in range(8)]))
    picks.append(act.name)
ok("choose_action 60 steps no crash", len(picks) == 60)

# ── dead suppression: static frame, ACTION1 pre-dead ─────────────────
a = fresh()
a._gate = lambda: False
a._dead_actions = {"ACTION1"}
picks = []
for i in range(40):
    act = a.choose_action([], frame())
    picks.append(act.name)
ok("ACTION1 suppressed while frame static", picks.count("ACTION1") == 0)
ok("ACTION6 fills the frame-static picks", picks.count("ACTION6") == 40)

# ── thrash rescue ranks by change-rate ───────────────────────────────
a = fresh()
a._gate = lambda: False
a._thrash = 6
a._effects = {"ACTION1": [1, 1, 5], "ACTION2": [0, 1, 0], "ACTION6": [0, 1, 0]}
act = a.choose_action([], frame())
ok("rescue picks highest change-rate", act.name == "ACTION1")

# ── outer fallback survives inner crash (v6 contract) ────────────────
a = fresh()
a._choose_action_inner = lambda *x: (_ for _ in ()).throw(RuntimeError("boom"))
act = a.choose_action([], frame())
ok("outer fallback no raise", act is not None and act is not GameAction.RESET)

# ── brain failure degrades to homeostat ──────────────────────────────
a = fresh()
a._gate = lambda: True
a._summary = lambda *x, **k: "S"
a._brain_act = lambda *x: (_ for _ in ()).throw(RuntimeError("llm down"))
act = a.choose_action([], frame())
ok("brain failure degrades to homeostat",
   act is not None and act is not GameAction.RESET)

# ── episode reset clears dead memory ─────────────────────────────────
a = fresh()
a._dead_actions = {"ACTION1"}
a._dead_xy = {(1, 2)}
act = a.choose_action([], frame(GameState.GAME_OVER))
ok("GAME_OVER → RESET + dead cleared",
   act is GameAction.RESET and not a._dead_actions and not a._dead_xy)

# ═════════ v8 CNN tier (design f5_cnn_proposer_v8) ═════════
try:
    import torch  # noqa: F401
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False

if not HAVE_TORCH:
    # graceful degradation contract: tier disables itself, run continues
    a = fresh(cnn=True)
    fr = frame()
    act = a._cnn_act(fr, [GameAction.ACTION1], 0)
    ok("no-torch: _cnn_act returns None (tier disabled, no crash)",
       act is None and a._cnn_off is True)
else:
    cls, tns, Fnn = ma._build_cnn()

    # T1 one-hot pad/clip — variable grids, out-of-range values, no assert
    g = [[-5, 99, 16], [7]]          # 3x2-ish ragged grid
    tens = MyAgent._cnn_tensor(g, tns, Fnn)
    ok("v8 tensor shape [16,64,64]", tuple(tens.shape) == (16, 64, 64))
    ok("v8 clamp low/high (-5→0, 99→15, 16→15)",
       tens[0, 0, 0] == 1.0 and tens[15, 0, 1] == 1.0
       and tens[15, 0, 2] == 1.0)
    ok("v8 pad cells are one-hot zero", tens[:, 1, 1:].sum().item() == 63.0
       and tens[7, 1, 0] == 1.0)

    # T2 masked seeded sampling
    zero_logits = tns.zeros(5 + 64 * 64)
    a1 = fresh(cnn=True)
    a1._cnn_torch = tns
    idx, act = a1._cnn_sample(zero_logits, [GameAction.ACTION1])
    ok("v8 sample only ACTION1 when avail=[1]",
       idx == 0 and act is GameAction.ACTION1 and all(
           a1._cnn_sample(zero_logits, [GameAction.ACTION1])[0] == 0
           for _ in range(10)))
    a1b = fresh(cnn=True)         # fresh RNG states on BOTH sides
    a1c = fresh(cnn=True)
    a1b._cnn_torch = tns
    a1c._cnn_torch = tns
    seq_a = [a1b._cnn_sample(zero_logits, [GameAction.ACTION1,
                                           GameAction.ACTION6])[0]
             for _ in range(6)]
    seq_b = [a1c._cnn_sample(zero_logits, [GameAction.ACTION1,
                                           GameAction.ACTION6])[0]
             for _ in range(6)]
    ok("v8 sampling deterministic (same seed → same seq)",
       seq_a == seq_b and all(i == 0 or i >= 5 for i in seq_a))

    # T3 end-to-end _cnn_act: proposal + experience + train step
    a = fresh(cnn=True)
    fr = frame()
    act = a._cnn_act(fr, [GameAction.ACTION1, GameAction.ACTION6], 0)
    ok("v8 _cnn_act returns an action", act is not None and a._cnn_off is False)
    ok("v8 prev state stored", a._cnn_prev is not None and a._cnn_prev_idx
       is not None and a._cnn_prev_key is not None)
    a._cnn_act(fr, [GameAction.ACTION1, GameAction.ACTION6], 3)
    ok("v8 experience recorded on step 2 (reward=changed)",
       len(a._cnn_buf) == 1 and a._cnn_buf[0][2] == 1.0)
    # refill to batch size and run a real train step
    t0 = a._cnn.conv1.weight.detach().clone()
    for i in range(64):   # CNN_BATCH (ma.CNN_BATCH == 64)
        a._cnn_buf.append((a._cnn_prev, i % 4096, float(i % 2)))
    try:
        a._cnn_train()
        train_ok = True
    except Exception as e:  # pragma: no cover
        print("    train error:", e)
        train_ok = False
    ok("v8 train step CPU no-crash", train_ok)
    ok("v8 weights changed after step",
       not t0.equal(a._cnn.conv1.weight.detach()))

    # T4 tier fallback: disabled tier → None, homeostat still serves
    a = fresh(cnn=False)  # _cnn_off=True
    ok("v8 off-tier returns None fast",
       a._cnn_act(frame(), [GameAction.ACTION1], 0) is None)

n = sum(1 for _, c in PASS if c)
print(f"\nSUITE {n}/{len(PASS)} PASS")
sys.exit(0 if n == len(PASS) else 1)
