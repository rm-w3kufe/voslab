#!/usr/bin/env python3
"""bench_pydantic.py — pydantic vs the hand-rolled check, on the SAME input.

NOT shipped. A measurement, per rmw3 2026-08-09: "una prueba de benchmark puede
ser util ya sea para evaluar la herramienta, como para probar la de nosotros
mismos (sin compromiso de que vayamos a implementarla)."

The sharper half of that framing is the second one. A second implementation of
the same rules is a DIFFERENTIAL TEST: where the two disagree, at least one is
wrong, and neither gets the benefit of the doubt.

Both read the SAME scan (debt_register.scan()), so the extraction is shared and
only the CHECKING is compared. Comparing extraction too would be a different
experiment.
"""
from __future__ import annotations
import importlib.util
import re
import sys
import time
from enum import Enum
from pathlib import Path

ROOT = Path(os.environ.get("VOS_ROOT", os.getcwd()))   # the bench lives in scratch, ¬in the tree
sys.path.insert(0, str(ROOT / "scripts/vsl/tools"))

spec = importlib.util.spec_from_file_location(
    "dr", ROOT / "scripts/vsl/tools/debt_register.py")
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

from pydantic import BaseModel, Field, ValidationError, field_validator


# ─── the pydantic statement of the same rules ────────────────────────────
class DebtClass(str, Enum):
    kernel = "kernel"
    experiment = "experiment"
    human = "human"
    doc = "doc"
    external = "external"
    conditional = "conditional"


class Debt(BaseModel):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,}$")
    cls: DebtClass = Field(alias="class")
    owner: str = Field(min_length=1)

    @field_validator("owner")
    @classmethod
    def owner_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("owner is blank")
        return v
    body: str = Field(min_length=1)
    gate: str = ""
    file: str
    line: int

    @field_validator("body")
    @classmethod
    def body_is_not_a_label(cls, v: str) -> str:
        if len(v.split()) < 3:
            raise ValueError("body is a label, not a statement")
        return v


def check_pydantic(debts: list[dict]) -> list[tuple[str, str]]:
    bad, seen = [], {}
    for d in debts:
        seen.setdefault(d["id"], []).append(f'{d["file"]}:{d["line"]}')
        try:
            Debt.model_validate(d)
        except ValidationError as e:
            for err in e.errors():
                loc = err["loc"][0] if err["loc"] else "?"
                bad.append((d["id"], f'{loc}: {err["msg"]}'))
    for did, where in seen.items():
        if len(where) > 1:
            bad.append((did, f"duplicate id in {len(where)} places"))
    return bad


# ─── the hand-rolled rules, extracted so they can be called ──────────────
def check_ours(debts: list[dict]) -> list[tuple[str, str]]:
    """Call the REAL check. Do NOT re-implement it here.

    This function used to be an inlined COPY of debt_register's rules. The copy
    froze the day it was written, so when the real check gained id-shape and
    line-type validation on 2026-08-09 the benchmark kept reporting those three
    divergences as OPEN — it lied in the direction of making a real fix look
    absent, and it was believed for one measurement.

    A benchmark against a COPY of the tool is not a differential test OF the
    tool. debt_register.findings() now returns its judgement as data precisely
    so that this file cannot drift from it again.
    """
    return [(d["id"], why) for d, why in dr.findings(debts)]

def main() -> int:
    debts = dr.scan()
    print(f"  input: {len(debts)} debts, one shared scan\n")

    t0 = time.perf_counter(); ours = check_ours(debts); t_ours = time.perf_counter() - t0
    t0 = time.perf_counter(); pyd = check_pydantic(debts); t_pyd = time.perf_counter() - t0

    o_ids = {i for i, _ in ours}
    p_ids = {i for i, _ in pyd}

    print(f"  ours     {len(ours):>3} findings   {t_ours*1000:6.2f} ms")
    print(f"  pydantic {len(pyd):>3} findings   {t_pyd*1000:6.2f} ms\n")

    only_p = p_ids - o_ids
    only_o = o_ids - p_ids
    print(f"  agree on : {len(o_ids & p_ids)}")
    print(f"  ONLY pydantic : {sorted(only_p) or '—'}")
    print(f"  ONLY ours     : {sorted(only_o) or '—'}\n")

    if only_p:
        print("  what pydantic caught that we did not:")
        for i, why in pyd:
            if i in only_p:
                print(f"    {i:<30} {why}")
    if only_o:
        print("  what we caught that pydantic did not:")
        for i, why in ours:
            if i in only_o:
                print(f"    {i:<30} {why}")

    # cost, measured rather than asserted
    src = (ROOT / "scripts/vsl/tools/debt_register.py").read_text(encoding="utf-8")
    body = re.search(r"def check\(.*?\n(?=\n\ndef )", src, re.S)
    print(f"\n  our check(): {len(body.group(0).splitlines()) if body else '?'} lines"
          f"  ▪ pydantic model + check: "
          f"{len(open(__file__).read().split('# ─── the pydantic')[1].split('# ─── the hand-rolled')[0].splitlines())} lines")
    differential()
    return 0




# ─── FAULT INJECTION — the part that is actually a test ──────────────────
# A clean corpus makes both checkers say 0, which measures nothing. These are
# malformed debts a reviewer would want caught. Each is a claim about what the
# rule MEANS; where the two implementations disagree, one of them is wrong.
FAULTS = [
    ("class missing",       dict(id="A-ONE", **{"class": ""}, owner="DS",
                                 body="a real body with words", gate="", file="f", line=1)),
    ("class not in enum",   dict(id="A-TWO", **{"class": "urgent"}, owner="DS",
                                 body="a real body with words", gate="", file="f", line=2)),
    ("owner missing",       dict(id="A-THREE", **{"class": "kernel"}, owner="",
                                 body="a real body with words", gate="", file="f", line=3)),
    ("body missing",        dict(id="A-FOUR", **{"class": "kernel"}, owner="DS",
                                 body="", gate="", file="f", line=4)),
    ("body is a label",     dict(id="A-FIVE", **{"class": "kernel"}, owner="DS",
                                 body="fix later", gate="", file="f", line=5)),
    ("id lowercase",        dict(id="a-six", **{"class": "kernel"}, owner="DS",
                                 body="a real body with words", gate="", file="f", line=6)),
    ("id too short",        dict(id="A", **{"class": "kernel"}, owner="DS",
                                 body="a real body with words", gate="", file="f", line=7)),
    ("owner is whitespace", dict(id="A-EIGHT", **{"class": "kernel"}, owner="   ",
                                 body="a real body with words", gate="", file="f", line=8)),
    ("line not an int",     dict(id="A-NINE", **{"class": "kernel"}, owner="DS",
                                 body="a real body with words", gate="", file="f", line="nine")),
]


def differential() -> None:
    print("\n  ── FAULT INJECTION ──────────────────────────────────────────")
    print(f"  {'fault':<22}{'ours':>6}{'pydantic':>10}   verdict")
    diverge = []
    for name, d in FAULTS:
        o = bool(check_ours([d]))
        p = bool(check_pydantic([d]))
        mark = "agree" if o == p else "◄ DIVERGE"
        if o != p:
            diverge.append((name, o, p))
        print(f"  {name:<22}{'✓' if o else '·':>6}{'✓' if p else '·':>10}   {mark}")
    print(f"\n  divergences: {len(diverge)}")
    for name, o, p in diverge:
        who = "pydantic only" if p else "ours only"
        print(f"    {name:<24} caught by {who}")


if __name__ == "__main__":
    sys.exit(main())
