#!/usr/bin/env bash
# vsf-auditd — continuous auditor at-the-ceiling.
#
# Picks one recovery_exercise gate at random (Poisson-thinned to keep
# pressure low), runs it, records the result in state.db.audits, and
# emits an algedonic if the gate fails.
#
# Idea, per operator + Beer: "once at ceiling, the auditor should run
# constantly". This is the systemd embodiment of that — fires every
# 10 min, decides via Poisson whether to actually audit (mean
# ~1 audit/hour), so gates exercise on average every ~1h without ever
# overlapping.
#
# Designed to run on n02 host (has ssh to LXCs + state.db).
set -euo pipefail

DB=/var/lib/vsf-state/state.db
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MEAN_S=3600   # target one audit per hour on average

# Schema bootstrap (idempotent). PRAGMA busy_timeout waits on lock
# contention (populate timer + auditd timer share state.db).
sqlite3 "$DB" <<'SQL'
PRAGMA busy_timeout = 10000;
CREATE TABLE IF NOT EXISTS audits (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT    NOT NULL,
    gate      TEXT    NOT NULL,             -- 'g2'|'g3'|'g4'|'g5'
    passed    INTEGER NOT NULL,             -- 0|1
    duration_s REAL,
    evidence  TEXT
);
CREATE INDEX IF NOT EXISTS idx_audits_ts ON audits(ts DESC);
SQL

# Poisson-thinned decision: we are invoked every T_INVOKE seconds by
# systemd. To realize a Poisson process with mean MEAN_S, we accept
# this invocation with probability p = T_INVOKE / MEAN_S.
# Operator-configurable via env; default T_INVOKE = 600 s (10 min).
T_INVOKE="${T_INVOKE:-600}"
PROB_NUM=$T_INVOKE
PROB_DEN=$MEAN_S
# random integer in [0, PROB_DEN)
R=$(( RANDOM * 1000 + RANDOM ))
R=$(( R % PROB_DEN ))
if (( R >= PROB_NUM )); then
    echo "$NOW  auditd: skip (Poisson-thinned; r=$R prob_num=$PROB_NUM)"
    exit 0
fi

# Pick a gate uniformly (G2 includes binary-tamper which writes/reads
# /tmp; G3 restarts the broker — disruptive; G4 kills nucleus; G5 is
# the cheapest. Weight cheaper gates higher to reduce ops noise.)
WEIGHTS=( 5 1 1 5 )   # g2 g3 g4 g5 — g3/g4 disruptive, lower weight
GATES=( g2 g3 g4 g5 )
TOTAL=0; for w in "${WEIGHTS[@]}"; do TOTAL=$(( TOTAL + w )); done
PICK=$(( RANDOM % TOTAL ))
chosen=""; acc=0
for i in "${!WEIGHTS[@]}"; do
    acc=$(( acc + WEIGHTS[i] ))
    if (( PICK < acc )); then chosen="${GATES[i]}"; break; fi
done

echo "$NOW  auditd: chose gate=$chosen"

# Run the gate. recovery_exercise.py lives in the repo on n02.
START=$(date +%s.%N)
out=$(VSF_LOCAL_N02=1 python3 /usr/local/bin/vsf-recovery-exercise --gate "$chosen" 2>&1 || true)
END=$(date +%s.%N)
dur=$(awk -v s="$START" -v e="$END" 'BEGIN{printf "%.2f", e-s}')

# Parse verdict from output (e.g., "[PASS] G2 covenant..." or "[FAIL] ...")
if echo "$out" | grep -q "^\[PASS\] G"; then
    passed=1
    evidence=$(echo "$out" | grep -E '^\[PASS\]' | head -1)
else
    passed=0
    evidence=$(echo "$out" | grep -E '^\[FAIL\]' | head -1)
fi

# Record in state.db.
sqlite3 "$DB" "PRAGMA busy_timeout = 10000;
                INSERT INTO audits(ts, gate, passed, duration_s, evidence)
                VALUES('$NOW', '$chosen', $passed, $dur, '$(echo "$evidence" | sed "s/'/''/g")');"

if (( passed == 0 )); then
    line="$NOW  G-AUDIT.1 gate_fail  gate=$chosen evidence=${evidence:0:200}"
    pct exec 104 -- bash -c "mkdir -p /alerts && echo '$line' >> /alerts/operator_inbox.log" \
        2>/dev/null || true
    # Also publish via NATS (mirroring populate.sh emit_algedonic shape)
    payload=$(printf '{"ts":"%s","source_id":"vsf-auditd","category":"gate_fail","severity":8.0,"signal":1,"gate":"%s","evidence":"%s"}' \
        "$NOW" "$chosen" "$(echo "$evidence" | sed 's/"/\\"/g')")
    plen=${#payload}
    pct exec 106 -- python3 -c "
import socket
p = b'''$payload'''
s = socket.socket(); s.connect(('127.0.0.1', 4222)); s.recv(4096)
s.send(b'CONNECT {}\r\nPUB vsf.alpha.algedonic ' + str($plen).encode() + b'\r\n' + p + b'\r\n')
s.close()
" 2>/dev/null || true
    echo "$NOW  auditd: GATE $chosen FAILED — algedonic emitted"
    exit 1
fi

echo "$NOW  auditd: gate=$chosen PASS (duration=${dur}s)"
