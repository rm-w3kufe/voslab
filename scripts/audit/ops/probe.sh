#!/usr/bin/env bash
# probe.sh — canonical live-inspection helpers.
#
# WHY THIS EXISTS: on 2026-07-23/24 an agent raised SEVEN false alarms in one
# session. Not one was a real system fault — every one was a broken measurement.
# The failures clustered into five classes, and each helper below closes one.
# Ad-hoc shell re-invents these bugs every session; a checked-in, self-tested
# instrument does not.
#
#   1. TIME       — absolute clock strings break across midnight; zero-padded
#                   %H%M compares as octal ("0008" is not a valid octal number).
#                   FIX: only ever use relative windows (`N min ago`), never a
#                   bare "HH:MM", and never arithmetic on %H%M.
#   2. QUOTING    — nested `pct exec ... bash -c '...'` mangles quotes and eats
#                   non-ASCII (a grep for "Ω" silently matched nothing).
#                   FIX: push a script file and execute it. Never inline.
#   3. SELF-MATCH — `pgrep -f X` / `pkill -f X` match the very command that
#                   contains X, so a wait-loop waits on itself forever and a
#                   pkill kills its own ssh session. Both happened.
#                   FIX: bracket trick, and always exclude $$.
#   4. VARIANTS   — grepping one phrasing of a log line when the code emits
#                   several ("IN Ω …" vs "Ω not calibrated — raw state emitted")
#                   reports healthy nodes as mute.
#                   FIX: match on the structural invariant, or enumerate first.
#   5. METHOD     — comparing `wc -l` from one run to `grep -c .` from the next
#                   produced a phantom "the chain shrank by 839 lines".
#                   FIX: one helper reports all counts together, always.
#
# Usage: probe.sh <subcommand> [args]   ·   probe.sh selftest

set -uo pipefail

_die() { echo "probe: $*" >&2; exit 2; }

# ── 1. TIME ──────────────────────────────────────────────────────────────
# Relative windows only. Callers pass minutes; we never format a wall clock.
# Returns non-zero (does NOT exit) on a bad window, so callers — including the
# selftest — can assert the rejection instead of being killed by it.
_since() {
    local mins="${1:?minutes required}"
    if ! [[ "$mins" =~ ^[0-9]+$ ]]; then
        echo "probe: window must be integer minutes, got '$mins'" >&2
        return 1
    fi
    echo "${mins} min ago"
}

# ── 3. SELF-MATCH ────────────────────────────────────────────────────────
# `pgrep -f foo` matches this very process if our argv contains "foo".
# The bracket trick ([f]oo) cannot match itself; -v $$ excludes us anyway.
_pgrep_other() {
    local pat="${1:?pattern required}"
    local bracketed="[${pat:0:1}]${pat:1}"
    pgrep -f "$bracketed" 2>/dev/null | grep -v "^$$\$" || true
}

# ── SUBCOMMANDS ──────────────────────────────────────────────────────────

# actors <lxc> — WHO is acting on this box right now?
# The question that must be asked BEFORE attributing any signal to a fault.
# A kill signature says WHAT happened, never WHO did it.
cmd_actors() {
    local lxc="${1:-}"
    echo "== actors on ${lxc:-host} =="
    if [[ -n "$lxc" ]]; then
        pct exec "$lxc" -- ps -eo pid,etimes,comm --no-headers 2>/dev/null \
            | awk '$2 < 600 {printf "  recent(%ss) pid=%s %s\n", $2, $1, $3}' | head -20
    else
        ps -eo pid,etimes,args --no-headers 2>/dev/null \
            | awk '$2 < 600' | grep -viE 'probe\.sh|ps -eo|awk' | head -20 \
            | sed 's/^/  /'
    fi
    echo "  -- deploy/rollout scripts running --"
    _pgrep_other "restart_" | sed 's/^/  pid /' || true
    _pgrep_other "deploy"   | sed 's/^/  pid /' || true
}

# window <lxc> <unit-glob> <minutes> [invariant]
# Which units logged anything in a RELATIVE window. `invariant` should be a
# structural token the code always emits (e.g. a field name), not one phrasing
# of one message — see failure class 4.
cmd_window() {
    local lxc="${1:?lxc}" glob="${2:?unit glob}" mins="${3:?minutes}" inv="${4:-}"
    local since; since=$(_since "$mins") || _die "bad window"
    local script; script=$(mktemp /tmp/probe_win.XXXXXX.sh)
    # Class 2: build a FILE, push it, run it. No inline nested quoting.
    cat > "$script" <<PROBE_EOF
#!/bin/bash
hit=0; miss=0; misslist=""
for u in \$(systemctl list-units '$glob' --all --no-legend --plain 2>/dev/null | awk '{print \$1}'); do
    log=\$(journalctl -u "\$u" --no-pager --since "$since" 2>/dev/null)
    if [ -z "$inv" ]; then
        n=\$(echo "\$log" | grep -vc '^\$')
        [ "\$n" -gt 0 ] && hit=\$((hit+1)) || { miss=\$((miss+1)); misslist="\$misslist \$u"; }
    else
        if echo "\$log" | grep -q '$inv'; then hit=\$((hit+1));
        else miss=\$((miss+1)); misslist="\$misslist \$u"; fi
    fi
done
echo "  window   : $since"
echo "  matched  : \$hit"
echo "  no-match : \$miss"
[ -n "\$misslist" ] && echo "  units:\$misslist"
PROBE_EOF
    if [[ -n "$lxc" && "$lxc" != "0" ]]; then
        pct push "$lxc" "$script" /tmp/probe_win.sh >/dev/null 2>&1
        pct exec "$lxc" -- chmod +x /tmp/probe_win.sh
        pct exec "$lxc" -- /tmp/probe_win.sh
    else
        chmod +x "$script"; "$script"
    fi
    rm -f "$script"
}

# lines <file> — ALL counts in one call, so two runs are never compared by
# different methods (failure class 5).
cmd_lines() {
    local f="${1:?file}"
    [[ -r "$f" ]] || _die "cannot read $f"
    printf "  wc -l        : %s\n" "$(wc -l < "$f")"
    printf "  non-blank    : %s\n" "$(grep -c . "$f" || true)"
    printf "  blank        : %s\n" "$(grep -c '^$' "$f" || true)"
    printf "  not-JSON-open: %s\n" "$(grep -cv '^{' "$f" || true)"
    printf "  bytes        : %s\n" "$(stat -c%s "$f")"
    printf "  mtime        : %s\n" "$(stat -c%y "$f")"
}

# variants <lxc> <unit> [minutes] — enumerate the DISTINCT message shapes a unit
# emits, before writing any grep against it (failure class 4).
cmd_variants() {
    local lxc="${1:?lxc}" unit="${2:?unit}" mins="${3:-120}"
    local since; since=$(_since "$mins") || _die "bad window"
    pct exec "$lxc" -- journalctl -u "$unit" --no-pager --since "$since" 2>/dev/null \
        | sed -E 's/^[A-Za-z]{3} [0-9]+ [0-9:]+ [^ ]+ [^:]+: //' \
        | sed -E 's/[0-9]+\.[0-9]+/N/g; s/\b[0-9]+\b/N/g; s/\[[^]]*\]/[X]/g' \
        | sort | uniq -c | sort -rn | head -15 | sed 's/^/  /'
}

cmd_selftest() {
    local fail=0
    echo "== probe.sh selftest =="

    # class 1 — relative windows, and reject a wall-clock string
    [[ "$(_since 5)" == "5 min ago" ]] || { echo "  FAIL _since"; fail=1; }
    if _since "23:20" 2>/dev/null; then echo "  FAIL: accepted a wall clock"; fail=1
    else echo "  ok  time: wall-clock strings rejected"; fi

    # class 3 — self-match. Our own argv contains the pattern; must not match us.
    local pat="probe_selftest_marker_xyz"
    # shellcheck disable=SC2034
    local _decoy="$pat"
    if [[ -z "$(_pgrep_other "$pat")" ]]; then echo "  ok  self-match: excluded"
    else echo "  FAIL: pgrep matched self"; fail=1; fi

    # class 5 — counts agree on a known file
    local t; t=$(mktemp)
    printf '{"a":1}\n\n{"b":2}\nnot-json\n' > "$t"
    local out; out=$(cmd_lines "$t")
    echo "$out" | grep -q "wc -l        : 4"    || { echo "  FAIL lines/wc"; fail=1; }
    echo "$out" | grep -q "non-blank    : 3"    || { echo "  FAIL lines/nonblank"; fail=1; }
    echo "$out" | grep -q "blank        : 1"    || { echo "  FAIL lines/blank"; fail=1; }
    echo "$out" | grep -q "not-JSON-open: 2"    || { echo "  FAIL lines/notjson"; fail=1; }
    [[ $fail -eq 0 ]] && echo "  ok  lines: all four counts consistent"
    rm -f "$t"

    [[ $fail -eq 0 ]] && echo "== PASS ==" || echo "== FAIL =="
    return $fail
}

case "${1:-}" in
    actors)   shift; cmd_actors "$@" ;;
    window)   shift; cmd_window "$@" ;;
    lines)    shift; cmd_lines "$@" ;;
    variants) shift; cmd_variants "$@" ;;
    selftest) shift; cmd_selftest "$@" ;;
    *) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
