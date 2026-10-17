#!/usr/bin/env bash
# run_suite.sh — full visible control run for LXC 114 / local
#   bash scripts/run_suite.sh [bench_n]
# Runs: 32 negative controls + covenant smoke + optional quick bench.
set -u
cd "$(dirname "$0")/.."
BENCH_N="${1:-200}"

echo "═══ ViArc-2 suite ═══"
fail=0
for t in tests/test_covenant.py tests/test_predicates.py tests/test_rsi_tools.py; do
  echo "── $t"
  python3 "$t" | tail -1 || fail=1
done
echo "── covenant smoke"
python3 covenant.py || fail=1
echo "── predicates smoke"
python3 predicates.py || fail=1
if [ "$BENCH_N" -gt 0 ]; then
  echo "── quick bench ($BENCH_N tasks)"
  if ! python3 bench_local.py "$BENCH_N" > /tmp/viarc_bench.log 2>&1; then
    echo "BENCH FAILED:"; tail -5 /tmp/viarc_bench.log; fail=1
  else
    head -6 /tmp/viarc_bench.log
  fi
fi
echo "═══ $([ $fail -eq 0 ] && echo ALL GREEN || echo FAILURES) ═══"
exit $fail
