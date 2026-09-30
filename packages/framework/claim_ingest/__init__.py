"""claim_ingest — domain-agnostic claim ingestion for declarative artifacts.

Read -> extract (deterministic-first) -> validate -> internal consistency
-> route (claim-gate) -> ledger with coverage denominators.

Design: docs/plans/claim_ingest_proposal.vsm (active, approved rmw3
2026-09-30). Domain-agnostic by design: any declarative artifact —
papers, RFCs, runbooks, READMEs, regulations, S5 messages.
"""
from .ids import claim_id_for, fingerprint, source_id_for
from .extract import (
    extract_deterministic,
    register_agent_claims,
    to_claim,
)
from .internal import (
    ContradictionBlocked,
    blocked_ids,
    ensure_certifiable,
    internal_check,
)
from .ledger import coverage, render_ledger, write_ledger
from .pipeline import ingest_text

__all__ = [
    "claim_id_for", "fingerprint", "source_id_for",
    "extract_deterministic", "register_agent_claims", "to_claim",
    "ContradictionBlocked", "blocked_ids", "ensure_certifiable",
    "internal_check",
    "coverage", "render_ledger", "write_ledger",
    "ingest_text",
]
