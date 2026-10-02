#!/bin/bash
# s5_stress.sh — M3: emit/clear S5 stress signal to VSF via NATS
# Usage (from WSL):
#   scripts/s5_stress.sh activate [reason]   — enter S5 caution mode (blocks all auto-reverts)
#   scripts/s5_stress.sh clear [reason]      — clear S5 caution mode
#   scripts/s5_stress.sh status              — print current caution_mode.json from LXC 104
# Publishes via: LXC 101 s5_stress_publish.py → NATS vsf.alpha.algedonic → LXC 104 subscriber

ACTION="${1:-activate}"
REASON="${2:-manual signal from rmw3(S5)}"

if [ "$ACTION" = "status" ]; then
    echo "=== S5 caution mode status (LXC 104) ==="
    ssh root@n02 "pct exec 104 -- cat /root/algedonic/caution_mode.json 2>/dev/null" | python3 -c "
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
ssh root@n02 "pct exec 101 -- python3 /root/vsf-scripts/s5_stress_publish.py '$ACTION' '$REASON'"
