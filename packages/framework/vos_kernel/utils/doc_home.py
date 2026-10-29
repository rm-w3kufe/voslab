#!/usr/bin/env python3
"""doc_home.py — kernel resolver for the canonical home of a document.

design: docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm
(PART IV-B tree_rules + PART IV-C home_policy; F4 DOC-HOME-POLICY, S5 2026-10-29)

WHY: the classification policy already answered "where does this doc live?"
for the normative/design/plan tree. The F4 cleanup added records and output
homes (sessions, audit, findings, papers, ...). This module makes the answer
available BEFORE a new doc is created and enforces it at write time:

  * resolve(type, status, name) -> logical chain + physical directory
  * suggest(...) -> the exact path to create (or the approved home list)
  * check_path(path) -> ok / advisory / block, with the canonical path in the
    message

R10: every answer comes from the declared policy (classify.py reads the
policy doc). No LLM, no heuristics guessing a home. R9: an unknown nature is
visible ("?"), never silently accepted as "somewhere".

R16: policy declares, instrument interprets. The policy block is
`home_policy:` in classification_policy_plan.vsm; editing that block
re-routes the gate without editing this file.

The write gate (scripts/vsl/classifier/socratic_gate.py) delegates here; the
CLI (scripts/vsl/classifier/doc_home.py) exposes `suggest` to authors before
the write.
"""
from __future__ import annotations

import importlib.util
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
CLASSIFY_PATH = ROOT / "scripts" / "vsl" / "classifier" / "classify.py"

# Structural exclusions: verified copies, vendored packages, runtime state and
# plugin decision trees are not documents that choose a docs/ home.
SKIP_DIRS = (
    "docs/canon_mirror",
    "packages",
    "state",
    ".opencode/plugins/support/trees",
)
SKIP_NAMES = {
    "README.vsm", "INDEX.vsm", "classification.local.vsm",
    "TASKS.vsm", "HANDOFF.vsm", "MATTERS.vsm", "ROADMAP.vsm",
    "technical_debt_registry.vsm",
}
# Managed roots: the existing classification gate has always blocked a
# misplaced doc here (system/design/plan are already clean). Mismatches in
# these roots block for tracked docs too; elsewhere tracked legacy docs get
# an advisory so the cleanup does not turn every edit into a wall.
MANAGED_ROOTS = (
    "system",
    "docs/design/sources",
    "docs/design/sandbox",
    "docs/plans",
)


@dataclass(frozen=True)
class HomeDecision:
    path: Path
    doc_type: str = ""
    status: str = ""
    logical_home: str = "?"
    expected: Path | None = None
    actual: Path | None = None
    tracked: bool = True
    ok: bool = True
    advisory: bool = False
    reason: str = ""
    message: str = ""


_C: Any = None


def classifier():
    """Load the policy-driven classifier once (same module the check uses)."""
    global _C
    if _C is not None:
        return _C
    if not CLASSIFY_PATH.is_file():
        raise FileNotFoundError(f"classifier missing: {CLASSIFY_PATH}")
    spec = importlib.util.spec_from_file_location("vos_classify", CLASSIFY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    _C = mod
    return mod


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _approved_paths() -> tuple[Path, ...]:
    C = classifier()
    paths: list[Path] = []
    for name in sorted(C.APPROVED_HOMES):
        p = C.physical_home(name)
        if p is not None and p not in paths:
            paths.append(p)
    return tuple(paths)


def _in_approved(path: Path) -> bool:
    return any(_under(path, root) for root in _approved_paths())


def _legacy_area(path: Path) -> str | None:
    C = classifier()
    rel = _rel(path)
    for area in C.LEGACY_AREAS:
        if rel == area or rel.startswith(area.rstrip("/") + "/"):
            return area
    return None


def _managed(path: Path) -> bool:
    rel = _rel(path)
    return any(rel == r or rel.startswith(r + "/") for r in MANAGED_ROOTS)


def _tracked(path: Path) -> bool:
    """True when git already knows the path (existing doc, not a new write)."""
    if not _under(path, ROOT):
        return False
    try:
        p = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "--",
             _rel(path)],
            capture_output=True, text=True, timeout=10,
        )
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # Fail open for legacy edits: an unavailable git must not turn every
        # write into a classification block. New-doc enforcement still works
        # when git is present (the normal write path).
        return True


def _approved_list() -> str:
    C = classifier()
    return ", ".join(
        f"{name}({_rel(C.physical_home(name))})"
        for name in sorted(C.APPROVED_HOMES)
        if C.physical_home(name) is not None
    )


def resolve(doc_type: str, status: str = "", name: str = "") -> tuple[str, Path | None]:
    """Return the canonical logical chain and physical directory for a nature."""
    C = classifier()
    chain = C.apply_chain(doc_type, status, name) if doc_type else "?"
    return chain, C.physical_home(chain)


def suggest(doc_type: str, status: str = "", name: str = "") -> HomeDecision:
    """Answer 'where should I create this doc?' from the policy."""
    chain, expected = resolve(doc_type, status, name)
    if expected is not None:
        return HomeDecision(
            path=expected,
            doc_type=doc_type,
            status=status,
            logical_home=chain,
            expected=expected,
            actual=expected,
            ok=True,
            reason="policy",
            message=f"{doc_type or '?'} -> home '{chain}' = {_rel(expected)}",
        )
    return HomeDecision(
        path=ROOT,
        doc_type=doc_type,
        status=status,
        logical_home=chain,
        expected=None,
        actual=None,
        ok=False,
        reason="unknown",
        message=(
            f"{doc_type or '?'} has no deterministic home in the policy. "
            f"Approved homes: {_approved_list()}"
        ),
    )


def check_path(path: str | Path) -> HomeDecision:
    """Classify ONE file for the write-time gate.

    Contract:
      * canonical / approved home -> ok
      * tracked legacy doc in a legacy area -> ok + advisory
      * new doc outside the approved homes -> block
      * typed doc whose policy home differs -> block (managed roots always;
        elsewhere only for new docs, so legacy edits stay possible)
      * external unknown file -> skip (not our corpus)
    """
    p = Path(path).resolve()
    if not p.exists() or p.suffix != ".vsm":
        return HomeDecision(path=p, ok=True, reason="skip",
                            message=f"[DOC-HOME] {p.name}: not a .vsm — skip")
    if p.name in SKIP_NAMES:
        return HomeDecision(path=p, ok=True, reason="skip",
                            message=f"[DOC-HOME] {p.name}: state/gateway artefact — skip")
    rel = _rel(p)
    if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
        return HomeDecision(path=p, ok=True, reason="skip",
                            message=f"[DOC-HOME] {p.name}: structural exclusion — skip")

    C = classifier()
    doc_type, status = C.read_doc_nature(p)
    chain, expected = resolve(doc_type, status, p.name)
    actual = p.parent
    tracked = _tracked(p)
    in_repo = _under(p, ROOT)

    if expected is not None:
        if _under(actual, expected):
            return HomeDecision(
                path=p, doc_type=doc_type, status=status,
                logical_home=chain, expected=expected, actual=actual,
                tracked=tracked, ok=True, reason="canonical",
                message=f"[DOC-HOME] {p.name}: home='{chain}' ✓ coincide "
                        f"(real: {_rel(actual)})",
            )

        # Misplaced. Managed roots are strict for every write (the existing
        # classification contract). Legacy dirs are advisory for tracked docs
        # so the F4 cleanup can edit them until their wave; a NEW doc there is
        # blocked. A new file in an approved area whose type points elsewhere
        # is also blocked (the policy answer wins over the chosen path).
        strict = _managed(actual) or not tracked or _in_approved(actual)
        if strict:
            return HomeDecision(
                path=p, doc_type=doc_type, status=status,
                logical_home=chain, expected=expected, actual=actual,
                tracked=tracked, ok=False, reason="mismatch",
                message=(
                    f"[DOC-HOME] {p.name}: MISMATCH — el árbol dice "
                    f"home='{chain}' ({_rel(expected)}) pero el archivo vive en "
                    f"{_rel(actual)}. Create/move it to {_rel(expected)}."
                ),
            )
        return HomeDecision(
            path=p, doc_type=doc_type, status=status,
            logical_home=chain, expected=expected, actual=actual,
            tracked=tracked, ok=True, advisory=True, reason="legacy-mismatch",
            message=(
                f"[DOC-HOME] {p.name}: legacy area {_rel(actual)} (advisory; "
                f"policy home is {_rel(expected)}). No new docs here."
            ),
        )

    # No deterministic home: the path itself decides whether a new doc may
    # be born. Approved areas accept; legacy areas accept only tracked docs;
    # anything else is a new orphan.
    if in_repo:
        if _in_approved(actual):
            return HomeDecision(
                path=p, doc_type=doc_type, status=status,
                logical_home=chain, expected=None, actual=actual,
                tracked=tracked, ok=True, reason="approved-area",
                message=(
                    f"[DOC-HOME] {p.name}: '{doc_type or '?'}' has no policy "
                    f"chain, but {_rel(actual)} is an approved home — ok"
                ),
            )
        area = _legacy_area(actual)
        if area is not None and tracked:
            return HomeDecision(
                path=p, doc_type=doc_type, status=status,
                logical_home=chain, expected=None, actual=actual,
                tracked=tracked, ok=True, advisory=True, reason="legacy-area",
                message=(
                    f"[DOC-HOME] {p.name}: legacy area {area} (advisory). "
                    f"No new docs here; promote/archive in F4."
                ),
            )
        reason = "legacy-new" if area is not None else "no-home"
        return HomeDecision(
            path=p, doc_type=doc_type, status=status,
            logical_home=chain, expected=None, actual=actual,
            tracked=tracked, ok=False, reason=reason,
            message=(
                f"[DOC-HOME] {p.name}: NEW doc outside the approved homes "
                f"({_rel(actual)}). Create it in one of: {_approved_list()}"
            ),
        )

    # Outside the repo: only a typed doc can be compared (socratic gate
    # fixtures); an unknown external file is out of corpus.
    if expected is None:
        return HomeDecision(path=p, doc_type=doc_type, status=status,
                            logical_home=chain, ok=True, reason="external",
                            message=f"[DOC-HOME] {p.name}: external/unknown — skip")
    return HomeDecision(
        path=p, doc_type=doc_type, status=status, logical_home=chain,
        expected=expected, actual=actual, tracked=False, ok=False,
        reason="external-mismatch",
        message=(
            f"[DOC-HOME] {p.name}: MISMATCH — policy home is "
            f"{_rel(expected)}; file is outside the repository."
        ),
    )
