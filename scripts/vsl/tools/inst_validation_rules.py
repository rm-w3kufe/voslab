#!/usr/bin/env python3
"""inst_validation_rules.py — runtime evaluator for the instance
validation rules declared in system/instance/inst-validation-01/
validation.vsm (G-30).

The document recorded outcomes measured by hand on 2026-08-09 for its
11 checks c1..c11; nothing re-evaluated them afterwards (G-30: 0
runtime consumers of its fails_if rules). This tool keeps the same
coverage ledger, split honestly:

  RUNNABLE   c1_pairs, c2_s1_pairs, c4_no_secrets, c5_contract_uniqueness
             — mechanical, deterministic (R10): file presence, secret
             literals, duplicate contract declarations.
  COVERED    c7_bindings -> checks/bindings-valid (#67)
             c8_parse    -> checks/vsl-gate-valid (grammar battery)
             (verified present here; their own rc is the live truth —
             this tool does not re-run them, no double counting)
  SKIPPED    c3_root_resolves   — requires @var-marking judgment per doc
             c6_hierarchy       — requires level-placement judgment
             c9_model_reality   — requires live substrate (vsf-q/state_db)
             c10_gates_current  — semantic (which precondition is cited)
             c11_debt_register  — semantic (finding deferred in prose)
             Each states WHY (mirrors the doc's own covers_not).

Exit codes: 0 = no runnable violation and coverage wiring intact;
1 = violation or missing coverage wiring; 2 = usage.

Usage:
    python3 scripts/vsl/tools/inst_validation_rules.py
    python3 scripts/vsl/tools/inst_validation_rules.py --self-test
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# c1: template -> instantiated counterparts (from validation.vsm outcome)
C1_MAPS = [
    ("system/instance/templates/instance.template.vsm",
     ["system/instance/vsf-instance-v1/instance.vsm"]),
    ("system/s1-operations/s1-template/contract.template.vsm",
     ["system/s1-operations/s1-clima/s1-clima.contract.vsm",
      "system/s1-operations/s1-econ/s1-econ.contract.vsm",
      "system/s1-operations/s1-bbh/s1-bbh.contract.vsm"]),
    ("system/s1-operations/s1-template/instance.template.vsm",
     ["system/s1-operations/s1-clima/s1-clima.instance.vsm",
      "system/s1-operations/s1-econ/s1-econ.instance.vsm",
      "system/s1-operations/s1-bbh/s1-bbh.instance.vsm"]),
    ("system/instance/templates/validation.template.vsm",
     ["system/instance/inst-validation-01/validation.vsm"]),
]
# c2: each S1 must carry BOTH its contract and instance document
C2_S1_DIRS = [
    "system/s1-operations/s1-clima",
    "system/s1-operations/s1-econ",
    "system/s1-operations/s1-bbh",
]
# c4: secret literals (reference-by-name is fine; literal value = fail)
C4_PATTERNS = [
    re.compile(r"NATSECRET[A-Za-z0-9]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?:password|secret|token)\s*[:=]\s*[\"']"
               r"[A-Za-z0-9+/_-]{16,}[\"']", re.IGNORECASE),
]
# coverage wiring: doc rule -> existing check that owns it live
C7_C8_COVERAGE = {
    "c7_bindings": "bindings-valid",
    "c8_parse": "vsl-gate-valid",
}
C3_C6_C9_C10_C11_SKIP = {
    "c3_root_resolves": "requires per-doc @var-marking judgment (covers_not: user-abs out of scope)",
    "c6_hierarchy": "requires coupling level-placement judgment",
    "c9_model_reality": "requires live substrate (vsf-q services / state_db)",
    "c10_gates_current": "semantic: whether the cited blocker is the satisfied precondition",
    "c11_debt_register": "semantic: whether a finding was deferred in prose",
}
CONTRACT_DECL_RE = re.compile(r'contract\("([^"<]+)"\)')
SCANNED_DIRS = ("system", "docs")
SKIP_PATH_PARTS = {"archive", "spec_revision", "canon_mirror", "node_modules", ".git"}


def _iter_docs(root: Path):
    for d in SCANNED_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in (".vsm", ".md"):
                continue
            if any(part in SKIP_PATH_PARTS for part in p.parts):
                continue
            yield p


def run_rules(root: Path) -> list[str]:
    """Evaluate every runnable rule. Deterministic (R10)."""
    violations: list[str] = []

    # c1_pairs: every template has its instantiated counterpart(s)
    for tmpl, counterparts in C1_MAPS:
        if not (root / tmpl).is_file():
            violations.append(f"c1_pairs: template missing: {tmpl}")
        for cp in counterparts:
            if not (root / cp).is_file():
                violations.append(
                    f"c1_pairs: template {tmpl} has no counterpart: {cp}"
                )

    # c2_s1_pairs: each S1 carries BOTH contract and instance
    for d in C2_S1_DIRS:
        base = Path(d).name
        for kind in ("contract", "instance"):
            f = root / d / f"{base}.{kind}.vsm"
            if not f.is_file():
                violations.append(
                    f"c2_s1_pairs: {d} missing {kind} document ({f.name})"
                )

    # c4_no_secrets: no credential/key/token literal in published docs
    for p in _iter_docs(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in C4_PATTERNS:
            m = pat.search(text)
            if m:
                violations.append(
                    f"c4_no_secrets: {p.relative_to(root)}: literal "
                    f"matches {pat.pattern[:40]!r}"
                )
                break

    # c5_contract_uniqueness: exactly ONE document declaring each contract
    decls: dict[str, list[str]] = {}
    for p in _iter_docs(root):
        if p.suffix != ".vsm":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in CONTRACT_DECL_RE.findall(text):
            decls.setdefault(name, []).append(str(p.relative_to(root)))
    for name, files in sorted(decls.items()):
        if len(files) > 1:
            violations.append(
                f"c5_contract_uniqueness: contract {name!r} declared in "
                f"{len(files)} documents: {', '.join(files)}"
            )

    # c7/c8 coverage wiring must exist (their own rc is the live truth)
    checks_dir = root / "packages/public/vsf-checks/checks"
    for rule, check in C7_C8_COVERAGE.items():
        if not (checks_dir / check).is_file():
            violations.append(
                f"{rule}: coverage check missing: checks/{check}"
            )

    return violations


def self_test() -> int:
    """Fixture roots: each violation class must be caught; clean passes."""
    failures: list[str] = []

    # (1) clean mini-root passes
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for tmpl, cps in C1_MAPS:
            (root / tmpl).parent.mkdir(parents=True, exist_ok=True)
            (root / tmpl).write_text("x\n")
            for cp in cps:
                (root / cp).parent.mkdir(parents=True, exist_ok=True)
                (root / cp).write_text("x\n")
        for d in C2_S1_DIRS:
            base = Path(d).name
            for kind in ("contract", "instance"):
                (root / d).mkdir(parents=True, exist_ok=True)
                (root / d / f"{base}.{kind}.vsm").write_text("x\n")
        checks_dir = root / "packages/public/vsf-checks/checks"
        checks_dir.mkdir(parents=True)
        for check in C7_C8_COVERAGE.values():
            (checks_dir / check).write_text("#!/bin/sh\nexit 0\n")
        clean = run_rules(root)
        if clean:
            failures.append(f"clean root flagged: {clean}")

        # (2) c2: S1 missing its instance document
        (root / "system/s1-operations/s1-econ/s1-econ.instance.vsm").unlink()
        # (3) c5: duplicate contract declaration
        dup = root / "system/s1-operations/s1-clima/second.vsm"
        dup.write_text('contract("S1-CLIMA") {\n}\n')
        # first declaration also present in s1-clima.contract.vsm? make it so
        (root / "system/s1-operations/s1-clima/s1-clima.contract.vsm").write_text(
            'contract("S1-CLIMA") {\n}\n')
        # (4) c4: secret literal
        (root / "system/leak.vsm").write_text(
            'token: "abcdef0123456789ZZZZ"\n')
        # (5) c1: counterpart removed
        (root / "system/instance/inst-validation-01/validation.vsm").unlink()

        dirty = run_rules(root)
        for prefix, wanted in (
            ("c2_s1_pairs", True),
            ("c5_contract_uniqueness", True),
            ("c4_no_secrets", True),
            ("c1_pairs", True),
        ):
            found = any(v.startswith(prefix) for v in dirty)
            if found != wanted:
                failures.append(f"{prefix}: found={found}, wanted={wanted}")

    if failures:
        for f in failures:
            print(f"SELF-TEST FAIL: {f}", file=sys.stderr)
        return 1
    print("self-test ok: clean root passes; c1/c2/c4/c5 violations caught")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    root = Path(args.root)
    violations = run_rules(root)
    print("inst_validation_rules: RUNNABLE c1_pairs c2_s1_pairs "
          "c4_no_secrets c5_contract_uniqueness")
    print("  COVERED   c7_bindings -> checks/bindings-valid, "
          "c8_parse -> checks/vsl-gate-valid")
    for rule, why in C3_C6_C9_C10_C11_SKIP.items():
        print(f"  SKIPPED   {rule} — {why}")
    if violations:
        for v in violations:
            print(f"  VIOLATION {v}")
        print(f"{len(violations)} violation(s)")
        return 1
    print("  OK — no runnable violation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
