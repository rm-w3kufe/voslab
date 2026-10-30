#!/usr/bin/env bash
# Ax_TraceabilityClosure gate (COVENANT-V04.code).
# Verifies every NON-pending `enforced_by:` entry in covenant_ops.vsm has a matching
# back-link `axiom_ref: covenant_ops.vsm#§regulation.<id>@<version>` in the referenced
# file. Bidirectional + version-pinned. Exit 1 if any link is broken (CI gate).
#
# Usage: scripts/audit/check_traceability.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OPS="$REPO/system/s5-policy/governance/covenant_ops.vsm"
VER="v0.1"

[ -f "$OPS" ] || { echo "covenant_ops.vsm not found: $OPS"; exit 2; }

fail=0; checked=0; pending=0
in_map=0
while IFS= read -r line; do
  trimmed="${line#"${line%%[![:space:]]*}"}"   # strip leading whitespace
  case "$trimmed" in
    enforced_by:*) in_map=1; continue ;;        # block header only (not mid-string mentions)
  esac
  [ "$in_map" = 1 ] || continue
  case "$trimmed" in
    gate:*|status:*) in_map=0; continue ;;
  esac
  id=$(printf '%s' "$line" | sed -n 's/^[[:space:]]*\([A-Za-z0-9_]\{1,\}\):.*/\1/p')
  target=$(printf '%s' "$line" | sed -n 's/[^"]*"\([^"]*\)".*/\1/p')
  [ -z "$id" ] && continue
  if [ "$target" = "pending" ]; then
    echo "  ◌ $id → pending (not yet enforced)"; pending=$((pending+1)); continue
  fi
  checked=$((checked+1))
  file="${target%%#*}"
  if [ ! -f "$REPO/$file" ]; then
    echo "  ✗ $id → $file  (file MISSING)"; fail=1; continue
  fi
  if grep -qF "axiom_ref: covenant_ops.vsm#§regulation.$id@$VER" "$REPO/$file"; then
    echo "  ✓ $id ↔ $file  (axiom_ref@$VER present)"
  else
    echo "  ✗ $id → $file  (no matching 'axiom_ref: ...#§regulation.$id@$VER' back-link)"; fail=1
  fi
done < "$OPS"

echo "── linked=$checked pending=$pending broken=$fail ──"
if [ "$fail" = 0 ]; then echo "TRACEABILITY OK"; else echo "TRACEABILITY BROKEN"; fi
exit $fail
