#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/route-policy-recognizer-v1/route_policy_recognizer.vsm
# (R16_impl_with_design — función meta-reflexive de CHILD-ROUTE-REPAIR 2026-10-14:
#  lee la política de placement distribuida, no la hardcodea)
"""route_policy.py — META-REFLEXIVE route-policy recognizer (PATTERN-RUNNER).

Recognition function registered from the CHILD-ROUTE-REPAIR investigation
(2026-10-14): the placement policy (TYPE → home) already lives DISTRIBUTED in
the `classification.local.vsm` hierarchy — this tool READS it instead of
hardcoding placement. Given a design-doc TYPE it recognizes where the doc
belongs per canon; given an impl's `design:` ref it recognizes whether the
target lives where the policy says (and where it should).

Meta-reflexive: the policy is the input, not an assumption — add a rule to a
classification.local.vsm and this recognizer follows it (Policy declares,
instrument interprets — R16).

R10 deterministic: fnmatch against policy rules, no randomness, no wall-clock
in the recognition path (clock only in --fix marker writes).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

RULE_RX = re.compile(r'rule\("([^"]+)",\s*type="([^"]+)",\s*home="([^"]+)"\)')
DESIGN_RX = re.compile(r"design:\s*(\S+\.vsm)")
HEADER_RX = re.compile(r"⟦\s*[^|]+\|\s*([^|\s]+?)\s*\|")

# where a decommissioned child doc's TYPE may still be read (read-only sources)
CHILD_SOURCES = ["docs/archive/child", None]  # None → ~/vsf/child (external)


def load_policy(root: Path) -> list[dict]:
    """Parse the distributed placement policy: every classification.local.vsm
    rule → {rule, type_pattern, home, level}. Skips __pycache__ + archives."""
    rules = []
    for p in sorted(root.rglob("classification.local.vsm")):
        s = str(p)
        if "__pycache__" in s or "/archive/" in s:
            continue
        level = str(p.parent.relative_to(root))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in RULE_RX.finditer(text):
            rules.append({
                "rule": m.group(1),
                "type_pattern": m.group(2),
                "home": m.group(3),
                "level": level,
            })
    return rules


def recognize(rules: list[dict], type_name: str) -> list[dict]:
    """Given a TYPE, return the canon locations the policy maps it to."""
    hits = []
    for r in rules:
        if fnmatch.fnmatch(type_name.upper(), r["type_pattern"].upper()):
            loc = r["level"] if r["home"] == "." else f"{r['level']}/{r['home']}"
            hits.append({**r, "location": loc})
    return hits


def _read_header_type(doc: Path) -> str | None:
    try:
        head = doc.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return None
    m = HEADER_RX.search(head)
    return m.group(1) if m else None


def _find_doc(root: Path, decl: str) -> Path | None:
    """Locate a design doc referenced by a (possibly dead) child/ path.
    Read-only: archive first, then the external child. Never moves them."""
    name = Path(decl).name
    # 1. already canon (ref resolves live)
    live = root / decl
    if live.is_file():
        return live
    # 2. archived local child
    arch = root / "docs" / "archive" / "child" / "docs" / name
    if arch.is_file():
        return arch
    # 3. external child (~/vsf/child) — read-only source
    ext = Path.home() / "vsf" / "child" / "docs" / name
    if ext.is_file():
        return ext
    return None


def scan(root: Path) -> dict:
    """Scan implementation design: refs → recognize policy home → report
    refs whose target does NOT live where the policy says (child/ drift)."""
    rules = load_policy(root)
    impl_dirs = [".opencode/plugins", "scripts", "packages", "system",
                 "checks", "projects"]
    violations, checked = [], 0
    seen = set()
    for d in impl_dirs:
        base = root / d
        if not base.is_dir():
            continue
        for f in list(base.rglob("*.ts")) + list(base.rglob("*.py")) \
                + list(base.rglob("*.sh")):
            if "__pycache__" in str(f) or "/archive/" in str(f):
                continue
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:400]
            except OSError:
                continue
            m = DESIGN_RX.search(head)
            if not m:
                continue
            decl = m.group(1)
            checked += 1
            if not decl.startswith("child/"):
                continue  # only child/ (decommissioned) is the drift class
            target = _find_doc(root, decl)
            if target is None:
                violations.append({
                    "impl": str(f.relative_to(root)), "ref": decl,
                    "status": "unresolvable",
                })
                continue
            ttype = _read_header_type(target)
            if not ttype:
                violations.append({
                    "impl": str(f.relative_to(root)), "ref": decl,
                    "status": "no-type", "type": None,
                })
                continue
            homes = recognize(rules, ttype)
            locations = sorted({h["location"] for h in homes})
            key = (str(f.relative_to(root)), decl, tuple(locations))
            if key in seen:
                continue
            seen.add(key)
            violations.append({
                "impl": str(f.relative_to(root)), "ref": decl,
                "type": ttype, "policy_home": locations or ["UNMAPPED"],
                "status": "child-drift" if locations else "unmapped-type",
            })
    return {
        "checked": checked,
        "child_refs": len(violations),
        "violations": violations,
        "policy_rules": len(rules),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="route-policy recognizer")
    ap.add_argument("--root", default=".")
    ap.add_argument("--recognize", metavar="TYPE",
                    help="recognize the canon home for a TYPE")
    ap.add_argument("--strict", action="store_true",
                    help="exit 2 if any child/ route drift is found")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    rules = load_policy(root)

    if args.recognize:
        hits = recognize(rules, args.recognize)
        out = {"type": args.recognize,
               "locations": sorted({h["location"] for h in hits}),
               "rules": hits}
        print(json.dumps(out, indent=2, default=str))
        return 0 if hits else 1

    result = scan(root)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"policy rules={result['policy_rules']} "
              f"impl design:refs checked={result['checked']} "
              f"child drift={result['child_refs']}")
        for v in result["violations"]:
            home = ",".join(v.get("policy_home", []))
            print(f"  [{v['status']}] {v['impl']} → {v['ref']}"
                  + (f" (TYPE={v.get('type')} → {home})"
                     if v.get("type") else ""))
    # Read-only signal: drift lives in the printed output. Exit 0 so the
    # pattern-runner records OK (drift ≠ tool failure); --strict exits 2
    # for gate/verification assertions.
    if args.strict and result["child_refs"] > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
