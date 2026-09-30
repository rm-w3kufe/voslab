#!/usr/bin/env bash
# onboard.sh — agent session-start canonical query.
#
# Runs in WSL. Prints what an agent must know at the top of a session, in the
# order R5 mandates, and NOTHING ELSE. Target: fits on two screens.
#
# Design rule (2026-08-10 boot audit): every line here must change the agent's
# next action. Aggregate the routine, print the anomalous. The previous version
# emitted 1347 lines of which 1136 were section 6, carrying 3 distinct facts
# across 564 repetitions — which forced every reader to pipe it through
# head/tail, and truncated reading is what produced two false findings in one
# session. Volume is not thoroughness.
#
# Usage:  bash scripts/state/onboard.sh
#         bash scripts/state/onboard.sh --full   # no aggregation, for auditing

set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
N02="${VSF_N02:-root@n02}"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=5 -o ServerAliveCountMax=2"
FULL=0
[ "${1:-}" = "--full" ] && FULL=1

# ── Connectivity probe ───────────────────────────────────────────────────────
N02_OK=0
if ssh $SSH_OPTS "$N02" 'test -f /var/lib/vsf-state/state.db' 2>/dev/null; then
    N02_OK=1
fi

# vsf-q wrapper — R4/B5: stderr is REPORTED, never swallowed. A failed query
# used to render as an empty section, indistinguishable from "nothing to
# report". Retries once past the intermittent `database is locked`.
_q() {
    local out rc
    out=$(ssh $SSH_OPTS "$N02" "/usr/local/bin/vsf-q $1" 2>&1); rc=$?
    if [ $rc -ne 0 ] || echo "$out" | grep -q 'locked'; then
        sleep 3
        out=$(ssh $SSH_OPTS "$N02" "/usr/local/bin/vsf-q $1" 2>&1); rc=$?
    fi
    if [ $rc -ne 0 ]; then
        echo "  ✗ vsf-q $1 FAILED (rc=$rc) — this section is UNKNOWN, not empty:"
        echo "$out" | sed 's/^/      /' | head -4
        return 1
    fi
    echo "$out"
}

_warn_no_canon() {
    cat <<'WARN'
  ╔══════════════════════════════════════════════════════════════════════╗
  ║  ⚠  STATE.DB UNREACHABLE — SESSION DIAGNOSTIC INCOMPLETE            ║
  ║  §1 hard rules · §2 services · §3 chains · §4 blockers = UNKNOWN        ║
  ║  DO NOT build, deploy, or change state until n02 is reachable.       ║
  ║  Fix: vsf-tunnels , then re-run this script.                         ║
  ╚══════════════════════════════════════════════════════════════════════╝
WARN
}

echo "═══════════════════════════════════════════════════════════════════════════"
echo "  VSF session onboard — $(date -u '+%Y-%m-%dT%H:%MZ')"
echo "═══════════════════════════════════════════════════════════════════════════"
[ "$N02_OK" -eq 0 ] && _warn_no_canon

# ── §0. OPEN TASKS ───────────────────────────────────────────────────────────
# B2: TASKS.vsm has TWO task syntaxes. The old awk parsed only `task(X):` and
# silently hid all 17 open tasks written as `task("X", …, status=open) = {`,
# including two P1s. Both are parsed here.
echo
echo "## 0. Open tasks"
python3 - "$REPO/TASKS.vsm" <<'PY'
import re, sys
from collections import Counter
txt = open(sys.argv[1], encoding='utf8', errors='replace').read()
rows, seeded = [], 0
unreadable, vocab = [], Counter()

# LOAD AUDIT — the boot must never drop a task silently. Everything below is
# reported even when it is inconvenient; a count the reader cannot trust is
# worse than no count. TASKS.vsm has THREE task syntaxes (2026-08-10 audit):
#   A  task(NAME):                    fields on following lines
#   B  task("NAME", attrs) = { ... }  brace body
#   C  task(NAME): field=v field=v    single line, inline fields
# and at least one definition is indented, which hides it from every parser
# in this repo unless leading whitespace is tolerated.
# A quoted name may be followed by attributes before the `)`; a bare one may
# not. Both must end in `):` or `)=` — that is what separates a definition
# from a prose mention like `task(X)'s loose end`, of which there are several.
_DEF = (r'^{lead}task\((?:"([^"]+)"[^\n]*|([A-Za-z0-9_.\-]+))\)\s*(?::|=)')
_defs = re.findall(_DEF.format(lead=r'[ \t]*'), txt, re.M)
_names = [a or b for a, b in _defs]
_indented = re.findall(_DEF.format(lead=r'[ \t]+'), txt, re.M)
_dupes = {n: c for n, c in Counter(_names).items() if c > 1}

# form A/C:  task(NAME): — leading whitespace TOLERATED on purpose
for m in re.finditer(r'^[ \t]*task\(([A-Za-z0-9_.\-]+)\):(.*?)(?=^[ \t]*task[\("]|\Z)', txt, re.S | re.M):
    name, body = m.group(1), m.group(2)
    g = lambda k: (re.search(rf'^\s+{k}\s*=\s*"?([^"\n]+)"?', body, re.M) or [None, ''])[1].strip()
    # first token only: `status = open   // note` must still read as open.
    # Taking the whole line made a trailing comment part of the value, which
    # silently dropped such a task from the open count entirely.
    st = g('status').split('//')[0].strip().split()[0] if g('status') else ''
    # Form C keeps its fields on the DEFINITION line itself —
    #   task(B): title="..."  status=done  commit=e99b29d
    # so an own-line anchor never sees them. Twelve tasks in the header block
    # are written this way and read as "no status" to every parser in the repo
    # until now (DS census 2026-08-10 §2, why_class_inline_on_def_line).
    if not st:
        st = (re.search(r'status\s*=\s*(\w+)', m.group(0).splitlines()[0]) or [None, ''])[1]
    if st in ('open', 'partial'):
        rows.append((name, g('priority') or '?', st, g('title')[:64]))
    elif st.startswith('seed'):
        seeded += 1
    elif not st:
        unreadable.append(name)
    else:
        vocab[st] += 1

# form B:  task("NAME", priority=P1, …, status=open) = { what: "..." }
# Leading whitespace TOLERATED (same as _DEF) — since 2026-08-10 P4 the
# parser family agrees indented task definitions are legal. This line was
# col-0 anchored and silently hid indented form-B tasks from the open count
# (tasks-census-converge diff, DEBT-TASKS-CENSUS-CONVERGE 2026-08-17).
for m in re.finditer(r'^[ \t]*task\("([^"]+)"(.*?)\)\s*=\s*\{(.*?)^\}', txt, re.S | re.M):
    name, attrs, body = m.group(1), m.group(2), m.group(3)
    st = (re.search(r'status\s*[:=]\s*"?(\w+)', attrs + body) or [None, ''])[1]
    pr = (re.search(r'priority\s*=\s*(\w+)', attrs) or [None, '?'])[1]
    what = (re.search(r'^\s*(?:what|title)\s*:\s*"(.*?)"', body, re.S | re.M) or [None, ''])[1]
    if st in ('open', 'partial'):
        rows.append((name, pr, st, ' '.join(what.split())[:64]))
    elif st.startswith('seed'):
        seeded += 1
    elif not st:
        unreadable.append(name)
    else:
        vocab[st] += 1

# form A-brace:  task(NAME) = { ... }   (bare id, brace body — same as form B
# but unquoted). Used by VSL-NOTATION-UNIVERSE-FULL-2026-08-13,
# AGENT-CYCLE-OBSERVABILITY-2026-08-17, DEBT-SOCRATIC-ENGINE-DIVERGENCE.
# Added 2026-08-18 for tasks-census-converge convergence (DEBT-TASKS-CENSUS-
# CONVERGE): tasks_provider._BLOCK_START accepts bare ids since same commit.
for m in re.finditer(r'^[ \t]*task\(([A-Za-z0-9_.\-]+)\)\s*=\s*\{(.*?)^\}', txt, re.S | re.M):
    name, body = m.group(1), m.group(2)
    st = (re.search(r'status\s*[:=]\s*"?(\w+)', body) or [None, ''])[1]
    pr = (re.search(r'priority\s*=\s*(\w+)', body) or [None, '?'])[1]
    what = (re.search(r'^\s*(?:what|title)\s*:\s*"(.*?)"', body, re.S | re.M) or [None, ''])[1]
    if st in ('open', 'partial'):
        rows.append((name, pr, st, ' '.join(what.split())[:64]))
    elif st.startswith('seed'):
        seeded += 1
    elif not st:
        unreadable.append(name)
    else:
        vocab[st] += 1

for n, p, s, t in sorted(rows, key=lambda r: (r[1], r[0])):
    print(f"  {n:<34} [{p:<6}] {s:<8} {t}")

print(f"  ── {len(rows)} open/partial · {seeded} seeded · "
      f"{len(set(_names))} task ids defined in total")
if _indented:
    got = [a or b for a, b in _indented]
    print(f"  ⚠ {len(got)} definition(s) INDENTED — invisible to any parser "
          f"anchored at column 0: {', '.join(got)}")
if _dupes:
    print(f"  ⚠ {len(_dupes)} DUPLICATE task ids — two definitions share a name, "
          f"so a lookup silently picks one: {', '.join(sorted(_dupes))}")
if unreadable:
    print(f"  ⚠ {len(unreadable)} task(s) carry NO status this parser can read — "
          f"counted neither open nor closed above.")
    print(f"      {len(vocab)} distinct status values in use. "
          f"See TASKS.vsm task(TASK-STATUS-VOCABULARY-NORMALISE) [DS].")

# ── state-canon cross-check (BOOT-RECONCILE-2026-08-10 P2) ─────────────────
# Two independent parsers read TASKS.vsm for the SAME purpose. On 2026-08-10
# they disagreed silently: tasks_provider.py dropped DASHAI-S4-LAB-EVAL and
# VSF-FEED-SPEC-REVIEW (naive brace counting swallowed blocks after a '{'
# inside a note string). This check compares ID SETS, not just cardinality:
# two different wrong-by-N sets would pass a count-only check (same caution
# as the former rules-table divergence check, removed with the table 2026-08-12).
try:
    import os as _os
    import sys as _sys
    _scm = os.path.expanduser('~/state-canon-mcp')  # no hardcoded usernames
    _sys.path.insert(0, _scm)
    _sys.path.insert(0, os.path.join(_scm, 'instances'))
    import tasks_provider as _tp
    _sc = _tp.parse_vsm_file(sys.argv[1])
    _sc_ids = {t['id'] for t in _sc['tasks']}
    _sc_open = {t['id'] for t in _sc['tasks']
                if str(t.get('status', '')).strip().lower() in ('open', 'partial')}
    _my_ids = set(_names)
    _my_open = {r[0] for r in rows}
    _diff_ids = _my_ids ^ _sc_ids
    _diff_open = _my_open ^ _sc_open
    if not _diff_ids and not _diff_open:
        print(f"  ✓ state-canon cross-check: {len(_sc_ids)} ids · "
              f"{len(_sc_open)} open/partial — id sets AGREE")
    else:
        if _diff_ids:
            print(f"  ⚠ state-canon ID-SET DIVERGES — only onboard: "
                  f"{sorted(_diff_ids & _my_ids) or '—'} · only state-canon: "
                  f"{sorted(_diff_ids & _sc_ids) or '—'}")
        if _diff_open:
            print(f"  ⚠ state-canon OPEN-SET DIVERGES — only onboard: "
                  f"{sorted(_diff_open & _my_open) or '—'} · only state-canon: "
                  f"{sorted(_diff_open & _sc_open) or '—'}")
        print(f"    state-canon={len(_sc_ids)} ids · {len(_sc_open)} open/partial vs "
              f"onboard={len(_my_ids)} ids · {len(_my_open)} open/partial")
except Exception as _e:
    print(f"  ? state-canon cross-check skipped (tasks_provider.py unreachable): {_e}")
PY

# ── §1. RULES ────────────────────────────────────────────────────────────────
# The DEFINITION lives in git (docs/spec_revision/system/boot/hard_rules.vsm,
# PROTOCOL_VERSION 3); RULES.md annotates it. Since R7 was resolved
# (2026-08-11) state.db NO LONGER mirrors rules — the table was dropped
# (TASKS.vsm R7-RULES-TABLE-CLEANUP-2026-08-11, executed 2026-08-12): state.db
# observes n02's deterministic world; rules live in the agent's
# non-deterministic world and are DECLARED, never polled. There is nothing to
# check here — the former mirror is gone, which is the whole point.
echo
echo "## 1. Hard rules"
echo "  definition: docs/spec_revision/system/boot/hard_rules.vsm   (read once/session)"
echo "  annotated:  RULES.md                                        (rationale + S5 history)"
echo "  ✓ no state.db mirror (R7 resolved 2026-08-11 — table dropped 2026-08-12)"

# ── §2. SERVICES ─────────────────────────────────────────────────────────────
# B4: the old version printed 130+ rows and never checked whether the census
# was still being WRITTEN. It was 5 days stale on 2026-08-10 and said nothing.
echo
echo "## 2. Services"
if [ "$N02_OK" -eq 1 ]; then
    _svc=$(_q services) && {
        _fresh=$(echo "$_svc" | grep -oE '2[0-9]{3}-[0-9]{2}-[0-9]{2}' | sort | tail -1)
        _age=$(( ( $(date -u +%s) - $(date -u -d "$_fresh" +%s 2>/dev/null || echo 0) ) / 86400 ))
        if [ "$_age" -ge 1 ]; then
            echo "  ⚠ CENSUS STALE — newest refreshed_at is $_fresh (${_age}d ago)."
            echo "    vsf-state-populate is not writing. Every active= below is a ${_age}-day-old claim."
        else
            echo "  ✓ census fresh (newest refreshed_at $_fresh)"
        fi
        if [ "$FULL" -eq 1 ]; then
            echo "$_svc"
        else
            echo "$_svc" | awk 'NR>2 && NF {t[$1"|"$2]++; if($4==1) a[$1"|"$2]++}
                END {for (k in t) {split(k,p,"|"); printf "    %-4s %-16s %2d/%-3d up\n", p[1], p[2], a[k]+0, t[k]}}' \
                | sort -n
            echo "    (--full for the per-service table)"
        fi
    }
else
    echo "  (SKIPPED — state.db unreachable)"
fi

# ── §3. CHAIN HEADS ──────────────────────────────────────────────────────────
echo
echo "## 3. Chain heads"
if [ "$N02_OK" -eq 1 ]; then _q chains; else echo "  (SKIPPED)"; fi

# ── §4. BLOCKERS ─────────────────────────────────────────────────────────────
echo
echo "## 4. Blocking S1 integration"
if [ "$N02_OK" -eq 1 ]; then
    _b=$(_q blockers) && { [ -n "$(echo "$_b" | tr -d '[:space:]')" ] && echo "$_b" || echo "  (none reported)"; }
else echo "  (SKIPPED)"; fi

# ── §5. LAST HANDOFF BLOCK ───────────────────────────────────────────────────
# B1: the old awk captured from the FIRST `session(` and exited at the first
# `^}` — it printed the OLDEST block in the file, always. On 2026-08-10 it
# handed the agent a block from 2026-05-10 labelled "Last". This walks to the
# last one.
echo
echo "## 5. Last HANDOFF block"
python3 - "$REPO/HANDOFF.vsm.md" <<'PY'
import re, sys
txt = open(sys.argv[1], encoding='utf8', errors='replace').read()
starts = [m.start() for m in re.finditer(r'^session\(', txt, re.M)]
if not starts:
    print("  (no session block found)"); raise SystemExit
block = txt[starts[-1]:].rstrip()
lines = block.splitlines()
print(f"  ({len(starts)} blocks in file; showing the last)")
for l in (lines if len(lines) <= 40 else lines[:40] + [f"  … {len(lines)-40} more lines — read HANDOFF.vsm.md"]):
    print("  " + l)
PY

# ── §6. ALGEDONIC ────────────────────────────────────────────────────────────
# B3: 564 escalations were printed verbatim — 387 of them the same string.
# Group by (type, source); show counts and the worst few by severity.
echo
echo "## 6. Algedonic"
if [ "$N02_OK" -eq 1 ]; then
    scp $SSH_OPTS -q "$REPO/projects/vsf-s5-algedonic/vsf_s5_digest.py" "$N02:/tmp/vsf_s5_digest.py" 2>/dev/null
    ssh $SSH_OPTS "$N02" "pct push 104 /tmp/vsf_s5_digest.py /tmp/vsf_s5_digest.py" >/dev/null 2>&1
    DIGEST=$(ssh $SSH_OPTS "$N02" "pct exec 104 -- python3 /tmp/vsf_s5_digest.py" 2>&1)
    if [ $? -ne 0 ]; then
        echo "  ✗ ledger query FAILED — UNKNOWN, not zero:"; echo "$DIGEST" | sed 's/^/      /' | head -3
    else
        echo "$DIGEST" | head -1 | sed 's/^/  /'
        # ranked by SEVERITY first, then volume — a single sev-7.0 outranks
        # 387 repetitions of sev 0.0, and the old flat dump buried exactly that.
        echo "$DIGEST" | grep '^ESC|' | awk -F'|' '
            {n[$3"|"$5]++; if ($4+0 > s[$3"|"$5]) s[$3"|"$5]=$4+0}
            END {for (k in n) {split(k,p,"|"); printf "%.1f|%d|%s|%s\n", s[k], n[k], p[1], p[2]}}' \
            | sort -t'|' -k1,1rn -k2,2rn \
            | awk -F'|' '{printf "    sev %-5s %5d×  %-24s [%s]\n", $1, $2, $3, $4}'
        echo "    → detail: pct exec 104 -- python3 /usr/local/bin/vsf_s5_tui.py"
    fi
else
    echo "  (SKIPPED)"
fi

# ── §7. INSTRUMENTS ──────────────────────────────────────────────────────────
# B6: the boot never named the MCP servers. Two exist, they serve DIFFERENT
# domains, and asking the wrong one returns [] — which reads as "nothing"
# rather than "wrong address". That cost a session.
echo
echo "## 7. Instruments — prefer these over raw ssh"
echo "  state-canon        tasks · focus · journal      → TASKS.vsm, current_focus.json"
echo "  state-canon-infra  services · lxcs · chains · topology → n02 state.db"
echo "                     (domain 'rules' RETRACTED 2026-08-12 — query raises,"
echo "                      canon = docs/spec_revision/system/boot/hard_rules.vsm)"
echo "  an empty result from one is NOT evidence of absence — check you asked the right server."
echo
echo "═══════════════════════════════════════════════════════════════════════════"
if [ "$N02_OK" -eq 0 ]; then
    echo "  END — STATE.DB WAS UNREACHABLE. Fix the tunnel and re-run."
else
    echo "  END — read RULES.md + the L0 definition before proposing any action."
fi
echo "═══════════════════════════════════════════════════════════════════════════"
