#!/usr/bin/env python3
"""start_preconditions.py — runtime consumer for instance `start:`
preconditions (G-29).

s1-clima, s1-econ and s1-bbh instances (plus the template) declare
`start: "preconditions before it may run: ..."` — but grep for an
evaluator returned 0 (G-29): the S1 admission preconditions were pure
text. This tool parses and reports them.

What it guarantees (mechanical, R10):
  - every *.instance.vsm under system/ carries a parseable `start:`
    block with at least one precondition (the template rule — a
    deleted field reads as unconsidered);
  - each precondition is classified against the only sources that
    exist today:
      MANUAL(S5)  rmw3 admission (lifecycle.3 ADMIT) — human gate,
                  never machine-resolved;
      COVERED     nucleus (S3/S4) config complete — the declarative
                  half is bindings-valid (#67): binds+refs both ways;
      UNKNOWN     no state source exists (e.g. R6 empirical exercise:
                  TASKS.vsm says 'R6 cleared 06-20' while
                  validation.vsm c10 records 'STILL OPEN rmw3
                  2026-07-30' — an evaluator must not invent
                  resolution; it reports the conflict).
  UNKNOWN is reported, never a violation (honesty over false
  precision); structural absence/malformation is a violation.

Exit codes: 0 = all instances structurally valid; 1 = a violation;
2 = usage. --self-test builds fixture instances (valid, missing,
malformed) and requires each case to land correctly.

Usage:
    python3 scripts/vsl/tools/start_preconditions.py
    python3 scripts/vsl/tools/start_preconditions.py --self-test
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
INSTANCE_GLOB = "**/*.instance.vsm"
START_RE = re.compile(r'start:\s*"(.*?)"\s*,', re.DOTALL)

# precondition text -> (classification, source)
RULES = [
    (re.compile(r"rmw3\s+admits|ADMIT", re.IGNORECASE),
     "MANUAL(S5)", "human admission gate (lifecycle.3 ADMIT)"),
    (re.compile(r"nucleus.*config\s+complete", re.IGNORECASE | re.DOTALL),
     "COVERED", "declarative half = checks/bindings-valid (#67)"),
    (re.compile(r"\bR6\b"),
     "UNKNOWN",
     "no state source; TASKS.vsm 'R6 cleared 06-20' conflicts with "
     "validation.vsm c10 'STILL OPEN rmw3 2026-07-30' — reported, "
     "not resolved"),
]
CLASS_UNKNOWN = ("UNKNOWN", "no state source declared for this precondition")


def split_preconditions(start_text: str) -> list[str]:
    """Split on the conjunction used by the docs (may be multi-line).

    ∧ inside parentheses belongs to one precondition (R6 spans
    '(S2..S5 ∧ algedonic ∧ covenant)') — only depth-0 ∧ separates.
    """
    flat = " ".join(start_text.split())
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in flat:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "∧" and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def classify(precondition: str) -> tuple[str, str]:
    for pat, cls, source in RULES:
        if pat.search(precondition):
            return cls, source
    return CLASS_UNKNOWN


def extract_start(text: str) -> str | None:
    m = START_RE.search(text)
    return m.group(1) if m else None


def scan(root: Path) -> tuple[list[str], list[str]]:
    """Return (violations, report lines) for every instance under root."""
    violations: list[str] = []
    report: list[str] = []
    instances = sorted(
        p for p in root.joinpath("system").glob(INSTANCE_GLOB)
        if "template" not in p.parts and "templates" not in p.parts
    )
    if not instances:
        violations.append("no *.instance.vsm found under system/")
        return violations, report
    for p in instances:
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8", errors="replace")
        start = extract_start(text)
        if start is None:
            violations.append(f"{rel}: missing or unparseable start: block")
            continue
        preconditions = split_preconditions(start)
        if not preconditions:
            violations.append(f"{rel}: start: parses to zero preconditions")
            continue
        report.append(f"{rel}: {len(preconditions)} precondition(s)")
        for pre in preconditions:
            cls, source = classify(pre)
            short = pre if len(pre) <= 70 else pre[:67] + "..."
            report.append(f"    [{cls:10s}] {short}  ({source})")
    return violations, report


def self_test() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        inst_dir = root / "system/s1-operations/s1-unit"
        inst_dir.mkdir(parents=True)

        # (1) valid instance passes
        good = inst_dir / "s1-unit.instance.vsm"
        good.write_text(
            'x {\n'
            '    start:     "preconditions: nucleus (S3/S4) config\n'
            '              complete ∧ rmw3 admits (lifecycle.3 ADMIT)",\n'
            '}\n'
        )
        violations, report = scan(root)
        if violations:
            failures.append(f"valid instance flagged: {violations}")
        if not any("MANUAL(S5)" in line for line in report):
            failures.append("MANUAL(S5) classification missing")
        if not any("COVERED" in line for line in report):
            failures.append("COVERED classification missing")

        # (2) missing start: -> violation
        good.write_text('x {\n    healthy: "y",\n}\n')
        violations, _ = scan(root)
        if not any("missing or unparseable start:" in v for v in violations):
            failures.append("missing start: not caught")

        # (3) malformed start (no closing quote) -> violation
        good.write_text('x {\n    start: "unterminated line\n}\n')
        violations, _ = scan(root)
        if not any("missing or unparseable start:" in v for v in violations):
            failures.append("malformed start: not caught")

        # (4) R6 precondition classifies UNKNOWN (conflict reported)
        good.write_text(
            'x {\n    start: "preconditions: R6 empirical exercise PASSED",\n}\n'
        )
        violations, report = scan(root)
        if violations:
            failures.append(f"R6 instance flagged: {violations}")
        if not any("UNKNOWN" in line and "R6" in line for line in report):
            failures.append("R6 conflict not reported as UNKNOWN")

    if failures:
        for f in failures:
            print(f"SELF-TEST FAIL: {f}", file=sys.stderr)
        return 1
    print("self-test ok: valid/missing/malformed/R6-conflict all land right")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    violations, report = scan(Path(args.root))
    print("start_preconditions: S1 admission preconditions")
    for line in report:
        print(f"  {line}")
    if violations:
        for v in violations:
            print(f"  VIOLATION {v}")
        print(f"{len(violations)} violation(s)")
        return 1
    print("  OK — every instance carries a parseable start: block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
