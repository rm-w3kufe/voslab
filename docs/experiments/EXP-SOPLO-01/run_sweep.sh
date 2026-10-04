#!/usr/bin/env bash
# EXP-SOPLO-01 σ-sweep driver. RUN ON LXC 108 (sandbox) — never the live nucleus.
# Each σ writes its own telemetry tree so analyze_soplo.py can discover sigma_* dirs.
#
#   ./run_sweep.sh [vsf-nucleus binary] [out dir]
#   env: SIGMAS, TICKS, VSF_SOPLO_N override defaults.
set -euo pipefail

BIN="${1:-./target/release/vsf-nucleus}"
OUT="${2:-/tmp/soplo_results}"
N="${VSF_SOPLO_N:-128}"
TICKS="${TICKS:-1500}"
SIGMAS="${SIGMAS:-0.0 0.01 0.02 0.05 0.10 0.20}"

mkdir -p "$OUT"
echo "EXP-SOPLO-01 sweep · bin=$BIN · N=$N · ticks=$TICKS · σ∈{$SIGMAS}"
for s in $SIGMAS; do
  d="$OUT/sigma_${s}"
  mkdir -p "$d"
  echo "── σ=$s → $d ──"
  VSF_DATA_DIR="$d" VSF_SOPLO_SIGMA="$s" VSF_SOPLO_N="$N" \
    "$BIN" --experiment soplo_landauer --ticks "$TICKS" | tail -n 9
done
echo
echo "done → analyze:  python3 analyze_soplo.py $OUT --plot --temp <measured_K>"
