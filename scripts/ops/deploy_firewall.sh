#!/usr/bin/env bash
# deploy_firewall.sh — Generate .fw files from topology.json and push to n02.
#
# Usage:
#   ./scripts/ops/deploy_firewall.sh [--dry-run]
#
# Requires: python3 (with topology_loader), ssh access to n02.
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VOSLAB="$(cd "$SCRIPT_DIR/../.." && pwd)"
FW_REMOTE_DIR="/etc/pve/firewall"
SSH_TARGET="n02"
TMP_DIR=$(mktemp -d)

trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== deploy_firewall.sh ==="
echo "Source: $VOSLAB/topology.json"
echo "Target: $SSH_TARGET:$FW_REMOTE_DIR"
echo "Dry-run: $DRY_RUN"
echo ""

# 1. Generate .fw files locally
echo "── Generating .fw files ──"
cd "$VOSLAB"
python3 -c "
import json, sys
from topology_loader import load_topology
from topology_reconciler import generate_fw_content

topo = load_topology(validate=True)
for cid in topo.container_ids():
    container = topo.containers[cid]
    content = generate_fw_content(cid, container)
    out = '$TMP_DIR/' + cid + '.fw'
    with open(out, 'w') as f:
        f.write(content)
    print(f'  ✓ {cid}.fw ({container[\"name\"]})')
" || { echo "✗ Generation failed"; exit 1; }

FW_COUNT=$(ls "$TMP_DIR"/*.fw 2>/dev/null | wc -l)
echo "  Generated: $FW_COUNT files"
echo ""

# 2. Diff with remote (before push)
echo "── Checking remote state ──"
ssh -o ConnectTimeout=10 "$SSH_TARGET" "ls $FW_REMOTE_DIR/*.fw 2>/dev/null | wc -l" >/dev/null 2>&1 || true
REMOTE_COUNT=$(ssh -o ConnectTimeout=10 "$SSH_TARGET" "ls $FW_REMOTE_DIR/*.fw 2>/dev/null | wc -l" 2>/dev/null || echo "0")
echo "  Remote files: $REMOTE_COUNT"

# 3. Push all .fw files in a single SSH session (fast)
echo "── Pushing to $SSH_TARGET ──"
PUSHED=0
SKIPPED=0
if $DRY_RUN; then
    for fw_file in "$TMP_DIR"/*.fw; do
        cid=$(basename "$fw_file" .fw)
        echo "  [dry-run] Would push $cid.fw"
        PUSHED=$((PUSHED + 1))
    done
else
    # Single tar + ssh pipe for all files
    tar -C "$TMP_DIR" -cf - . | ssh -o ConnectTimeout=10 "$SSH_TARGET" "tar -C $FW_REMOTE_DIR -xf -" 2>/dev/null
    PUSHED=$FW_COUNT
    echo "  ✓ All $PUSHED files pushed in one connection"
fi

echo ""
echo "── Summary ──"
echo "  Pushed: $PUSHED"
echo "  Skipped: $SKIPPED"
if ! $DRY_RUN; then
    echo "  Restarting Proxmox firewall..."
    ssh -o ConnectTimeout=10 "$SSH_TARGET" "pve-firewall restart 2>/dev/null || true" 2>/dev/null || true
    echo "  Done."
fi
