"""claim-audit gate — chain integrity of epistemic claims (EPISTEMIC-CERT-001).

A claim asserted past DECLARED (status OBSERVED/CERTIFIED, or carrying any
cert ref) must have a resolvable certificate chain: every cert id exists in
state/epistemic/certs.jsonl, CERTIFIED claims hold a passing cert, and
conformance claims at risk=delivery hold an independent cert (plan F16).
An interpretation can never be CERTIFIED (ceiling: INTERPRETIVE).

Inputs accepted:
  - a prose artifact (.md) with an adjacent or central `<stem>.claims.vsm`
    sidecar: the sidecar's chains are audited against the cert registry
  - a `.claims.vsm` sidecar itself: audited directly
  - a .md with explicit `<!-- claim:` markers but no sidecar: rejected
    (assertion without registry)
  - anything else: out of scope -> accepted

Negative case: a README with a sidecar claiming CERTIFIED status and no
resolvable cert — the gate MUST reject it (exit != 0).

Real-data audit: `python3 -m vos_kernel.epistemic audit-artifact <file> --strict`
"""

from __future__ import annotations

import os
import tempfile

from gate_suite.harness import register
from vos_kernel.epistemic import (
    EpicStore,
    audit_claim,
    find_sidecar,
    load_sidecar,
)


def _sidecar_claims(path: str):
    """Return (claims, error). Handles both artifacts and sidecar files."""
    from pathlib import Path

    p = Path(path)
    sidecar = p if p.name.endswith(".claims.vsm") else find_sidecar(p)
    if sidecar is None:
        if p.suffix == ".md" and "<!-- claim:" in p.read_text(errors="replace"):
            return [], "claim markers present but no sidecar found"
        return None, None  # no claims asserted -> out of scope
    try:
        return load_sidecar(sidecar), None
    except (ValueError, OSError) as e:
        return [], f"sidecar parse: {e}"


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED."""
    if not (path.endswith(".md") or path.endswith(".claims.vsm")):
        return 0  # out of scope
    claims, err = _sidecar_claims(path)
    if claims is None and err is None:
        return 0  # no sidecar, no markers -> nothing asserted
    if err is not None:
        return 1
    certs = {c["id"]: c for c in EpicStore().load("certs") if "id" in c}
    for cl in claims:
        if audit_claim(cl, certs):
            return 1  # broken chain -> reject
    return 0


def negative_case() -> str:
    from vos_kernel.epistemic import new_doc_sidecar

    root = tempfile.mkdtemp(prefix="voslab_claim_")
    art = os.path.join(root, "README.md")
    with open(art, "w") as f:
        f.write("# planted\n\nResult: 42/42.\n")
    claims = [{
        "id": "CL-CTL", "text": "planted certified claim",
        "text_hash": "", "type": "conformance", "subject": "README.md",
        "risk": "delivery", "status": "CERTIFIED",
        "provenance": "ctl", "certs": [],
    }]
    with open(os.path.join(root, "README.claims.vsm"), "w") as f:
        f.write(new_doc_sidecar("readme_ctl_claims", claims))
    return art


def positive_case() -> str:
    from vos_kernel.epistemic import new_doc_sidecar

    root = tempfile.mkdtemp(prefix="voslab_claim_ok_")
    art = os.path.join(root, "README.md")
    with open(art, "w") as f:
        f.write("# ok\n\nDeclared only: 42/42.\n")
    claims = [{
        "id": "CL-CTL-OK", "text": "declared claim, honest unknown",
        "text_hash": "", "type": "conformance", "subject": "README.md",
        "risk": "delivery", "status": "DECLARED",
        "provenance": "ctl", "certs": [],
    }]
    with open(os.path.join(root, "README.claims.vsm"), "w") as f:
        f.write(new_doc_sidecar("readme_ctl_claims_ok", claims))
    return art


register("claim-audit", check, negative_case)
