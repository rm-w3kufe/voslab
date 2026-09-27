"""guard-coverage gate — F→G of EPISTEMIC-CERT-001 (plan §6, phase EP-1).

Every finding that carries a `fix` must name an executable guard that exists
in guards.jsonl and is not dead/none. A fix without a guard is the classic
"correction that hides its own bugs" failure (FIXES.md: "A correction with
hidden bugs is worse than the original").

Inputs accepted:
  - a findings JSONL file (guards read from a sibling guards.jsonl if
    present, else from the central store state/epistemic/guards.jsonl)
  - a directory containing findings.jsonl
  - anything else: out of scope -> accepted

Negative case: a findings file where a finding has a fix but no guard —
the gate MUST reject it (exit != 0).

Run by the harness: register("guard-coverage", check, negative_case).
The real-data audit is `python3 -m vos_kernel.epistemic audit-guards`.
"""

from __future__ import annotations

import json
import os
import tempfile

from gate_suite.harness import register

# central store (repo layout: <root>/packages/framework/gate_suite/gates/...)
_CENTRAL = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "state", "epistemic", "guards.jsonl")
)


def _load_jsonl(path: str) -> list[dict]:
    out = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _guards_for(findings_path: str) -> dict[str, dict]:
    """Sibling guards.jsonl first (self-contained temp artifacts), else the
    central registry."""
    sibling = os.path.join(os.path.dirname(findings_path), "guards.jsonl")
    src = sibling if os.path.exists(sibling) else _CENTRAL
    if not os.path.exists(src):
        return {}
    try:
        return {g["id"]: g for g in _load_jsonl(src) if "id" in g}
    except (OSError, json.JSONDecodeError, KeyError):
        return {}


def _audit_file(findings_path: str) -> int:
    try:
        findings = _load_jsonl(findings_path)
    except (OSError, json.JSONDecodeError):
        return 1  # unreadable ledger -> reject
    guards = _guards_for(findings_path)
    for f in findings:
        fid = f.get("id", "?")
        status = f.get("guard_status")
        if status not in ("live", "dead", "unknown", "none"):
            return 1  # malformed finding
        fix = f.get("fix")
        if not isinstance(fix, str):
            return 1
        if not fix:
            continue  # no fix -> F→G does not apply
        gid = f.get("guard")
        if not gid or status in ("none", "dead"):
            return 1  # fix without a usable guard -> reject
        if gid not in guards:
            return 1  # guard does not exist -> reject
    return 0


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED."""
    if os.path.isdir(path):
        findings = os.path.join(path, "findings.jsonl")
        if not os.path.exists(findings):
            return 0  # no findings ledger in scope -> accept
        return _audit_file(findings)
    if path.endswith(".jsonl") and os.path.basename(path) == "findings.jsonl":
        return _audit_file(path)
    if path.endswith(".jsonl"):
        # a generic jsonl: audit only if it looks like a findings ledger
        try:
            findings = _load_jsonl(path)
        except (OSError, json.JSONDecodeError):
            return 0  # not ours -> out of scope
        if findings and all(isinstance(f, dict) and "symptom" in f
                            for f in findings):
            return _audit_file(path)
        return 0
    return 0


def negative_case() -> str:
    root = tempfile.mkdtemp(prefix="voslab_f2g_")
    with open(os.path.join(root, "guards.jsonl"), "w") as f:
        f.write(json.dumps({
            "id": "G-EXIST", "cmd": ["true"], "expect": ["any"],
            "ts": "2026-09-27T00:00:01Z",
        }) + "\n")
    with open(os.path.join(root, "findings.jsonl"), "w") as f:
        f.write(json.dumps({
            "id": "FND-CTL", "symptom": "planted defect",
            "root_cause": "planted", "fix": "patched the symptom",
            "guard": "", "guard_status": "none", "learn_ref": "ctl",
        }) + "\n")
    return os.path.join(root, "findings.jsonl")


def positive_case() -> str:
    root = tempfile.mkdtemp(prefix="voslab_f2g_ok_")
    with open(os.path.join(root, "guards.jsonl"), "w") as f:
        f.write(json.dumps({
            "id": "G-EXIST", "cmd": ["true"], "expect": ["any"],
            "ts": "2026-09-27T00:00:01Z",
        }) + "\n")
    with open(os.path.join(root, "findings.jsonl"), "w") as f:
        f.write(json.dumps({
            "id": "FND-OK", "symptom": "real defect",
            "root_cause": "rc", "fix": "fixed with guard",
            "guard": "G-EXIST", "guard_status": "live", "learn_ref": "ctl",
        }) + "\n")
    return os.path.join(root, "findings.jsonl")


register("guard-coverage", check, negative_case)
