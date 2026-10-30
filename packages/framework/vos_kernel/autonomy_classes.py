"""autonomy_classes.py — per-class activation registry (A-3 / CC-8.2 pre-work).

Machine-checkable bounds for per-class auto-execution (backlog A-3:
"registro por clase propuesto (sin auto-approve real)"). NOTHING here
grants autonomy: `can_execute()` returns False for every class until S5
signs a specific one (R17: no stage self-promotes; L4_AUTO stays False).

Registry file: state/autonomy_classes.json (tracked knowledge — S5 edits
the signature, we only validate). Contract:
    docs/design/sandbox/autonomy-class-registry-01/autonomy_class_registry.vsm (proposed)

Class schema (all required unless noted):
    id, name            identifiers
    scope               list of path globs the class may touch
    max_blast_radius    human+machine label (e.g. "docs-only", "tests-only")
    trial_cycles        K clean auto-actions required by S5 at ratification
    status              "proposed" | "ratified" | "revoked"
    auto_execute        MUST be false until ratified (validated)
    sha_pin             required only when status == "ratified"
    s5_signed_at        required only when status == "ratified"
    rationale           free text (why the class exists)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[3]  # vos_kernel -> packages -> framework? no: vOSlab
REGISTRY_PATH = WORKSPACE / "state" / "autonomy_classes.json"

STATUSES = ("proposed", "ratified", "revoked")
REQUIRED_ANY = ("id", "name", "scope", "max_blast_radius", "trial_cycles",
                "status", "auto_execute", "rationale")
REQUIRED_RATIFIED = ("sha_pin", "s5_signed_at")


def validate_class(entry: dict[str, Any]) -> list[str]:
    """Violations for one class entry (empty = schema-valid). Deterministic (R10)."""
    fails: list[str] = []
    if not isinstance(entry, dict):
        return ["entry must be an object"]
    cid = entry.get("id", "?")
    for field in REQUIRED_ANY:
        if field not in entry:
            fails.append(f"{cid}: missing field {field}")
    status = entry.get("status")
    if status is not None and status not in STATUSES:
        fails.append(f"{cid}: status {status!r} not in {list(STATUSES)}")
    scope = entry.get("scope")
    if scope is not None and (
        not isinstance(scope, list) or not scope
        or not all(isinstance(g, str) and g for g in scope)
    ):
        fails.append(f"{cid}: scope must be a non-empty list of globs")
    if not isinstance(entry.get("trial_cycles"), int) or entry.get("trial_cycles", 0) < 1:
        if "trial_cycles" in entry:
            fails.append(f"{cid}: trial_cycles must be a positive integer")
    if entry.get("auto_execute") is not False:
        fails.append(
            f"{cid}: auto_execute must be false until S5 signs this class (R17)"
        )
    if status == "ratified":
        for field in REQUIRED_RATIFIED:
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                fails.append(f"{cid}: ratified class requires {field}")
    return fails


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load the registry file: {classes: [...], ...}. Raises on malformed JSON."""
    target = Path(path) if path else REGISTRY_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("classes"), list):
        raise ValueError(f"{target}: registry must be an object with a 'classes' list")
    return data


def validate_registry(registry: dict[str, Any]) -> list[str]:
    """All violations: schema + duplicate ids."""
    fails: list[str] = []
    seen: set[str] = set()
    for entry in registry.get("classes", []):
        fails.extend(validate_class(entry))
        cid = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(cid, str):
            if cid in seen:
                fails.append(f"{cid}: duplicate class id")
            seen.add(cid)
    return fails


def can_execute(
    class_id: str,
    registry: dict[str, Any] | None = None,
    head_sha: str | None = None,
) -> tuple[bool, str]:
    """May the system auto-execute inside this class RIGHT NOW?

    Returns (allowed, reason). Allowed only when: the class exists, its
    schema is valid, S5 signed it (status=ratified + s5_signed_at), and —
    if head_sha is given — it matches the class sha_pin. Everything else
    is blocked with the exact reason (honest, no silent allows).
    """
    if registry is None:
        try:
            registry = load_registry()
        except (OSError, ValueError) as exc:
            return False, f"registry unreadable: {exc}"
    entry = next(
        (c for c in registry.get("classes", []) if isinstance(c, dict)
         and c.get("id") == class_id),
        None,
    )
    if entry is None:
        return False, f"unknown class {class_id!r}"
    violations = validate_class(entry)
    if violations:
        return False, f"schema violations: {violations}"
    if entry.get("status") != "ratified":
        return False, (
            f"class {class_id!r} is {entry.get('status')} — S5 has not signed "
            f"it (R17: no stage self-promotes)"
        )
    if head_sha is not None and entry.get("sha_pin") != head_sha:
        return False, (
            f"sha_pin mismatch: class pinned to {entry.get('sha_pin')}, "
            f"HEAD is {head_sha} — re-ratify after the change"
        )
    return True, f"class {class_id!r} ratified by S5 at {entry.get('s5_signed_at')}"


def main(argv: list[str] | None = None) -> int:
    """CLI: validate the live registry; --check CLASS [HEAD_SHA] gates one class."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=None)
    parser.add_argument("--check", metavar="CLASS", default=None)
    parser.add_argument("--head-sha", default=None)
    args = parser.parse_args(argv)
    try:
        registry = load_registry(args.registry)
    except (OSError, ValueError) as exc:
        print(f"autonomy-classes: {exc}", file=sys.stderr)
        return 2
    violations = validate_registry(registry)
    if violations:
        for v in violations:
            print(f"autonomy-classes: {v}", file=sys.stderr)
        return 1
    if args.check:
        allowed, reason = can_execute(args.check, registry, args.head_sha)
        print(("ALLOW " if allowed else "BLOCK ") + reason)
        return 0 if allowed else 1
    print(f"autonomy-classes: {len(registry['classes'])} classes, schema OK "
          f"(all auto_execute=false until S5 signs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
