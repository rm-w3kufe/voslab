#!/usr/bin/env python3
"""verify_chain_diverse — second-opinion Merkle chain verifier (DIVERSE-VERIFIER).

INDEPENDENCE RULE (load-bearing, do not "fix"):
  This file must NEVER share code with the vsf-agent Rust crate, be generated
  from it, or be refactored to mirror its structure. It is the MONITOR LANE
  (Airbus command/monitor pattern): a deliberately independent implementation
  of the chain-format v2 encoding contract, written in a different language by
  a different process. A logic bug in the crate's canonical_hash is invisible
  to every crate-linked verifier (common-mode failure) — THIS tool is the one
  that can see it. Divergence between implementations is the feature.
  Reference: docs/spec/self_audit/ + the crate's encoding contract in
  projects/vsf-agent/src/canonical_hash.rs module docs (contract, not code).

Checks per event (chain_format_version=2 only; v1 is serde_json-byte-dependent
and NOT reproducible outside the crate — v1 events are reported as 'v1_skipped'):
  1. content:  stored hash == recomputed byte-stable hash
  2. linkage:  prev_hash == prior event's hash
  3. foreign:  chain fields present + system_id in --writers
  4. seam:     prev_hash=null mid-file classified separately (restart segment start)

Output: one JSON report on stdout. Exit codes: 0 clean, 1 findings, 2 error.
Usage:
  verify_chain_diverse.py --file tail.jsonl [--writers vsf_nucleus] [--max-findings 10]
  ... | verify_chain_diverse.py --stdin
Provenance: session 2026-07-02 (caught the A0 foreign-writer live); packaged per
docs/spec/self_audit/diverse_verifier.spec.vsm.
"""
import argparse
import hashlib
import json
import struct
import sys


# ── encoding (from the v2 contract: length-prefixed LE, tagged Values) ─────────

def _w_len_str(buf, s):
    b = s.encode("utf-8")
    buf += struct.pack("<Q", len(b))
    buf += b


def _w_opt_str(buf, s):
    if s is None:
        buf.append(0)
    else:
        buf.append(1)
        _w_len_str(buf, s)


def _w_opt_f64(buf, v):
    if v is None:
        buf.append(0)
    else:
        buf.append(1)
        buf += struct.pack("<d", v)


def _w_value(buf, v):
    if v is None:
        buf.append(0)
    elif v is False:
        buf.append(1)
    elif v is True:
        buf.append(2)
    elif isinstance(v, int):
        if v >= 0:
            buf.append(3)
            buf += struct.pack("<Q", v)
        else:
            buf.append(4)
            buf += struct.pack("<q", v)
    elif isinstance(v, float):
        buf.append(5)
        buf += struct.pack("<d", v)
    elif isinstance(v, str):
        buf.append(6)
        _w_len_str(buf, v)
    elif isinstance(v, list):
        buf.append(7)
        buf += struct.pack("<Q", len(v))
        for it in v:
            _w_value(buf, it)
    elif isinstance(v, dict):
        buf.append(8)
        keys = sorted(v.keys())
        buf += struct.pack("<Q", len(keys))
        for k in keys:
            _w_len_str(buf, k)
            _w_value(buf, v[k])
    else:
        raise TypeError(f"unhandled JSON type: {type(v)}")


def canonical_hash_v2(ev: dict) -> str:
    buf = bytearray()
    _w_len_str(buf, ev["ts"])
    _w_len_str(buf, ev["system_id"])
    _w_len_str(buf, ev["event_type"])
    _w_len_str(buf, ev["status"])
    _w_len_str(buf, ev["signal_status"])
    buf += struct.pack("<d", float(ev["duration_s"]))
    _w_value(buf, ev["metrics"])
    _w_opt_f64(buf, ev.get("variety_delta"))
    _w_opt_f64(buf, ev.get("trust_score"))
    buf += struct.pack("<Q", ev.get("algedonic_seq", 0))
    _w_opt_str(buf, ev.get("origin"))
    cfv = ev.get("chain_format_version")
    _w_opt_str(buf, str(cfv) if cfv is not None else None)
    _w_opt_str(buf, ev.get("prev_hash"))
    return hashlib.sha256(bytes(buf)).hexdigest()


# ── verification ────────────────────────────────────────────────────────────────

CHAIN_FIELDS = ("hash", "prev_hash")


def verify(lines, writers, max_findings):
    findings = []
    counts = {"total": 0, "v2_ok": 0, "v1_skipped": 0, "foreign": 0,
              "seams": 0, "content_bad": 0, "link_bad": 0, "malformed": 0}
    prior_hash = None
    prior_present = False

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        counts["total"] += 1
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            counts["malformed"] += 1
            findings.append({"idx": i, "kind": "malformed_line",
                             "detail": line[:120]})
            prior_hash, prior_present = None, False
            continue

        # 3. foreign-writer: missing chain fields OR undeclared system_id
        sysid = ev.get("system_id", "")
        if any(f not in ev for f in CHAIN_FIELDS) or sysid not in writers:
            counts["foreign"] += 1
            findings.append({"idx": i, "kind": "foreign_writer",
                             "system_id": sysid, "ts": ev.get("ts", "?"),
                             "detail": "missing chain fields or undeclared writer"})
            # foreign lines are not part of the chain: do not update prior
            continue

        cfv = ev.get("chain_format_version")
        stored = ev.get("hash")

        # 4. seam: null prev_hash after we already had chain context
        if ev.get("prev_hash") is None and prior_present:
            counts["seams"] += 1
            findings.append({"idx": i, "kind": "restart_seam",
                             "ts": ev.get("ts", "?"),
                             "detail": "prev_hash=null mid-stream (new segment; "
                                       "cross-check a real restart before dismissing)"})
        # 2. linkage
        elif prior_hash is not None and ev.get("prev_hash") != prior_hash:
            counts["link_bad"] += 1
            findings.append({"idx": i, "kind": "link_break",
                             "ts": ev.get("ts", "?"),
                             "detail": f"prev_hash {str(ev.get('prev_hash'))[:16]}.. != "
                                       f"prior {prior_hash[:16]}.."})

        # 1. content
        if cfv == 2 and stored:
            recomputed = canonical_hash_v2(ev)
            if recomputed != stored:
                counts["content_bad"] += 1
                findings.append({"idx": i, "kind": "content_tamper",
                                 "ts": ev.get("ts", "?"),
                                 "detail": f"stored {stored[:16]}.. != "
                                           f"recomputed {recomputed[:16]}.."})
            else:
                counts["v2_ok"] += 1
        elif cfv in (None, 1):
            counts["v1_skipped"] += 1

        prior_hash = stored
        prior_present = True

    return {"counts": counts, "findings": findings[:max_findings],
            "clean": not findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--writers", default="vsf_nucleus",
                    help="comma-separated declared chain writers")
    ap.add_argument("--max-findings", type=int, default=10)
    a = ap.parse_args()

    if a.stdin:
        lines = sys.stdin.readlines()
    elif a.file:
        with open(a.file, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    else:
        ap.error("need --file or --stdin")

    try:
        report = verify(lines, set(a.writers.split(",")), a.max_findings)
    except Exception as e:  # report, never crash silently
        print(json.dumps({"error": str(e)}))
        sys.exit(2)

    print(json.dumps(report, indent=2))
    sys.exit(0 if report["clean"] else 1)


if __name__ == "__main__":
    main()
