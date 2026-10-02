#!/bin/bash
# s5_stress.sh — M3: emit/clear S5 stress signal to VSF via NATS
# Usage (from WSL):
#   scripts/s5_stress.sh activate [reason]   — enter S5 caution mode (blocks all auto-reverts)
#   scripts/s5_stress.sh clear [reason]      — clear S5 caution mode
#   scripts/s5_stress.sh status              — print current caution_mode.json from LXC 104
# Publishes via: LXC 101 s5_stress_publish.py → NATS vsf.alpha.algedonic → LXC 104 subscriber

ACTION="${1:-activate}"
REASON="${2:-manual signal from rmw3(S5)}"

# D-05: LXC container ids from the single source of truth
# (system/instance/lxc_topology.json); fail loud on missing config.
TOPO_JSON="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)/system/instance/lxc_topology.json"
topo_anchor() {
    python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['anchors'][sys.argv[2]])" "$TOPO_JSON" "$1" || {
        echo "FATAL: cannot read LXC topology anchor '$1' from $TOPO_JSON" >&2; exit 1; }
}
POLICY_LXC="$(topo_anchor algedonic)" || exit 1
NUCLEUS_LXC="$(topo_anchor nucleus)" || exit 1

if [ "$ACTION" = "status" ]; then
    echo "=== S5 caution mode status (LXC $POLICY_LXC) ==="
    ssh root@n02 "pct exec $POLICY_LXC -- cat /root/algedonic/caution_mode.json 2>/dev/null" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"  active:   {d.get('active')}\")
print(f\"  category: {d.get('trigger_category')}\")
print(f\"  sev:      {d.get('trigger_sev')}\")
print(f\"  entered:  {d.get('entered_at_iso')}\")
print(f\"  expires:  {d.get('expires_at_iso')}\")
"
    exit 0
fi

if [ "$ACTION" != "activate" ] && [ "$ACTION" != "clear" ]; then
    echo "Usage: $0 [activate|clear|status] [reason]"
    exit 1
fi

echo "→ publishing s5_stress to vsf.alpha.algedonic  action=$ACTION"
ssh root@n02 "pct exec $NUCLEUS_LXC -- python3 /root/vsf-scripts/s5_stress_publish.py '$ACTION' '$REASON'"
