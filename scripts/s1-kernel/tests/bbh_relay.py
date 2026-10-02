#!/usr/bin/env python3
"""bbh_relay — audited S3* read of bbh-lab's RELAYED findings, for the validation gate.

The problem this closes: bbh-lab is agent-only (no telemetry) and vsf cannot reach it
directly (ssh times out). So [O] validating a finding has been SECOND-DEGREE — trusting
C2's summary. This is the S3* relay that makes it first-degree on the CONTENT:

  bbh-lab (writes its raw finding dossiers)  →  C2/bbh-wsl publishes them VERBATIM to a
  relay file (transport only, no editorializing)  →  vsf reads bbh-lab's OWN evidence
  through an AUDITED, ATTENUATED query.

C2 carries the bytes; it does not interpret them. The validator sees bbh-lab's own PoC,
not C2's paraphrase — which is the whole point of an audit channel (s3star_direct_query.spec
+ finding_validation_gate.spec §transport). Every read is logged (the sporadic/routine
tripwire), and the query is by-finding (a slice, never the raw dump).

Relay file convention:
  ~/bbh-wsl/relay/bbh-lab-findings.jsonl  — one JSON object per line, one per finding,
  written by C2 VERBATIM from bbh-lab. Fields expected per finding:
    { "id", "program", "asset", "vuln_class", "severity", "poc", "source":"bbh-lab" }
  (.vsm is also accepted for the compressed VSL form; see _load.)

Stdlib only. `bbh_relay.py selftest`.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from s3star_query import s3star_query, Descent, audit_tail  # noqa: E402

RELAY_DIR = Path.home() / "bbh-wsl" / "relay"
RELAY_FILE = RELAY_DIR / "bbh-lab-findings.jsonl"

# vsf reads bbh-lab (the grandchild) with bbh-wsl as the transport intermediary.
# Levels: deeper-is-smaller; vsf is L2, bbh-wsl L1, bbh-lab L0 here (relative).
_DESCENT = lambda: Descent("vsf", 2, "bbh-lab", 0, intermediaries=["bbh-wsl"])


def _load(relay_file: Path) -> list[dict]:
    """Read the relay file (JSONL) into finding records. Raw — no interpretation."""
    if not relay_file.exists():
        raise FileNotFoundError(
            f"no relay at {relay_file} — C2 (bbh-wsl) has not published bbh-lab's findings yet"
        )
    out = []
    for ln in relay_file.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def read_finding(finding_id: str, reason: str,
                 relay_file: Path = RELAY_FILE, audit_log=None) -> dict | None:
    """Audited S3* read of ONE finding's raw dossier from bbh-lab (via C2 relay).

    Attenuated: returns a single finding, never the whole relay. Audited: the read is
    logged as an S3* event through s3star_query, so validation reads are accountable.
    """
    records = _load(relay_file)  # C2 transports; we read bbh-lab's own bytes

    def provider(q):
        fid = q.get("id")
        for r in records:
            if r.get("id") == fid:
                return r
        return None

    kw = {} if audit_log is None else {"audit_log": audit_log}
    return s3star_query(_DESCENT(), {"domain": "finding", "id": finding_id},
                        reason, provider, **kw)


def list_finding_ids(relay_file: Path = RELAY_FILE) -> list[str]:
    """The finding ids present in the relay (cheap index; not an audited content read)."""
    return [r.get("id") for r in _load(relay_file)]


def provenance(finding: dict) -> str:
    """What can be validated FIRST-DEGREE vs from the relay, per finding — the honest label
    [O] attaches so scope-vs-PoC verification degree is never hidden."""
    has_poc = bool(finding.get("poc"))
    src = finding.get("source", "?")
    return (f"scope: first-degree (checkable vs the program's public scope) | "
            f"poc: relay from {src} ({'present' if has_poc else 'MISSING — cannot validate'})")


def selftest() -> int:
    import tempfile
    fail = 0

    def check(name, cond):
        nonlocal fail
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")
        if not cond:
            fail = 1

    d = Path(tempfile.mkdtemp())
    relay = d / "bbh-lab-findings.jsonl"
    audit = d / "audit.jsonl"
    # a sample relay written "by C2 verbatim from bbh-lab"
    findings = [
        {"id": "AFF-001", "program": "affirm", "asset": "api.affirm.com",
         "vuln_class": "auth_bypass", "severity": "Critical",
         "poc": "1. GET /v2/... 2. tamper JWT alg=none 3. 200 w/ other user's data",
         "source": "bbh-lab"},
        {"id": "AIR-002", "program": "airtable", "asset": "airtable.com/api",
         "vuln_class": "idor", "severity": "High", "poc": "steps...", "source": "bbh-lab"},
    ]
    relay.write_text("\n".join(json.dumps(f) for f in findings) + "\n")

    ids = list_finding_ids(relay)
    check("index lists finding ids", ids == ["AFF-001", "AIR-002"])

    r = read_finding("AFF-001", "validate affirm Critical auth_bypass before submission",
                     relay_file=relay, audit_log=audit)
    check("returns the raw finding", r["vuln_class"] == "auth_bypass")
    check("carries bbh-lab's own PoC", "alg=none" in r["poc"])

    ev = audit_tail(audit, 1)[0]
    check("read is audited (S3*)", ev["kind"] == "s3star_direct_read")
    check("audit records vsf->bbh-lab", ev["reader"] == "vsf" and ev["target"] == "bbh-lab")
    check("audit records C2 as transport", ev["skipped"] == ["bbh-wsl"])
    check("audit records the validation reason", "affirm" in ev["reason"])

    prov = provenance(r)
    check("provenance labels scope first-degree", "scope: first-degree" in prov)
    check("provenance labels poc as relay", "poc: relay from bbh-lab" in prov)

    # a finding with no PoC is honestly flagged un-validatable
    check("missing-PoC flagged", "MISSING" in provenance({"source": "bbh-lab"}))

    # a missing relay raises (does not silently pass)
    try:
        read_finding("X", "r", relay_file=d / "nope.jsonl")
        check("missing relay raises", False)
    except FileNotFoundError:
        check("missing relay raises", True)

    print("  == PASS ==" if not fail else "  == FAIL ==")
    return fail


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "ids":
        for i in list_finding_ids():
            print(i)
        sys.exit(0)
    print(__doc__)
