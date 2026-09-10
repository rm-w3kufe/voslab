#!/usr/bin/env python3
"""route_component.py — Executable routing policy (prop_routing_policy).

Implements the decision tree as route(): domain-agnostic logic goes to
socratic-engine, write-time enforcement to opencode plugins, validation
math to vsf scripts, specifications to docs/. Anything else returns
evaluate_case_by_case with low confidence (never guessed).

Heuristics are file-evidence based and deterministic (R10):
  .ts under .opencode/plugins/            -> opencode_plugin
  .py importing socratic_engine           -> socratic-engine
  .py under scripts/vsl/{tools,validator,classifier} -> vsf_script
  .vsm with parseable header              -> docs_spec_revision
  else                                    -> evaluate_case_by_case

execute_routing() moves files ONLY inside the repo, ONLY to existing
directories, and refuses anything else (closed-lab rule). Dry-run first.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[2]

DEST_DIRS = {
    "opencode_plugin": VOSLAB / ".opencode" / "plugins" / "operational",
    "vsf_script": VOSLAB / "scripts" / "vsl" / "tools",
    "socratic-engine": None,  # external package: reference only, never move
    "docs_spec_revision": VOSLAB / "docs",
}


@dataclass
class RoutingDecision:
    destination: str
    confidence: float
    reasons: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)
    examples: list = field(default_factory=list)


def _read_head(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def route_component(path: Path | str) -> RoutingDecision:
    """Route a component file to its substrate. Never raises on missing."""
    p = Path(path)
    suffix = p.suffix.lower()
    parts = p.parts
    head = _read_head(p)

    if suffix == ".ts" and ".opencode" in parts and "plugins" in parts:
        return RoutingDecision(
            "opencode_plugin", 0.9,
            ["typescript under .opencode/plugins/ (lifecycle hooks)"],
            [], ["vsl-check-on-write.ts"])

    if suffix == ".py":
        if "socratic_engine" in head and "PredicateResult" in head:
            return RoutingDecision(
                "socratic-engine", 0.75,
                ["defines engine predicates (domain logic)"],
                ["vsf_script"],
                ["vsf_predicates.py"])
        if "scripts" in parts and "vsl" in parts:
            return RoutingDecision(
                "vsf_script", 0.8,
                ["python under scripts/vsl/ (validation/calc)"],
                [], ["check.py"])

    if suffix == ".vsm":
        if re.search(r"⟦\s*\w+\s*\|", head):
            return RoutingDecision(
                "docs_spec_revision", 0.8,
                ["parseable VSM header (specification)"],
                [], ["write_gates.vsm"])

    return RoutingDecision(
        "evaluate_case_by_case", 0.2,
        ["no routing evidence matched"],
        ["vsf_script", "docs_spec_revision"], [])


@dataclass
class RoutingResult:
    decision: dict
    dry_run: bool = True
    moved: bool = False
    dest: str | None = None
    reason: str = ""


def execute_routing(path: Path | str, decision: RoutingDecision,
                    dry_run: bool = True) -> RoutingResult:
    """Move a file to its routed destination. Conservative by design."""
    from dataclasses import asdict as _asdict
    p = Path(path)
    dest = DEST_DIRS.get(decision.destination)
    result = RoutingResult(decision=_asdict(decision), dry_run=dry_run)
    if decision.destination == "evaluate_case_by_case":
        result.reason = "low confidence: human decides"
        return result
    if dest is None:
        result.reason = (f"{decision.destination} is external: "
                         "reference only, files never move there")
        return result
    if not p.is_file():
        result.reason = "source missing"
        return result
    try:
        p.resolve().relative_to(VOSLAB)
        target = (dest / p.name).resolve()
        target.relative_to(VOSLAB)
    except (ValueError, RuntimeError):
        result.reason = "outside workspace: refused"
        return result
    if not dest.is_dir():
        result.reason = f"destination dir missing: {dest}"
        return result
    result.dest = str(target)
    if dry_run:
        result.reason = "dry-run: nothing moved"
        return result
    shutil.move(str(p), str(target))
    result.moved = True
    return result
