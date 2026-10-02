#!/usr/bin/env python3
"""
gen_test_ca.py — BEACON-ACTIVATION B1: Ed25519 test CA + node cert generation.

Usage:
  python3 scripts/s5-governance/gen_test_ca.py              # generate CA
  python3 scripts/s5-governance/gen_test_ca.py node <id>    # generate node cert

Output in _beacon_ca/ (same format as gen_test_ca.sh).
Uses cryptography library for reliable Ed25519 support across OpenSSL versions.
"""

import json
import os
import sys
from datetime import datetime, timezone

CA_DIR = os.path.join(os.path.dirname(__file__), "..", "_beacon_ca")
NODES_DIR = os.path.join(CA_DIR, "nodes")


def _canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


def gen_ca():
    """Generate Ed25519 CA keypair + self-signed cert."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    os.makedirs(CA_DIR, exist_ok=True)

    # Generate Ed25519 keypair
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Extract raw 32-byte public key
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    pubkey_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    pubkey_hex = pubkey_bytes.hex()

    # Write keys
    # Private key in raw binary format (32 bytes for Ed25519)
    from cryptography.hazmat.primitives.serialization import PrivateFormat, NoEncryption
    privkey_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    with open(os.path.join(CA_DIR, "ca.key"), "wb") as f:
        f.write(privkey_bytes)
    with open(os.path.join(CA_DIR, "ca.pubkey"), "wb") as f:
        f.write(pubkey_bytes)
    with open(os.path.join(CA_DIR, "ca.pubkey.hex"), "w") as f:
        f.write(pubkey_hex + "\n")

    # Self-signed cert
    issued = datetime.now(timezone.utc).isoformat()
    import time as ttime
    expires = datetime.fromtimestamp(ttime.time() + 365 * 86400, tz=timezone.utc).isoformat()

    cert_payload = {
        "ca_id": "vsf-test-ca-001",
        "pubkey_hex": pubkey_hex,
        "issued": issued,
        "expires": expires,
    }
    sig = private_key.sign(_canonical_json(cert_payload))
    sig_hex = sig.hex()

    cert = {
        "ca_id": "vsf-test-ca-001",
        "pubkey_hex": pubkey_hex,
        "issued": issued,
        "expires": expires,
        "sig_hex": sig_hex,
    }
    with open(os.path.join(CA_DIR, "ca.cert.json"), "w") as f:
        json.dump(cert, f, indent=2)

    print(f"✅ Test CA generated: {CA_DIR}/")
    print(f"   CA pubkey (hex): {pubkey_hex}")
    print(f"   Next: python3 scripts/s5-governance/gen_test_ca.py node <node-id>")


def gen_node(node_id: str):
    """Generate a node Ed25519 keypair + cert signed by CA."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

    if not os.path.exists(os.path.join(CA_DIR, "ca.key")):
        print("ERROR: CA not initialized. Run without args first.")
        sys.exit(1)

    os.makedirs(NODES_DIR, exist_ok=True)

    # Read CA key
    with open(os.path.join(CA_DIR, "ca.key"), "rb") as f:
        ca_privkey_bytes = f.read()
    ca_private_key = ed25519.Ed25519PrivateKey.from_private_bytes(ca_privkey_bytes)

    with open(os.path.join(CA_DIR, "ca.pubkey.hex")) as f:
        ca_pubkey_hex = f.read().strip()

    # Generate node Ed25519 keypair
    node_private_key = ed25519.Ed25519PrivateKey.generate()
    node_public_key = node_private_key.public_key()

    node_pubkey_bytes = node_public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    node_pubkey_hex = node_pubkey_bytes.hex()

    # Write node keys
    node_privkey_bytes = node_private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    with open(os.path.join(NODES_DIR, f"{node_id}.key"), "wb") as f:
        f.write(node_privkey_bytes)
    with open(os.path.join(NODES_DIR, f"{node_id}.pubkey"), "wb") as f:
        f.write(node_pubkey_bytes)

    # Build cert payload and sign with CA
    issued = datetime.now(timezone.utc).isoformat()
    cert_payload = {
        "node_id": node_id,
        "pubkey_hex": node_pubkey_hex,
        "ca_pubkey_hex": ca_pubkey_hex,
        "issued": issued,
    }
    cert_sig = ca_private_key.sign(_canonical_json(cert_payload))
    cert_sig_hex = cert_sig.hex()

    node_cert = {
        "node_id": node_id,
        "pubkey_hex": node_pubkey_hex,
        "ca_pubkey_hex": ca_pubkey_hex,
        "issued": issued,
        "sig_hex": cert_sig_hex,
    }
    with open(os.path.join(NODES_DIR, f"{node_id}.cert.json"), "w") as f:
        json.dump(node_cert, f, indent=2)

    print(f"✅ Node cert generated: {os.path.join(NODES_DIR, f'{node_id}.cert.json')}")
    print(f"   node_id={node_id} pubkey_hex={node_pubkey_hex[:32]}…")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        gen_ca()
    elif sys.argv[1] == "node":
        node_id = sys.argv[2] if len(sys.argv) > 2 else "node-001"
        gen_node(node_id)
    else:
        print("Usage: python3 scripts/s5-governance/gen_test_ca.py              # generate CA")
        print("       python3 scripts/s5-governance/gen_test_ca.py node <id>    # generate node cert")
        sys.exit(1)
