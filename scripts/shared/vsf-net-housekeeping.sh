#!/usr/bin/env bash
# VSF Network Housekeeping
# -----------------------------------------------------------------------------
# Audits dead network services / SSH tunnels and (optionally) auto-cleans a
# small, pre-approved set of LOW-RISK dead listeners.
#
# Design (per operator decision 2026-05-31):
#   - scope=local : full audit + SAFE auto-clean (dead listeners live here)
#   - scope=n02   : audit only, REPORT-ONLY (never auto-kill remote services)
#
# Rigor protocol: destructive actions are gated. Default is DRY-RUN (report).
# Auto-clean only runs with --apply, only on scope=local, only for the
# categories below, and never touches an allowlisted process/port.
#
# Safe auto-clean categories (local only):
#   HUNG_HTTP    a local app server (uvicorn / http.server / gunicorn) that is
#               LISTENing but returns HTTP 000 on two spaced probes.
#   ZOMBIE_TUNNEL  an `ssh -N` process that holds NO listening socket (dead
#               forward — the remote endpoint vanished).
#   DUP_TUNNEL   two+ ssh processes forwarding the SAME local port; keep the
#               newest (highest PID), kill the rest.
# Everything else is REPORTED, never killed.
#
# Usage:
#   vsf-net-housekeeping.sh [--scope=local|n02|all] [--apply] [--json]
#
# Exit: 0 always (a housekeeping pass is informational; failures are logged).
set -u

SCOPE="local"
APPLY=0
JSON=0
N02_HOST="${VSF_N02_HOST:-root@n02}"
PROBE_TIMEOUT="${VSF_PROBE_TIMEOUT:-4}"

for arg in "$@"; do
  case "$arg" in
    --scope=*) SCOPE="${arg#*=}" ;;
    --apply)   APPLY=1 ;;
    --json)    JSON=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ── Allowlist ────────────────────────────────────────────────────────────────
# Ports / process patterns that must NEVER be auto-killed even if a probe fails
# (transient restarts, non-HTTP services we cannot probe with curl, etc.).
# Override by writing one entry per line to $ALLOW_FILE.
ALLOW_FILE="${VSF_NETHK_ALLOW:-$HOME/.config/vsf/net-housekeeping.allow}"
ALLOW_PORTS_DEFAULT="22 25 4222 8222 8888"      # sshd, postfix, NATS, NATS-ui, jupyter
ALLOW_PROC_DEFAULT="sshd|postfix|master|systemd|node|dockerd"
# NOTE: netdata intentionally NOT allowlisted — decommissioned 2026-05-31; flag if it resurfaces.
ALLOW_PORTS="$ALLOW_PORTS_DEFAULT"
ALLOW_PROC="$ALLOW_PROC_DEFAULT"
if [ -f "$ALLOW_FILE" ]; then
  while IFS= read -r line; do
    case "$line" in
      port:*) ALLOW_PORTS="$ALLOW_PORTS ${line#port:}" ;;
      proc:*) ALLOW_PROC="$ALLOW_PROC|${line#proc:}" ;;
    esac
  done < "$ALLOW_FILE"
fi

is_allowlisted_port() { case " $ALLOW_PORTS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# HTTP-ish ports we are willing to probe + treat HTTP 000 as "hung".
HTTP_PORTS="80 85 8000 8006 8080 8081 8082 8088 8090 9000 9001 9100 9101 19999"
is_http_port() { case " $HTTP_PORTS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# ── Reporting buffers ────────────────────────────────────────────────────────
REPORT=""    # human lines
ACTIONS=""   # what auto-clean did / would do
add()    { REPORT="${REPORT}$1"$'\n'; }
action() { ACTIONS="${ACTIONS}$1"$'\n'; }

probe_http() { # port -> echoes status code (000 = dead)
  curl -s -m "$PROBE_TIMEOUT" -o /dev/null -w '%{http_code}' "http://127.0.0.1:$1/" 2>/dev/null || echo 000
}

# ── Local audit + safe auto-clean ────────────────────────────────────────────
audit_local() {
  add "── LOCAL (this host) ─ $TS"

  # 1. Map LISTEN sockets -> port + owning process (ss, no header).
  local seen_ports=""
  while read -r _ _ _ local_addr _ procinfo; do
    [ -z "$local_addr" ] && continue
    local port="${local_addr##*:}"
    local proc; proc="$(printf '%s' "$procinfo" | sed -n 's/.*(("\([^"]*\)".*/\1/p')"
    local pid;  pid="$(printf '%s' "$procinfo" | sed -n 's/.*pid=\([0-9]*\).*/\1/p')"
    [ -z "$port" ] && continue
    case " $seen_ports " in *" $port:$pid "*) continue ;; esac
    seen_ports="$seen_ports $port:$pid"

    local status="" verdict="OK"
    if is_http_port "$port"; then
      status="$(probe_http "$port")"
      if [ "$status" = "000" ]; then verdict="DEAD(000)"; fi
    else
      status="n/a"
    fi
    add "  :$port  ${proc:-?}(${pid:-?})  http=$status  -> $verdict"

    # SAFE auto-clean: HUNG_HTTP (local app server returning 000)
    if [ "$verdict" = "DEAD(000)" ] && [ "$SCOPE" != "n02" ]; then
      if is_allowlisted_port "$port"; then
        action "  SKIP HUNG_HTTP :$port ${proc} (allowlisted)"
      elif printf '%s' "${proc:-}" | grep -qiE "${ALLOW_PROC}"; then
        action "  SKIP HUNG_HTTP :$port ${proc} (allowlisted proc)"
      elif printf '%s' "${proc:-}" | grep -qiE 'python|uvicorn|gunicorn|http\.server'; then
        # re-probe once to avoid a transient blip
        sleep 2
        if [ "$(probe_http "$port")" = "000" ]; then
          if [ "$APPLY" = "1" ] && [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null && action "  KILLED HUNG_HTTP :$port ${proc}(${pid})" \
                                    || action "  FAIL  HUNG_HTTP :$port ${proc}(${pid})"
          else
            action "  WOULD-KILL HUNG_HTTP :$port ${proc}(${pid})  [dry-run]"
          fi
        fi
      else
        action "  REPORT  DEAD :$port ${proc}(${pid}) (not an auto-clean category)"
      fi
    fi
  done < <(ss -H -tlnp 2>/dev/null)

  # 2. SSH tunnels: zombie (no listening socket) + duplicate (same fwd port).
  audit_ssh_tunnels
}

audit_ssh_tunnels() {
  # Collect listening ports owned by ssh, keyed by port -> "pid pid ..."
  declare -A port_pids
  while read -r line; do
    local port pid
    port="$(printf '%s' "$line" | awk '{print $4}')"; port="${port##*:}"
    pid="$(printf '%s' "$line" | sed -n 's/.*pid=\([0-9]*\).*/\1/p')"
    [ -z "$port" ] || [ -z "$pid" ] && continue
    port_pids[$port]="${port_pids[$port]:-} $pid"
  done < <(ss -H -tlnp 2>/dev/null | grep '"ssh"')

  # DUP_TUNNEL: same local port served by >1 DISTINCT ssh pid -> keep newest.
  # (ss lists each tunnel twice — IPv4 + IPv6 — with the same pid; dedupe first.)
  for port in "${!port_pids[@]}"; do
    # shellcheck disable=SC2206
    local upids=($(printf '%s\n' ${port_pids[$port]} | sort -un))
    if [ "${#upids[@]}" -gt 1 ]; then
      local newest; newest="$(printf '%s\n' "${upids[@]}" | sort -n | tail -1)"
      add "  DUP_TUNNEL :$port pids=${upids[*]} (keep $newest)"
      for p in "${upids[@]}"; do
        [ "$p" = "$newest" ] && continue
        if [ "$SCOPE" != "n02" ] && [ "$APPLY" = "1" ]; then
          kill "$p" 2>/dev/null && action "  KILLED DUP_TUNNEL :$port ssh($p)"
        else
          action "  WOULD-KILL DUP_TUNNEL :$port ssh($p)  [dry-run]"
        fi
      done
    fi
  done

  # ZOMBIE_TUNNEL: ssh -N process holding NO listening socket.
  while read -r pid cmd; do
    [ -z "$pid" ] && continue
    if ! ss -H -tlnp 2>/dev/null | grep -q "pid=$pid,"; then
      add "  ZOMBIE_TUNNEL ssh($pid): $cmd  (no listening socket)"
      if [ "$SCOPE" != "n02" ] && [ "$APPLY" = "1" ]; then
        kill "$pid" 2>/dev/null && action "  KILLED ZOMBIE_TUNNEL ssh($pid)"
      else
        action "  WOULD-KILL ZOMBIE_TUNNEL ssh($pid)  [dry-run]"
      fi
    fi
  done < <(pgrep -af 'ssh .*-N' 2>/dev/null | awk '{pid=$1; $1=""; print pid, $0}')
}

# ── n02 audit (REPORT-ONLY) ──────────────────────────────────────────────────
audit_n02() {
  add "── n02 (host + LXCs) ─ REPORT-ONLY ─ $TS"
  local out
  out="$(ssh -o ConnectTimeout="$PROBE_TIMEOUT" "$N02_HOST" '
    echo "[host listeners]"
    ss -H -tlnp 2>/dev/null | awk "{print \$4, \$6}" | grep -vE "127.0.0.53|:22 " | sort -u
    echo "[lxc services]"
    for id in $(pct list 2>/dev/null | awk "NR>1{print \$1}"); do
      st=$(pct status "$id" 2>/dev/null | awk "{print \$2}")
      echo "  LXC $id: $st"
    done
  ' 2>&1)"
  add "$out"
  add "  (n02 dead-service classification is manual — review above, clean by hand)"
}

# ── Run ──────────────────────────────────────────────────────────────────────
case "$SCOPE" in
  local) audit_local ;;
  n02)   audit_n02 ;;
  all)   audit_local; audit_n02 ;;
  *) echo "bad scope: $SCOPE" >&2; exit 2 ;;
esac

MODE="DRY-RUN"; [ "$APPLY" = "1" ] && MODE="APPLY"
if [ "$JSON" = "1" ]; then
  printf '{"ts":"%s","scope":"%s","mode":"%s"}\n' "$TS" "$SCOPE" "$MODE"
fi
printf '%s\n' "VSF net-housekeeping  scope=$SCOPE  mode=$MODE  $TS"
printf '%s' "$REPORT"
echo "── actions ──"
printf '%s' "${ACTIONS:-  (none)
}"
exit 0
