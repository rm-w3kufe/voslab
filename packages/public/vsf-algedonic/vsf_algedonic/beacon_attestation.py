#!/usr/bin/env python3
"""
beacon_attestation.py — BEACON-ACTIVATION B2: Ed25519 attestation protocol.

Implements the beacon_activation.spec.vsm attestation protocol:
  trust_root → S5 CA root pubkey (pinned)
  kernel_birth_payload → {kernel_id, vsf_version, watermark, covenant_sha,
                          calibration, cert, sig}
  beacon_verify:
    1. cert chains to the pinned root (REJECT if not)
    2. sig verifies over payload with cert key (REJECT if not)
    3. covenant_sha matches current (REJECT if not)
    4. (optional, phase 2) calibration hash matches census
    → PASS: TRUSTED registration
    → FAIL: REJECTED + algedonic

Usage:
    verifier = BeaconAttestation(ca_pubkey_hex="...")
    result = verifier.verify(payload_dict)
    # result = {"status": "trusted"|"rejected", "reason": "...", "node_id": "..."}

Can be imported by:
  - beacon/main.py (the actual vsf-api)
  - client test scripts (for development)
  - vsf-nucleus (for building the payload)

Uses stdlib hashlib + json + time only.
Ed25519 verification uses the 'cryptography' package (already installed on beacon).
For environment without cryptography: falls back to 'nacl' (PyNaCl) or raises ImportError.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger("vsf.beacon.attestation")

# ── Ed25519 verification ─────────────────────────────────────────────────────

def _verify_ed25519(pubkey_bytes: bytes, message: bytes, sig_bytes: bytes) -> bool:
    """Verify an Ed25519 signature. Supports multiple backends."""
    # Prefer 'cryptography' (used by beacon main.py)
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        pubkey = ed25519.Ed25519PublicKey.from_public_bytes(pubkey_bytes)
        pubkey.verify(sig_bytes, message)
        return True
    except ImportError:
        pass
    except Exception:
        return False

    # Fallback: nacl (PyNaCl)
    try:
        import nacl.bindings
        nacl.bindings.crypto_sign_verify_detached(sig_bytes, message, pubkey_bytes)
        return True
    except ImportError:
        pass
    except Exception:
        return False

    # Fallback: raw using built-in... this won't work without library
    raise ImportError(
        "Ed25519 verification requires 'cryptography' or 'nacl' package. "
        "Install: pip install cryptography"
    )


def _hex_to_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str)


def _canonical_json(obj: dict) -> bytes:
    """Deterministic JSON serialization for signature verification."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


# ── Cert chain verification ──────────────────────────────────────────────────

def verify_node_cert(node_cert: dict, ca_pubkey_hex: str) -> tuple[bool, str, bytes | None]:
    """Verify that node_cert was signed by the CA.

    Args:
        node_cert: dict with node_id, pubkey_hex, ca_pubkey_hex, issued, sig_hex
        ca_pubkey_hex: pinned CA root public key (64 hex chars = 32 bytes)

    Returns:
        (ok, reason, node_pubkey_bytes)
    """
    # Check CA match
    if node_cert.get("ca_pubkey_hex") != ca_pubkey_hex:
        return False, f"CA mismatch: cert says {node_cert.get('ca_pubkey_hex')[:16]}… pinned {ca_pubkey_hex[:16]}…", None

    # Check node_id present
    node_id = node_cert.get("node_id", "")
    if not node_id:
        return False, "cert missing node_id", None

    # Extract pubkey
    node_pubkey_hex = node_cert.get("pubkey_hex", "")
    if len(node_pubkey_hex) != 64:
        return False, f"invalid pubkey_hex length={len(node_pubkey_hex)}", None
    node_pubkey_bytes = _hex_to_bytes(node_pubkey_hex)

    # Rebuild payload that was signed
    cert_payload = {
        "node_id": node_cert["node_id"],
        "pubkey_hex": node_cert["pubkey_hex"],
        "ca_pubkey_hex": node_cert["ca_pubkey_hex"],
        "issued": node_cert.get("issued", ""),
    }
    payload_bytes = _canonical_json(cert_payload)

    # Verify CA signature over the cert payload
    sig_hex = node_cert.get("sig_hex", "")
    if len(sig_hex) != 128:
        return False, f"invalid sig_hex length={len(sig_hex)}", None
    sig_bytes = _hex_to_bytes(sig_hex)

    ca_pubkey_bytes = _hex_to_bytes(ca_pubkey_hex)
    try:
        ok = _verify_ed25519(ca_pubkey_bytes, payload_bytes, sig_bytes)
        if not ok:
            return False, "cert signature invalid", None
    except Exception as e:
        return False, f"cert verification error: {e}", None

    return True, "cert valid", node_pubkey_bytes


# ── Full attestation verification ────────────────────────────────────────────

class BeaconAttestation:
    """Beacon attestation verifier. Stateless; pinned CA pubkey on init."""

    def __init__(self, ca_pubkey_hex: str, current_covenant_sha: str | None = None):
        """
        Args:
            ca_pubkey_hex: S5 CA root public key (64 hex chars, 32 bytes)
            current_covenant_sha: SHA-256 of the LIVE covenant (for hash check)
        """
        self.ca_pubkey_hex = ca_pubkey_hex
        self.current_covenant_sha = current_covenant_sha

        # Validate CA pubkey format
        if len(ca_pubkey_hex) != 64:
            raise ValueError(f"CA pubkey must be 64 hex chars, got {len(ca_pubkey_hex)}")

    def set_covenant_sha(self, sha: str):
        """Update the current covenant SHA (called when covenant changes)."""
        self.current_covenant_sha = sha

    def verify(self, payload: dict) -> dict:
        """Verify a full kernel_birth_payload.

        Args:
            payload: dict with:
                - kernel_id: str
                - vsf_version: str
                - watermark: str
                - covenant_sha: str (64 hex)
                - calibration: str (hash of passing census, optional)
                - cert: dict (the node cert)
                - sig: str (128 hex = 64 bytes Ed25519 signature)

        Returns:
            dict: {
                "status": "trusted" | "rejected",
                "node_id": str,
                "reason": str,
                "verified_at": str (ISO timestamp),
            }
        """
        node_id = payload.get("kernel_id", "unknown")
        reason_parts = []
        trusted = True

        # ── Step 1: Verify cert chain ─────────────────────────────────────────
        node_cert = payload.get("cert")
        if not node_cert or not isinstance(node_cert, dict):
            return self._reject(node_id, "missing or invalid 'cert' field")

        cert_ok, cert_reason, node_pubkey = verify_node_cert(node_cert, self.ca_pubkey_hex)
        if not cert_ok:
            return self._reject(node_id, f"cert: {cert_reason}")
        reason_parts.append(f"cert=OK(node_id={node_cert.get('node_id','?')})")

        if node_pubkey is None:
            return self._reject(node_id, "cert valid but no pubkey extracted")

        # ── Step 2: Verify signature over the payload body ────────────────────
        # The sig is over a canonical subset: {kernel_id, vsf_version, watermark,
        # covenant_sha, calibration} in sorted-key JSON.
        sig_hex = payload.get("sig", "")
        if len(sig_hex) != 128:
            return self._reject(node_id, f"invalid signature length {len(sig_hex)}")

        sig_body = {
            "kernel_id": payload["kernel_id"],
            "vsf_version": payload.get("vsf_version", ""),
            "watermark": payload.get("watermark", ""),
            "covenant_sha": payload.get("covenant_sha", ""),
            "calibration": payload.get("calibration", ""),
        }
        sig_message = _canonical_json(sig_body)
        sig_bytes = _hex_to_bytes(sig_hex)

        try:
            sig_ok = _verify_ed25519(node_pubkey, sig_message, sig_bytes)
            if not sig_ok:
                return self._reject(node_id, "payload signature invalid")
        except Exception as e:
            return self._reject(node_id, f"signature verification error: {e}")
        reason_parts.append("sig=OK")

        # ── Step 3: Verify covenant_sha matches ──────────────────────────────
        if self.current_covenant_sha:
            payload_cov_sha = payload.get("covenant_sha", "")
            if payload_cov_sha != self.current_covenant_sha:
                return self._reject(
                    node_id,
                    f"covenant_sha mismatch: received {payload_cov_sha[:16]}… "
                    f"current {self.current_covenant_sha[:16]}…"
                )
            reason_parts.append("covenant=OK")

        # ── Step 4: Calibration check (phase 2, optional) ────────────────────
        # TODO (phase 2): verify calibration hash against EVC census
        calibration = payload.get("calibration", "")
        if calibration:
            reason_parts.append(f"calibration={calibration[:16]}… (note: phase-2 verify pending)")

        # ── ALL CHECKS PASSED ────────────────────────────────────────────────
        now = datetime.now(timezone.utc).isoformat()
        return {
            "status": "trusted",
            "node_id": node_id,
            "reason": "; ".join(reason_parts),
            "verified_at": now,
            "cert_node_id": node_cert.get("node_id", ""),
        }

    def _reject(self, node_id: str, reason: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        log.warning("BEACON REJECTED node=%s reason=%s", node_id, reason)
        return {
            "status": "rejected",
            "node_id": node_id,
            "reason": reason,
            "verified_at": now,
        }


# ── Registry writer ──────────────────────────────────────────────────────────

def write_registry_entry(registry_path: str, result: dict, remote_ip: str = ""):
    """Append a TRUSTED or REJECTED entry to registry.jsonl.

    Format per beacon_activation spec:
      {"node_id":"...", "status":"trusted"|"rejected", "ts":"...",
       "reason":"...", "ip":"...", "verified_at":"...", "cert_node_id":"..."}
    """
    import os
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "node_id": result.get("node_id", "unknown"),
        "status": result["status"],
        "reason": result.get("reason", ""),
        "ip": remote_ip,
        "verified_at": result.get("verified_at", ""),
        "cert_node_id": result.get("cert_node_id", ""),
    }
    # Ensure parent dir exists
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def build_kernel_payload(kernel_id: str, vsf_version: str, watermark: str,
                         covenant_sha: str, node_key_path: str,
                         calibration: str = "") -> dict:
    """Build a signed kernel_birth_payload for testing.

    Args:
        kernel_id: node identifier (e.g. "vsf_nucleus")
        vsf_version: binary version string
        watermark: the VSF watermark string
        covenant_sha: SHA-256 of the covenant being attested to
        node_key_path: path to Ed25519 private key file
        calibration: optional calibration hash

    Returns:
        dict: the full signed payload, ready to POST to the beacon
    """
    from cryptography.hazmat.primitives.asymmetric import ed25519
    import os

    # Read node key
    with open(node_key_path, "rb") as f:
        key_bytes = f.read()
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)

    # Build signature body
    sig_body = {
        "kernel_id": kernel_id,
        "vsf_version": vsf_version,
        "watermark": watermark,
        "covenant_sha": covenant_sha,
        "calibration": calibration,
    }
    sig_message = _canonical_json(sig_body)
    sig = private_key.sign(sig_message)
    sig_hex = sig.hex()

    # Read node cert
    cert_dir = os.path.dirname(node_key_path)
    cert_path = os.path.join(os.path.dirname(cert_dir), f"{kernel_id}.cert.json")
    if not os.path.exists(cert_path):
        # Try with node-
        cert_path = os.path.join(cert_dir, f"{kernel_id}.cert.json")
    if os.path.exists(cert_path):
        with open(cert_path) as f:
            cert = json.load(f)
    else:
        raise FileNotFoundError(f"cert not found for {kernel_id} at {cert_path}")

    return {
        "kernel_id": kernel_id,
        "vsf_version": vsf_version,
        "watermark": watermark,
        "covenant_sha": covenant_sha,
        "calibration": calibration,
        "cert": cert,
        "sig": sig_hex,
    }
