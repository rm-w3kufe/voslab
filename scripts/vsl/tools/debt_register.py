#!/usr/bin/env python3
"""debt_register.py — derive the debt register from the corpus itself.

WHY THIS EXISTS
---------------
rmw3, 2026-08-08: "al final del ciclo de tareas, vamos a tener un resumen de
todo lo encontrado con errores o con deudas, pero no desarrollado? como vamos
a encontrar luego estas deudas en un mar de backlog?"

The concern was correct and the answer is structural, not a better list.

A hand-maintained debt list is the backlog. It rots the moment the document it
describes is edited, and nothing detects the rot -- that is precisely how this
project accumulated 314 orphaned tasks by 2026-08-02.

So the register is DERIVED. Debts are written WHERE THEY WERE FOUND, in the
document, next to their evidence, using one marker:

    debt(ID, class=<class>, owner=<owner>) [ , gate=<gate> ]
    // free-text body: every following comment line, until a non-comment line

CITING a debt from elsewhere uses the BARE id -- KERNEL-ABREATH-ALIGN -- never
the debt(...) form. A citation that looks like a declaration IS a declaration
to this script, and it has bitten twice: once in the ledger (fixed by scope)
and once inside system/, where the gate caught it and blocked the commit. That
second time is the tool working.

Nothing is maintained. This script reads the corpus and prints what is there.
Delete the marker and the debt leaves the register; there is no second place
to update, so there is no second place to forget.

    the finding stays with its evidence  ->  it can be judged
    one command lists every finding      ->  it can be found
    the list cannot drift from the docs  ->  it can be trusted

CLASSES -- what has to happen, not how urgent it is:
    kernel      a code change to vsf-nucleus. BATCHED, per rmw3 (S5) 2026-08-07
    experiment  needs a run before it can be closed
    human       rmw3's own act: a ratification, a promotion, a decision
    doc         a document that does not exist yet, or is not conformant
    external    blocked on somebody outside the system
    conditional not a debt yet -- becomes one if a named thing happens

Deterministic, stdlib-only. No LLM in this path (R10).

    python3 scripts/vsl/debt_register.py            # the register
    python3 scripts/vsl/debt_register.py --check    # gate: every debt well-formed
    python3 scripts/vsl/debt_register.py --class kernel
    python3 scripts/vsl/debt_register.py --json
"""
from __future__ import annotations
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# system/ ONLY. The ledger was scanned too at first and immediately produced a
# duplicate: the ledger CITES debt ids in its certification notes, and a
# citation is not a declaration. Worse, it would have let a debt live in the
# ledger -- which is a record of operations, not a place anyone looks for work.
# A debt belongs in the document it is a debt ABOUT. If it belongs to no
# document, it is a task, and tasks live in TASKS.vsm.
# system/ AND sandbox/. The distinction that matters here is ¬which rail a
# document sits on, it is what the tool is FOR:
#   CERTIFICATION is scoped — only system/ is canon, and the gates say so.
#   FINDABILITY is ¬scoped — a debt declared in a spec under test is still a
#   debt, and a register that cannot see it recreates the backlog it exists
#   to prevent.
# Added 2026-08-09 the moment sandbox/ was created and its four debts were
# invisible on the first run.
SCAN = [ROOT / "docs/spec_revision/system",
        ROOT / "docs/spec_revision/sandbox"]
SKIP_DIRS = {"agent_layer"}

ID_SHAPE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
ID_MIN = 4
CLASSES = {"kernel", "experiment", "human", "doc", "external", "conditional"}

# debt(ID, class=x, owner=y) with optional gate=. Tolerant of whitespace and of
# a leading `//` -- a debt is usually written inside a comment, beside the
# finding it came from.
# The attribute list is OPTIONAL in the pattern and REQUIRED by --check. That
# is deliberate: the first version required a comma, so debt(KERNEL-ABREATH-
# ALIGN) -- written before this convention existed -- matched nothing, and
# --check reported "0 debts, all well-formed". A gate that cannot see the
# malformed case is a gate that certifies its own blind spot.
# The id pattern is DELIBERATELY PERMISSIVE here and STRICT in check().
# It used to be [A-Z][A-Z0-9-]{2,}, which meant a marker with a malformed id
# — `debt(ds-lowercase, …)` — was not extracted AT ALL. It did not fail the
# gate; it VANISHED. A debt that disappears because its name is wrong is the
# worst possible outcome for a register whose only job is findability.
# Extract anything marker-shaped; judge the shape in check(), where a defect
# gets REPORTED instead of silently dropped.
DEBT = re.compile(
    r"debt\(\s*(?P<id>[^\s,()]{2,})\s*(?:,(?P<attrs>[^)]*))?\)")
ATTR = re.compile(r"(\w+)\s*=\s*([^,\s]+)")


def body_after(lines: list[str], i: int) -> str:
    """Every following COMMENT line is the debt's body.

    The body stops at the first line that is not a comment, so a debt cannot
    silently swallow the specification underneath it — and at the NEXT debt
    marker, so it cannot swallow its NEIGHBOUR either. Without the second stop,
    infra_ops's three consecutive markers each printed the other two's text and
    the register became unreadable at exactly the point it had most to say.
    """
    out = []
    for raw in lines[i + 1:]:
        s = raw.strip()
        if not s.startswith("//"):
            break
        if DEBT.search(s):
            break
        out.append(s.lstrip("/").strip())
    return " ".join(out).strip()


def scan() -> list[dict]:
    debts = []
    for root in SCAN:
        if not root.exists():
            continue
        for f in sorted(root.rglob("*.vsm")):
            if any(s in f.parts for s in SKIP_DIRS):
                continue
            lines = f.read_text(encoding="utf-8").splitlines()
            for i, raw in enumerate(lines):
                m = DEBT.search(raw)
                if not m:
                    continue
                attrs = dict(ATTR.findall(m.group("attrs") or ""))
                # the marker line itself may carry the first sentence
                inline = raw.split(")", 1)[1].strip().lstrip(":").strip() \
                    if ")" in raw else ""
                debts.append({
                    "id": m.group("id"),
                    "class": attrs.get("class", ""),
                    "owner": attrs.get("owner", ""),
                    "gate": attrs.get("gate", ""),
                    "file": str(f.relative_to(ROOT)),
                    "line": i + 1,
                    "body": (inline + " " + body_after(lines, i)).strip(),
                })
    return debts


def findings(debts: list[dict]) -> list[tuple[dict, str]]:
    """The JUDGEMENT, as data. Extracted 2026-08-09.

    The pydantic differential re-implemented these rules INLINE instead of
    calling them. The copy froze when it was written, so the moment the real
    check gained id-shape validation the benchmark kept reporting the gap as
    open — it lied in the direction of making a real fix look absent.
    A benchmark against a COPY of the tool is not a differential test of the
    tool. Copies are references, never parallel authorities
    (feedback_single_source). Both the CLI and the benchmark consume this.
    """
    bad: list[tuple[dict, str]] = []
    seen = defaultdict(list)
    for d in debts:
        seen[d["id"]].append(f'{d["file"]}:{d["line"]}')
        # .strip() on every field. A whitespace-only owner passed BOTH this
        # check (`not "   "` is False) and a pydantic model with
        # min_length=1 (three characters satisfy it) -- found 2026-08-09 by
        # running the two implementations against injected faults. The
        # benchmark's useful result was ¬which tool won, it was the one blind
        # spot they SHARED.
        # ── THE ESCAPE HATCH, CLOSED. rmw3 2026-08-10 ──────────────────
        # "veo un patron muy preocupante en ti, que DS no tiene: mientras DS
        #  encuentra bugs y los corrige para poder avanzar, tu los reportas,
        #  los dejas de lado y los olvidas. esto no es tolerable."
        #
        # He was right, and the register is HOW. Measured the same hour: five
        # debts owned by O, ALL with gate=none. Nothing blocked any of them.
        # They were work I could do and wrote down instead of doing.
        # The register was built so ∄ finding is lost. It became the mechanism
        # for losing MY OWN, because registering feels like completing.
        #
        # RULE: owner=O ∧ gate=none is ¬a debt, it is UNDONE WORK.
        # If it is mine and nothing blocks it, writing it down INSTEAD of doing
        # it is the defect. To defer it I must name what actually blocks it —
        # and "I did not get to it" is ¬a gate.
        # This does ¬apply to rmw3 or DS: their debts are dispatched work, and
        # a dispatch is a real gate.
        if d["owner"] == "O" and (d.get("gate") or "none") == "none":
            bad.append((d, "owner=O with gate=none — this is UNDONE WORK, ¬a "
                           "debt. Do it, or name what blocks it."))
            continue

        # ID SHAPE — adopted from the pydantic differential, ¬the dependency.
        # Re-run 2026-08-09 against the current corpus: 3 divergences, ALL in
        # pydantic's favour (lowercase id, id too short, line not an int).
        # An earlier note in this cycle recorded the two as "equal"; the fresh
        # measurement says otherwise, and it matters — `owner=ds` had to be
        # hand-corrected today precisely because ∄ check looked at SHAPE.
        # The dependency stays out (stdlib-only, R10); the CHECKS come in.
        if not ID_SHAPE.match(d["id"]) or len(d["id"]) < ID_MIN:
            bad.append((d, f'id "{d["id"]}" is not SCREAMING-KEBAB '
                           f'(A-Z 0-9 -, ≥ 4 chars) — a register grouped by id '
                           f'splits on case'))
        elif not isinstance(d["line"], int):
            bad.append((d, f'line {d["line"]!r} is not an int — a citation '
                           f'that cannot be resolved is not a citation'))
        elif d["class"] not in CLASSES:
            bad.append((d, f'class={d["class"] or "MISSING"} '
                           f'-- must be one of {sorted(CLASSES)}'))
        elif not d["owner"].strip():
            bad.append((d, "owner MISSING or blank"))
        elif not d["body"].strip():
            bad.append((d, "body MISSING -- a debt with no body is a label"))
        elif len(d["body"].split()) < 3:
            bad.append((d, f'body is a LABEL, ¬a statement: "{d["body"]}"'))
    for did, where in seen.items():
        if len(where) > 1:
            bad.append(({"id": did, "file": where[0], "line": 0},
                        f"DUPLICATE id in {len(where)} places: {', '.join(where)}"))
    return bad


def check(debts: list[dict]) -> int:
    """A debt with no class is a debt nobody can route. A debt with no owner is
    a debt nobody will pick up. Both are how a register becomes a graveyard."""
    bad = findings(debts)
    if bad:
        print(f"  ✗ {len(bad)} malformed debt(s) — BLOCKING\n")
        for d, why in bad:
            print(f"    {d['id']:<28} {d['file']}:{d['line']}")
            print(f"      {why}")
        return 1
    print(f"  ✓ {len(debts)} debts, all well-formed "
          f"(id · class · owner · body · unique)")
    return 0


def report(debts: list[dict], only: str | None) -> int:
    by = defaultdict(list)
    for d in debts:
        by[d["class"] or "UNCLASSED"].append(d)
    order = ["kernel", "experiment", "human", "doc", "external",
             "conditional", "UNCLASSED"]
    print(f"  DEBT REGISTER — {len(debts)} open, derived from the corpus\n")
    for cls in order:
        if cls not in by or (only and cls != only):
            continue
        rows = sorted(by[cls], key=lambda d: d["id"])
        print(f"  ── {cls.upper()} ({len(rows)}) "
              + "─" * max(0, 58 - len(cls)))
        for d in rows:
            gate = f"  gate:{d['gate']}" if d["gate"] else ""
            print(f"    {d['id']:<28} {d['owner']:<8}{gate}")
            print(f"      {d['file']}:{d['line']}")
            body = d["body"]
            while body:
                print(f"      {body[:72]}")
                body = body[72:]
        print()
    return 0


def main() -> int:
    debts = scan()
    if "--json" in sys.argv:
        print(json.dumps(debts, indent=2, ensure_ascii=False))
        return 0
    if "--check" in sys.argv:
        return check(debts)
    only = None
    if "--class" in sys.argv:
        only = sys.argv[sys.argv.index("--class") + 1]
    return report(debts, only)


if __name__ == "__main__":
    sys.exit(main())
