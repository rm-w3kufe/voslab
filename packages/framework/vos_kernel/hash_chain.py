"""hash_chain.py — chained-hash verdict records (debt D-06 FASE C / C3).

Every ROUND record written by ``round_runner.emit`` is sealed into a
deterministic hash chain:

  record_hash = sha256(canonical_json(payload) + prev_hash)

where ``payload`` is the record minus its chain fields and ``prev_hash``
is the ``record_hash`` of the previous *sealed* record (``GENESIS`` for
the first one).  Re-computing the hash over a tampered payload fails; a
record whose ``prev_hash`` does not match its predecessor breaks the
linkage.  Legacy (pre-C3) records without chain fields are reported as
``unsealed`` and do not fail the chain.

R10: same input → same output.  No time, no randomness, stdlib only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

GENESIS = "genesis"
CHAIN_FIELDS = ("prev_hash", "record_hash")


def canonical_json(payload: dict) -> str:
    """Deterministic serialization: sorted keys, no whitespace, UTF-8."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def payload_hash(payload: dict, prev_hash: str) -> str:
    material = canonical_json(payload) + prev_hash
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def is_sealed(record: dict) -> bool:
    return all(isinstance(record.get(f), str) and record[f]
               for f in CHAIN_FIELDS)


def seal(record: dict, prev_hash: str) -> dict:
    """Return a sealed COPY of ``record`` chained to ``prev_hash``.

    Existing chain fields on the input are dropped first, so re-sealing
    a record is idempotent given the same ``prev_hash`` and the caller's
    dict is never mutated.
    """
    payload = {k: v for k, v in record.items() if k not in CHAIN_FIELDS}
    out = dict(payload)
    out["prev_hash"] = prev_hash
    out["record_hash"] = payload_hash(payload, prev_hash)
    return out


def last_sealed_hash(rounds_dir: Path) -> str:
    """``record_hash`` of the newest sealed ROUND file, else ``GENESIS``.

    Ordering is the file name itself (ROUND-<UTC timestamp>Z), newest
    first.  Unsealed legacy records are skipped.
    """
    for path in sorted(Path(rounds_dir).glob("ROUND-*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if is_sealed(record):
            return record["record_hash"]
    return GENESIS


def verify_rounds(rounds_dir: Path) -> dict[str, Any]:
    """Verify the chain over a rounds directory.

    Returns ``{"status": "ok"|"FAIL", "sealed": int, "unsealed": [names],
    "errors": [messages]}``.  Unsealed legacy records never fail the
    chain; among sealed records both payload integrity and linkage to
    the previous sealed record are checked.
    """
    report: dict[str, Any] = {"status": "ok", "sealed": 0,
                              "unsealed": [], "errors": []}
    expected_prev = GENESIS
    for path in sorted(Path(rounds_dir).glob("ROUND-*.json")):
        name = path.name
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report["errors"].append(f"{name}: unreadable ({exc})")
            continue
        if not is_sealed(record):
            report["unsealed"].append(name)
            continue
        payload = {k: v for k, v in record.items()
                   if k not in CHAIN_FIELDS}
        if payload_hash(payload, record["prev_hash"]) != record["record_hash"]:
            report["errors"].append(
                f"{name}: hash mismatch (payload altered since sealing)")
        elif record["prev_hash"] != expected_prev:
            report["errors"].append(
                f"{name}: broken link (prev_hash {record['prev_hash'][:16]} "
                f"!= expected {expected_prev[:16]})")
        report["sealed"] += 1
        expected_prev = record["record_hash"]
    if report["errors"]:
        report["status"] = "FAIL"
    return report
