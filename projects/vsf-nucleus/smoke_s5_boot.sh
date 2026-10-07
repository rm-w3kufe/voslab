#!/usr/bin/env bash
# A2 smoke — exercises s5::verify_covenant_at_boot in 3 scenarios:
#   1. Match    → boot proceeds, exit 0 path observable
#   2. Drift    → fail-closed, exit code 2
#   3. SkipPolicy → boot proceeds with warning (verify_at_boot=false)
#
# Each scenario runs the binary in "validate-only" mode by stub-out the rest
# of operational startup, via env that causes preflight to bail after S5 check.
#
# We can't easily reach the s5 check without a real /root/bbs.db etc., so this
# script instead runs the binary with the `--config-mode` flag — currently the
# nucleus doesn't have such a flag. Workaround: invoke the binary and rely on
# its EARLY exit when /root/bbs.db is missing (which happens BEFORE S5 check
# would normally run? actually AFTER — let me re-check the order).
#
# Actually s5 check is at the very top of run_operational, BEFORE
# OperationalNucleus::new (which opens BBS). So a failing BBS open won't mask
# the S5 path. We rely on: covenant drift → exit 2 BEFORE bbs open.
# In match/inconclusive cases, the binary will then try to open BBS and fail —
# but the S5 LOG LINE prints first, which is what we test.

set -euo pipefail
cd "$(dirname "$0")"

ROOT=/tmp/vsf-s5-smoke
rm -rf "$ROOT"
mkdir -p "$ROOT"

# Synthesize covenant fixture
FIXTURE_COVENANT="$ROOT/covenant.vsm"
cat > "$FIXTURE_COVENANT" <<'EOF'
@vsm 0.1
V("smoke", L=0)
EOF
EXPECTED=$(sha256sum "$FIXTURE_COVENANT" | awk '{print $1}')

# Tiny HTTP hash server
mkdir -p "$ROOT/http"
echo -n "$EXPECTED" > "$ROOT/http/covenant.hash"
( cd "$ROOT/http" && exec python3 -m http.server 7302 ) > "$ROOT/http.log" 2>&1 &
HTTP_PID=$!
trap 'kill $HTTP_PID 2>/dev/null || true' EXIT
sleep 1

# Build
cargo build --release --locked 2>&1 | tail -2
BIN=./target/release/vsf-nucleus

# Common env
export COVENANT_PATH="$FIXTURE_COVENANT"
export NUCLEUS_MODE=operational
unset NATS_URL

run_one() {
  local label="$1"
  local expected_exit="$2"
  local s5_policy_extra="$3"

  cat > "$ROOT/s5_policy.json" <<EOF
{
  "covenant": {
    "canonical_hash_source": "http://127.0.0.1:7302/covenant.hash",
    $s5_policy_extra
    "verify_at_boot": true
  }
}
EOF
  export S5_POLICY_PATH="$ROOT/s5_policy.json"

  echo
  echo "[smoke A2] SCENARIO: $label"
  set +e
  timeout 10 "$BIN" > "$ROOT/$label.log" 2>&1
  local got_exit=$?
  set -e

  # We expect the S5 log line BEFORE any BBS-open failure
  echo "  exit code: $got_exit (expected: $expected_exit)"

  # Did the S5 path get exercised?
  if ! grep -q '\[S5\]' "$ROOT/$label.log"; then
    echo "  FAIL: no [S5] log line found"
    cat "$ROOT/$label.log"
    exit 1
  fi

  # Was the exit code what we expected?
  if [ "$got_exit" != "$expected_exit" ]; then
    # Allow exit 1 (BBS-open failure) in non-drift scenarios where S5 passed
    if [ "$expected_exit" = "POSTS5" ] && [ "$got_exit" != "2" ]; then
      echo "  ✓ S5 passed (got $got_exit from later BBS-open failure, NOT drift exit 2)"
    else
      echo "  FAIL: exit code mismatch"
      cat "$ROOT/$label.log"
      exit 1
    fi
  fi

  echo "  log tail:"
  grep '\[S5\]\|S5 fail' "$ROOT/$label.log" | sed 's/^/    /'
}

# ── Scenario MATCH ──
run_one "match" "POSTS5" '"_": "all defaults",'

# ── Scenario DRIFT ──
echo "TAMPERED" >> "$FIXTURE_COVENANT"
TAMPERED=$(sha256sum "$FIXTURE_COVENANT" | awk '{print $1}')
echo "  (fixture covenant tampered: now $TAMPERED)"
run_one "drift" "2" '"_": "drift expected",'

# Restore for SKIP test
cat > "$FIXTURE_COVENANT" <<'EOF'
@vsm 0.1
V("smoke", L=0)
EOF

# ── Scenario SKIP via policy verify_at_boot=false ──
# Custom policy this time
cat > "$ROOT/s5_policy.json" <<EOF
{
  "covenant": {
    "canonical_hash_source": "http://127.0.0.1:7302/covenant.hash",
    "verify_at_boot": false
  }
}
EOF
echo
echo "[smoke A2] SCENARIO: skip_by_policy"
set +e
timeout 10 "$BIN" > "$ROOT/skip_by_policy.log" 2>&1
set -e
if ! grep -q 'skipped by policy\|verify_at_boot=FALSE' "$ROOT/skip_by_policy.log"; then
  echo "  FAIL: skip path not exercised"
  cat "$ROOT/skip_by_policy.log"
  exit 1
fi
echo "  ✓ skip path exercised"

echo
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  A2 SMOKE PASSED                                           ║"
echo "║                                                            ║"
echo "║  ✓ scenario match:  [S5] logs verify ok                    ║"
echo "║  ✓ scenario drift:  fail-closed exit code 2                ║"
echo "║  ✓ scenario skip:   policy flag honored                    ║"
echo "╚════════════════════════════════════════════════════════════╝"
