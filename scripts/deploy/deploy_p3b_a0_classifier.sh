#!/usr/bin/env bash
# deploy_p3b_a0_classifier.sh — deploy A0_classifier.py (Python daemon) to LXC 101.
# Gate: EXP-A01-01 COMPLETE + S5 approval OI_3 (rmw3, 2026-06-21)
#
# SCOPE: this deploys the A0/A0.1 ethics classifier ONLY. It is NOT covered by the
# canonical deploy_bundle.sh (which handles the Rust nucleus + s3-star + g6_sink).
# TODO (tracked in kernel_scaffolding_register): fold the A0-classifier deploy into
# deploy_bundle.sh so there is one canonical deploy path. Until then this stays.
# (The companion deploy_p3a_nucleus.sh was DELETED 2026-06-22 — it duplicated the
# nucleus-binary deploy that deploy_bundle.sh already does correctly.)
#
# Designed to run FROM WSL. All pct/systemctl commands execute on n02 via SSH.
#
# Usage: bash scripts/deploy/deploy_p3b_a0_classifier.sh [--sandbox | --prod]

set -euo pipefail

N02="root@n02"
LXC_SANDBOX=108
LXC_PROD=101
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

MODE="${1:-}"
if [[ "$MODE" != "--sandbox" && "$MODE" != "--prod" ]]; then
    echo "Usage: $0 --sandbox   (certify on LXC 108)"
    echo "       $0 --prod      (deploy to LXC 101, requires sandbox PASS)"
    exit 1
fi

push_classifier() {
    local lxc="$1"
    echo "[p3b] uploading A0_classifier.py to n02…"
    scp "$REPO_ROOT/scripts/vsl/A0_classifier.py" "${N02}:/tmp/A0_classifier_deploy.py"
    echo "[p3b] pushing A0_classifier.py → LXC ${lxc} /root/vsf-scripts/"
    ssh "$N02" "pct exec ${lxc} -- mkdir -p /root/vsf-scripts && \
                pct push ${lxc} /tmp/A0_classifier_deploy.py /root/vsf-scripts/vsl/A0_classifier.py && \
                pct exec ${lxc} -- chmod +x /root/vsf-scripts/vsl/A0_classifier.py"
}

if [[ "$MODE" == "--sandbox" ]]; then
    echo "=== P3b SANDBOX CERTIFICATION (LXC ${LXC_SANDBOX}) ==="
    push_classifier "$LXC_SANDBOX"

    EVENTS_PATH="/var/lib/vsf/vsf_nucleus/events.jsonl"
    echo "[p3b] smoke-test: --once on LXC ${LXC_SANDBOX}"
    ssh "$N02" "pct exec ${LXC_SANDBOX} -- bash -c '
        EVENTS=\"${EVENTS_PATH}\"
        if [[ ! -f \"\$EVENTS\" ]]; then
            echo \"{}\" > /tmp/vsf_sandbox_events_test.jsonl
            EVENTS=/tmp/vsf_sandbox_events_test.jsonl
        fi
        python3 /root/vsf-scripts/vsl/A0_classifier.py \
            --events \"\$EVENTS\" \
            --a0-events-out /tmp/vsf_a0_events_sandbox.jsonl \
            --signal-out /tmp/vsf_ethics_signal_sandbox.json \
            --signal-out-s4 /tmp/vsf_s4_intel_sandbox.json \
            --once 2>&1 | tail -20
    '"
    echo "[p3b] sandbox smoke-test complete. Verify output above."
    echo "[p3b] If PASS → run: bash $0 --prod"
    exit 0
fi

# --prod path
echo "=== P3b PRODUCTION DEPLOY (LXC ${LXC_PROD}) ==="
echo "[p3b] WARNING: this wires the live S5 ethics enforcement path."
echo "[p3b] Gate: EXP-A01-01 COMPLETE, OI_3 S5-approved 2026-06-21."
read -rp "Confirm deploy to LXC ${LXC_PROD}? [yes/N] " confirm
if [[ "$confirm" != "yes" ]]; then echo "aborted."; exit 1; fi

push_classifier "$LXC_PROD"

echo "[p3b] uploading service unit to n02…"
scp "$REPO_ROOT/scripts/systemd/vsf-a0-classifier.service" \
    "${N02}:/tmp/vsf-a0-classifier.service"

echo "[p3b] installing service on LXC ${LXC_PROD}…"
ssh "$N02" "pct push ${LXC_PROD} /tmp/vsf-a0-classifier.service \
                /etc/systemd/system/vsf-a0-classifier.service && \
            pct exec ${LXC_PROD} -- systemctl daemon-reload && \
            pct exec ${LXC_PROD} -- systemctl enable vsf-a0-classifier.service && \
            pct exec ${LXC_PROD} -- systemctl start  vsf-a0-classifier.service"

sleep 3
echo "[p3b] service status:"
ssh "$N02" "pct exec ${LXC_PROD} -- systemctl status vsf-a0-classifier.service --no-pager" \
    | head -20

echo ""
echo "[p3b] Verifying ethics_signal.json (wait up to 35s for first cycle)…"
sleep 35
ssh "$N02" "pct exec ${LXC_PROD} -- cat /run/vsf/ethics_signal.json" || \
    echo "[p3b] signal not yet written — check: ssh root@n02 pct exec ${LXC_PROD} -- journalctl -u vsf-a0-classifier -n 30"

echo "[p3b] P3b COMPLETE."
echo "[p3b] Next: deploy P3a binary to LXC ${LXC_PROD}. Run:"
echo "      bash scripts/deploy_p3a_nucleus.sh"
