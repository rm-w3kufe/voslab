#!/usr/bin/env bash
# bootstrap.sh — deploy/setup vOSLAB on a target host (idempotent).
# Transport is git; this script makes the clone self-booting:
#   venv + deps + verify gate-suite, and (optionally) resolve external pins.
#
# Usage:
#   ./bootstrap.sh            # setup vOSLAB (venv + deps + test)
#   ./bootstrap.sh --with-packages   # also resolve external ~/packages/* pins (pins.toml)
#
# R1 (locality): run this ON the target (e.g. inside an LXC), never build on WSL.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_ROOT/.venv"
PYTHON="${PYTHON:-python3}"

echo "== vOSLAB bootstrap @ $REPO_ROOT =="

# 1. virtualenv (isolated, target-local)
if [ ! -d "$VENV" ]; then
  echo "-- creating venv"
  "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 2. dependencies
echo "-- installing deps"
pip install -q --upgrade pip
pip install -q pytest
pip install -q -e "$REPO_ROOT"

# 3. (optional) resolve external package pins into ~/packages + link into vOSLAB
if [ "${1:-}" = "--with-packages" ]; then
  echo "-- resolving external pins (pins.toml)"
  if [ -f "$REPO_ROOT/scripts/resolve_pins.py" ]; then
    "$PYTHON" "$REPO_ROOT/scripts/resolve_pins.py" "$REPO_ROOT/pins.toml"
  else
    echo "   (resolve_pins.py not present yet — extraction phase pending; skipping)"
  fi
fi

# 4. verify the NERVES are alive
echo "-- verifying gate-suite (negative-control harness)"
"$PYTHON" -m pytest -q

echo "== vOSLAB bootstrap OK =="
