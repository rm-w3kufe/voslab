#!/usr/bin/env python3
# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: system/kernel/tree_trace_attest.py)
"""test_tree_trace_attest.py — Tests for Capa 2: Ed25519 Attestation."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tree_trace_attest import (
    AttestationSigner,
    AttestationVerifier,
    KeyManager,
    MerkleTree,
    persist_attestation,
    persist_session_attestation,
    _sha256,
    _canonical,
)


def test_key_generation():
    """Keys are generated and persisted."""
    with tempfile.TemporaryDirectory() as tmp:
        km = KeyManager(Path(tmp) / "keys")
        priv, pub, kid = km.get_or_create()
        assert len(priv) == 32
        assert len(pub) == 32
        assert len(kid) == 16

        # Same keys on re-open
        km2 = KeyManager(Path(tmp) / "keys")
        priv2, pub2, kid2 = km2.get_or_create()
        assert priv == priv2
        assert pub == pub2
        print("PASS: test_key_generation")
    return True


def test_sign_and_verify():
    """Sign a trace and verify it."""
    with tempfile.TemporaryDirectory() as tmp:
        km = KeyManager(Path(tmp) / "keys")
        signer = AttestationSigner(Path(tmp) / "keys")

        trace = {
            "trace_id": "test-001",
            "tree_shape": "AND(a, b)",
            "final_truth": "Truth.TRUE",
            "total_nodes": 3,
            "nodes": [],
        }
        att = signer.sign_trace(trace)
        assert att.trace_hash
        assert att.signature_b64
        assert att.key_id

        verifier = AttestationVerifier(km.info().pubkey_hex)
        r = verifier.verify_trace(att.__dict__ if hasattr(att, '__dict__') else {k: getattr(att, k) for k in att.__dataclass_fields__})
        assert r["ok"], f"Verification failed: {r['reason']}"
        print("PASS: test_sign_and_verify")
    return True


def test_merkle_tree():
    """Merkle tree builds correctly."""
    h1 = _sha256(b"leaf1")
    h2 = _sha256(b"leaf2")
    h3 = _sha256(b"leaf3")

    tree = MerkleTree([h1, h2, h3])
    assert tree.root_hex
    assert len(tree.root_hex) == 64  # SHA-256 hex

    # Single leaf
    tree1 = MerkleTree([h1])
    assert tree1.root == h1

    # Empty
    tree0 = MerkleTree([])
    assert tree0.root == b"\x00" * 32

    # Proof
    proof = tree.proof(0)
    assert len(proof) > 0

    print("PASS: test_merkle_tree")
    return True


def test_session_attestation():
    """Session attestation builds Merkle tree over traces."""
    with tempfile.TemporaryDirectory() as tmp:
        km = KeyManager(Path(tmp) / "keys")
        signer = AttestationSigner(Path(tmp) / "keys")

        for i in range(5):
            trace = {"trace_id": f"trace-{i}", "tree_shape": f"P{i}", "final_truth": "TRUE", "total_nodes": i + 1, "nodes": []}
            signer.sign_trace(trace)

        session = signer.build_session_attestation("test-session")
        assert session.trace_count == 5
        assert session.merkle_root
        assert session.signature_b64
        assert session.key_id

        # Verify
        verifier = AttestationVerifier(km.info().pubkey_hex)
        r = verifier.verify_session({k: getattr(session, k) for k in session.__dataclass_fields__})
        assert r["ok"], f"Session verification failed: {r['errors']}"
        assert r["merkle_ok"]
        assert r["traces_ok"] == 5
        assert r["traces_fail"] == 0
        print("PASS: test_session_attestation")
    return True


def test_tamper_detection():
    """Tampering with a trace hash is detected."""
    with tempfile.TemporaryDirectory() as tmp:
        km = KeyManager(Path(tmp) / "keys")
        signer = AttestationSigner(Path(tmp) / "keys")

        for i in range(3):
            trace = {"trace_id": f"trace-{i}", "tree_shape": "P", "final_truth": "TRUE", "total_nodes": 1, "nodes": []}
            signer.sign_trace(trace)

        session = signer.build_session_attestation("test-session")
        session_dict = {k: getattr(session, k) for k in session.__dataclass_fields__}

        # Tamper with a trace hash
        session_dict["traces"][0]["trace_hash"] = "00" * 32

        verifier = AttestationVerifier(km.info().pubkey_hex)
        r = verifier.verify_session(session_dict)
        assert not r["ok"], "Tampered session should fail"
        assert r["traces_fail"] > 0
        print("PASS: test_tamper_detection")
    return True


def test_wrong_key():
    """Verification with wrong key fails."""
    with tempfile.TemporaryDirectory() as tmp:
        signer = AttestationSigner(Path(tmp) / "keys")
        trace = {"trace_id": "t1", "tree_shape": "P", "final_truth": "TRUE", "total_nodes": 1, "nodes": []}
        att = signer.sign_trace(trace)

        # Wrong key
        other_km = KeyManager(Path(tmp) / "other_keys")
        other_km.get_or_create()
        verifier = AttestationVerifier(other_km.info().pubkey_hex)
        r = verifier.verify_trace(att.__dict__ if hasattr(att, '__dict__') else {k: getattr(att, k) for k in att.__dataclass_fields__})
        assert not r["ok"], "Wrong key should fail"
        print("PASS: test_wrong_key")
    return True


def test_persist_and_load():
    """Attestations persist to disk and are loadable."""
    with tempfile.TemporaryDirectory() as tmp:
        att_dir = Path(tmp) / "attestations"
        signer = AttestationSigner(Path(tmp) / "keys")

        trace = {"trace_id": "persist-001", "tree_shape": "X", "final_truth": "FALSE", "total_nodes": 2, "nodes": []}
        att = signer.sign_trace(trace)
        persist_attestation(att, att_dir)

        # Read back
        loaded = json.load(open(att_dir / "persist-001.attest.json"))
        assert loaded["trace_id"] == "persist-001"
        assert loaded["trace_hash"]
        assert loaded["signature_b64"]

        print("PASS: test_persist_and_load")
    return True


if __name__ == "__main__":
    tests = [
        test_key_generation,
        test_sign_and_verify,
        test_merkle_tree,
        test_session_attestation,
        test_tamper_detection,
        test_wrong_key,
        test_persist_and_load,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            if t():
                passed += 1
            else:
                failed += 1
                print(f"FAIL: {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"ERROR: {t.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
