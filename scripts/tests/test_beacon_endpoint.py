#!/usr/bin/env python3
"""
test_beacon_endpoint.py — HTTP contract test for /api/v1/attested_check.

Verifies the RATIFIED kernel_birth contract (s4-anticipation:1274) against the
FastAPI app in scripts/algedonic/vsf_beacon_main.py:
  1. _canonical_hash armed (LICENSE line or COVENANT_PATH fallback = 13df6604…)
  2. Real nucleus shape (beacon.rs:139-147) → 202 trusted
  3. Tampered sig → 403 rejected
  4. Wrong covenant (validly re-signed) → 403 covenant mismatch
  5. Empty payload → 422 required
  6. Legacy aliases (run_id/covenant_hash) → 202 trusted
  7. registry.jsonl statuses + health counts
  8. health without token → 404

Run standalone (not collected by pytest — testpaths=["tests"]):
  python3 scripts/tests/test_beacon_endpoint.py

Requires: _beacon_ca/ (scripts/s5-governance/gen_test_ca.sh), fastapi, httpx.
"""

import datetime
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CA_DIR = os.path.join(REPO, "_beacon_ca")
NODE_KEY = os.path.join(CA_DIR, "nodes", "vsf_nucleus.key")

COV = "13df660492dcfae8aa264298e7c3a5065fb4f68577f784fd5f7bb443861898d0"

if not os.path.exists(NODE_KEY):
    print(f"SKIP: {NODE_KEY} missing — run scripts/s5-governance/gen_test_ca.sh first")
    sys.exit(0)

TMP = tempfile.mkdtemp(prefix="beacon_ep_")
os.environ["CA_PUBKEY_PATH"] = os.path.join(CA_DIR, "ca.pubkey.hex")
os.environ["COVENANT_PATH"] = os.path.join(REPO, "docs/governance/covenant.vsm")
os.environ["REGISTRY_PATH"] = os.path.join(TMP, "registry.jsonl")
os.environ["DB_PATH"] = os.path.join(TMP, "beacon.db")
os.environ["HONEYPOT_LOG"] = os.path.join(TMP, "honeypot.log")
os.environ["MONITOR_TOKEN"] = "endpoint-test"

sys.path.insert(0, os.path.join(REPO, "scripts", "algedonic"))
import vsf_beacon_main as m  # noqa: E402
from beacon_attestation import build_kernel_payload  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

fail = 0


def check(name, cond, detail=""):
    global fail
    print(("  PASS " if cond else "  FAIL ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fail += 1


def main():
    c = TestClient(m.app)

    # 1. _canonical_hash armed?
    h = m._canonical_hash()
    check("_canonical_hash armed (COVENANT_PATH fallback)", h == COV, f"got {h}")

    # 2. Real nucleus payload (exact shape of beacon.rs:139-147)
    helper = build_kernel_payload("vsf_nucleus", "1.0.0", "E2E-WM", COV, NODE_KEY, "")
    nucleus_payload = {
        "kernel_id": "vsf_nucleus",
        "vsf_version": helper["vsf_version"],
        "watermark": helper["watermark"],
        "covenant_sha": COV,
        "calibration": "",
        "cert": helper["cert"],
        "sig": helper["sig"],
    }
    r = c.post("/api/v1/attested_check", json=nucleus_payload)
    check(
        "VALID (nucleus shape) → trusted",
        r.status_code == 202 and r.json().get("status") == "trusted",
        f"http={r.status_code} body={r.text[:160]}",
    )

    # 3. Tampered sig → 403
    bad = dict(nucleus_payload)
    bad["sig"] = "00" * 64
    r = c.post("/api/v1/attested_check", json=bad)
    check(
        "SIG tampered → 403 rejected",
        r.status_code == 403 and r.json().get("status") == "rejected",
        f"http={r.status_code}",
    )

    # 4. Wrong covenant (validly re-signed so verification reaches covenant check)
    other_cov = __import__("hashlib").sha256(b"other").hexdigest()
    helper2 = build_kernel_payload("vsf_nucleus", "1.0.0", "E2E-WM", other_cov, NODE_KEY, "")
    wrong = dict(nucleus_payload)
    wrong["covenant_sha"] = other_cov
    wrong["sig"] = helper2["sig"]
    wrong["watermark"] = helper2["watermark"]
    r = c.post("/api/v1/attested_check", json=wrong)
    j = r.json() if r.status_code != 422 else {}
    check(
        "COVENANT mismatch → 403 covenant reason",
        r.status_code == 403 and "covenant" in j.get("reason", ""),
        f"http={r.status_code} body={r.text[:160]}",
    )

    # 5. Empty → 422
    r = c.post("/api/v1/attested_check", json={})
    check("EMPTY payload → 422 required", r.status_code == 422, f"http={r.status_code}")

    # 6. Legacy aliases → accepted
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    legacy = {
        "version": "1.0.0",
        "platform": "linux",
        "run_id": "vsf_nucleus",
        "covenant_hash": COV,
        "timestamp": ts,
        "vsf_version": "1.0.0",
        "watermark": helper["watermark"],
        "calibration": "",
        "cert": helper["cert"],
        "sig": helper["sig"],
    }
    r = c.post("/api/v1/attested_check", json=legacy)
    check(
        "LEGACY aliases → trusted",
        r.status_code == 202 and r.json().get("status") == "trusted",
        f"http={r.status_code} body={r.text[:160]}",
    )

    # 7. registry + health
    with open(os.environ["REGISTRY_PATH"]) as f:
        statuses = [json.loads(line)["status"] for line in f.read().strip().splitlines()]
    check(
        "registry: 2 trusted + 2 rejected",
        statuses.count("trusted") == 2 and statuses.count("rejected") == 2,
        f"statuses={statuses}",
    )
    r = c.get("/health", params={"t": "endpoint-test"})
    check(
        "health: attestation_active + counts",
        r.status_code == 200
        and r.json()["attestation_active"] is True
        and r.json()["beacons"] == 4
        and r.json()["nodes"] == 1,
        f"body={r.text[:160]}",
    )

    # 8. health without token → 404
    r = c.get("/health", params={"t": "wrong"})
    check("health wrong token → 404", r.status_code == 404, f"http={r.status_code}")

    print("=" * 60)
    print("ALL TESTS PASSED" if fail == 0 else f"{fail} FAILURES")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
