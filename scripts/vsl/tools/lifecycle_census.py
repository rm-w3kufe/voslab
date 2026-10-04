#!/usr/bin/env python3
"""lifecycle_census.py — R10 decision-tree census over docs/ (G-27 auto_verify).

Applies the deterministic lifecycle decision tree from
docs/plans/docs_lifecycle_proposal.vsm (@decision_tree_R10) to every file
under docs/ and reports counts per destination category plus violators:
files whose observed category requires a transition that has not happened.

Categories, evaluated in this fixed order (same input -> same output):

  FROZEN       path under archive/, spec_revision/ or canon_mirror/
  RECORD       dir in {sessions, findings, experiments, evaluation,
               correspondence, historical, incidents}
  NARRATIVE    extension in {md, txt, rst}
  ARTIFACT     extension in {pdf, png, jpg, jpeg, svg, tex, bib, html,
               csv, tsv, ipynb, yaml, toml, lock, json, jsonl}
  STAY-D-C     .py under papers/ — stays with its paper record per
               decision D-C (experiment/paper scripts are companions)
  RUNTIME      .py elsewhere in docs/ — belongs in scripts/ or
               packages/ (violator if present)
  CONSIDERED   basename exists in system/ with identical sha256 AND
               the path is NOT bound by instance.vsm (duplicated logic
               with no live binding — should be archived; a bound
               duplicate like governance/covenant.vsm is the deliberate
               live canonical copy and classifies as ACTIVE-GOV)
  ACTIVE-GOV   bound by an instance.vsm docs/ prefix, or path under
               {plans, plan, governance} — living governance docs
  LOGIC-MARKER carries the census predicate|spec(|rule(|ante: marker
               without a system/ twin — reported for information
               (residual family tracked as G-26, not moved blindly)
  KERNEL-GAP   marker + system/ twin exists whose predicates are not
               kernel-enforced (rule 9 — backlog G-28..G-32; info)
  DOCS-LEGIT   everything else (the docs/ home for legitimate docs)

Violators (exit 1): RUNTIME outside D-C, or CONSIDERED without a live
binding — each demands a transition per the lifecycle model and was
not transitioned. LOGIC-MARKER and KERNEL-GAP are reported but never
violators (remediation is judgment/kernel work, tracked in backlog).

Usage:
    python3 scripts/vsl/tools/lifecycle_census.py [--root docs] [--json]
    python3 scripts/vsl/tools/lifecycle_census.py --violators  # rc1 if any

Exit codes: 0 = no violators, 1 = violators found, 2 = usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

RECORD_DIRS = {
    "sessions", "findings", "experiments", "evaluation",
    "correspondence", "historical", "incidents",
}
FROZEN_DIRS = {"archive", "spec_revision", "canon_mirror"}
NARRATIVE_EXT = {".md", ".txt", ".rst"}
ARTIFACT_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".svg", ".tex", ".bib",
    ".html", ".csv", ".tsv", ".ipynb", ".yaml", ".toml", ".lock",
    ".json", ".jsonl",
}
# Living governance paths (ACTIVE-GOV by path, not only by instance binding).
ACTIVE_GOV_DIRS = {"plans", "plan", "governance"}
# Paper/experiment .py companions stay with their records (decision D-C).
D_C_DIRS = {"papers"}
# Narrow census marker from the original 47-logic-candidates scan.
PREDICATE_RE = re.compile(r"\bpredicate|\bspec\(|\brule\(|\bante:")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def system_index(root: Path) -> dict[str, set[str]]:
    """basename -> set of sha256 for every file under root/system."""
    idx: dict[str, set[str]] = {}
    sysdir = root / "system"
    if not sysdir.is_dir():
        return idx
    for p in sysdir.rglob("*"):
        if p.is_file():
            idx.setdefault(p.name, set()).add(sha256(p))
    return idx


def instance_prefixes(root: Path) -> list[str]:
    """docs/ prefixes referenced by instance.vsm (ACTIVE binding)."""
    inst = root / "system/instance/vsf-instance-v1/instance.vsm"
    if not inst.is_file():
        return []
    text = inst.read_text(errors="replace")
    refs = set(re.findall(r"docs/[A-Za-z0-9_./-]+", text))
    # normalize to directory-ish prefixes RELATIVE to the census root
    # (docs/ stripped — classify() compares against root-relative paths)
    out = set()
    for r in refs:
        r = r[len("docs/"):]
        out.add(r if r.endswith("/") else r.rsplit("/", 1)[0] + "/")
    return sorted(out)


def carries_logic(path: Path) -> bool:
    """Predicate-like logic marker (deterministic content probe)."""
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return False
    return bool(PREDICATE_RE.search(text))


def classify(path: Path, root: Path, sys_idx: dict[str, set[str]],
             prefixes: list[str]) -> str:
    rel = path.relative_to(root)
    parts = rel.parts
    ext = path.suffix.lower()

    # 1. FROZEN
    if parts and parts[0] in FROZEN_DIRS:
        return "FROZEN"
    # 2. RECORD
    if any(p in RECORD_DIRS for p in parts):
        return "RECORD"
    # 3. NARRATIVE / ARTIFACT (json/jsonl evidence lives as artifact)
    if ext in NARRATIVE_EXT:
        return "NARRATIVE"
    if ext in ARTIFACT_EXT:
        return "ARTIFACT"
    # 4/5. RUNTIME — .py: D-C companions stay, the rest must transition
    if ext == ".py":
        if any(p in D_C_DIRS for p in parts):
            return "STAY-D-C"
        return "RUNTIME"
    # 6. CONSIDERED: byte-identical twin in system/, no live binding.
    #    A bound duplicate is the deliberate live canonical copy.
    rel_s = str(rel)
    bound = any(rel_s.startswith(pfx) for pfx in prefixes)
    shas = sys_idx.get(path.name, set())
    if shas and sha256(path) in shas:
        return "ACTIVE-GOV" if bound else "CONSIDERED"
    # 7/8/9. living governance by path, then logic probes
    if bound or (parts and parts[0] in ACTIVE_GOV_DIRS):
        return "ACTIVE-GOV"
    logic = ext in (".vsm", ".md") and carries_logic(path)
    if logic:
        return "KERNEL-GAP" if path.name in sys_idx else "LOGIC-MARKER"
    # 10. DOCS-LEGIT
    return "DOCS-LEGIT"


# Only untransitioned states are violators; LOGIC-MARKER/KERNEL-GAP are
# judgment/kernel work already tracked (G-26 / G-28..G-32).
VIOLATORS = {"CONSIDERED", "RUNTIME"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="docs", help="census root (default: docs)")
    ap.add_argument("--json", action="store_true", help="machine output")
    ap.add_argument("--violators", action="store_true",
                    help="print violators only")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"lifecycle_census: root not found: {root}", file=sys.stderr)
        return 2

    repo = Path.cwd()
    sys_idx = system_index(repo)
    prefixes = instance_prefixes(repo)

    rows: list[tuple[str, str]] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            rows.append((str(p.relative_to(root)), classify(p, root, sys_idx, prefixes)))

    counts = Counter(cat for _, cat in rows)
    # Violators only count outside FROZEN/RECORD (frozen copies are
    # provenance by design; runtime next to records is doctrine D-C).
    violators = [
        (rel, cat) for rel, cat in rows
        if cat in VIOLATORS and not rel.startswith(tuple(FROZEN_DIRS))
        and not any(f"/{d}/" in f"/{rel}/" for d in RECORD_DIRS)
    ]

    if args.json:
        print(json.dumps({
            "root": str(root),
            "total": len(rows),
            "counts": dict(counts.most_common()),
            "logic_markers": [rel for rel, cat in rows if cat == "LOGIC-MARKER"],
            "kernel_gaps": [rel for rel, cat in rows if cat == "KERNEL-GAP"],
            "violators": violators,
        }, indent=2))
    elif args.violators:
        for rel, cat in violators:
            print(f"{cat:12s} {rel}")
        print(f"{len(violators)} violators")
    else:
        print(f"lifecycle_census: {root}/ — {len(rows)} files")
        for cat, n in counts.most_common():
            print(f"  {cat:12s} {n:4d}")
        if violators:
            print(f"\nVIOLATORS ({len(violators)}):")
            for rel, cat in violators:
                print(f"  {cat:12s} {rel}")

    return 1 if violators else 0


if __name__ == "__main__":
    sys.exit(main())
