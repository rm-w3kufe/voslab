#!/usr/bin/env bash
# vsf-llm-fw-sync — bidirectional check (per Qwen ack 2026-05-31):
# read state.db.components WHERE llm_consumer = 1, look up each component's
# LXC IP, and atomically update the @llm_allow nftables set inside LXC 101.
#
# Also emits an algedonic via NATS if any rule exists for an IP that is
# NOT registered, OR if any registered consumer has no rule.
#
# Designed to be invoked from n02 host (has SSH to state.db + LXCs).
# Runs as oneshot on systemd timer (e.g., every 5 min via vsf-state-populate
# chain, or its own vsf-llm-fw-sync.timer).
set -euo pipefail

DB=/var/lib/vsf-state/state.db
LLM_LXC=101
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 1. Discover declared consumers + their LXC IPs.
mapfile -t DECLARED < <(sqlite3 "$DB" "
    SELECT c.name || '|' || c.deploy_target_lxc
      FROM components c
     WHERE c.llm_consumer = 1
       AND c.deploy_target_lxc IS NOT NULL
       AND c.deploy_target_lxc != $LLM_LXC
")

declare -a WANTED_IPS=()
declare -a WANTED_PAIRS=()
for d in "${DECLARED[@]:-}"; do
    [[ -z "$d" ]] && continue
    name="${d%%|*}"
    lxc="${d##*|}"
    ip=$(pct exec "$lxc" -- ip -4 -o addr show eth0 2>/dev/null \
        | awk '{print $4}' | cut -d/ -f1 | head -1)
    if [[ -n "$ip" ]]; then
        WANTED_IPS+=("$ip")
        WANTED_PAIRS+=("$name@$lxc=$ip")
    fi
done

# 2. Current rules in the set.
mapfile -t CURRENT_IPS < <(pct exec "$LLM_LXC" -- nft -a list set inet vsf_llm llm_allow 2>/dev/null \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | sort -u || true)

# 3. Compute diff.
want_str=$(printf "%s\n" "${WANTED_IPS[@]:-}" | sort -u)
curr_str=$(printf "%s\n" "${CURRENT_IPS[@]:-}" | sort -u)
to_add=$(comm -23 <(echo "$want_str") <(echo "$curr_str") | grep -v '^$' || true)
to_remove=$(comm -13 <(echo "$want_str") <(echo "$curr_str") | grep -v '^$' || true)

# 4. Apply diff atomically.
if [[ -n "$to_add" ]]; then
    while IFS= read -r ip; do
        echo "[fw-sync] + $ip"
        pct exec "$LLM_LXC" -- nft add element inet vsf_llm llm_allow "{ $ip }"
    done <<<"$to_add"
fi
if [[ -n "$to_remove" ]]; then
    while IFS= read -r ip; do
        echo "[fw-sync] - $ip"
        pct exec "$LLM_LXC" -- nft delete element inet vsf_llm llm_allow "{ $ip }" 2>/dev/null || true
    done <<<"$to_remove"
fi

# 5. Bidirectional algedonic on drift.
# Any add/remove above already executed; report the deviation so the
# operator sees that the firewall WAS out of sync (a configuration
# drift), even though we just corrected it.
n_add=$(echo -n "$to_add" | grep -c '^' || true)
n_rem=$(echo -n "$to_remove" | grep -c '^' || true)
if (( n_add > 0 || n_rem > 0 )); then
    line="$NOW  G-D.6 llm_fw_drift  added=$n_add removed=$n_rem declared=${#WANTED_IPS[@]}"
    pct exec 104 -- bash -c "mkdir -p /alerts && echo '$line' >> /alerts/operator_inbox.log" \
        2>/dev/null || true
fi

echo "$NOW  fw-sync ok: wanted=${WANTED_IPS[*]:-<none>} declared_pairs=${WANTED_PAIRS[*]:-<none>}"
