#!/usr/bin/env python3
"""vsf_algedonic_pub.py — canonical algedonic NATS publisher (G1).
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Single canonical source for safety-channel publishes (G1 closure): token-auth
+ categorized subject + PING round-trip so auth errors surface + loud stderr
on every failure path. Stdlib only, no broker client dependency.

WHY this exists (C1 lesson, populate.sh): three independent breaks each drop
a signal silently — (a) anonymous CONNECT answered `-ERR Authorization
Violation` after token auth went live, (b) `2>/dev/null || true` swallowed it
(47,858 inbox lines, ZERO ledger rows), (c) bare subject `vsf.<id>.algedonic`
matches NOTHING (ledger subscribes `vsf.<id>.algedonic.>` which needs ≥1
further token). This helper refuses all three by construction:
anonymous is never attempted (no token → loud False), the subject always
carries the category suffix, and every failure prints to stderr.

Severity discipline (s5_algedonic map): self-pathology (this publisher's own
failures, refresh/probe misses) stays ≤5 — never near the 8.0 caution veto.
Real findings keep their existing severities (7.0/8.0). A monitoring hiccup
must never suspend S3 decisions.

Deterministic (R10): no random, no sampling here. Sporadic target selection
lives in the CALLER (e.g. spotcheck random.choice), which is sampling, not
a decision predicate — unpredictability there is the Beer requirement.
"""
import json
import os
import socket
import sys
from datetime import datetime, timezone

DEFAULT_HOST = os.environ.get("NATS_HOST", "10.10.20.20")
DEFAULT_PORT = int(os.environ.get("NATS_PORT", "4222"))
DEFAULT_VSF_ID = os.environ.get("VSF_ID", "alpha")
CREDS_PATH = "/etc/vsf/nats-creds.env"


def _load_token(explicit=None):
    """Token from explicit arg, else $NATS_TOKEN, else creds file. None if absent."""
    if explicit:
        return explicit
    tok = os.environ.get("NATS_TOKEN", "")
    if tok:
        return tok
    try:
        with open(CREDS_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("NATS_TOKEN="):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val:
                        return val
    except OSError:
        pass
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish(category, severity, source_id, detail, lxc=None, component=None,
            ts=None, token=None, host=None, port=None, vsf_id=None,
            timeout=5) -> bool:
    """Publish one algedonic event. Returns True only on a clean round-trip.

    Loud on every failure path (stderr) and returns False — never silent.
    Raises ValueError on programmer errors (empty category/source, bad
    severity range) so misuse fails in tests, not in production silence.
    """
    if not category or not str(category).strip() or any(
            ch.isspace() for ch in str(category)):
        raise ValueError("algedonic category must be a single non-empty token")
    if not source_id or not str(source_id).strip():
        raise ValueError("algedonic source_id must be non-empty")
    try:
        sev = float(severity)
    except (TypeError, ValueError):
        raise ValueError(f"algedonic severity must be numeric, got {severity!r}")
    if not 0 <= sev <= 10:
        raise ValueError(f"algedonic severity out of range [0,10]: {sev}")

    tok = _load_token(token)
    if not tok:
        print("vsf_algedonic_pub: NO TOKEN (set NATS_TOKEN or %s) — "
              "refusing anonymous publish (anonymous delivers nowhere); "
              "signal DROPPED LOUDLY" % CREDS_PATH, file=sys.stderr)
        return False

    host = host or DEFAULT_HOST
    port = port or DEFAULT_PORT
    vid = vsf_id or DEFAULT_VSF_ID
    subject = f"vsf.{vid}.algedonic.{category}"
    payload = {
        "ts":        ts or _now_iso(),
        "source_id": source_id,
        "category":  str(category),
        "severity":  sev,
        "detail":    str(detail),
    }
    if lxc is not None:
        payload["lxc"] = lxc
    if component is not None:
        payload["component"] = component
    body = json.dumps(payload).encode()
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.recv(4096)  # INFO
            s.sendall(b'CONNECT {"verbose":false,"auth_token":"'
                      + tok.encode() + b'"}\r\n')
            s.sendall(b"PUB " + subject.encode() + b" "
                      + str(len(body)).encode() + b"\r\n" + body + b"\r\n")
            s.sendall(b"PING\r\n")  # round-trip so auth errors surface
            reply = s.recv(4096)
        if b"-ERR" in reply:
            print("vsf_algedonic_pub: NATS refused: %s"
                  % reply[:120].decode(errors="replace"), file=sys.stderr)
            return False
        return True
    except Exception as exc:
        print(f"vsf_algedonic_pub: publish FAILED ({category}): {exc}",
              file=sys.stderr)
        return False
