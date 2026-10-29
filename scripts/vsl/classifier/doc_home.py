#!/usr/bin/env python3
"""doc_home.py — CLI for the kernel DOC-HOME resolver.

design: docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm
(PART IV-B tree_rules + PART IV-C home_policy; F4 DOC-HOME-POLICY, S5 2026-10-29)

Usage:
  python3 scripts/vsl/classifier/doc_home.py suggest <TYPE> [status] [name]
      -> prints the canonical physical home for a NEW document.
  python3 scripts/vsl/classifier/doc_home.py check <path>
      -> write-time gate: 0 = canonical/approved/advisory; 1 = block.
  python3 scripts/vsl/classifier/doc_home.py roots
      -> prints the declared homes and their new-doc admission.
  python3 scripts/vsl/classifier/doc_home.py --self
      -> deterministic selftest (policy loads, canonical doc accepted,
         misplaced doc blocked).

R9: an unknown nature prints the approved homes instead of inventing one.
R10: the answer is the declared policy, never an LLM opinion.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "packages" / "framework") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "framework"))

from vos_kernel.utils.doc_home import (  # noqa: E402
    check_path,
    classifier,
    resolve,
    suggest,
)


def _print_roots() -> None:
    C = classifier()
    for name in sorted(C.HOME_ROOTS):
        path = C.physical_home(name)
        if path is None:
            continue
        admission = "new-docs" if name in C.APPROVED_HOMES else "frozen/legacy"
        print(f"{name:20s} {path.relative_to(ROOT)!s:55s} {admission}")
    print("\nlegacy areas (tracked edits only):")
    for area in C.LEGACY_AREAS:
        print(f"  {area}")
    print("\napproved new-doc homes:")
    for name in sorted(C.APPROVED_HOMES):
        path = C.physical_home(name)
        if path is not None:
            print(f"  {name:20s} {path.relative_to(ROOT)}")


def _selftest() -> int:
    C = classifier()
    ok = C.classify(ROOT / "system/boot/hard_rules.vsm")
    if ok != "system/boot":
        print(f"FAIL: hard_rules classifies to {ok!r}, expected system/boot",
              file=sys.stderr)
        return 1
    good = ROOT / "system/s5-policy/vsl-language/definitions_theory.vsm"
    if not good.exists():
        print("FAIL: canonical fixture missing", file=sys.stderr)
        return 1
    d = check_path(good)
    if not d.ok or d.advisory:
        print(f"FAIL: canonical doc blocked: {d.message}", file=sys.stderr)
        return 1
    print("PASS: doc_home selftest — policy loads and canonical doc accepted")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]

    if cmd == "--self":
        return _selftest()

    if cmd == "roots":
        _print_roots()
        return 0

    if cmd == "suggest":
        if len(argv) < 2:
            print("usage: doc_home.py suggest <TYPE> [status] [name]", file=sys.stderr)
            return 2
        doc_type = argv[1]
        status = argv[2] if len(argv) > 2 else ""
        name = argv[3] if len(argv) > 3 else ""
        d = suggest(doc_type, status, name)
        print(d.message)
        return 0 if d.expected is not None else 1

    if cmd == "check":
        if len(argv) < 2:
            print("usage: doc_home.py check <path>", file=sys.stderr)
            return 2
        d = check_path(argv[1])
        print(d.message, file=sys.stderr)
        if d.advisory:
            print("[DOC-HOME] advisory only (legacy area; no new docs)",
                  file=sys.stderr)
        return 0 if d.ok else 1

    print(f"unknown command: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
