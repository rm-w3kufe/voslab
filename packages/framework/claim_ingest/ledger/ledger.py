"""Ledger: per-source sidecar with coverage denominators (proposal rule).

`coverage()` is a deterministic predicate (R10): buckets every claim by
registry status; `render_ledger()` emits a valid CLAIMS-v1 .vsm that the
existing sidecar loader (`load_sidecar`) can still parse — the ledger adds
`coverage`, `internal_check` and `routes` blocks after `claims`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from vos_kernel.epistemic import repo_root
from vos_kernel.utils.vsm_kernel import new_doc, validate_vsm_content

from .coverage import coverage  # re-export


def compact_routes(routes: list[dict]) -> dict:
    """claim_id -> {route, status, verdict} (trace ids stay in the store)."""
    out: dict = {}
    for r in routes:
        cid = r.get("claim_id", "?")
        out[cid] = {
            "route": r.get("route"),
            "status": r.get("status"),
            "verdict": r.get("verdict"),
        }
    return dict(sorted(out.items()))


def render_ledger(name: str, claims: list[dict], cov: dict,
                  internal: dict, routes: list[dict] | None = None) -> str:
    """CLAIMS-v1 document: claims + coverage + internal_check (+ routes)."""
    parts = [
        "// claim_ingest ledger — deterministic-first extraction "
        "(docs/plans/claim_ingest_proposal.vsm, active)",
        "claims = " + json.dumps(claims, indent=2, ensure_ascii=False),
        "coverage = " + json.dumps(cov, indent=2, ensure_ascii=False),
        "internal_check = "
        + json.dumps(internal, indent=2, ensure_ascii=False),
    ]
    if routes is not None:
        parts.append("routes = "
                     + json.dumps(compact_routes(routes), indent=2,
                                  ensure_ascii=False))
    body = "\n".join(parts) + "\n"
    return new_doc(name, "CLAIMS-v1", body, status="active")


def ledger_name_for(source_name: str) -> str:
    """Header/footer name must be a clean identifier."""
    stem = Path(source_name).stem
    name = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_").lower()
    return name or "ledger"


def write_ledger(path: Path | str, name: str, claims: list[dict],
                 cov: dict, internal: dict,
                 routes: list[dict] | None = None) -> Path:
    """Write the ledger; refuses paths outside the vOSlab workspace (R: no
    writing outside ~/vOSlab) and pre-validates VSM content before disk."""
    path = Path(path).resolve()
    root = repo_root().resolve()
    if path != root and root not in path.parents:
        raise PermissionError(
            f"ledger path outside workspace: {path} (root {root})")
    content = render_ledger(ledger_name_for(name), claims, cov, internal,
                            routes)
    v = validate_vsm_content(content)
    if not v["valid"]:
        raise ValueError(f"ledger VSM invalid: {v['errors']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
