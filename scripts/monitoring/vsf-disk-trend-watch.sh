#!/bin/bash
# vsf-disk-trend-watch.sh — Disk space + SMART trend monitor
# design: docs/spec_revision/design-sources/monitoring_runners.vsm
# route: monitoring_runners.vsm §flota/§helpers — registro canonico de la familia monitoring (T7-F2; entry_point = unit systemd o invocacion manual)
# verify: DORMANT (units sin instalar) — smoke T4-F2 solo al instalarse; sin test unitario (deuda T7)
# Part of DISK-SMART-AND-SPACE-TREND-WATCH task
# Alerts via algedonic when thresholds breached
#
# Thresholds:
#   - Disk usage > 85%: WARNING
#   - Disk usage > 95%: CRITICAL
#   - Reallocated sectors increase: WARNING
#   - SMART FAILED: CRITICAL

set -euo pipefail

# Config
DISK="${1:-/dev/mapper/pve-root}"
THRESHOLD_WARN=85
THRESHOLD_CRIT=95
STATE_FILE="/var/lib/vsf-disk-trend/state.json"
ALGEDONIC_DB="/root/algedonic/ledger.db"

# Ensure state dir exists
mkdir -p "$(dirname "$STATE_FILE")"

# Get current disk usage
DISK_USAGE=$(df "$DISK" | tail -1 | awk '{print $5}' | tr -d '%')
DISK_FREE=$(df -h "$DISK" | tail -1 | awk '{print $4}')

# Get SMART data
SMART_REALLOC=$(smartctl -A "$DISK" 2>/dev/null | grep Reallocated_Sector_Ct | awk '{print $NF}' || echo "0")
SMART_PENDING=$(smartctl -A "$DISK" 2>/dev/null | grep Current_Pending_Sector | awk '{print $NF}' || echo "0")
SMART_RESULT=$(smartctl -H "$DISK" 2>/dev/null | grep -i "result" | awk '{print $NF}' || echo "UNKNOWN")

# Load previous state
if [ -f "$STATE_FILE" ]; then
    PREV_REALLOC=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('reallocated', 0))" 2>/dev/null || echo "0")
    PREV_USAGE=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('usage', 0))" 2>/dev/null || echo "0")
else
    PREV_REALLOC=0
    PREV_USAGE=0
fi

# Save current state
cat > "$STATE_FILE" <<EOF
{
  "ts": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "usage": $DISK_USAGE,
  "free": "$DISK_FREE",
  "reallocated": $SMART_REALLOC,
  "pending": $SMART_PENDING,
  "smart_result": "$SMART_RESULT"
}
EOF

# Alert logic
ALERT_LEVEL="ok"
ALERT_MSG=""

# SMART FAILED
if [ "$SMART_RESULT" = "FAILED" ]; then
    ALERT_LEVEL="critical"
    ALERT_MSG="SMART FAILED on $DISK"
fi

# Disk usage critical
if [ "$DISK_USAGE" -ge "$THRESHOLD_CRIT" ]; then
    ALERT_LEVEL="critical"
    ALERT_MSG="Disk usage ${DISK_USAGE}% >= ${THRESHOLD_CRIT}% on $DISK"
fi

# Disk usage warning
if [ "$DISK_USAGE" -ge "$THRESHOLD_WARN" ] && [ "$ALERT_LEVEL" != "critical" ]; then
    ALERT_LEVEL="warning"
    ALERT_MSG="Disk usage ${DISK_USAGE}% >= ${THRESHOLD_WARN}% on $DISK"
fi

# Reallocated sectors increased
if [ "$SMART_REALLOC" -gt "$PREV_REALLOC" ]; then
    ALERT_LEVEL="warning"
    ALERT_MSG="Reallocated sectors increased: ${PREV_REALLOC} -> ${SMART_REALLOC} on $DISK"
fi

# Pending sectors
if [ "$SMART_PENDING" -gt 0 ]; then
    ALERT_LEVEL="warning"
    ALERT_MSG="Pending sectors: ${SMART_PENDING} on $DISK"
fi

# Emit algedonic alert if needed
if [ "$ALERT_LEVEL" != "ok" ]; then
    SEVERITY="5.0"
    if [ "$ALERT_LEVEL" = "critical" ]; then
        SEVERITY="8.0"
    fi
    
    # Insert into algedonic ledger
    if [ -f "$ALGEDONIC_DB" ]; then
        sqlite3 "$ALGEDONIC_DB" <<EOF
INSERT INTO algedonic_ledger (ts, source, type, severity, payload, status)
VALUES (
  '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
  'vsf-disk-trend-watch',
  'disk_trend',
  $SEVERITY,
  '{"alert_level": "$ALERT_LEVEL", "message": "$ALERT_MSG", "usage": $DISK_USAGE, "free": "$DISK_FREE", "reallocated": $SMART_REALLOC, "pending": $SMART_PENDING}',
  'pending_human'
);
EOF
    fi
    
    echo "[disk-trend-watch] $ALERT_LEVEL: $ALERT_MSG"
else
    echo "[disk-trend-watch] OK: usage=${DISK_USAGE}% free=${DISK_FREE} realloc=${SMART_REALLOC} pending=${SMART_PENDING}"
fi
