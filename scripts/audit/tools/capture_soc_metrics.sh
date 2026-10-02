#!/usr/bin/env bash
# ============================================================================
# SOC Stage A — phase 1 — continuous resource metrics capture (AC3 study feed)
# v1.1  (2026-08-02) — robust: /proc/stat CPU, deterministic service states,
#                       retried indexer health poll.
# Via cron every 5 min; appends one JSON line per run.
# One script per container (115 indexer / 116 server / 117 dashboard).
# Output: /var/lib/soc-metrics/<role>.jsonl
# ============================================================================
set -u

ROLE="${1:-unknown}"
OUT="/var/lib/soc-metrics/${ROLE}.jsonl"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- memory ---
read -r mem_total mem_used mem_avail <<< "$(free -m | awk 'NR==2 {print $2,$3,$7}')"
swap_used="$(free -m | awk 'NR==3 {print $3}')"

# --- load ---
load1="$(awk '{print $1}' /proc/loadavg)"

# --- CPU from /proc/stat (deterministic; top parse is brittle) ---
read -r cpu_user cpu_sys cpu_iowait <<< "$(
  head -1 /proc/stat | awk '{
    idle=$5+$6; total=$2+$3+$4+$5+$6+$7+$8;
    u=($2+$3)*100/total; sy=$4*100/total; io=$6*100/total;
    printf "%.1f %.1f %.1f", u, sy, io }'
)"

# --- java/node RSS (first matching proc) ---
proc_rss_mb=0
proc_pid="$(pgrep -f 'opensearch|elasticsearch|wazuh-dashboard|node' | head -1)"
if [ -n "${proc_pid}" ]; then
  proc_rss_mb="$(( $(awk '/VmRSS/ {print $2}' /proc/${proc_pid}/status 2>/dev/null || echo 0) / 1024 ))"
fi

# --- disk ---
read -r disk_used_pct disk_used_gb disk_free_gb <<< "$(df -BG / | awk 'NR==2 {gsub(/%/,"",$5); gsub(/G/,"",$3); gsub(/G/,"",$4); print $5, $3, $4}')"

# --- service states (one line each; uninstalled = "inactive") ---
svc_states="{"
for svc in wazuh-indexer wazuh-manager filebeat wazuh-dashboard; do
  st="$(systemctl is-active ${svc} 2>/dev/null | tr -d '\n')"
  [ -z "${st}" ] && st="inactive"
  svc_states="${svc_states}\"${svc}\":\"${st}\","
done
svc_states="${svc_states%,}}"

# --- per-role extras ---
extras="{}"
if [ "${ROLE}" = "indexer" ]; then
  if [ -r /etc/soc-metrics/indexer-admin.env ]; then
    . /etc/soc-metrics/indexer-admin.env 2>/dev/null
    if [ -n "${ADMIN_PW:-}" ]; then
      cluster_status="na"; active_shards="0"; unassigned="0"; nodes="0"; heap_used="0"
      # retry poll (indexer is slow under shared-host IO)
      for i in 1 2 3; do
        health="$(curl -sk -m 15 -u "admin:${ADMIN_PW}" "https://10.10.50.115:9200/_cluster/health" 2>/dev/null || true)"
        [ -n "${health}" ] && break
        sleep 5
      done
      [ -n "${health}" ] && {
        read -r cluster_status active_shards unassigned nodes <<< "$(
          echo "${health}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','na'), d.get('active_shards',0), d.get('unassigned_shards',0), d.get('number_of_nodes',0))"
        )"
        heap_used="$(curl -sk -m 15 -u "admin:${ADMIN_PW}" "https://10.10.50.115:9200/_cat/nodes?h=heap.percent" 2>/dev/null | tr -d '[:space:]' || echo 0)"
        [ -z "${heap_used}" ] && heap_used="0"
      }
      [ -z "${cluster_status:-}" ] && cluster_status="na"
      extras="{\"cluster_status\":\"${cluster_status}\",\"active_shards\":${active_shards:-0},\"unassigned_shards\":${unassigned:-0},\"nodes\":${nodes:-0},\"heap_used_pct\":${heap_used%%\.*}}"
    fi
  fi
fi

jline="{\"ts\":\"${TS}\",\"role\":\"${ROLE}\",\"mem_total_mb\":${mem_total},\"mem_used_mb\":${mem_used},\"mem_avail_mb\":${mem_avail},\"swap_used_mb\":${swap_used},\"load1\":${load1},\"cpu_user\":${cpu_user},\"cpu_sys\":${cpu_sys},\"cpu_iowait\":${cpu_iowait},\"proc_rss_mb\":${proc_rss_mb},\"disk_used_pct\":${disk_used_pct},\"disk_used_gb\":${disk_used_gb},\"disk_free_gb\":${disk_free_gb},\"services\":${svc_states},\"extras\":${extras}}"

mkdir -p /var/lib/soc-metrics
echo "${jline}" >> "${OUT}"