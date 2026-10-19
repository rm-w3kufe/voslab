#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Build the self-contained Kaggle submission notebook (stdlib only).

    python3 arc-solver/build_notebook.py [--out kaggle_notebook.ipynb]

v11 (2026-10-19) — judge-schema exactness (AGI-2 0.00 forensic):

* **Entry schema == sample_submission** — the final write strips the
  internal ``loo``/``source`` telemetry from every entry: sample entries
  carry ``attempt_1``/``attempt_2`` ONLY, and in-file extras were the
  sole schema deviation found in the 2026-10-18 judged file (259/259
  entries). Gates still read telemetry from ``sub`` in memory; partials
  in /tmp/viarc keep it for resume/forensics.

v10 (2026-10-17) — review-driven corrections, all offline at eval time:

* **Schema whitelist** — only keys present in the competition's
  ``sample_submission.json`` (240 scored test tasks) are solved and
  written. Earlier runs solved the discovered union (1120) which made
  the file schema-invalid (root cause of the 2026-09-12 no-score).
* **Operating point K=4 + LOO=2** — budget concentrated on the 240
  scored tasks: ~82s/puzzle x 240 = 5.5h < 9.5h LLM guard.
* **Judge-legible format** — one ``%%writefile`` cell per module (the
  AGI-3 starter pattern) instead of a single 330KB dict line; markdown
  header cell; deterministic nbformat cell ids.
* **Output hygiene** — modules/partial/memory live in /tmp/viarc;
  /kaggle/working is cleaned of stale artifacts on start so the final
  root holds ONLY submission.json (output-file picker safety).
* **Fail loud with evidence** — discovery/whitelist asserts print
  ``ls`` of /kaggle/input before raising.
"""
import argparse
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TMPDIR = "/tmp/viarc"
MODULES = ["recognizer.py", "solver_smart_v2.py", "solver_v3.py",
           "rsi_module.py", "agent.py", "solve.py", "rsi_bridge.py",
           "composer.py", "llm_serialize.py", "llm_harness.py",
           "covenant.py", "predicates.py", "checks.py"]

SETUP_CELL = '''import os
os.makedirs("/tmp/viarc", exist_ok=True)
'''

RUN_CELL = '''import glob, json, os, sys, time

# Operating point: K=4 self-consistency + 2 LOO checks certified over
# ONLY the scored test tasks (sample_submission keys). At ~82s/puzzle
# that is 240 x 82s = 5.5h < the 9.5h LLM guard; the symbolic tail
# still finishes the schema if certify falls behind.
os.environ.setdefault("LLM_K_SAMPLES", "4")
os.environ.setdefault("LLM_LOO_MAX", "2")

# Higiene (AGI-3 lesson): modules/partial/memory live in /tmp —
# /kaggle/working keeps ONLY submission.json (picker safety).
WORK = "/kaggle/working"
TMP = "/tmp/viarc"
os.makedirs(TMP, exist_ok=True)
for _f in os.listdir(WORK):
    _p = os.path.join(WORK, _f)
    if os.path.isfile(_p) and (_f.endswith(".py") or _f in (
            "submission.json", "submission.partial.json",
            "pattern_memory_export.json")):
        os.remove(_p)  # stale artifacts from previous kernel versions
print("working root after clean:", sorted(os.listdir(WORK)))

sys.path.insert(0, TMP)
import solve
from solve import solve_all_tests
import covenant as COV

CANDIDATES = ["/kaggle/input"]

# Poison guard (2026-10-17): HF tokenizer vocabs (vocab.json) contain the
# literal token strings "train"/"test" with int ids — a bare key check
# would register them as ARC tasks and kill the run with
# TypeError: 'int' object is not iterable. Require real task shape.
def _is_task(x):
    if not isinstance(x, dict): return False
    tr, te = x.get("train"), x.get("test")
    if not isinstance(tr, list) or not isinstance(te, list): return False
    if not tr or not te: return False
    return all(isinstance(p, dict) and isinstance(p.get("input"), list)
               for p in tr) and all(
                   isinstance(p, dict) and isinstance(p.get("input"), list)
                   for p in te)

tasks = {}
for root in CANDIDATES:
    for dirpath, _dn, files in os.walk(root):
        if dirpath.count(os.sep) - root.count(os.sep) > 3:
            continue
        for f in files:
            if not f.endswith(".json"):
                continue
            p = os.path.join(dirpath, f)
            try:
                with open(p) as fp:
                    d = json.load(fp)
            except Exception as e:
                print("skip unreadable", p, e)
                continue
            if _is_task(d):
                tasks[os.path.splitext(f)[0]] = d
            elif isinstance(d, dict):
                for tid, t in d.items():
                    if _is_task(t):
                        tasks[tid] = t
print("tasks found:", len(tasks))
if not tasks:
    print("listdir /kaggle/input:", sorted(os.listdir("/kaggle/input"))[:50])
    raise SystemExit("no ARC tasks discovered under /kaggle/input")

# --- scored-key whitelist (schema contract; fixes the sep-12 no-score) ---
# sample_submission defines exactly the keys evaluation compares.
# Solving the extra training/eval keys made earlier files invalid.
sample_path = None
for _root in CANDIDATES:
    for _dp, _dn, _fs in os.walk(_root):
        if _dp.count(os.sep) - _root.count(os.sep) > 4:
            continue
        if "sample_submission.json" in _fs:
            sample_path = os.path.join(_dp, "sample_submission.json")
            break
    if sample_path:
        break
if not sample_path:
    print("listdir /kaggle/input:", sorted(os.listdir("/kaggle/input"))[:50])
    raise SystemExit("sample_submission.json not found under /kaggle/input")
with open(sample_path) as fp:
    VALID = set(json.load(fp))
assert VALID, "sample_submission.json has no keys"
missing = sorted(VALID - set(tasks))
if missing:
    print("WARNING: scored keys absent from discovery:", missing[:20])
target = sorted(t for t in tasks if t in VALID)
print(f"serving {len(target)} scored tasks "
      f"(sample keys: {len(VALID)}, discovered: {len(tasks)})")

def valid_grid(g):
    return (isinstance(g, list) and g and all(
        isinstance(r, list) and r and all(
            isinstance(v, int) and 0 <= v <= 9 for v in r) for r in g))

# M1 (2026-10-16): LLM deadline guard + resumable partial. The LLM
# path serves puzzles until the deadline; the rest fall back to the
# symbolic engine (always fast, always completes the schema).
t0 = time.time()
DEADLINE_S = float(os.environ.get("LLM_BUDGET_SECONDS", str(9.5 * 3600)))
try:
    import llm_harness as LH
    LH.set_deadline(t0 + DEADLINE_S)
    print(f"llm budget: {DEADLINE_S/3600:.1f}h, model:",
          "staged" if LH.model_path() else "absent (symbolic only)")
except Exception as e:
    print("llm harness unavailable:", e)

PART = os.path.join(TMP, "submission.partial.json")
sub = {}
if os.path.exists(PART):
    try:
        sub = json.load(open(PART))
        print("resumed from partial:", len(sub), "tasks")
    except Exception:
        sub = {}

SMOKE_N = int(os.environ.get("SMOKE_N", "0"))  # 12 = GPU smoke; 0 = full
for tid in target[:SMOKE_N or None]:
    if tid in sub:
        continue
    try:
        preds = solve_all_tests(tasks[tid])
        assert len(preds) == len(tasks[tid]["test"])
        for pr in preds:
            pv = COV.check_attempt_pair(pr["attempt_1"], pr["attempt_2"],
                                        pr.get("source", "symbolic"),
                                        "unverified", pr.get("loo"), None)
            if not pv.passed:
                print("COVENANT", tid, [str(x) for x in pv.violations])
        sub[tid] = preds
    except Exception as e:
        print("TASK FAIL", tid, repr(e)[:200], "-> input-copy fallback")
        sub[tid] = [{"attempt_1": t["input"], "attempt_2": t["input"]}
                    for t in tasks[tid]["test"]]
    if len(sub) % 20 == 0:
        with open(PART, "w") as fp:
            json.dump(sub, fp)
        print(f"checkpoint {len(sub)}/{len(target)} "
              f"({time.time()-t0:.0f}s)")

# Defense in depth: never let an unscored key reach the file.
sub = {k: v for k, v in sub.items() if k in VALID}

# Gates suite + algedonic telemetry (VSM runtime, fail-loud never crash)
try:
    import checks as CK
    _st = solve.runtime_state()
    if _st is not None:
        _st.tasks_total = len(target)
    for r in CK.run_gates(sub, _st, getattr(solve, "SOURCE_TALLY", {}),
                          modules_written=sorted(__MODULE_NAMES__)):
        print(r)
    if _st is not None:
        print("budget decision:", COV.decide_budget(_st))
        print("algedonic:", COV.algedonic_signals(_st) or "none")
except Exception as e:
    print("gates unavailable:", repr(e)[:200])

# RSI memory export: certified tools survive the run for next version
try:
    import rsi_bridge as _RB
    _mem = _RB._memory_path()
    if _mem.exists():
        import shutil
        shutil.copy(_mem, os.path.join(TMP, "pattern_memory_export.json"))
        print("pattern memory exported:",
              len(_RB._load_rsi_patterns()), "active tools")
except Exception as e:
    print("memory export skipped:", repr(e)[:120])
out = os.path.join(WORK, "submission.json")
# v11 (2026-10-19): judge schema == sample_submission exactly —
# attempt_1/attempt_2 only per entry. Telemetry (loo/source) was the
# only deviation vs the sample in the 2026-10-18 judged file; gates
# above already consumed it from `sub`, partials in TMP keep it.
clean = {tid: [{k: pr[k] for k in ("attempt_1", "attempt_2") if k in pr}
               for pr in preds] for tid, preds in sub.items()}
_dropped = (sum(len(pr) for preds in sub.values() for pr in preds)
            - sum(len(pr) for preds in clean.values() for pr in preds))
if _dropped:
    print(f"schema strip: {_dropped} telemetry fields dropped, "
          f"entries kept: {sum(len(p) for p in clean.values())}")
with open(out, "w") as fp:
    json.dump(clean, fp)
print(f"wrote {out}: {len(clean)} tasks in {time.time()-t0:.1f}s")
try:
    import solve as _S
    print("source tally:", getattr(_S, "SOURCE_TALLY", {}))
except Exception:
    pass
'''

MD_CELL = """# ViArc VSM AGI-2 solver v2 — symbolic engine + certified LLM (offline)

**Entry:** ARC Prize 2026, track ARC-AGI-2 · **Team:** rm -w3kufe
**Model:** Qwen2.5-3B-Instruct (Apache-2.0, staged as competition dataset,
no internet at evaluation) · **Runtime:** single GPU kernel, ≤ 12h, CPU
symbolic fallback always completes the schema.

## Method
1. **Deterministic symbolic propose** — dynamics + composer program
   enumeration, leave-one-out (LOO) certified against train pairs
   (local baseline 8.9% on 1000 puzzles, zero crashes).
2. **Certified LLM path** — the staged model serializes grids and proposes
   candidates; every proposal must pass **V1 self-consistency** (majority
   of K=4 samples) and **V2 leave-one-out understanding** (2 held-out
   train outputs reproduced) before it may compete. Fluent but
   uncertified guesses never outrank verified symbolic programs.
3. **Scored scope & budget** — only the keys of the competition's
   `sample_submission.json` (the 240 scored test tasks) are solved;
   K=4+LOO=2 costs ~82s/puzzle → 5.5h, inside the 9.5h LLM guard with
   a resumable partial; after the deadline the run finishes symbolically.
   Schema-validated `submission.json`, 2 attempts per test input.
4. **Judge schema exactness** — `submission.json` is entry-schema
   identical to `sample_submission.json` (`attempt_1`/`attempt_2` only);
   internal certification telemetry never reaches the judged file.

## Reproduce
Kernel runs end-to-end offline: staged model + embedded engine, no code
outside this notebook. Deterministic under fixed seeds (R10).

## Licensing
Code CC0-1.0 · model weights Apache-2.0 (upstream license included).
"""


def _cell_id(kind, i, name=""):
    """Deterministic nbformat id (anti MissingIDFieldWarning)."""
    return hashlib.sha1(f"agi2v11:{kind}:{i}:{name}".encode()
                        ).hexdigest()[:8]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    run = RUN_CELL.replace("__MODULE_NAMES__",
                            json.dumps(sorted(MODULES)))

    cells = [
        {"cell_type": "markdown", "metadata": {}, "id": _cell_id("md", 0),
         "source": MD_CELL.splitlines(keepends=True)},
        {"cell_type": "code", "metadata": {}, "id": _cell_id("setup", 1),
         "execution_count": None, "outputs": [],
         "source": SETUP_CELL.splitlines(keepends=True)},
    ]
    for i, name in enumerate(MODULES):
        with open(os.path.join(HERE, name)) as fp:
            src = fp.read()
        magic = f"%%writefile {TMPDIR}/{name}\n"
        cells.append({"cell_type": "code", "metadata": {},
                      "id": _cell_id("mod", 2 + i, name),
                      "execution_count": None, "outputs": [],
                      "source": (magic + src).splitlines(keepends=True)})
    cells.append({"cell_type": "code", "metadata": {},
                  "id": _cell_id("run", 2 + len(MODULES)),
                  "execution_count": None, "outputs": [],
                  "source": run.splitlines(keepends=True)})

    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3",
                           "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
            "kaggle": {"accelerator": "gpu", "isInternetEnabled": False,
                       "dockerImageVersionId": 0},
        },
        "cells": cells,
    }
    out = a.out or os.path.join(HERE, "kaggle_notebook.ipynb")
    with open(out, "w") as fp:
        json.dump(nb, fp)
    print(f"notebook: {out} ({os.path.getsize(out)} bytes, "
          f"{len(cells)} cells: md + setup + {len(MODULES)} writefile + run)")


if __name__ == "__main__":
    main()
