#!/usr/bin/env python3
"""vsm_logic.py — decide VSM structural logic over DECLARED facts.

THE QUESTION rmw3 ASKED
-----------------------
"¿es posible parsear o validar la lógica de VSM de manera determinista?"

Measured answer, in three tiers:

  TIER 1 — STRUCTURAL. Decidable, and this file decides it.
    A finite graph with finite relations: who is whose child, at what level,
    which subsystem couples to which, which uses an LLM. First-order over a
    finite domain. No reasoner required — the OWL benchmark derived 3/3 of
    these, but a reasoner is a convenience here, not a necessity.

  TIER 2 — QUANTITATIVE. Decidable given the numbers.
    A2 budget hierarchy B(child) ≤ B(parent); A8 absorption
    |Sig(L)| ≤ |Sig(L+1)|·(1−r). Arithmetic over declared values. Not built
    here — it needs the values declared, which is the same blocker as Tier 1.

  TIER 3 — SEMANTIC. NOT decidable, and saying so is the point.
    Whether an axiom is TRUE of the world, whether a compression lost what
    mattered, whether a claim's verifier is adequate. That is ~70% of
    certification and it is done by reading.

WHY IT DID NOT EXIST ALREADY — the blocker was never the reasoner
-----------------------------------------------------------------
Measured 2026-08-09: of 48 documents, FOUR declare a `V(...)` a machine can
read, and NOT ONE declares its parent. The OWL 2 RL benchmark derived 3/3
relational defects with 0 false positives — over facts written BY HAND for the
test. It proved the reasoning. It never proved we can obtain the facts.

So the corpus could not be checked for VSM logic because the corpus does not
STATE its VSM logic. That is the same lesson the whole cycle produced from a
different direction: `layer` was uncheckable while it was undeclared; @status
drifted while one of its three senses had no name. Structure that is inferred
from prose is structure nobody can verify.

THE FACT SHAPE
--------------
A document that describes a viable system declares:

    structure(V) = {
      id:       "s1-clima"
      level:    1
      parent:   "vsf-nucleus"          // ∅ for a root
      s4_llm:   ⊥                      // does its S4 use an LLM?
      couples:  [ "s1-econ" via "vsf-nucleus".S3 ]
    }

From that, these decide mechanically:

    A1   level(child) = level(parent) + 1, and the relation is one-way
    A4   ∀ coupling to a SIBLING: a mediator is named, and it is the parent's S3
    D6   s4_llm = ⊤ ⟹ level ≥ 2
    S3*  is a CHANNEL, ¬a tuple element — enforced by the shape: there is no
         slot for it among the subsystems, so it cannot be written as one

    python3 scripts/vsl/vsm_logic.py --selftest
    python3 scripts/vsl/vsm_logic.py [file.vsm ...]

Deterministic, stdlib-only. No LLM in this path (R10).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "docs/spec_revision"

BLOCK = re.compile(r"structure\(V\)\s*=\s*\{(.*?)\n\s*\}", re.S)
FIELD = re.compile(r'^\s*([a-z_0-9]+)\s*:\s*(.+?)\s*$', re.M)
COUPLE = re.compile(r'"([^"]+)"\s+via\s+"([^"]+)"\.S3')
TRUE, FALSE = "⊤", "⊥"


def parse(text: str, src: str = "?") -> list[dict]:
    out = []
    for m in BLOCK.finditer(text):
        body = m.group(1)
        f = {k: v for k, v in FIELD.findall(body)}
        if "id" not in f:
            continue
        out.append({
            "src": src,
            "id": f.get("id", "").strip('"'),
            "level": int(f["level"]) if f.get("level", "").strip().lstrip("-").isdigit() else None,
            "parent": None if f.get("parent", "∅").strip() in ("∅", '""', "-")
                      else f.get("parent", "").strip('"'),
            "s4_llm": f.get("s4_llm", FALSE).strip() == TRUE,
            "couples": COUPLE.findall(f.get("couples", "")),
            "couples_raw": f.get("couples", ""),
        })
    return out


def decide(systems: list[dict]) -> list[tuple[str, str, str]]:
    """Return (axiom, system_id, why) for every violation. Empty = clean."""
    by_id = {s["id"]: s for s in systems}
    bad: list[tuple[str, str, str]] = []

    for s in systems:
        sid, lvl, par = s["id"], s["level"], s["parent"]

        # ── A1 — recursion. child = parent + 1, ONE direction ────────────
        # The single most repeated defect of this cycle: three documents
        # independently restated A1 from memory and three inverted it. An
        # index can invert; a named role cannot. So the check is on the
        # NUMBERS, which is the one place the inversion becomes visible.
        if par is not None:
            if par not in by_id:
                bad.append(("A1", sid, f'parent "{par}" is not declared'))
            elif by_id[par]["level"] is None or lvl is None:
                bad.append(("A1", sid, "level missing on this or its parent"))
            elif lvl != by_id[par]["level"] + 1:
                bad.append(("A1", sid,
                            f'level {lvl}, parent "{par}" is level '
                            f'{by_id[par]["level"]} — child must be parent+1'))
            elif by_id[par]["parent"] == sid:
                bad.append(("A1", sid,
                            f'"{par}" is declared BOTH parent and child of '
                            f'"{sid}" — the relation is one-way'))

        # ── D6 — no LLM below level 2 ────────────────────────────────────
        if s["s4_llm"] and (lvl is None or lvl < 2):
            bad.append(("D6", sid,
                        f"S4 uses an LLM at level {lvl} — requires level ≥ 2"))

        # ── A4 — no direct sibling coupling ──────────────────────────────
        # A coupling that names NO mediator is direct by omission. The check
        # reads what is written, ¬what was meant: an unmediated entry in
        # `couples` is a violation even if the prose alongside says otherwise.
        raw = s["couples_raw"].strip()
        if raw and raw not in ("[]", "∅"):
            named = {a for a, _ in s["couples"]}
            for peer in re.findall(r'"([^"]+)"', raw):
                if peer in named or peer == par:
                    continue
                if peer in by_id and by_id[peer]["parent"] == par:
                    bad.append(("A4", sid,
                                f'couples to sibling "{peer}" with ∄ mediator '
                                f'— A4 requires the parent\'s S3'))
            for peer, mediator in s["couples"]:
                if par is not None and mediator != par:
                    bad.append(("A4", sid,
                                f'couples to "{peer}" via "{mediator}".S3, but '
                                f'its parent is "{par}" — the mediator must be '
                                f'the PARENT\'s S3'))
    return bad


# ── self-test: every axiom, violated and respected ───────────────────────
CASES = [
    ("A1 respected", '''
structure(V) = {
  id: "root"
  level: 0
  parent: ∅
  s4_llm: ⊥
}
structure(V) = {
  id: "child"
  level: 1
  parent: "root"
  s4_llm: ⊥
}''', []),
    ("A1 inverted — the defect found in THREE documents", '''
structure(V) = {
  id: "root"
  level: 0
  parent: ∅
  s4_llm: ⊥
}
structure(V) = {
  id: "child"
  level: 0
  parent: "root"
  s4_llm: ⊥
}''', ["A1"]),
    ("D6 violated — LLM at L1", '''
structure(V) = {
  id: "kernel"
  level: 1
  parent: ∅
  s4_llm: ⊤
}''', ["D6"]),
    ("D6 respected — LLM at L2", '''
structure(V) = {
  id: "cog"
  level: 2
  parent: ∅
  s4_llm: ⊤
}''', []),
    ("A4 violated — sibling coupled with no mediator", '''
structure(V) = {
  id: "parent"
  level: 0
  parent: ∅
  s4_llm: ⊥
}
structure(V) = {
  id: "a"
  level: 1
  parent: "parent"
  s4_llm: ⊥
  couples: [ "b" ]
}
structure(V) = {
  id: "b"
  level: 1
  parent: "parent"
  s4_llm: ⊥
}''', ["A4"]),
    ("A4 respected — mediated by the parent's S3", '''
structure(V) = {
  id: "parent"
  level: 0
  parent: ∅
  s4_llm: ⊥
}
structure(V) = {
  id: "a"
  level: 1
  parent: "parent"
  s4_llm: ⊥
  couples: [ "b" via "parent".S3 ]
}
structure(V) = {
  id: "b"
  level: 1
  parent: "parent"
  s4_llm: ⊥
}''', []),
    ("A1 — parent not declared", '''
structure(V) = {
  id: "orphan"
  level: 2
  parent: "ghost"
  s4_llm: ⊥
}''', ["A1"]),
]


def _selftest() -> int:
    ok = fail = 0
    for name, src, want in CASES:
        got = sorted({ax for ax, _, _ in decide(parse(src))})
        if got == sorted(want):
            ok += 1
        else:
            fail += 1
            print(f"  ✗ {name}: want {sorted(want)}, got {got}")
    print(f"  vsm_logic selftest: {ok} passed, {fail} failed")
    return 1 if fail else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    paths = [Path(a) for a in args] if args else sorted(CORPUS.rglob("*.vsm"))
    systems = []
    for p in paths:
        systems += parse(p.read_text(encoding="utf-8"), str(p.name))
    if not systems:
        print("  ∄ structure(V) block found — the corpus does not STATE its")
        print("    VSM logic yet, so there is nothing to decide. That is the")
        print("    blocker, and it is a DECLARATION problem, ¬a reasoning one.")
        return 0
    bad = decide(systems)
    print(f"  vsm logic — {len(systems)} declared system(s) in {len(paths)} file(s)")
    if not bad:
        print("  ✓ A1 ▪ A4 ▪ D6 hold over every declared system")
        print("    (TIER 1 only. Quantitative axioms and SEMANTICS are ¬decided.)")
        return 0
    for ax, sid, why in bad:
        print(f"  ✗ {ax}  {sid}: {why}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
