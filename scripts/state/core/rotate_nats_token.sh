#!/bin/bash
# rotate_nats_token.sh — run on n02 host as root.
# Rotates the fleet-wide NATS auth token everywhere it's configured.
# Usage: rotate_nats_token.sh <OLD_TOKEN> <NEW_TOKEN>
#
# Sequence: update server first, then rapid-fire every running client
# (brief auth-gap window while each client restarts — unavoidable with
# single-static-token auth, minimized by doing this in one script run
# instead of manual steps). Stopped LXCs (112/113) get their configs
# updated too (so they're correct whenever restarted) but no restart.
#
# Before adding a new LXC/service here: check docs/spec/nats_token_registry.vsm
# first, and update BOTH files together — this script and that registry must
# stay in sync, or the next rotation repeats 2026-08-03's postmortem.

set -euo pipefail

OLD="${1:?Usage: rotate_nats_token.sh <OLD_TOKEN> <NEW_TOKEN>}"
NEW="${2:?Usage: rotate_nats_token.sh <OLD_TOKEN> <NEW_TOKEN>}"

if [ "${#OLD}" -ne 32 ] || [ "${#NEW}" -ne 32 ]; then
  echo "ERROR: both tokens must be 32 hex chars. Got OLD=${#OLD} NEW=${#NEW}" >&2
  exit 1
fi

echo "=== [1/4] Server (106): updating nats-server.conf + reload ==="
pct exec 106 -- sed -i "s/$OLD/$NEW/g" /etc/nats-server.conf
pct exec 106 -- systemctl reload nats-server 2>/dev/null || pct exec 106 -- systemctl restart nats-server
sleep 1
pct exec 106 -- systemctl is-active nats-server

echo "=== [2/4] Running clients: update + restart, rapid sequence ==="

echo "  -- LXC 101 (clima-bridge, econ-bridge, markov-bridge, s3-alloc) --"
pct exec 101 -- sed -i "s/$OLD/$NEW/g" /etc/systemd/system/vsf-s4-clima-bridge.service.d/nats-auth.conf
pct exec 101 -- sed -i "s/$OLD/$NEW/g" /etc/systemd/system/vsf-s4-econ-bridge.service.d/nats-auth.conf
pct exec 101 -- sed -i "s/$OLD/$NEW/g" /etc/systemd/system/vsf-s4-markov-bridge.service.d/nats-auth.conf
pct exec 101 -- sed -i "s/$OLD/$NEW/g" /etc/default/vsf-s3-alloc
pct exec 101 -- systemctl daemon-reload
pct exec 101 -- systemctl restart vsf-s4-clima-bridge.service vsf-s4-econ-bridge.service vsf-s4-markov-bridge.service
pct exec 101 -- systemctl restart vsf-s3-alloc.service 2>/dev/null || echo "    (vsf-s3-alloc restart skipped -- check service name if this errors)"

echo "  -- LXC 104 (covenant, ledger, ca-monitor) --"
pct exec 104 -- sed -i "s/$OLD/$NEW/g" /etc/systemd/system/vsf-s5-covenant.service
pct exec 104 -- sed -i "s/$OLD/$NEW/g" /etc/systemd/system/vsf-s5-ledger.service
pct exec 104 -- sed -i "s/$OLD/$NEW/g" /etc/systemd/system/vsf-s5-ca-monitor.service
pct exec 104 -- systemctl daemon-reload
pct exec 104 -- systemctl restart vsf-s5-covenant.service vsf-s5-ledger.service vsf-s5-ca-monitor.service

echo "  -- LXC 107 (s3-star) --"
pct exec 107 -- sed -i "s/$OLD/$NEW/g" /etc/systemd/system/vsf-s3-star.service.d/nats-url.conf
pct exec 107 -- systemctl daemon-reload
pct exec 107 -- systemctl restart vsf-s3-star.service

echo "  -- LXC 104 + 107: EnvironmentFiles=/etc/vsf/nats-creds.env --"
echo "     (FOUND LATE 2026-08-03: EnvironmentFile= wins over drop-in Environment=."
echo "      Missing this step leaves the client silently using the OLD token even"
echo "      though 'systemctl show -p Environment' looks correct -- verify with"
echo "      /proc/<pid>/environ + ss -tnp, not systemctl show alone. See"
echo "      docs/spec/nats_token_registry.vsm rotation_postmortem_2026_08_03.)"
pct exec 104 -- sed -i "s/$OLD/$NEW/g" /etc/vsf/nats-creds.env 2>/dev/null || true
pct exec 107 -- sed -i "s/$OLD/$NEW/g" /etc/vsf/nats-creds.env 2>/dev/null || true
pct exec 107 -- systemctl restart vsf-s3-star.service   # re-restart: the earlier restart above may have used the stale EnvironmentFile value

echo "  -- n02 host (service_watchdog cron) --"
sed -i "s/$OLD/$NEW/g" /etc/cron.d/vsf-watchdog

echo "=== [3/4] Stopped LXCs (112, 113): update configs, no restart needed ==="
pct mount 112 >/dev/null
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/112/rootfs/etc/systemd/system/vsf-clima-l0.service.d/nats-url.conf
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/112/rootfs/etc/systemd/system/vsf-clima-l1@.service.d/nats-url.conf
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/112/rootfs/etc/systemd/system/vsf-clima-l2@.service.d/nats-url.conf
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/112/rootfs/etc/systemd/system/vsf-clima-l3@.service.d/nats-url.conf
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/112/rootfs/etc/default/vsf-clima
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/112/rootfs/etc/vsf/nats-creds.env 2>/dev/null || true
pct unmount 112

pct mount 113 >/dev/null
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/113/rootfs/etc/systemd/system/s1-econ-kernel.service
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/113/rootfs/etc/vsf/nats.token 2>/dev/null || true
sed -i "s/$OLD/$NEW/g" /var/lib/lxc/113/rootfs/opt/s1-econ/s1_econ_kernel.py 2>/dev/null || true
rm -f /var/lib/lxc/113/rootfs/opt/s1-econ/__pycache__/*.pyc
pct unmount 113

echo "=== [3b/4] Sanity: any remaining OLD token anywhere on 112/113's disk? ==="
pct mount 112 >/dev/null; grep -rl "$OLD" /var/lib/lxc/112/rootfs/ 2>/dev/null && echo "  !! FOUND LEFTOVER on 112, see above" || echo "  112 clean"; pct unmount 112
pct mount 113 >/dev/null; grep -rl "$OLD" /var/lib/lxc/113/rootfs/ 2>/dev/null && echo "  !! FOUND LEFTOVER on 113, see above" || echo "  113 clean"; pct unmount 113

echo "=== [4/4] Verification ==="
sleep 3
echo "  service_watchdog deep NATS probe (with new token):"
VSF_NATS_TOKEN="$NEW" python3 -c "
import sys; sys.path.insert(0,'/root/vsf-scripts')
import service_watchdog as sw
print('  check_nats:', sw.check_nats())
print('  check_nats_deep:', sw.check_nats_deep())
"
echo "  vsf-s4-clima-bridge NRestarts (should be unchanged, not climbing):"
pct exec 101 -- systemctl show vsf-s4-clima-bridge -p NRestarts,ActiveState
echo "  vsf-s3-star recent log (should show reconnect if it restarted):"
pct exec 107 -- journalctl -u vsf-s3-star --no-pager -n 5

echo "=== DONE. Old token is now REJECTED everywhere it was updated. ==="
echo "Remaining manual step: redact the OLD token from repo source (s1_econ_kernel.py"
echo "fallback default, state.json, TASKS.vsm) -- NOT done by this script, see"
echo "docs/spec/nats_token_registry.vsm repo_source_code_needs_redaction_not_just_rotation."
