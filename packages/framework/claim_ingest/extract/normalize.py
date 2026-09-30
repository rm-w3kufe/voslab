"""Normalize extracted candidates into registry-valid epistemic claims.

Deterministic candidates and agent-supplied claims share one shape:
both get ids from the source sequence, both are labeled by `method`
("deterministic" | "agent") — the provenance of every claim is visible
in the ledger (claim_ingest proposal, extract layer).
"""
from __future__ import annotations

from vos_kernel.epistemic import sha256_bytes
from vos_kernel.router import DEFAULT_CHECKABLE, DEFAULT_FALSIFIER

from ..ids import claim_id_for


def to_claim(cand: dict, source_id: str, seq: int, subject: str,
             risk: str = "exploratory") -> dict:
    """Deterministic candidate -> DECLARED registry claim."""
    ctype = cand["type"]
    text = cand["text"]
    claim: dict = {
        "id": claim_id_for(source_id, seq),
        "type": ctype,
        "subject": subject,
        "risk": risk,
        "status": "DECLARED",
        "text": text,
        "text_hash": sha256_bytes(text.encode("utf-8")),
        "provenance": f"claim_ingest deterministic:{cand.get('pattern', '?')}",
        "method": cand.get("method", "deterministic"),
        "section": cand.get("section", "body"),
        "source_id": source_id,
        "checkable": DEFAULT_CHECKABLE.get(ctype, "none"),
        "falsifier": DEFAULT_FALSIFIER.get(ctype, "false") == "true",
        "certs": [],
    }
    for key in ("value", "quantity", "op", "refs", "negated", "scope"):
        if cand.get(key) not in (None, False, []):
            claim[key] = cand[key]
    return claim


def register_agent_claims(raws: list[dict], source_id: str, seq_start: int,
                          subject: str, risk: str = "exploratory"
                          ) -> list[dict]:
    """Agent-supplied claims (method="agent"), same normalization rules.

    Each raw dict needs `text`; may carry type/section/value/quantity/
    op/scope/status. Ids continue the deterministic sequence.
    """
    claims: list[dict] = []
    for i, raw in enumerate(raws):
        if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
            raise ValueError(f"agent claim #{i}: missing text")
        ctype = raw.get("type", "theorem")
        text = str(raw["text"])
        claim: dict = {
            "id": claim_id_for(source_id, seq_start + i),
            "type": ctype,
            "subject": str(raw.get("subject", subject)),
            "risk": str(raw.get("risk", risk)),
            "status": str(raw.get("status", "DECLARED")),
            "text": text,
            "text_hash": sha256_bytes(text.encode("utf-8")),
            "provenance": str(raw.get("provenance", "claim_ingest agent")),
            "method": "agent",
            "section": str(raw.get("section", "agent")),
            "source_id": source_id,
            "checkable": DEFAULT_CHECKABLE.get(ctype, "none"),
            "falsifier": DEFAULT_FALSIFIER.get(ctype, "false") == "true",
            "certs": [],
        }
        for key in ("value", "quantity", "op", "refs", "negated", "scope"):
            if raw.get(key) not in (None, False, []):
                claim[key] = raw[key]
        claims.append(claim)
    return claims
