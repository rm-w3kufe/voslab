#!/bin/bash
# design: docs/plans/ergo_batches_adopted.vsm
# route: cli/manual — verify-runner batch (DISTILL batch-1 adopted)
# Agrupa los comandos de verificacion repetidos del triage (pytest/run_gates/check).
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-fast}"
case "$mode" in
  fast)
    python3 -m pytest system/kernel/tests -q
    ;;
  gates)
    python3 packages/framework/run_gates.py
    ;;
  full)
    "$0" fast
    "$0" gates
    ;;
  doc)
    python3 scripts/vsl/validator/check.py "${2:?usage: verify.sh doc <file.vsm>}"
    ;;
  *)
    echo "usage: verify.sh [fast|gates|full|doc <file.vsm>]" >&2
    exit 2
    ;;
esac
