#!/usr/bin/env bash
# vsf-storage-probe — check LVM thin-pool data_percent across all volumes.
#
# Lives on n02 at /usr/local/bin/vsf-storage-probe.sh. Run by root via
# vsf-storage-probe.timer (every 5 min).
#
# Reads `lvs -o lv_name,data_percent,pool_lv` for every logical volume in
# the VG. If any volume exceeds ALERT_THRESHOLD_PCT, publishes an algedonic
# via NATS (same python3 pattern as vsf-state-populate).
#
# ALERT_THRESHOLD_PCT: percentage at which an LV triggers a warning.
# CRIT_THRESHOLD_PCT:  percentage at which an LV triggers a critical alert.
#
# The incident on 2026-07-26 (vm-101-disk-0 at 97.78%, vm-112-disk-0 at
# 95.36%) was NOT caught by any automated detector. This probe closes that
# gap. See TASKS.vsm(ALGEDONIC-STORAGE-BLINDSPOT).

set -euo pipefail

LOCK=/var/lock/vsf-storage-probe.lock
exec 200>"$LOCK"
flock -n 200 || { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)  storage-probe already running, skipping"; exit 0; }

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DB=/var/lib/vsf-state/state.db

ALERT_THRESHOLD_PCT=85
CRIT_THRESHOLD_PCT=95

# ── NATS publisher ─────────────────────────────────────────────────────
publish_nats() {
    local subject="$1" payload="$2"
    [[ -r /etc/vsf/nats-creds.env ]] && . /etc/vsf/nats-creds.env
    if [[ -z "${NATS_TOKEN:-}" ]]; then
        echo "  ! storage-probe: NATS_TOKEN unset (/etc/vsf/nats-creds.env)" >&2
        return 1
    fi
    python3 - "$NATS_TOKEN" "$payload" "$subject" <<'PYEOF' 2>/dev/null || return 1
import socket, sys
token, payload, subject = sys.argv[1], sys.argv[2].encode(), sys.argv[3].encode()
s = socket.create_connection(("10.10.20.20", 4222), timeout=5); s.settimeout(5)
s.recv(4096)
s.sendall(b'CONNECT {"verbose":false,"auth_token":"' + token.encode() + b'"}\r\n')
s.sendall(b"PUB " + subject + b" " + str(len(payload)).encode() + b"\r\n" + payload + b"\r\n")
s.sendall(b"PING\r\n")
r = s.recv(4096)
s.close()
if b"-ERR" in r:
    sys.stderr.write("  ! NATS refused: %s\n" % r[:120].decode(errors="replace"))
    sys.exit(1)
PYEOF
}

# ── Scan LVM volumes ───────────────────────────────────────────────────
# Read all volumes in the VG, their data_percent, and pool membership.
# Skip non-thin volumes (root, swap) and the pool metadata volume itself.
ALERT_COUNT=0
CRIT_COUNT=0
FIRED=0

# ── Guest df override (S5 2026-10-08 'si, se apruebs') ──────────────────────
# LVM data_percent on thin volumes counts deleted-but-untrimmed blocks:
# vm-116-disk-0 reported 99.63% LVM while its root fs sat at 61% and the
# pool at 34.6% (false sev=10, 2026-10-08; guest fstrim is blocked without
# CAP). For a RUNNING container's ROOT volume (vm-<id>-disk-0) read the
# guest's real Use% instead. Stopped guests and extra disks (disk-1+) keep
# the LVM figure as a conservative upper bound (discard-cap = follow-up).
# Prints the effective %, or nothing when the LVM figure must be used.
eff_pct() {
    local lv="$1" lvm_pct="$2" vmid use
    pct_int=${lvm_pct%.*}
    # lvs pads field names ('  vm-116-disk-0') — trim ONLY for the match;
    # the lv travels unpadded-unchanged into payload/fingerprint so open
    # ledger rows keep their dedup identity.
    local lvc="${lv//[[:space:]]/}"
    if [[ "$lvc" =~ ^vm-([0-9]+)-disk-0$ ]]; then
        vmid="${BASH_REMATCH[1]}"
        # timeout on both calls (q13 pattern): a stuck lxc-attach must
        # degrade to the LVM figure, never hold the probe past its cadence
        if timeout 8 pct status "$vmid" 2>/dev/null | grep -q "status: running"; then
            use=$(timeout 8 pct exec "$vmid" -- df -P / 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}' || true)
            if [[ "$use" =~ ^[0-9]+$ ]]; then
                echo "$use"; return 0
            fi
        fi
    fi
    echo "$pct_int"
}

emit_if_threshold() {
    local lv="$1" pct="$2" pool="$3" severity="$4" category="$5" fs="${6:-}"
    local extra=""
    [[ -n "$fs" ]] && extra=",\"fs_percent\":${fs},\"measured\":\"df\""
    local detail
    detail=$(printf '{"lv":"%s","data_percent":%s,"pool":"%s"%s}' "$lv" "$pct" "$pool" "$extra")
    local subject="vsf.alpha.algedonic.${category}"
    local payload
    payload=$(printf '{"ts":"%s","source_id":"vsf-storage-probe","category":"%s","severity":%s,"signal":1,"lv":"%s","data_percent":%s,"pool":"%s"%s,"detail":%s}' \
        "$NOW" "$category" "$severity" "$lv" "$pct" "$pool" "$extra" "$detail")
    # Also write to the host-local alert log (independent of LXC health)
    echo "$NOW  $category  lv=$lv  data_percent=$pct%  pool=$pool" >> /var/log/vsf-storage-alerts.log 2>/dev/null || true
    if publish_nats "$subject" "$payload"; then
        echo "  ! $category: lv=$lv data_percent=$pct% pool=$pool (alert sent via NATS)"
    else
        echo "  ! $category: lv=$lv data_percent=$pct% pool=$pool (NATS failed — logged only)"
    fi
    FIRED=1
}

while IFS='|' read -r lv pct pool; do
    # Skip non-thin volumes (root, swap) — they have no data_percent or pool
    [[ -z "$pct" || "$pct" == "null" || -z "$pool" ]] && continue
    # Skip the pool metadata volume itself (the 'data' LV in the pool)
    [[ "$pool" == "$lv" ]] && continue

    # effective % = guest df for running root volumes, LVM otherwise
    eff=$(eff_pct "$lv" "$pct")
    fs_arg=""
    if [[ "$eff" != "${pct%.*}" && "$eff" =~ ^[0-9]+$ ]]; then
        fs_arg="$eff"   # guest df in play → carry it in the payload
    fi

    if [[ "$eff" -ge "$CRIT_THRESHOLD_PCT" ]]; then
        emit_if_threshold "$lv" "$pct" "$pool" 10.0 "lvm_data_percent_critical" "$fs_arg"
        CRIT_COUNT=$((CRIT_COUNT + 1))
    elif [[ "$eff" -ge "$ALERT_THRESHOLD_PCT" ]]; then
        emit_if_threshold "$lv" "$pct" "$pool" 7.0 "lvm_data_percent_warning" "$fs_arg"
        ALERT_COUNT=$((ALERT_COUNT + 1))
    fi
done < <(lvs --units g --noheadings --separator '|' -o lv_name,data_percent,pool_lv 2>/dev/null || true)

# ── Emit cycle_manifest (so the ledger can auto-close if conditions clear) ──
EVALUATED_COUNT=$(lvs --noheadings -o lv_name 2>/dev/null | grep -c . || echo 0)
# Build condition_set from all volumes above warning threshold
CONDITION_SET="["
SEP=""
while IFS='|' read -r lv pct pool; do
    [[ -z "$pct" || "$pct" == "null" || -z "$pool" ]] && continue
    [[ "$pool" == "$lv" ]] && continue
    pct_int=${pct%.*}
    eff=$(eff_pct "$lv" "$pct")   # same guest-df override as the alert loop
    if [[ "$eff" -ge "$ALERT_THRESHOLD_PCT" ]]; then
        # Fingerprint = sha256("lvm_data_percent_<alert-level>|<lv>")
        if [[ "$eff" -ge "$CRIT_THRESHOLD_PCT" ]]; then
            FP_RAW="lvm_data_percent_critical|${lv}"
            CAT="lvm_data_percent_critical"
        else
            FP_RAW="lvm_data_percent_warning|${lv}"
            CAT="lvm_data_percent_warning"
        fi
        FP=$(printf "%s" "$FP_RAW" | sha256sum | cut -d' ' -f1)
        CONDITION_SET+="${SEP}\"${FP}\""
        SEP=","
    fi
done < <(lvs --units g --noheadings --separator '|' -o lv_name,data_percent,pool_lv 2>/dev/null || true)
CONDITION_SET+="]"
MANIFEST_PAYLOAD=$(printf '{"ts":"%s","emitter":"vsf-storage-probe","evaluated_count":%s,"condition_set":%s}' \
    "$NOW" "$EVALUATED_COUNT" "$CONDITION_SET")
publish_nats "vsf.alpha.algedonic.cycle_manifest" "$MANIFEST_PAYLOAD" || true
echo "  storage-probe manifest: evaluated_count=$EVALUATED_COUNT"

# ── Write state to state.db for dashboard visibility ───────────────────
sqlite3 -cmd ".timeout 10000" "$DB" "
DELETE FROM storage_probe_state;" 2>/dev/null || true
while IFS='|' read -r lv pct pool; do
    [[ -z "$pct" || "$pct" == "null" ]] && continue
    # effective % (guest df for running root volumes) so the dashboard
    # shows the figure the alerting logic actually trusts
    eff=$(eff_pct "$lv" "$pct")
    sqlite3 -cmd ".timeout 10000" "$DB" "
    INSERT INTO storage_probe_state (lv_name, data_percent, pool_lv, refreshed_at)
    VALUES ('${lv//\'/\'\'}', ${eff}, '${pool//\'/\'\'}', '$NOW');" 2>/dev/null || true
done < <(lvs --units g --noheadings --separator '|' -o lv_name,data_percent,pool_lv 2>/dev/null || true)

echo "$NOW  storage-probe ok  alerts=$ALERT_COUNT  crit=$CRIT_COUNT"
