#!/usr/bin/env python3
"""
test_decision_auth_fix.py — 7-test battery for DECISION-AUTH-FIX.

Tests verify_decision() using the FIXED DecisionVerifier:

  (a) Valid signed-by-operational-key-chained-to-root → PASS
  (b) Forged key embedded in record (old signer_pubkey) → REJECT
  (c) Cert claims a different CA → REJECT
  (d) Tampered payload → REJECT
  (e) Missing cert → REJECT
  (f) Valid cert but wrong decision signature → REJECT
  (g) Rotated/expired operational key → REJECT

Run from the repo root:
  export PYTHONPATH=scripts
  python3 scripts/tests/test_decision_auth_fix.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# Ensure scripts/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vsf_decision_auth import DecisionVerifier, verify_decision, sign_decision
from beacon_attestation import verify_node_cert, build_kernel_payload

CA_DIR = os.environ.get("VSF_CA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_beacon_ca"))
NODES_DIR = os.path.join(CA_DIR, "nodes")


def get_ca_pubkey_hex() -> str:
    with open(os.path.join(CA_DIR, "ca.pubkey.hex")) as f:
        return f.read().strip()


def get_node_key_path(node_id: str) -> str:
    return os.path.join(NODES_DIR, f"{node_id}.key")


def get_node_cert_path(node_id: str) -> str:
    return os.path.join(NODES_DIR, f"{node_id}.cert.json")


def load_cert(node_id: str) -> dict:
    with open(get_node_cert_path(node_id)) as f:
        return json.load(f)


def load_private_key_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def canonical_json(obj: dict) -> bytes:
    import json as _json
    return _json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


# ── Test helpers ─────────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"


def test(label: str, condition: bool) -> str:
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}")
    return status


def run_test_a(verifier: DecisionVerifier) -> tuple[str, str]:
    """(a) Valid signed decision (operational key chained to root) → PASS."""
    label = "a: valid decision signed by operational key chained to root"
    try:
        signed = sign_decision(
            escalation_id="test-esc-a",
            verdict="APPROVE",
            by="rmw3",
            note="test valid",
            key_id="s5-operational",
            private_key_path=get_node_key_path("s5-operational"),
            cert_path=get_node_cert_path("s5-operational"),
        )
        result = verifier.verify(signed)
        ok = result.get("valid") is True
        return label, test(label, ok)
    except Exception as e:
        return label, test(label, False) + f" (EXCEPTION: {e})"


def run_test_b(verifier: DecisionVerifier) -> tuple[str, str]:
    """(b) Forged key: attacker provides a SELF-SIGNED cert (not chaining to pinned CA) → REJECT.

    The old vulnerability was: signer_pubkey from the record would be trusted.
    Fixed: cert must chain to pinned root. A self-signed cert fails chain verification.
    """
    label = "b: forged cert (self-signed, not chaining to pinned CA) → REJECT"
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

        # Attacker generates THEIR OWN keypair + self-signed cert
        attacker_priv = ed25519.Ed25519PrivateKey.generate()
        attacker_pub = attacker_priv.public_key()
        attacker_pub_hex = attacker_pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

        # Self-sign a forged cert
        forged_cert_payload = {
            "node_id": "attacker-node",
            "pubkey_hex": attacker_pub_hex,
            "ca_pubkey_hex": get_ca_pubkey_hex(),  # claims OUR CA, but CA didn't sign it
            "issued": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        forged_cert_sig = attacker_priv.sign(canonical_json(forged_cert_payload))  # self-signed!
        forged_cert = dict(forged_cert_payload)
        forged_cert["sig_hex"] = forged_cert_sig.hex()

        # Sign a decision with the forged key
        body = {
            "escalation_id": "test-esc-b",
            "verdict": "APPROVE",
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "by": "attacker",
            "note": "forged decision",
        }
        forged_sig = attacker_priv.sign(canonical_json(body)).hex()

        signed = dict(body)
        signed["sig"] = forged_sig
        signed["sig_algorithm"] = "ed25519"
        signed["cert"] = forged_cert
        signed["signer_pubkey"] = attacker_pub_hex  # old field, now IGNORED

        result = verifier.verify(signed)
        return label, test(label, result.get("valid") is False)
    except Exception as e:
        return label, test(label, False) + f" (EXCEPTION: {e})"


def run_test_c(verifier: DecisionVerifier) -> tuple[str, str]:
    """(c) Cert claims a different CA → REJECT.

    Create a SECOND test CA, issue a cert there, use it in the decision.
    verifier has the FIRST CA's root pinned → should reject.
    """
    label = "c: cert from different CA (must REJECT)"
    try:
        # Use a second CA identity: re-gen CA, issue a different-operational cert
        # But we can't regen CA in place. Instead: manually construct a cert
        # that claims a DIFFERENT ca_pubkey_hex.
        # Easiest: take the real cert, change ca_pubkey_hex to garbage.
        original_cert = load_cert("s5-operational")
        tampered_cert = dict(original_cert)
        tampered_cert["ca_pubkey_hex"] = "b" * 64  # different CA claim
        # The sig is still signed by the ORIGINAL CA, so CA verification will
        # fail because the pinned root doesn't match ca_pubkey_hex in the cert.
        signed = sign_decision(
            escalation_id="test-esc-c",
            verdict="APPROVE",
            by="rmw3",
            note="different CA",
            key_id="s5-operational",
            private_key_path=get_node_key_path("s5-operational"),
            cert_path=get_node_cert_path("s5-operational"),
        )
        signed["cert"] = tampered_cert  # override with different-CA claim
        # Re-sign with the real key (so decision sig is valid)
        from cryptography.hazmat.primitives.asymmetric import ed25519
        with open(get_node_key_path("s5-operational"), "rb") as f:
            priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(f.read())
        body = {k: signed[k] for k in ("escalation_id", "verdict", "ts", "by", "note") if k in signed}
        signed["sig"] = priv_key.sign(canonical_json(body)).hex()

        result = verifier.verify(signed)
        return label, test(label, result.get("valid") is False)
    except Exception as e:
        return label, test(label, False) + f" (EXCEPTION: {e})"


def run_test_d(verifier: DecisionVerifier) -> tuple[str, str]:
    """(d) Tampered payload → REJECT."""
    label = "d: tampered payload (escalation_id changed after signing)"
    try:
        signed = sign_decision(
            escalation_id="test-esc-d-original",
            verdict="APPROVE",
            by="rmw3",
            note="tamper test",
            key_id="s5-operational",
            private_key_path=get_node_key_path("s5-operational"),
            cert_path=get_node_cert_path("s5-operational"),
        )
        # Tamper with the escalation_id (but keep sig unchanged)
        signed["escalation_id"] = "test-esc-d-TAMPERED"
        # The sig no longer matches
        result = verifier.verify(signed)
        return label, test(label, result.get("valid") is False)
    except Exception as e:
        return label, test(label, False) + f" (EXCEPTION: {e})"


def run_test_e(verifier: DecisionVerifier) -> tuple[str, str]:
    """(e) Missing cert → REJECT."""
    label = "e: missing cert field (must REJECT)"
    try:
        signed = sign_decision(
            escalation_id="test-esc-e",
            verdict="DENY",
            by="rmw3",
            note="no cert",
            key_id="s5-operational",
            private_key_path=get_node_key_path("s5-operational"),
            cert_path=get_node_cert_path("s5-operational"),
        )
        del signed["cert"]  # remove the cert
        result = verifier.verify(signed)
        return label, test(label, result.get("valid") is False)
    except Exception as e:
        return label, test(label, False) + f" (EXCEPTION: {e})"


def run_test_f(verifier: DecisionVerifier) -> tuple[str, str]:
    """(f) Valid cert but wrong decision signature → REJECT."""
    label = "f: valid cert, wrong decision signature (must REJECT)"
    try:
        signed = sign_decision(
            escalation_id="test-esc-f",
            verdict="APPROVE",
            by="rmw3",
            note="wrong sig",
            key_id="s5-operational",
            private_key_path=get_node_key_path("s5-operational"),
            cert_path=get_node_cert_path("s5-operational"),
        )
        # Replace signature with all-zeros
        signed["sig"] = "0" * 128
        result = verifier.verify(signed)
        return label, test(label, result.get("valid") is False)
    except Exception as e:
        return label, test(label, False) + f" (EXCEPTION: {e})"


def run_test_g(verifier: DecisionVerifier, verifier2: DecisionVerifier) -> tuple[str, str]:
    """(g) Rotated operational key → REJECT.

    Sign with an OLD key, but the cert has a NEW key.
    """
    label = "g: rotated operational key (old key, new cert) → REJECT"
    try:
        import tempfile
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

        ca_pubkey_hex = get_ca_pubkey_hex()

        # Load the CA to issue a new cert
        with open(os.path.join(CA_DIR, "ca.key"), "rb") as f:
            ca_priv_bytes = f.read()
        ca_priv = ed25519.Ed25519PrivateKey.from_private_bytes(ca_priv_bytes)

        # Generate a NEW operational key (the "rotated" one)
        new_priv = ed25519.Ed25519PrivateKey.generate()
        new_pub = new_priv.public_key()
        new_pub_hex = new_pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

        # Issue a cert for the NEW key
        from datetime import datetime, timezone
        cert_payload = {
            "node_id": "s5-operational-rotated",
            "pubkey_hex": new_pub_hex,
            "ca_pubkey_hex": ca_pubkey_hex,
            "issued": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        cert_sig = ca_priv.sign(canonical_json(cert_payload))
        new_cert = dict(cert_payload)
        new_cert["sig_hex"] = cert_sig.hex()

        # Now sign with the OLD key (from s5-operational, not the new rotated key)
        old_key_path = get_node_key_path("s5-operational")
        with open(old_key_path, "rb") as f:
            old_priv_bytes = f.read()
        old_priv = ed25519.Ed25519PrivateKey.from_private_bytes(old_priv_bytes)

        body = {
            "escalation_id": "test-esc-g",
            "verdict": "APPROVE",
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "by": "rmw3",
            "note": "rotated key test",
        }
        old_sig = old_priv.sign(canonical_json(body)).hex()

        signed = dict(body)
        signed["sig"] = old_sig
        signed["sig_algorithm"] = "ed25519"
        signed["cert"] = new_cert  # cert says the NEW key is the operational key

        # verifier has the SAME CA pinned → but the cert pubkey doesn't match the key
        # that signed the decision → REJECT
        result = verifier.verify(signed)
        return label, test(label, result.get("valid") is False)
    except Exception as e:
        return label, test(label, False) + f" (EXCEPTION: {e})"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Check beacon lib availability
    if not has_verify_node_cert():
        print("[SKIP] beacon_attestation.verify_node_cert not available — tests require it")
        sys.exit(0)

    ca_pubkey_hex = get_ca_pubkey_hex()
    print(f"CA pubkey: {ca_pubkey_hex[:16]}...")
    print(f"Nodes dir: {NODES_DIR}")
    print()

    # Check s5-operational cert exists
    if not os.path.exists(get_node_cert_path("s5-operational")):
        print("[ERROR] s5-operational cert not found. Run first:")
        print("  python3 scripts/s5-governance/gen_test_ca.py")
        print("  python3 scripts/s5-governance/gen_test_ca.py node s5-operational")
        sys.exit(1)

    # Create verifier with the pinned CA root
    verifier = DecisionVerifier(ca_pubkey_hex=ca_pubkey_hex)

    results = []
    print("─── 7-test battery: DECISION-AUTH-FIX ───")
    print()

    results.append(run_test_a(verifier))
    results.append(run_test_b(verifier))
    results.append(run_test_c(verifier))
    results.append(run_test_d(verifier))
    results.append(run_test_e(verifier))
    results.append(run_test_f(verifier))
    results.append(run_test_g(verifier, verifier))

    print()
    passed = sum(1 for _, status in results if status == "PASS")
    total = len(results)
    print(f"─── {passed}/{total} tests passing ───")

    if passed < total:
        print("FAILURES:")
        for label, status in results:
            if status != "PASS":
                print(f"  {label}: {status}")
        sys.exit(1)
    else:
        print("✅ All tests pass. DECISION-AUTH-FIX verified.")
        sys.exit(0)


def has_verify_node_cert() -> bool:
    try:
        from beacon_attestation import verify_node_cert
        return True
    except ImportError:
        return False
    except Exception:
        return False


if __name__ == "__main__":
    main()
