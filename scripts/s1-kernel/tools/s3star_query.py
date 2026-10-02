#!/usr/bin/env python3
"""s3star_query — audited direct-descendant state query (Beer's S3*).

Phase 1 reference PoC for docs/spec/vsm_recursion/s3star_direct_query.spec.vsm.

A parent may read a NON-ADJACENT descendant's state directly (R13-legal: reads flow
DOWN; only upward reads are forbidden). That direct, level-skipping read is Beer's
S3* — the sporadic direct audit channel that verifies the routine reporting chain.
It stays sound under TWO conditions, and this module ENFORCES the second and RECORDS
evidence for the first:

  (1) ATTENUATION — the read is a typed query returning a SLICE, never a raw firehose.
      That is the provider's job (state-canon's query surface). This wrapper does not
      fetch raw state itself; it calls an injected `provider` and records the result
      size as evidence the read was attenuated (a huge result is a red flag).

  (2) SPORADIC + AUDITED — every direct descendant read EMITS AN AUDIT EVENT (who read
      whom, when, why, skipping which intermediaries). This makes 'sporadic vs routine'
      OBSERVABLE: a spike in these events is a spike a monitor can see. Routine
      aggregation must stay on the intermediary path; S3* is the logged exception.

Directional by construction (R13): a reader queries a DESCENDANT. This module refuses a
read whose target is not below the reader — it will not become an upward-read channel.

Stdlib only. `s3star_query.py selftest`.
"""
from __future__ import annotations
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_AUDIT_LOG = Path("/var/lib/vsf/recursion/s3star_audit.jsonl")

# Result larger than this many bytes (serialized) is flagged: a direct read should be a
# SLICE, not a dump. Not a hard limit (the provider owns attenuation) — an audit signal.
ATTENUATION_WARN_BYTES = 8192


class S3StarError(ValueError):
    pass


@dataclass
class Descent:
    """The recursion position of reader and target, so we can verify direction and
    record which intermediaries the direct read skipped."""
    reader: str            # e.g. "vsf"
    reader_level: int      # deeper-is-smaller convention; parent has the LARGER level
    target: str            # e.g. "bbh-lab"
    target_level: int
    intermediaries: list[str] = field(default_factory=list)  # skipped by the direct read

    def validate(self) -> "Descent":
        if self.target_level >= self.reader_level:
            raise S3StarError(
                f"S3* is DOWNWARD only (R13): reader '{self.reader}' (L{self.reader_level}) "
                f"cannot direct-read '{self.target}' (L{self.target_level}) — that is not a "
                f"descendant. Upward reads are forbidden."
            )
        if self.reader == self.target:
            raise S3StarError("reader and target are the same node")
        return self


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def s3star_query(
    descent: Descent,
    query: dict,
    reason: str,
    provider: Callable[[dict], Any],
    audit_log: Path = DEFAULT_AUDIT_LOG,
    _clock: Callable[[], str] = _now,
) -> Any:
    """Perform an audited direct read of a descendant.

    descent  — who is reading whom (validated as downward).
    query    — the TYPED, attenuated query (a slice request, not 'give me everything').
    reason   — why this direct read is warranted (S3* is intentional, never idle).
    provider — callable(query) -> attenuated state. THIS is the attenuator; inject the
               descendant's typed state surface (e.g. a BbhStateProvider query).
    Returns the provider's result, AFTER the audit event is durably appended.
    """
    descent.validate()
    if not reason or not reason.strip():
        raise S3StarError("an S3* direct read must carry a reason — it is audit, not idle browsing")
    if not isinstance(query, dict) or not query:
        raise S3StarError("query must be a non-empty typed slice request, not a raw dump")

    result = provider(query)
    size = len(json.dumps(result, default=str))

    event = {
        "ts": _clock(),
        "kind": "s3star_direct_read",
        "reader": descent.reader,
        "reader_level": descent.reader_level,
        "target": descent.target,
        "target_level": descent.target_level,
        "skipped": descent.intermediaries,
        "query": query,
        "reason": reason.strip(),
        "result_bytes": size,
        "attenuation_ok": size <= ATTENUATION_WARN_BYTES,
    }
    # Emit the audit event FIRST-durable: the read is not "done" until it is on record.
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")

    if not event["attenuation_ok"]:
        # Condition 1 signal: this read looks like a firehose, not a slice. Not fatal
        # (the provider owns attenuation) but loud — a direct read this large is a
        # design smell, exactly the variety-overload the recursion exists to prevent.
        sys.stderr.write(
            f"[s3star] WARNING: direct read of {descent.target} returned {size}B "
            f"(> {ATTENUATION_WARN_BYTES}B) — attenuate the query; S3* reads a slice, not a dump\n"
        )
    return result


def audit_tail(audit_log: Path = DEFAULT_AUDIT_LOG, n: int = 20) -> list[dict]:
    """Read the last n audit events — the visibility that makes 'sporadic' measurable."""
    if not audit_log.exists():
        return []
    lines = [l for l in audit_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines[-n:]]


# ── selftest ──────────────────────────────────────────────────────────────────
def selftest() -> int:
    import tempfile
    fail = 0

    def check(name, cond):
        nonlocal fail
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")
        if not cond:
            fail = 1

    tmp = Path(tempfile.mkdtemp()) / "audit.jsonl"

    # a mock descendant provider that returns an attenuated slice
    def mock_provider(q):
        return {"finding_id": q.get("id"), "status": "confirmed", "cwe": "CWE-362"}

    d = Descent("vsf", 2, "bbh-lab", -1, intermediaries=["bbh-wsl"])

    # happy path: downward read, attenuated, audited
    r = s3star_query(d, {"domain": "findings", "id": "F-1"}, "verify finding against scope",
                     mock_provider, audit_log=tmp, _clock=lambda: "T0")
    check("returns the provider result", r["status"] == "confirmed")
    ev = audit_tail(tmp)
    check("one audit event emitted", len(ev) == 1)
    check("audit records reader→target", ev[0]["reader"] == "vsf" and ev[0]["target"] == "bbh-lab")
    check("audit records skipped intermediary", ev[0]["skipped"] == ["bbh-wsl"])
    check("audit records the reason", ev[0]["reason"].startswith("verify finding"))
    check("attenuation_ok for a small slice", ev[0]["attenuation_ok"] is True)

    # a second read appends (append-only → 'sporadic' is countable)
    s3star_query(d, {"domain": "findings", "id": "F-2"}, "spot-check second finding",
                 mock_provider, audit_log=tmp, _clock=lambda: "T1")
    check("append-only: two events now", len(audit_tail(tmp)) == 2)

    # R13 direction: an UPWARD read is refused
    up = Descent("bbh-lab", -1, "vsf", 2)
    try:
        s3star_query(up, {"x": 1}, "should never work", mock_provider, audit_log=tmp)
        check("refuses upward read (R13)", False)
    except S3StarError:
        check("refuses upward read (R13)", True)

    # a read with no reason is refused (S3* is intentional)
    try:
        s3star_query(d, {"x": 1}, "  ", mock_provider, audit_log=tmp)
        check("refuses a reasonless read", False)
    except S3StarError:
        check("refuses a reasonless read", True)

    # a firehose result is flagged (attenuation signal), but still recorded
    big = {"blob": "x" * 20000}
    s3star_query(d, {"domain": "dump"}, "intentional big read", lambda q: big,
                 audit_log=tmp, _clock=lambda: "T2")
    last = audit_tail(tmp)[-1]
    check("firehose read flagged attenuation_ok=False", last["attenuation_ok"] is False)

    print("  == PASS ==" if not fail else "  == FAIL ==")
    return fail


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "tail":
        for e in audit_tail():
            print(json.dumps(e))
        sys.exit(0)
    print(__doc__)
