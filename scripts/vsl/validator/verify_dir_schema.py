#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/dir-schema-v1/dir_schema.spec.vsm
"""verify_dir_schema.py — DIR-SCHEMA policy verifier (DIR-SCHEMA-RECURSIVE-
2026-08-14). Deterministic, stdlib-only, no LLM (R10).

The POLICY lives in docs/spec_revision/design-sources/dir-schema-v1/dir_schema.spec.vsm. This
verifier INTERPRETS it — it never duplicates rules in code. Single source
of truth: edit the spec, the check follows.

What it checks, over docs/spec_revision/:
  (a) COVERED   — every .vsm under scope is classified by EXACTLY ONE
                  category (by TYPE from the ⟦ name | TYPE | vsm-1.0 | date ⟧
                  header, or by explicit files: entry — files wins).
  (b) PLACED    — the file's real directory is the one its category declares
                  (a file whose TYPE says s2 but sits in s4 is a violation).
  (c) STATIC    — a category declared static=true may not gain NEW files not
                  declared in the spec (the tree is stable; a new file must
                  be declared, not silently added).

Usage:
    python3 scripts/vsl/verify_dir_schema.py            # check (default)
    python3 scripts/vsl/verify_dir_schema.py --json     # machine-readable
    python3 scripts/vsl/verify_dir_schema.py --self     # fixture self-test

Exit codes: 0 = clean; 1 = VIOLATION; 2 = config error (spec missing).
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs/spec_revision/design-sources/dir-schema-v1/dir_schema.spec.vsm"
SCOPE = ROOT / "docs/spec_revision"

CAT_RE = re.compile(r'category\("([^"]+)",\s*role="([^"]+)"[^)]*\)\s*\{')
TYPES_RE = re.compile(r'types:\s*\[(.*?)\]', re.S)
FILES_RE = re.compile(r'files:\s*\[(.*?)\]', re.S)
STR_RE = re.compile(r'"([^"]+)"')


def load_policy(spec_text: str) -> list[dict]:
    """Parse the spec into categories: {dir, role, static, types, files}."""
    cats = []
    for m in CAT_RE.finditer(spec_text):
        d, role = m.group(1), m.group(2)
        # `static=true` may appear in the category declaration line, BEFORE
        # the `{` (e.g. category("…", role="boot", static=true) {). Grab the
        # whole declaration + body, not just the body after the brace.
        decl = spec_text[m.start():m.end()]
        end = spec_text.find("},", m.end())
        body = spec_text[m.end():end]
        tm = TYPES_RE.search(body)
        fm = FILES_RE.search(body)
        types = set(STR_RE.findall(tm.group(1))) if tm else set()
        files = set(STR_RE.findall(fm.group(1))) if fm else set()
        cats.append({
            "dir": d,
            "role": role,
            "static": "static=true" in (decl + body),
            "types": types,
            "files": files,
        })
    return cats


def doc_type(p: Path) -> str:
    """TYPE from the ⟦ name | TYPE | vsm-1.0 | date ⟧ header (2nd slot)."""
    line0 = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not line0 or "⟦" not in line0[0]:
        return "NO-HEADER"
    parts = line0[0].replace("⟦", "").split("|")
    return parts[1].strip() if len(parts) > 1 else "NO-HEADER"


def check(base: Path | None = None) -> list[str]:
    base = base or ROOT
    findings = []
    if not (base / SPEC.relative_to(ROOT)).exists():
        return ["CONFIG  dir_schema.spec.vsm missing — the policy must exist "
                "before the check can interpret it"]
    spec_text = (base / SPEC.relative_to(ROOT)).read_text(encoding="utf-8")
    cats = load_policy(spec_text)

    type2dir: dict[str, str] = {}
    for c in cats:
        for t in c["types"]:
            if t in type2dir:
                findings.append(f"COLLISION  type {t} declared in both "
                                f"{type2dir[t]} and {c['dir']}")
            type2dir[t] = c["dir"]
    file2dir: dict[str, str] = {}
    for c in cats:
        for f in c["files"]:
            if f in file2dir:
                findings.append(f"COLLISION  file {f} declared in both "
                                f"{file2dir[f]} and {c['dir']}")
            file2dir[f] = c["dir"]

    scope = base / SCOPE.relative_to(ROOT)
    vsms = sorted(scope.rglob("*.vsm")) if scope.exists() else []
    for p in vsms:
        rel = str(p.relative_to(base))
        t = doc_type(p)
        expected = file2dir.get(rel) or type2dir.get(t)
        if expected is None:
            findings.append(f"UNCOVERED  {rel} (type {t}) — no category declares "
                            f"this TYPE or file; add it to dir_schema.spec.vsm")
            continue
        if not rel.startswith(expected):
            findings.append(f"MISPLACED  {rel} (type {t}) — belongs under "
                            f"{expected}, found elsewhere")

    # (c) STATIC — a static category may not contain undeclared files.
    # Non-.vsm artifacts are ignored (the policy governs documents).
    # DIRECT children only (glob *), not recursive: category dirs are LEAF
    # containers — a file in a subdirectory belongs to that subcategory, and
    # the parent category must not re-flag it. The scope root (docs/spec_revision)
    # is a category only for its own top-level files.
    # A file is DECLARED if it is classified (by type or by explicit files:)
    # into THIS category. An undeclared file = sits in the dir without the
    # category claiming it (type belongs elsewhere, or no category at all).
    for c in cats:
        if not c["static"]:
            continue
        d = base / c["dir"]
        if not d.exists():
            continue
        for p in sorted(d.glob("*.vsm")):
            rel = str(p.relative_to(base))
            t = doc_type(p)
            # skip the spec itself (it declares itself by type)
            if rel == str(SPEC.relative_to(ROOT)):
                continue
            declared_here = (rel in file2dir and file2dir[rel] == c["dir"]) \
                or t in c["types"]
            if not declared_here:
                findings.append(f"UNDECLARED  {rel} sits in static {c['dir']} "
                                f"but the policy does not claim it (type "
                                f"{t} belongs to {type2dir.get(t, 'no category')}) "
                                f"— declare or move")

    return findings


# ══════════════════════════════════════════════════════════════════════
# selftest — fixture tree must FAIL; live tree must PASS
# ══════════════════════════════════════════════════════════════════════
def _make_fixture() -> Path:
    """A minimal broken tree: a MISPLACED file (type s2 in s4 dir), an
    UNCOVERED file (type not in any category), and an UNDECLARED file in a
    static dir. The policy spec is a copy of the REAL one (so the fixture
    exercises the real rules)."""
    d = Path(tempfile.mkdtemp(prefix="dir-schema-fixture-"))
    (d / "docs/spec_revision" / "system" / "s4-intelligence").mkdir(parents=True)
    (d / "docs/spec_revision" / "system" / "s2-coordination").mkdir(parents=True)
    (d / "docs/spec_revision" / "system" / "boot").mkdir(parents=True)
    (d / "docs/spec_revision" / "design-sources").mkdir(parents=True)
    # copy the real spec (self-test must use the real policy); spec/ root
    # REMOVED 2026-08-17 (no spec without plan — PART III); dir_schema
    # is a design source → it lives in design-sources/
    shutil.copy(SPEC, d / "docs/spec_revision/design-sources" / "dir_schema.spec.vsm")

    # (a) MISPLACED — an s2 type sitting in the s4 dir
    (d / "docs/spec_revision" / "system" / "s4-intelligence" / "s2_misplaced.vsm").write_text(
        "⟦ s2_misplaced | S2-NATS-01 | vsm-1.0 | 2026-08-14 ⟧\n\n@vsm 1.0\n",
        encoding="utf-8")
    # (b) UNCOVERED — a type no category declares
    (d / "docs/spec_revision" / "system" / "boot" / "ghost.vsm").write_text(
        "⟦ ghost | GHOST-TYPE-99 | vsm-1.0 | 2026-08-14 ⟧\n\n@vsm 1.0\n",
        encoding="utf-8")
    # (c) UNDECLARED — a file in a static dir not declared in the policy
    (d / "docs/spec_revision" / "system" / "boot" / "undeclared_new.vsm").write_text(
        "⟦ undeclared_new | VSL-HARD-RULES-v1 | vsm-1.0 | 2026-08-14 ⟧\n\n@vsm 1.0\n",
        encoding="utf-8")
    return d


def selftest() -> int:
    ok = True
    fx = _make_fixture()
    try:
        findings = check(base=fx)
        print(f"  fixture: {len(findings)} finding(s)")
        names = [f.split()[0] for f in findings]
        for expected in ("MISPLACED", "UNCOVERED", "UNDECLARED"):
            if expected not in names:
                print(f"    ✗ fixture should flag {expected}")
                ok = False
        for f in findings:
            print(f"    {f[:90]}")
    finally:
        shutil.rmtree(fx, ignore_errors=True)
    if ok:
        print("  selftest: PASS — all fixture classes detected")
    else:
        print("  selftest: FAIL — a fixture class was NOT detected")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--self" in args:
        return selftest()
    if not SPEC.exists():
        if "--json" in args:
            print(json.dumps({"ok": False, "error": "spec missing",
                              "findings": []}))
        else:
            print("✗ [dir-schema] config error: dir_schema.spec.vsm missing")
        return 2

    findings = check()
    if "--json" in args:
        print(json.dumps({"ok": not findings, "findings": findings}))
        return 0 if not findings else 1

    if findings:
        print(f"✗ [dir-schema] {len(findings)} violation(s):")
        for f in findings:
            print(f"    {f}")
        return 1
    print("✓ [dir-schema] clean: every .vsm under docs/spec_revision/ is "
          "classified and placed per dir_schema.spec.vsm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
