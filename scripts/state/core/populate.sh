#!/usr/bin/env bash
# populate.sh — refresh the live tables in vsf-state.db from Proxmox state.
#
# Lives on n02 at /usr/local/bin/vsf-state-populate. Run by root.
#
# Refreshes ONLY the tables that describe what's running NOW:
#   - services (PIDs, shas, active flags)
#   - chain_state (line counts, head hashes)
#
# Does NOT touch: lxcs, components, specs (canonical, edit by hand
# via the schema+seed). Does NOT touch tasks (agent owns those).
# (The `rules` table no longer exists — dropped 2026-08-12,
# R7-RULES-TABLE-CLEANUP-2026-08-11; rules are declared in
# system/boot/hard_rules.vsm, never mirrored.)
#
# Usage:
#   /usr/local/bin/vsf-state-populate                # full refresh
#   /usr/local/bin/vsf-state-populate --services     # services only
#   /usr/local/bin/vsf-state-populate --chains       # chains only

set -euo pipefail

# q11 v2: flock guard — prevent concurrent runs overlapping the timer.
LOCK=/var/lock/vsf-state-populate.lock
exec 200>"$LOCK"
flock -n 200 || { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)  populate already running, skipping"; exit 0; }

DB=/var/lib/vsf-state/state.db
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WANT_SVC=1
WANT_CHAIN=1
case "${1:-}" in
    --services) WANT_CHAIN=0 ;;
    --chains)   WANT_SVC=0 ;;
    "")         ;;
    *)          echo "usage: $0 [--services|--chains]"; exit 2 ;;
esac

# Read every (lxc, service) the components table cares about.
mapfile -t TARGETS < <(sqlite3 -cmd ".timeout 10000" "$DB" "
    SELECT deploy_target_lxc || '|' || name
      FROM components
     WHERE deploy_target_lxc IS NOT NULL")

# q13 fix 2026-08-04: cache LXC running-state once per populate cycle.
# Without this, refresh_service() calls `pct exec <lxc>` for every declared
# component, including LXCs that are STOPPED. A stopped LXC's pct exec blocks
# up to the 15s timeout per call; with 98 declared services on LXC 112 alone
# (clima, intentionally stopped behind the S1-SOC-REOPEN gate), a single
# populate run spawned 80+ hanging pct subprocesses and drove PSI io avg10
# to ~74 every 5 minutes. Cache `pct status` once, skip pct exec for stopped
# LXCs — they write a stub inactive record so the DB still reflects reality
# (service inactive because its host is down), without the IO cost.
declare -A LXC_RUNNING=()
for _t in "${TARGETS[@]}"; do
    _lxc="${_t%%|*}"
    [[ -n "${LXC_RUNNING[$_lxc]:-}" ]] && continue   # already cached
    # lxc 0 == host-pseudo-node, always "running" (special case)
    if [[ "$_lxc" == "0" ]]; then
        LXC_RUNNING[0]=1
    else
        LXC_RUNNING[$_lxc]=$(pct status "$_lxc" 2>/dev/null | awk '{print $2}')
    fi
done

refresh_service () {
    local lxc=$1 name=$2 outfile=$3
    # q13 fix 2026-08-04: skip pct exec for stopped LXCs (see LXC_RUNNING cache
    # above). Still emit a stub record so state.db reflects reality: pid=0,
    # active=0, exec_path='', binary_sha='', since=''. This eliminates the
    # 15s pct-exec-timeout storm against LXC 112 (98 services) etc.
    if [[ "${LXC_RUNNING[$lxc]:-}" != "running" ]]; then
        printf '%s|%s|%s|%s|%s|%s|%s\n' \
            "$lxc" "$name" "0" "0" "" "" "" > "$outfile" 2>/dev/null || true
        return 0
    fi
    # q11 v2: single pct exec call for is-active + timestamp + pid + sha.
    # Avoids 5 sequential pct exec calls per service (was 10s/service → 330s total).
    # Pure bash on the remote side — 3 systemctl calls LOCAL to the LXC,
    # only 1 pct exec overhead instead of 5.
    local raw since='' pid=0 sha=''
    raw=$(timeout 15 pct exec "$lxc" -- bash -c '
name="$1"
active=$(systemctl show -p ActiveState --value "$name" 2>/dev/null)
[ "$active" != "active" ] && { echo "inactive||0|"; exit 0; }
since=$(systemctl show -p ActiveEnterTimestamp --value "$name" 2>/dev/null || echo "")
pid=$(systemctl show -p ExecMainPID --value "$name" 2>/dev/null || echo "0")
sha=""
if [ -n "$pid" ] && [ "$pid" -gt 0 ] 2>/dev/null; then
  f=/proc/"$pid"/exe
  [ -r "$f" ] && sha=$(sha256sum "$f" 2>/dev/null | cut -d" " -f1 || echo "")
fi
echo "active|${since-}|$pid|$sha"
' _ "$name" 2>/dev/null || true)
    local active_str
    IFS='|' read -r active_str since pid sha <<< "$raw"
    local active=0
    [[ "$active_str" == "active" ]] && active=1
    printf '%s|%s|%s|%s|%s|%s|%s\n' \
        "$lxc" "$name" "${pid:-0}" "$active" "" "$sha" "$since" > "$outfile" 2>/dev/null || true
}

# Flush collected service records into state.db (serial writes, no contention)
_flush_services() {
    local tmpdir=$1
    for svc_file in "$tmpdir"/*.svc; do
        [[ -f "$svc_file" ]] || continue
        IFS='|' read -r lxc name pid active exe sha since < "$svc_file"
        # Sanitize for sqlite
        exe=${exe//\'/\'\'}
        sqlite3 -cmd ".timeout 10000" "$DB" "
INSERT INTO services (lxc, name, pid, active, exec_path, binary_sha, active_since, refreshed_at)
VALUES ($lxc, '$name', '$pid', $active, '$exe', '$sha', '$since', '$NOW')
ON CONFLICT(lxc, name) DO UPDATE SET
    pid          = excluded.pid,
    active       = excluded.active,
    exec_path    = excluded.exec_path,
    binary_sha   = excluded.binary_sha,
    active_since = excluded.active_since,
    refreshed_at = excluded.refreshed_at;
" 2>/dev/null || echo "  [flush] failed: lxc=$lxc name=$name"
    done
    rm -f "$tmpdir"/*.svc 2>/dev/null
}

refresh_chain () {
    local chain_id=$1 lxc=$2 path=$3
    local count='' head='' last_ts=''
    # q12: count only non-blank lines (grep -c . vs wc -l).
    # Prevents blank-line bloat from inflating chain state counters.
    # sed -i "/^$/d" can be run periodically to clean up (blank lines
    # are a nucleus writer bug producing empty lines between events).
    count=$(pct exec "$lxc" -- grep -c '.' "$path" 2>/dev/null || echo 0)
    local tail
    tail=$(pct exec "$lxc" -- tail -1 "$path" 2>/dev/null || echo '')
    if [[ -n "$tail" ]]; then
        head=$(echo "$tail" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('hash') or d.get('finding',{}).get('ts',''))" 2>/dev/null || echo '')
        last_ts=$(echo "$tail" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('ts') or d.get('finding',{}).get('ts',''))" 2>/dev/null || echo '')
    fi
    sqlite3 -cmd ".timeout 10000" "$DB" <<EOF
INSERT INTO chain_state (chain_id, lxc, file_path, line_count, head_hash, last_event_ts, refreshed_at)
VALUES ('$chain_id', $lxc, '$path', $count, '$head', '$last_ts', '$NOW')
ON CONFLICT(chain_id) DO UPDATE SET
    line_count    = excluded.line_count,
    head_hash     = excluded.head_hash,
    last_event_ts = excluded.last_event_ts,
    refreshed_at  = excluded.refreshed_at;
EOF
}

# ── services (PARALLEL: up to 10 concurrent pct exec) ───────────────────
# q11 fix 2026-07-23: parallelize pct exec calls across services.
# Each refresh_service() does 1-4 pct exec calls (systemctl + possible
# sha256sum). With 98 declared services, sequential was 8-16 min.
# Parallel batches of 10 bring it to ~1-2 min.
# DB writes are batched serially to avoid "database is locked" from
# 10 concurrent sqlite3 processes.
_run_batch_svc() {
    local -n _pids_ref=$1 _files_ref=$2
    shift 2
    for tgt in "$@"; do
        local lxc="${tgt%%|*}" name="${tgt##*|}"
        local svc_file="$SVC_TMPDIR/${lxc}_${name//\//_}.svc"
        echo "  refresh service: lxc=$lxc name=$name"
        (refresh_service "$lxc" "$name" "$svc_file") &
        _pids_ref+=($!)
        _files_ref+=("$svc_file")
    done
}
if [[ $WANT_SVC -eq 1 ]]; then
    MAX_PARALLEL=3
    SVC_TMPDIR=$(mktemp -d /tmp/vsf-populate-svc.XXXXXX)
    declare -a BATCH
    for tgt in "${TARGETS[@]}"; do
        BATCH+=("$tgt")
        if [[ ${#BATCH[@]} -ge $MAX_PARALLEL ]]; then
            BATCH_PIDS=(); BATCH_FILES=()
            _run_batch_svc BATCH_PIDS BATCH_FILES "${BATCH[@]}"
            for pid in "${BATCH_PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
            BATCH=()
        fi
    done
    # Flush remaining (non-full batch)
    if [[ ${#BATCH[@]} -gt 0 ]]; then
        BATCH_PIDS=(); BATCH_FILES=()
        _run_batch_svc BATCH_PIDS BATCH_FILES "${BATCH[@]}"
        for pid in "${BATCH_PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
    fi
    # Serial flush all collected data into state.db
    echo "  flushing service records to state.db..."
    _flush_services "$SVC_TMPDIR"
    rmdir "$SVC_TMPDIR" 2>/dev/null || true
fi

# ── chains ──────────────────────────────────────────────────────────────
if [[ $WANT_CHAIN -eq 1 ]]; then
    refresh_chain nucleus 101 /var/lib/vsf/vsf_nucleus/events.jsonl
    refresh_chain s3_star 107 /var/lib/vsf/s3_star/events.jsonl
fi


# ── emit_algedonic <category> <severity> <lxc> <component> <inbox_line> <json_detail> ─
# Dual-channel publisher: file append to /alerts/operator_inbox.log on LXC 104
# (g6 sink's monitored path) AND NATS publish on vsf.alpha.algedonic.<category>.
# Failures on either channel never abort populate.
emit_algedonic() {
    local cat=$1 sev=$2 lxc=$3 component=$4 inbox_line=$5 detail_json=$6
    pct exec 104 -- bash -c "mkdir -p /alerts && echo '$inbox_line' >> /alerts/operator_inbox.log" \
        2>/dev/null || true
    local payload
    payload=$(printf '{"ts":"%s","source_id":"vsf-state-populate","category":"%s","severity":%s,"signal":1,"lxc":%s,"component":"%s","detail":%s}' \
        "$NOW" "$cat" "$sev" "$lxc" "$component" "$detail_json")
    # C1 fix 2026-07-24 — this publish had been silently dead since 2026-07-12.
    # THREE independent breaks, each of which alone drops the signal:
    #   (a) AUTH: it sent `CONNECT {}` (anonymous). NATS token auth went live
    #       2026-07-12 and answers `-ERR 'Authorization Violation'`.
    #   (b) SILENCE: `2>/dev/null || true` swallowed the failure, so 47,858
    #       inbox lines accumulated while the ledger recorded ZERO of them.
    #       Fixing (a) without (b) would just make the NEXT break invisible too,
    #       so failures now go to stderr and land in the service journal.
    # SUBJECT — do NOT "simplify" this to a bare `vsf.alpha.algedonic`. The real
    # consumer is vsf_s5_ledger.py, which subscribes to `vsf.<id>.algedonic.>`;
    # a `>` wildcard requires at least one further token, so the bare subject
    # matches NOTHING. (The exact-subject `vsf_algedonic_subscriber.py` is dead
    # code — no unit executes it; `vsf-s5-algedonic.service` actually runs
    # vsf_s5_agent.py. Reading that file and "correcting" the subject to match
    # it broke a working publish on 2026-07-24; reverted the same session.)
    # Published straight from the host — it reaches 10.10.20.20:4222 directly,
    # so the old `pct exec 106` detour is gone.
    [[ -r /etc/vsf/nats-creds.env ]] && . /etc/vsf/nats-creds.env
    if [[ -z "${NATS_TOKEN:-}" ]]; then
        echo "  ! algedonic NOT published ($cat): NATS_TOKEN unset (/etc/vsf/nats-creds.env)" >&2
        return 0
    fi
    # Script on stdin, data via argv: no nested quoting, no interpolation.
    python3 - "$NATS_TOKEN" "$payload" "vsf.alpha.algedonic.$cat" <<'PYEOF' || echo "  ! algedonic publish FAILED ($cat)" >&2
import socket, sys
token, payload, subject = sys.argv[1], sys.argv[2].encode(), sys.argv[3].encode()
s = socket.create_connection(("10.10.20.20", 4222), timeout=5); s.settimeout(5)
s.recv(4096)                                    # INFO
s.sendall(b'CONNECT {"verbose":false,"auth_token":"' + token.encode() + b'"}\r\n')
s.sendall(b"PUB " + subject + b" " + str(len(payload)).encode() + b"\r\n" + payload + b"\r\n")
s.sendall(b"PING\r\n")                          # force a round-trip so auth errors surface
r = s.recv(4096)
s.close()
if b"-ERR" in r:
    sys.stderr.write("  ! NATS refused: %s\n" % r[:120].decode(errors="replace"))
    sys.exit(1)
PYEOF
}

# ── G-D.4 (v2 / G-D.5): script-aware sha divergence check ───────────────
# For each component with components.deploy_path set, sha256sum the
# file at that path inside its lxc and compare to the most recent
# deploys.to_sha for the component. Works uniformly for Rust binaries
# AND scripts (we are comparing artifact-content vs deployed-content,
# not /proc/<pid>/exe vs to_sha — that older check failed for scripts
# whose /proc/exe is the interpreter).
#
# On divergence: append a G-D.4 line to /alerts/operator_inbox.log on
# LXC 104 (the g6 sink's monitored inbox).
#
# q11 fix 2026-07-23: parallelize sha256sum checks (but keep algedonic
# emission serial to avoid appends racing on operator_inbox.log).
_load_sha_checks() {
    local checks=()
    while IFS='|' read -r component lxc deploy_path dep_sha dep_ts; do
        checks+=("$component|$lxc|$deploy_path|$dep_sha|$dep_ts")
    done
    echo "${checks[@]}"
}
    mapfile -t SHA_CHECKS < <(sqlite3 -cmd ".timeout 10000" "$DB" <<SQL
SELECT c.name, c.deploy_target_lxc, c.deploy_path,
       d.to_sha, d.ts
  FROM components c
  JOIN (SELECT component, target_lxc, to_sha, ts,
               ROW_NUMBER() OVER (PARTITION BY component ORDER BY ts DESC) AS rn
          FROM deploys WHERE result LIKE 'ok%') d
    ON d.component = c.name AND d.target_lxc = c.deploy_target_lxc AND d.rn = 1
 WHERE c.deploy_path IS NOT NULL;
SQL
)
_check_one_sha() {
    local entry="$1"
    IFS='|' read -r component lxc deploy_path dep_sha dep_ts <<< "$entry"
    local current_sha=''
    if [[ "$lxc" -eq 0 ]]; then
        current_sha=$(sha256sum "$deploy_path" 2>/dev/null | awk '{print $1}' || echo '')
    else
        current_sha=$(pct exec "$lxc" -- sha256sum "$deploy_path" 2>/dev/null | awk '{print $1}' || echo '')
    fi
    if [[ -z "$current_sha" ]]; then
        echo "missing|$component|$lxc|$deploy_path"
    elif [[ "$current_sha" != "$dep_sha" ]]; then
        echo "divergent|$component|$lxc|$deploy_path|$current_sha|$dep_sha|$dep_ts"
    fi
}
_run_sha_batch() {
    local results=()
    local pids=()
    for entry in "$@"; do
        (_check_one_sha "$entry") &
        pids+=($!)
    done
    for pid in "${pids[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
}
# Collect sha results (parallel batches of 10)
declare -a SHA_RESULTS
declare -a SHA_BATCH
for entry in "${SHA_CHECKS[@]}"; do
    SHA_BATCH+=("$entry")
    if [[ ${#SHA_BATCH[@]} -ge 10 ]]; then
        while IFS= read -r result; do
            [[ -n "$result" ]] && SHA_RESULTS+=("$result")
        done < <(_run_sha_batch "${SHA_BATCH[@]}")
        SHA_BATCH=()
    fi
done
[[ ${#SHA_BATCH[@]} -gt 0 ]] && while IFS= read -r result; do
    [[ -n "$result" ]] && SHA_RESULTS+=("$result")
done < <(_run_sha_batch "${SHA_BATCH[@]}")

# Emit algedonics serially (avoid racing on operator_inbox.log)
for result in "${SHA_RESULTS[@]}"; do
    IFS='|' read -r outcome component lxc deploy_path extra1 extra2 extra3 <<< "$result"
    if [[ "$outcome" == "missing" ]]; then
        detail=$(printf '{"path":"%s"}' "$deploy_path")
        emit_algedonic file_missing 8.0 "$lxc" "$component" \
            "$NOW  G-D.4 file_missing  lxc=$lxc component=$component path=$deploy_path" \
            "$detail"
        echo "  ! algedonic: $component on $lxc — deploy_path missing on disk"
    elif [[ "$outcome" == "divergent" ]]; then
        detail=$(printf '{"path":"%s","on_disk":"%s","last_deploy":"%s","deployed_at":"%s"}' \
            "$deploy_path" "${extra1:0:16}" "${extra2:0:16}" "$extra3")
        emit_algedonic sha_divergence 7.0 "$lxc" "$component" \
            "$NOW  G-D.4 sha_divergence  lxc=$lxc component=$component path=$deploy_path on_disk=${extra1:0:16} last_deploy=${extra2:0:16} deployed_at=$extra3" \
            "$detail"
        echo "  ! algedonic: $component on $lxc — on-disk sha != last deploy sha"
    fi
done

# ── q17.phase_2: emit cycle_manifest after SHA checks ──────────────────
# The manifest tells the ledger: "this cycle I evaluated N components; of
# those, only these K fingerprints are diverged." The ledger uses this to
# auto-close conditions that are absent from the manifest (proving they
# cleared — not that the emitter went silent).
# See docs/spec/condition_vs_event.spec.vsm §phase_2
EMITTER="vsf-state-populate"
EVALUATED_COUNT="${#SHA_CHECKS[@]}"
# Build condition_set: array of fingerprint strings for each divergence.
# Fingerprint = sha256("category|field1|field2|...") per compute_fingerprint().
CONDITION_SET="["
SEP=""
for result in "${SHA_RESULTS[@]}"; do
    IFS='|' read -r outcome component lxc deploy_path extra1 extra2 extra3 <<< "$result"
    if [[ "$outcome" == "divergent" ]]; then
        FP=$(printf "sha_divergence|%s|%s" "$lxc" "$component" | sha256sum | cut -d' ' -f1)
        CONDITION_SET+="${SEP}\"${FP}\""
        SEP=","
    fi
done
CONDITION_SET+="]"
MANIFEST_PAYLOAD=$(printf '{"ts":"%s","emitter":"%s","evaluated_count":%s,"condition_set":%s}' \
    "$NOW" "$EMITTER" "$EVALUATED_COUNT" "$CONDITION_SET")
# Publish via NATS using the same method as emit_algedonic
[[ -r /etc/vsf/nats-creds.env ]] && . /etc/vsf/nats-creds.env
if [[ -n "${NATS_TOKEN:-}" ]]; then
    python3 - "$NATS_TOKEN" "$MANIFEST_PAYLOAD" "vsf.alpha.algedonic.cycle_manifest" <<'PYEOF' || echo "  ! manifest publish FAILED" >&2
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
# Count condition_set entries (JSON array length)
CS_SIZE=$(echo "$CONDITION_SET" | python3 -c 'import json,sys; print(len(json.loads(sys.stdin.read())))' 2>/dev/null || echo 0)
echo "  manifest: evaluated_count=$EVALUATED_COUNT condition_set_size=$CS_SIZE"
else
    echo "  ! manifest NOT published: NATS_TOKEN unset (/etc/vsf/nats-creds.env)" >&2
fi

# ── push_services_mirror: write services_mirror.json to LXC 104 ─────────
# TRIAGE-EVIDENCE-RULE: the agent on LXC 104 needs restart evidence.
# This mirror gives it (name, active_since, active, lxc) per declared component.
# q11 fix 2026-07-23: reads from state.db (main loop already wrote to it)
# instead of re-scanning every service via pct exec. Eliminates ~98 pct exec calls.
push_services_mirror() {
    local json_out=$(mktemp /tmp/services_mirror.XXXXXX.json)
    echo "  [push_services_mirror] json=$json_out"
    python3 -c "
import json, sqlite3, sys
db = sqlite3.connect('/var/lib/vsf-state/state.db')
rows = db.execute('SELECT lxc, name, active, active_since FROM services').fetchall()
mirror = {}
for lxc, name, active, active_since in rows:
    mirror[name] = {'active': active, 'active_since': active_since or '', 'lxc': lxc}
with open('$json_out', 'w') as f:
    json.dump(mirror, f)
print('mirror keys:', list(mirror.keys()))
" 2>&1 || echo "  [push_services_mirror] python error (continuing)"
    if [[ -s "$json_out" ]]; then
        echo "  [push_services_mirror] json_out size=$(stat -c%s "$json_out")"
        pct push 104 "$json_out" /root/algedonic/services_mirror.json 2>&1 || echo "  [push_services_mirror] pct push failed"
        echo "  services_mirror pushed to LXC 104"
    else
        echo "  [push_services_mirror] json_out empty or missing"
    fi
    rm -f "$json_out"
}

# Run services_mirror push after services refresh
push_services_mirror

# ── D.4 R1: sync filesystem-sourced metadata into state.db ────────────
# Single source of truth principle: the dashboard queries state.db ONLY
# (never the operator inbox file directly). Best-effort; failures here
# never abort the run.
sync_alert_counts () {
    local inbox=/alerts/operator_inbox.log
    if ! pct exec 104 -- test -r "$inbox" 2>/dev/null; then
        echo "  alert_counts: inbox not readable; skip"
        return 0
    fi
    # (category, count, last_ts) in one awk pass on LXC 104.
    local rows
    rows=$(pct exec 104 -- awk '
        match($0, /cat=[^ ]+/) {
            cat = substr($0, RSTART+4, RLENGTH-4);
            n[cat]++;
            if ($1 > t[cat]) t[cat] = $1;
        }
        END { for (c in n) printf "%s|%d|%s\n", c, n[c], t[c]; }
    ' "$inbox" 2>/dev/null || true)
    sqlite3 -cmd ".timeout 10000" "$DB" "DELETE FROM alert_counts;" 2>/dev/null || true
    while IFS='|' read -r cat n last_ts; do
        [[ -z "$cat" ]] && continue
        sqlite3 -cmd ".timeout 10000" "$DB" "INSERT OR REPLACE INTO alert_counts
                       (category, count, last_ts, refreshed_at)
                       VALUES ('${cat//\'/\'\'}', $n, '${last_ts//\'/\'\'}', '$NOW');" \
            2>/dev/null || true
    done <<< "$rows"
}

sync_checkpoint_stats () {
    local dir=/var/lib/vsf-witness
    if ! pct exec 101 -- test -d "$dir" 2>/dev/null; then
        return 0
    fi
    local out total valid last
    out=$(pct exec 101 -- bash -c '
        f=/var/lib/vsf-witness/checkpoints.jsonl
        [[ -f $f ]] || { echo "0|0|"; exit 0; }
        total=$(wc -l < $f 2>/dev/null || echo 0)
        valid=$(grep -c "\"valid\"[[:space:]]*:[[:space:]]*true" $f 2>/dev/null || echo 0)
        last=$(tail -1 $f 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read()); print(d.get(\"ts\", \"\"))
except Exception:
    print(\"\")
" 2>/dev/null || echo "")
        echo "$total|$valid|$last"
    ' 2>/dev/null || echo "0|0|")
    IFS='|' read -r total valid last <<< "$out"
    sqlite3 -cmd ".timeout 10000" "$DB" "INSERT INTO checkpoint_stats
                   (id, corpus_size, valid_count, last_minted_ts, refreshed_at)
                   VALUES (1, ${total:-0}, ${valid:-0}, '${last:-}', '$NOW')
                   ON CONFLICT(id) DO UPDATE SET
                     corpus_size    = excluded.corpus_size,
                     valid_count    = excluded.valid_count,
                     last_minted_ts = excluded.last_minted_ts,
                     refreshed_at   = excluded.refreshed_at;" 2>/dev/null || true
}

sync_opsroom_sessions_gc () {
    sqlite3 -cmd ".timeout 10000" "$DB" "DELETE FROM opsroom_sessions
                   WHERE last_heartbeat IS NULL
                      OR last_heartbeat < datetime('now', '-1 hour');" 2>/dev/null || true
}

# Run sync hooks only when running services pass (skipped when --chains-only).
if [[ $WANT_SVC -eq 1 ]]; then
    sync_alert_counts        || true
    sync_checkpoint_stats    || true
    sync_opsroom_sessions_gc || true
fi

echo "$NOW  populate ok"
