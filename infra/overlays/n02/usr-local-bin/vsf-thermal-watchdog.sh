#!/bin/bash
# vsf-thermal-watchdog.sh — n02 thermal monitoring
# Task: THERMAL-WATCHDOG-MISSING (2026-08-02, implemented 2026-10-12)
# Spec: system/s3-control/thermal-gov-01/amendment_2026-08-02.vsm
#
# Reads coretemp (hwmon5), logs to /var/log/vsf-thermal.log,
# writes algedonic alert if temp exceeds threshold.
#
# Thresholds:
#   WARN:  75°C  (log warning)
#   CRIT:  85°C  (algedonic alert + log critical)
#   EMERG: 95°C  (algedonic alert + emergency log)

set -euo pipefail

# ── Config ──
HWMON_DIR="/sys/class/hwmon/hwmon5"
LOG_FILE="/var/log/vsf-thermal.log"
ALGEDONIC_DB="/root/algedonic/ledger.db"
WARN_C=75
CRIT_C=85
EMERG_C=95
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ── Read temps ──
read_temp() {
    local label=$1
    local input=$2
    if [[ -f "$input" ]]; then
        local millideg
        millideg=$(cat "$input" 2>/dev/null || echo 0)
        echo $((millideg / 1000))
    else
        echo -1
    fi
}

package_c=$(read_temp "Package" "$HWMON_DIR/temp1_input")
core0_c=$(read_temp "Core0" "$HWMON_DIR/temp2_input")
core1_c=$(read_temp "Core1" "$HWMON_DIR/temp3_input")

# ── Determine max ──
max_c=$package_c
[[ $core0_c -gt $max_c ]] && max_c=$core0_c
[[ $core1_c -gt $max_c ]] && max_c=$core1_c

# ── Log entry ──
log_entry() {
    local level=$1
    local msg=$2
    echo "[$TIMESTAMP] [$level] $msg" >> "$LOG_FILE"
}

# ── Algedonic alert ──
algedonic_alert() {
    local severity=$1
    local temp=$2
    local msg="thermal-watchdog: ${temp}C on n02 (threshold: ${severity})"
    
    # Write to algedonic DB if exists
    if [[ -f "$ALGEDONIC_DB" ]]; then
        sqlite3 "$ALGEDONIC_DB" \
            "INSERT INTO alerts (ts, severity, source, message) VALUES ('$TIMESTAMP', '$severity', 'thermal-watchdog', '$msg');" \
            2>/dev/null || true
    fi
    
    # Also log to syslog
    logger -p "daemon.${severity,,}" -t "vsf-thermal" "$msg"
}

# ── Evaluate ──
if [[ $max_c -ge $EMERG_C ]]; then
    log_entry "EMERG" "Package=${package_c}C Core0=${core0_c} Core1=${core1_c} MAX=${max_c}C (EMERG=${EMERG_C}C)"
    algedonic_alert "EMERG" "$max_c"
elif [[ $max_c -ge $CRIT_C ]]; then
    log_entry "CRIT" "Package=${package_c}C Core0=${core0_c} Core1=${core1_c} MAX=${max_c}C (CRIT=${CRIT_C}C)"
    algedonic_alert "CRIT" "$max_c"
elif [[ $max_c -ge $WARN_C ]]; then
    log_entry "WARN" "Package=${package_c}C Core0=${core0_c} Core1=${core1_c} MAX=${max_c}C (WARN=${WARN_C}C)"
else
    log_entry "OK" "Package=${package_c}C Core0=${core0_c} Core1=${core1_c} MAX=${max_c}C"
fi
