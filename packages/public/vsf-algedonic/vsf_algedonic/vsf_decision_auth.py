#!/usr/bin/env python3
"""
vsf_decision_auth.py — Ed25519 decision signing + verification for SUPERVISION-LAYER B2/B3.

SAME PKI PATTERN AS THE BEACON (beacon_attestation.py):
  - S5 CA root (offline) pinned on the verifying host from a TRUSTED SOURCE (config/const)
  - S5 OPERATIONAL key certified by the CA root (cert in the decision record)
  - Decision signature verified against the operational key FROM THE VERIFIED CERT
  - NEVER trusts signer_pubkey or ca_root from the record itself (DECISION-AUTH-FIX)

CERT CHAIN (2-level, same as beacon):
  CA root (self-signed, pinned) ──signs──> S5 operational cert ──cert pubkey verifies──> decision sig

USAGE:
  # Generate CA + S5 operational cert (same beacon PKI)
  python3 scripts/s5-governance/gen_test_ca.py                     # generate CA root
  python3 scripts/s5-governance/gen_test_ca.py node s5-operational  # issue operational cert

  # Sign a decision (produces record with cert + sig)
  python3 -c "
    from vsf_decision_auth import sign_decision, generate_operational_key
    signed = sign_decision('esc-001', 'APPROVE', 'rmw3')
    print(__import__('json').dumps(signed, indent=2))
  "

  # Verify from CLI
  python3 scripts/algedonic/vsf_decision_auth.py verify signed.json <pinned_ca_pubkey.hex>

API (import):
  from vsf_decision_auth import DecisionVerifier, sign_decision, verify_decision
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

# Import the beacon's cert-chain verification (same PKI)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from beacon_attestation import verify_node_cert, _canonical_json
    HAS_BEACON_LIB = True
except ImportError:
    HAS_BEACON_LIB = False
    # Fallback canonical JSON for standalone use (but cert verification requires beacon lib)
    def _canonical_json(obj: dict) -> bytes:
        return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()

CA_DIR = Path(os.environ.get("VSF_CA_DIR", "_beacon_ca"))
DECISION_KEY_DIR = Path(os.environ.get("VSF_DECISION_KEY_DIR", "_beacon_ca/decision_keys"))


# ── Key loaders ──────────────────────────────────────────────────────────────

def _load_public_key(hex_key: str) -> ed25519.Ed25519PublicKey:
    """Load an Ed25519 public key from its hex representation (64 hex chars)."""
    raw = bytes.fromhex(hex_key)
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)


def _load_private_key(path: str) -> ed25519.Ed25519PrivateKey:
    """Load an Ed25519 private key from raw 32-byte binary file."""
    with open(path, "rb") as f:
        raw = f.read()
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def _get_ca_pubkey_hex() -> str:
    """Return the CA root public key hex from the test CA dir.

    In PRODUCTION this comes from a PINNED config file, never from the record.
    For test/development we read from the local _beacon_ca/ directory.
    """
    hex_path = CA_DIR / "ca.pubkey.hex"
    if hex_path.exists():
        return hex_path.read_text().strip()
    raise FileNotFoundError(
        f"CA pubkey not found at {hex_path}. Run gen_test_ca.py first."
    )


# ── B2: Generate S5 operational keypair + cert ───────────────────────────────

def generate_operational_key(key_id: str = "s5-operational") -> tuple[str, str]:
    """Generate an S5 operational Ed25519 keypair (for signing decisions).

    In prod, this key is ISSUED by the offline S5 CA in a ceremony.
    For test, we use gen_test_ca.py node <key_id> to create the cert.

    Returns:
        (pubkey_hex, path_to_private_key)
    """
    DECISION_KEY_DIR.mkdir(parents=True, exist_ok=True)

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_path = DECISION_KEY_DIR / f"{key_id}.key"
    pub_hex_path = DECISION_KEY_DIR / f"{key_id}.pubkey.hex"

    priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    with open(priv_path, "wb") as f:
        f.write(priv_bytes)
    pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub_hex = pub_bytes.hex()
    with open(pub_hex_path, "w") as f:
        f.write(pub_hex + "\n")

    ca_hex = _get_ca_pubkey_hex()
    with open(DECISION_KEY_DIR / f"{key_id}.issuer", "w") as f:
        f.write(ca_hex + "\n")

    print(f"[decision_auth] Generated S5 operational key '{key_id}'", file=sys.stderr)
    print(f"[decision_auth]   Private: {priv_path}", file=sys.stderr)
    print(f"[decision_auth]   Pubkey hex: {pub_hex[:16]}...", file=sys.stderr)
    print(f"[decision_auth]   NOTE: use gen_test_ca.py node {key_id} for a proper cert", file=sys.stderr)

    return pub_hex, str(priv_path)


# ── B2: Sign a decision ─────────────────────────────────────────────────────

def sign_decision(
    escalation_id: str,
    verdict: str,
    by: str = "rmw3",
    note: str = "",
    private_key_path: str | None = None,
    cert_path: str | None = None,
    key_id: str = "s5-operational",
) -> dict:
    """Create and sign a supervision_decision record.

    The decision includes a `cert` field (the S5 operational key cert issued
    by the CA root) and the Ed25519 `sig` over the canonical body.

    Args:
        escalation_id: unique escalation identifier
        verdict: APPROVE | DENY | ADJUST
        by: signer identity
        note: human-readable justification
        private_key_path: path to Ed25519 private key (default:
            _beacon_ca/nodes/<key_id>.key from gen_test_ca.py node)
        cert_path: path to the node cert JSON (default:
            _beacon_ca/nodes/<key_id>.cert.json from gen_test_ca.py node)
        key_id: the node/cert ID (default: s5-operational)

    Returns:
        dict: the signed decision including cert, sig, sig_algorithm
    """
    # Default paths: look in nodes/ (where gen_test_ca.py node places them)
    if private_key_path is None:
        private_key_path = str(Path(CA_DIR) / "nodes" / f"{key_id}.key")
    if cert_path is None:
        cert_path = str(Path(CA_DIR) / "nodes" / f"{key_id}.cert.json")

    if not os.path.exists(private_key_path):
        raise FileNotFoundError(
            f"S5 operational key not found at {private_key_path}. "
            f"Run 'python3 scripts/s5-governance/gen_test_ca.py node {key_id}' first."
        )
    if not os.path.exists(cert_path):
        raise FileNotFoundError(
            f"S5 operational cert not found at {cert_path}. "
            f"Run 'python3 scripts/s5-governance/gen_test_ca.py node {key_id}' first."
        )

    # Build decision body (everything EXCEPT sig, cert, and metadata)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    decision_body = {
        "escalation_id": escalation_id,
        "verdict": verdict,
        "ts": ts,
        "by": by,
        "note": note,
    }

    # Load private key and sign the canonical JSON
    private_key = _load_private_key(private_key_path)
    sig_payload = _canonical_json(decision_body)
    signature = private_key.sign(sig_payload)
    sig_hex = signature.hex()

    # Load the cert
    with open(cert_path) as f:
        cert = json.load(f)

    # Build the signed record
    signed = dict(decision_body)
    signed["sig"] = sig_hex
    signed["sig_algorithm"] = "ed25519"
    signed["cert"] = cert

    return signed


# ── DecisionVerifier (B3) — same pattern as BeaconAttestation ────────────────

class DecisionVerifier:
    """Decision signature verifier. Stateless; pinned CA pubkey on init.

    Same PKI pattern as BeaconAttestation:
      - ca_pubkey_hex is PINNED at construction (from trusted config)
      - Verification REQUIRES a cert in the decision record
      - Cert must chain to the pinned root (verify_node_cert from beacon lib)
      - Decision signature verified against cert's operational pubkey
      - Fail-closed: any missing/invalid field → REJECT

    Usage:
        verifier = DecisionVerifier(ca_pubkey_hex="<64 hex chars>")
        result = verifier.verify(signed_decision_dict)
        # result = {"valid": True} or {"valid": False, "reason": "..."}
    """

    def __init__(self, ca_pubkey_hex: str | None = None):
        """Initialize with PINNED CA root public key.

        Args:
            ca_pubkey_hex: S5 CA root public key hex (64 chars).
                If None, reads from local test CA directory.
                NEVER from the decision record.
        """
        if ca_pubkey_hex is None:
            ca_pubkey_hex = _get_ca_pubkey_hex()

        if len(ca_pubkey_hex) != 64:
            raise ValueError(f"CA pubkey must be 64 hex chars, got {len(ca_pubkey_hex)}")
        self._ca_pubkey_hex = ca_pubkey_hex

    def verify(self, decision: dict) -> dict:
        """Verify a signed supervision decision.

        Steps:
          1. Check required fields (escalation_id, verdict, sig, cert)
          2. Verify cert chains to pinned CA root (via beacon's verify_node_cert)
          3. Verify decision signature against the cert's operational pubkey
          4. Fail-closed on any error

        Args:
            decision: the signed decision dict with 'cert' and 'sig'

        Returns:
            {"valid": True} or {"valid": False, "reason": "..."}
        """
        # ── Step 0: Required fields ───────────────────────────────────────
        if "escalation_id" not in decision:
            return {"valid": False, "reason": "missing escalation_id"}
        if "verdict" not in decision:
            return {"valid": False, "reason": "missing verdict"}
        if "sig" not in decision:
            return {"valid": False, "reason": "no signature field ('sig')"}
        if "cert" not in decision:
            return {"valid": False, "reason": "no cert field — operational key cert required"}

        # ── Step 1: Verify cert chain to pinned root ──────────────────────
        if not HAS_BEACON_LIB:
            return {"valid": False, "reason": "beacon_attestation library not available — cannot verify cert chain"}

        cert = decision["cert"]
        cert_ok, cert_reason, operational_pubkey_bytes = verify_node_cert(
            cert, self._ca_pubkey_hex
        )
        if not cert_ok:
            return {"valid": False, "reason": f"cert: {cert_reason}"}
        if operational_pubkey_bytes is None:
            return {"valid": False, "reason": "cert valid but no pubkey extracted"}

        # ── Step 2: Verify decision signature ─────────────────────────────
        sig_hex = decision["sig"]
        sig_algorithm = decision.get("sig_algorithm", "ed25519")

        if sig_algorithm != "ed25519":
            return {"valid": False, "reason": f"unsupported algorithm: {sig_algorithm}"}

        try:
            sig_bytes = bytes.fromhex(sig_hex)
        except (ValueError, TypeError):
            return {"valid": False, "reason": "invalid signature hex"}

        # Rebuild canonical body: ONLY the decision fields (no sig, cert, metadata)
        canon_body = {k: decision[k] for k in ("escalation_id", "verdict", "ts", "by", "note")
                      if k in decision}
        canon_payload = _canonical_json(canon_body)

        try:
            operational_pubkey = ed25519.Ed25519PublicKey.from_public_bytes(operational_pubkey_bytes)
            operational_pubkey.verify(sig_bytes, canon_payload)
        except Exception as e:
            return {"valid": False, "reason": f"signature verification failed: {e}"}

        # ── ALL CHECKS PASSED ─────────────────────────────────────────────
        return {"valid": True}


# ── Convenience function (backward compatible signature, but FIXED) ──────────

def verify_decision(signed: dict, ca_pubkey_hex: str | None = None) -> dict:
    """Verify a signed decision (convenience wrapper).

    FIXED (DECISION-AUTH-FIX): uses DecisionVerifier with PINNED CA root.
    The ca_pubkey_hex arg is from the CALLER/CONFIG (trusted source), NEVER from the record.
    The record's signer_pubkey and ca_root_pubkey fields are IGNORED for verification.

    Args:
        signed: decision dict with 'cert' and 'sig'
        ca_pubkey_hex: pinned CA root from TRUSTED SOURCE (config).
            If None, reads from local test CA.

    Returns:
        {"valid": True} or {"valid": False, "reason": "..."}
    """
    verifier = DecisionVerifier(ca_pubkey_hex=ca_pubkey_hex)
    return verifier.verify(signed)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "generate":
        key_id = sys.argv[2] if len(sys.argv) > 2 else "s5-operational"
        generate_operational_key(key_id)

    elif cmd == "verify":
        if len(sys.argv) < 3:
            print("Usage: vsf_decision_auth.py verify <signed_decision.json> [pinned_ca_pubkey.hex]")
            sys.exit(1)
        with open(sys.argv[2]) as f:
            signed = json.load(f)
        ca_pubkey_hex = None
        if len(sys.argv) > 3:
            with open(sys.argv[3]) as f:
                ca_pubkey_hex = f.read().strip()
        result = verify_decision(signed, ca_pubkey_hex=ca_pubkey_hex)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("valid") else 1)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
