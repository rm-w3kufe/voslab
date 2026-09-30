"""Ingest pipeline: extract -> validate -> consistency -> route -> ledger.

    ingest_text(text, name=...) -> {
      source_id, fingerprint, claims, routes, coverage, internal, ledger
    }

Deterministic-first (claim_ingest proposal): candidates come from the
pattern net; agent claims ride along labeled method="agent". Every claim
is registry-validated before routing; the block rule runs before any
route (no CERTIFIED under an open intra-source contradiction).
"""
from __future__ import annotations

from pathlib import Path

from vos_kernel.epistemic import EpicStore, validate_claim
from vos_kernel.router import route_claim

from .extract.normalize import register_agent_claims, to_claim
from .extract.patterns import extract_deterministic
from .ids import source_id_for, fingerprint
from .internal.consistency import ensure_certifiable, internal_check
from .ledger.ledger import ledger_name_for, render_ledger, write_ledger
from .ledger.coverage import coverage


def ingest_text(text: str, *, name: str, subject: str | None = None,
                sections: dict[str, str] | None = None,
                agent_claims: list[dict] | None = None,
                risk: str = "exploratory",
                store=None, route: bool = True, logger=None,
                register: bool = False,
                ledger_path: Path | str | None = None) -> dict:
    """One artifact's text -> routed claim set + ledger + denominators.

    `register=True` lands the claims in the EpicStore registry, idempotent
    by claim id (re-ingest of identical content upserts, never duplicates).
    """
    subject = subject or name
    # fingerprint the ACTUAL artifact content: sections when provided,
    # plain text otherwise (never the empty string)
    content = text
    if sections:
        content = "\n".join(f"{k}\n{v}" for k, v in sections.items())
    sid = source_id_for(name, content)

    candidates = extract_deterministic(text, sections)
    claims = [to_claim(c, sid, i + 1, subject, risk)
              for i, c in enumerate(candidates)]
    if agent_claims:
        claims.extend(register_agent_claims(
            agent_claims, sid, len(claims) + 1, subject, risk))

    errs = [e for c in claims for e in validate_claim(c)]
    if errs:
        raise ValueError("invalid extracted claims: " + "; ".join(errs))

    internal = internal_check(claims)
    for c in claims:
        ensure_certifiable(c, internal)  # block rule, before any route

    if register:
        store = store or EpicStore()
        for c in claims:
            if store.get("claims", c["id"]) is None:
                store.append("claims", c)
            else:
                store.upsert("claims", c)

    routes: list[dict] = []
    if route:
        for c in claims:
            routes.append(route_claim(c, store=store, logger=logger))

    cov = coverage(claims, routes)
    ledger_content = render_ledger(ledger_name_for(name), claims, cov,
                                   internal, routes if route else None)

    ledger_written: str | None = None
    if ledger_path is not None:
        ledger_written = str(write_ledger(
            ledger_path, name, claims, cov, internal,
            routes if route else None))

    return {
        "source_id": sid,
        "fingerprint": fingerprint(content),
        "claims": claims,
        "routes": routes,
        "coverage": cov,
        "internal": internal,
        "ledger": ledger_content,
        "ledger_path": ledger_written,
    }
