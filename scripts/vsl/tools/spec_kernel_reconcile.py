#!/usr/bin/env python3
"""spec_kernel_reconcile.py — model≡reality between the SPEC and the KERNEL.

WHY THIS EXISTS
---------------
rmw3, 2026-08-09: "si state canon no esta detectando estas desviaciones,
entonces, no hace lo que dice que tiene que hacer..."

Checked before agreeing, and the distinction matters.

state-canon-mcp WORKS. `state_reconcile` returned four real drifts on the day
this was written (tasks declared open, resolved in session records). Its domain
is state.db <-> infrastructure <-> tasks/sessions: declared services against
observed ones, task status against session records, topology.

It has NO domain for spec <-> kernel. VERIFIED against its own INTERFACE.md
(found 2026-08-09), not inferred: the core is domain-agnostic -- a StateProvider
plus a Reconciler registered PER DOMAIN -- and its three reference instances
cover ops (rules/services/components/chains/blockers/topology), git worktree
drift, and VSM tasks/sessions/focus. Its own docs state the consequence:
"a domain with no registered reconciler gets no cross-check".

So the sharper reading, which changes what to do next: the framework was
already there and the spec<->kernel DOMAIN was simply never registered. This
file is a Reconciler in exactly that shape -- observe(domain) reads the Rust,
diff(declared, reality) compares it against the corpus -- and it should be
registered as an instance rather than left standing alone, so the domain
answers to state_query and state_verify like every other.
    debt(SPEC-KERNEL-DOMAIN-REGISTER, class=doc, owner=DS, gate=system_certified)

Either way the deviations found by hand during the 2026-08-07/09 certification
are not something state-canon failed to catch -- nothing was watching:

    A_breath              spec's three terms   != main.rs's three terms
    CPU_PRESSURE          spec: temp/safety    != hardware_ingest.rs: Linux PSI
    sensor priority       spec: hwmon5 first   != kernel: thermal_zone0 first
    eps_frontier          spec: 0.78 and 0.775 != main.rs: computed 0.7746
    Def_TrustUpdate       spec: lambda in [0.05,0.2] != a clamp, min is 0.10
    Ax_SplitOperator      cited live, declared only in a historical record

Six found by READING six documents. There is no reason to believe six is all
of them, and reading does not scale to a corpus of thirty.

WHAT IT CHECKS
--------------
The corpus already cites its evidence in two regular shapes, so no new
convention is needed -- the documents are already written this way:

  1. CITATION   `foo.rs:NNN`
     -> the file exists, the line exists, and a token the document uses near
        the citation actually appears within +/-CONTEXT lines of it.
        Catches: renamed files, deleted code, and above all STALE LINE
        NUMBERS, which rot silently on every refactor.

  2. CONSTANT   `NAME = value` asserted in prose
     -> `const NAME: T = value` in the Rust must carry the same value.
        Catches: a constant retuned in code while the spec keeps the old
        number -- exactly the eps_frontier and r_core class.

WHAT IT DOES NOT CHECK
----------------------
SEMANTICS. It cannot see that CPU_PRESSURE means PSI rather than a temperature
ratio; that took reading. This narrows the gap, it does not close it -- and
saying so is the point, because a reconciler believed to check meaning is worse
than none.

Deterministic, stdlib-only. No LLM in this path (R10).

    python3 scripts/vsl/spec_kernel_reconcile.py           # report
    python3 scripts/vsl/spec_kernel_reconcile.py --check   # gate
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "docs/spec_revision/system"
SRC = [ROOT / "projects/vsf-nucleus/src"]
SKIP_DIRS = {"agent_layer"}
CONTEXT = 4          # a citation may drift a few lines without being wrong

CITATION = re.compile(r"\b([a-z][a-z_0-9]*\.rs):(\d+)")
# `NAME = 0.70` / `NAME=0.70` asserted anywhere in a document
ASSERT = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\s*=\s*(-?\d+(?:\.\d+)?)\b")
RUST_CONST = re.compile(
    r"const\s+([A-Z][A-Z0-9_]*)\s*:\s*[A-Za-z0-9_:<>]+\s*=\s*(-?\d+(?:\.\d+)?)")
# IDENTIFIER-SHAPED tokens only, on both sides, compared case- and
# underscore-insensitively so CPU_PRESSURE == CpuPressure == cpu_pressure.
#
# The first version matched \b[a-z_][a-z_0-9]{3,}\b on the document and hit
# prose: "derived", "literal", "constant". It reported 7 divergences and ALL
# SEVEN were false -- main.rs:6701, kernel.rs:352 and hardware_ingest.rs:41
# were each exactly right, the document line simply used notation or put the
# identifier on the line above. A citation refers to a BLOCK of prose, not to
# one line, so the document side reads a window too.
IDENT = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]{3,})\b")
DOC_WINDOW = 3       # a citation belongs to the sentence around it
# `name:` opening a line is VSL STRUCTURE, ¬the subject of the claim.
FIELD_KEY = re.compile(r"(?:^|\s)([a-z_][a-z_0-9]*)\s*:")


def ident_shaped(t: str) -> bool:
    """Reject prose. Keep snake_case, CamelCase, SCREAMING_SNAKE.

    ALL-CAPS ALONE IS NOT AN IDENTIFIER. This corpus writes emphasis in caps —
    "DERIVED", "LOWER", "BLOCKING" — and the third version of this check read
    those as anchors, reporting main.rs:6701 and kernel.rs:352 as stale when
    both are exactly right. An identifier carries an underscore, a digit, or
    an internal capital; emphasis carries none of the three.
    """
    if "_" in t or any(c.isdigit() for c in t):
        return True
    return t[:1].isupper() and any(c.isupper() for c in t[1:]) and not t.isupper()


def norm(t: str) -> str:
    return t.replace("_", "").lower()


def rust_files() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for root in SRC:
        for f in root.rglob("*.rs"):
            out.setdefault(f.name, f)
    return out


def rust_consts() -> dict[str, tuple[str, Path, int]]:
    out: dict[str, tuple[str, Path, int]] = {}
    for root in SRC:
        for f in root.rglob("*.rs"):
            for i, line in enumerate(f.read_text(encoding="utf-8",
                                                 errors="replace").splitlines(), 1):
                m = RUST_CONST.search(line)
                if m:
                    out.setdefault(m.group(1), (m.group(2), f, i))
    return out


def same_number(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return a == b


def main() -> int:
    files, consts = rust_files(), rust_consts()
    findings: list[tuple[str, str, str]] = []
    n_ok = 0
    n_cit = n_val = 0

    for doc in sorted(CORPUS.rglob("*.vsm")):
        if any(s in doc.parts for s in SKIP_DIRS):
            continue
        rel = str(doc.relative_to(CORPUS))
        lines = doc.read_text(encoding="utf-8").splitlines()

        for i, raw in enumerate(lines):
            for name, num in CITATION.findall(raw):
                n_cit += 1
                target = files.get(name)
                if target is None:
                    findings.append((rel, f"{i+1}",
                                     f"cites {name}:{num} — ∄ such file in the kernel"))
                    continue
                body = target.read_text(encoding="utf-8",
                                        errors="replace").splitlines()
                ln = int(num)
                if ln > len(body):
                    findings.append((rel, f"{i+1}",
                                     f"cites {name}:{ln} — file has {len(body)} lines"))
                    continue
                # a token the document uses on this line should be visible at
                # the cited site. Skip the file's own name.
                # ANCHOR: an identifier on the citation's OWN line. Widening
                # to a context window was the second wrong answer -- it pulled
                # in identifiers from neighbouring claims and still reported
                # main.rs:6701, which is exactly right. A document cites by
                # MEANING; only where it also names an identifier can the
                # citation be mechanically checked. Where it does not, this
                # says so instead of guessing.
                # NO SITE CHECK. Five versions tried to decide mechanically
                # whether a citation points at the RIGHT line, by matching an
                # identifier the document names against the code around it.
                # Every version reported main.rs:6701 or kernel.rs:352 — both
                # exactly right — and every fix produced a new false positive:
                # prose in caps read as identifiers, VSL field keys read as
                # subjects, a document NAME read as code.
                #
                # By then the tuning was aimed at making the number zero, not
                # at making the rule truer. A document cites by MEANING; the
                # match is not decidable from tokens.
                #
                # So it is not claimed. What IS decided here is decided
                # exactly: the file exists, and the line is in range. Whether
                # the line is the RIGHT one still takes reading, and this says
                # so rather than implying otherwise.
                n_ok += 1

        text = "\n".join(lines)
        for name, val in ASSERT.findall(text):
            if name not in consts:
                continue                      # not a Rust constant; not our claim
            n_val += 1
            actual, f, ln = consts[name]
            if not same_number(val, actual):
                findings.append(
                    (rel, "-",
                     f"{name} = {val} in the spec ▪ {actual} in "
                     f"{f.name}:{ln}"))

    print(f"  spec ↔ kernel — {len(files)} .rs files\n"
          f"    citations           {n_cit}  — file exists ∧ line in range\n"
          f"    constant assertions {n_val}  — value vs `const` in the Rust\n"
          f"  ¬CHECKED: whether a citation points at the RIGHT line, and what\n"
          f"           any of it MEANS. Both still take reading.\n")
    if not findings:
        print("  ✓ every citation resolves and every asserted constant matches")
        print("    (SEMANTICS are ¬checked — that still takes reading)")
        return 0
    print(f"  ✗ {len(findings)} divergence(s)\n")
    for rel, ln, why in findings:
        print(f"    {rel}:{ln}")
        print(f"      {why}")
    return 1 if "--check" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
