#!/usr/bin/env bash
# gen_test_ca.sh — BEACON-ACTIVATION B1: generate throwaway Ed25519 CA + node certs.
# Usage:
#   ./gen_test_ca.sh                    # generate CA (once)
#   ./gen_test_ca.sh node <node-id>      # generate a node cert signed by CA
#
# Output:
#   _beacon_ca/ (directory)
#     ca.key        — Ed25519 CA private key
#     ca.pubkey     — Ed25519 CA public key (binary, 32 bytes)
#     ca.pubkey.hex — CA public key as hex (for pinning)
#     ca.cert.json  — CA self-describing certificate (JSON envelope for dev)
#     nodes/
#       <node-id>.key      — node Ed25519 private key
#       <node-id>.pubkey   — node Ed25519 public key (binary, 32 bytes)
#       <node-id>.cert.json — node certificate signed by CA
#
# This is a TEST CA for development on LXC 108.
# Production uses the offline S5 CA (ed25519 root 624e8d3e, WSL+USB).
# The beacon_activation spec says: "DS builds + tests on LXC 108 with a
# throwaway CA, then rmw3 issues the REAL nucleus cert for prod."

set -euo pipefail
CA_DIR="_beacon_ca"
KEYGEN_TOOL="openssl"

mkdir -p "$CA_DIR/nodes"

case "${1:-}" in
    node)
        NODE_ID="${2:-node-001}"
        if [ ! -f "$CA_DIR/ca.key" ]; then
            echo "ERROR: CA not initialized. Run ./gen_test_ca.sh first (no args)." >&2
            exit 1
        fi
        NODE_KEY="$CA_DIR/nodes/$NODE_ID.key"
        NODE_PUBKEY="$CA_DIR/nodes/$NODE_ID.pubkey"
        NODE_CERT="$CA_DIR/nodes/$NODE_ID.cert.json"

        # Generate node Ed25519 keypair
        openssl genpkey -algorithm ED25519 -out "$NODE_KEY"
        openssl pkey -in "$NODE_KEY" -pubout -outform DER -out /tmp/_node_pub.der
        # Extract raw 32-byte public key
        dd if=/tmp/_node_pub.der bs=1 skip=12 2>/dev/null > "$NODE_PUBKEY"
        rm /tmp/_node_pub.der

        NODE_PUBKEY_HEX=$(xxd -p -c 32 < "$NODE_PUBKEY")
        CA_PUBKEY_HEX=$(cat "$CA_DIR/ca.pubkey.hex")

        # Sign the node public key with the CA key
        # The cert is: {"node_id":"...","pubkey_hex":"...","ca_pubkey_hex":"...","issued":"..."}
        ISSUED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        PAYLOAD=$(cat <<JSON
{"node_id":"$NODE_ID","pubkey_hex":"$NODE_PUBKEY_HEX","ca_pubkey_hex":"$CA_PUBKEY_HEX","issued":"$ISSUED"}
JSON
)
        # Sign the payload with CA key
        SIG=$(echo -n "$PAYLOAD" | openssl pkeyutl -sign -inkey "$CA_DIR/ca.key" -rawin | xxd -p -c 64)

        cat > "$NODE_CERT" <<CERT
{
  "node_id": "$NODE_ID",
  "pubkey_hex": "$NODE_PUBKEY_HEX",
  "ca_pubkey_hex": "$CA_PUBKEY_HEX",
  "issued": "$ISSUED",
  "sig_hex": "$SIG"
}
CERT
        echo "✅ Node cert generated: $NODE_CERT"
        echo "   node_id=$NODE_ID pubkey_hex=$NODE_PUBKEY_HEX"
        ;;

    *)
        # Generate CA Ed25519 keypair
        openssl genpkey -algorithm ED25519 -out "$CA_DIR/ca.key"
        # Extract raw 32-byte public key from DER
        openssl pkey -in "$CA_DIR/ca.key" -pubout -outform DER -out /tmp/_ca_pub.der
        dd if=/tmp/_ca_pub.der bs=1 skip=12 2>/dev/null > "$CA_DIR/ca.pubkey"
        rm /tmp/_ca_pub.der
        xxd -p -c 32 < "$CA_DIR/ca.pubkey" > "$CA_DIR/ca.pubkey.hex"
        CA_PUBKEY_HEX=$(cat "$CA_DIR/ca.pubkey.hex")

        # Self-sign CA cert
        ISSUED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        EXPIRES=$(date -u -d "+1 year" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+1y +%Y-%m-%dT%H:%M:%SZ)
        PAYLOAD=$(cat <<JSON
{"ca_id":"vsf-test-ca-001","pubkey_hex":"$CA_PUBKEY_HEX","issued":"$ISSUED","expires":"$EXPIRES"}
JSON
)
        SIG=$(echo -n "$PAYLOAD" | openssl pkeyutl -sign -inkey "$CA_DIR/ca.key" -rawin | xxd -p -c 64)

        cat > "$CA_DIR/ca.cert.json" <<CERT
{
  "ca_id": "vsf-test-ca-001",
  "pubkey_hex": "$CA_PUBKEY_HEX",
  "issued": "$ISSUED",
  "expires": "$EXPIRES",
  "sig_hex": "$SIG"
}
CERT
        echo "✅ Test CA generated: $CA_DIR/"
        echo "   CA pubkey (hex): $CA_PUBKEY_HEX"
        echo "   CA cert: $CA_DIR/ca.cert.json"
        echo ""
        echo "   Next: ./gen_test_ca.sh node <node-id>"
        ;;
esac
