"""workspaces — declared-workspace registry (EP-4 D2, plan line 30 / M7).

A write landing outside the repo is invisible to every repo-local
instrument unless its root is DECLARED here: gap-resolution.ts then logs
``declared workspace <id>`` (result ok) instead of the blind
``no gaps triggered`` skip (baseline: 756 skips, plan line 347), and logs
``UNDECLARED external write`` (result skip) for anything unknown — both
countable in logs/agent_plugin.jsonl.

Determinism (R10): longest-root match with path-separator boundary
(``/a/ws2`` is NOT inside ``/a/ws``), ties broken by id; registry JSON is
written with sort_keys, entries kept sorted by id.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from vos_kernel.epistemic import repo_root

KINDS = ("sandbox", "shared", "reference", "remote")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REGISTRY_VERSION = 1


def registry_path(root: Path | None = None) -> Path:
    if root is None:
        # Test/ops seam: point the CLI at an isolated registry without
        # touching the real one (repo_root() is __file__-anchored).
        override = os.environ.get("VOS_WORKSPACES_PATH")
        if override:
            return Path(override)
    return (root or repo_root()) / "state" / "workspaces.json"


def load(root: Path | None = None) -> dict:
    """Read the registry; fail-soft to an empty one (never crash)."""
    try:
        data = json.loads(registry_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": REGISTRY_VERSION, "workspaces": []}
    if not isinstance(data, dict) or not isinstance(
            data.get("workspaces"), list):
        return {"version": REGISTRY_VERSION, "workspaces": []}
    return data


def _save(reg: dict, root: Path | None = None) -> None:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(path_root: str) -> str:
    expanded = os.path.expanduser(path_root)
    if not os.path.isabs(expanded):
        raise ValueError(f"workspace root must be absolute: {path_root}")
    return os.path.normpath(expanded)


def entries(root: Path | None = None) -> list[dict]:
    return sorted(load(root)["workspaces"], key=lambda e: e.get("id", ""))


def declare(path_root: str, ws_id: str, kind: str, note: str = "",
            registry_root: Path | None = None) -> dict:
    """Declare a workspace root. Strict: unique id AND unique root."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}: {kind}")
    if not _ID_RE.match(ws_id):
        raise ValueError(f"invalid workspace id: {ws_id!r}")
    norm = _normalize(path_root)
    reg = load(registry_root)
    for e in reg["workspaces"]:
        if e.get("id") == ws_id:
            raise ValueError(f"workspace id already declared: {ws_id}")
        if e.get("root") == norm:
            raise ValueError(
                f"root already declared: {norm} (id={e.get('id')})")
    entry = {
        "id": ws_id,
        "root": norm,
        "kind": kind,
        "note": note,
        "registered_at": _now(),
    }
    reg["workspaces"] = sorted(
        [*reg["workspaces"], entry], key=lambda e: e.get("id", ""))
    reg["version"] = REGISTRY_VERSION
    reg["updated_at"] = _now()
    _save(reg, registry_root)
    return entry


def lookup(target: str, registry_root: Path | None = None) -> dict | None:
    """Longest declared root containing target (separator boundary)."""
    norm = os.path.normpath(os.path.abspath(
        os.path.expanduser(target)))
    hits = []
    for e in entries(registry_root):
        root = e.get("root")
        if not root:
            continue
        # tolerate trailing slashes in hand-edited registries (mirror of
        # the TS `w.root.replace(/\\/+$/, "")` in gap-resolution.ts)
        root_norm = root.rstrip(os.sep) or os.sep
        prefix = root_norm if root_norm.endswith(os.sep) else root_norm + os.sep
        if norm == root_norm or norm.startswith(prefix):
            hits.append(e)
    if not hits:
        return None
    # longest root wins; ties broken by id (deterministic, R10)
    hits.sort(key=lambda e: (-len(e["root"].rstrip(os.sep) or os.sep),
                             e["id"]))
    return hits[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="vos_kernel.workspaces",
        description="EP-4 D2: declare / list / check external workspaces")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("declare", help="declare an external workspace root")
    p.add_argument("root")
    p.add_argument("--id", required=True, dest="ws_id")
    p.add_argument("--kind", required=True)
    p.add_argument("--note", default="")

    sub.add_parser("list", help="print declared workspaces (JSON)")

    p = sub.add_parser("check", help="is path inside a declared workspace? "
                                     "(rc0 declared / rc1 undeclared)")
    p.add_argument("path")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "declare":
            entry = declare(args.root, args.ws_id, args.kind, args.note)
            print(json.dumps(entry, sort_keys=True))
            return 0
        if args.cmd == "list":
            print(json.dumps({"version": REGISTRY_VERSION,
                              "workspaces": entries()},
                             indent=2, sort_keys=True))
            return 0
        # check
        hit = lookup(args.path)
        if hit:
            print(f"declared {hit['id']} ({hit['kind']}): {args.path}")
            return 0
        print(f"undeclared {args.path}")
        return 1
    except ValueError as exc:
        print(f"workspaces: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
