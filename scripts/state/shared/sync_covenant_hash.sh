#!/bin/bash
# sync_covenant_hash.sh — propagate a covenant promotion to the MUTABLE class only.
#
# Dry-run by default; --apply to write. Runs from ANY cwd.
#
# 2026-09-30 FND-SYNC-COVENANT-DRIFT-01: the promotion corpus lives in the
# UPSTREAM ~/vsf tree (governance/, core/ policy JSON, registry) — vOSlab
# holds a working copy of the TOOL, not the corpus. Paths bind to VSF_ROOT
# (same pattern as scripts/ops/covenant_preflight.sh); the old in-repo
# ROOT=../.. resolved to scripts/ and every target was dead.
#
# Registry:  ~/vsf/docs/spec/covenant_hash_registry.vsm  (read it before running)
# Audit:     scripts/state/attestation/verify_covenant_hash.py (run it after)
#
# WHAT THIS DELIBERATELY DOES NOT DO
# ----------------------------------
# It does NOT sed every occurrence of the old hash. Seven-plus of them are
# PROVENANCE HEADERS -- "this experiment ran under covenant sha dde12ead..."
# -- recording which constitution was in force when a result was produced.
# Rewriting those to the new hash would claim the experiments ran under a
# covenant that did not exist yet. That is falsification, not synchronisation,
# and it is the exact failure a naive "propagate uniformly" script produces.
# The provenance paths are hard-refused below.
#
# It does NOT touch .primer_sources_manifest.json either. That baseline is
# owned by verify_boot_primer.py --update, which must run only after a human
# re-reads the primer against the changed covenant (R4). Updating it here
# would convert a verification gate into a rubber stamp.
#
# ORDER MATTERS
# -------------
# The published canonical (vsf.u2738.org/covenant.hash) goes LAST, by hand.
# Until it changes, every node still fails closed against the old covenant
# rather than accepting an unannounced one. Publishing first would open a
# window where a node accepts a covenant nobody has verified.

set -euo pipefail

VSF="${VSF_ROOT:-/home/rmw3/vsf}"
CANONICAL="$VSF/docs/governance/covenant.vsm"
POLICY="$VSF/core/s5_policy.default.json"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

# Paths whose hash is a historical record. Never rewritten.
# (Paths are vsf-tree-relative — they are echoed as documentation of the
#  refusal policy; the only file ever written is $POLICY above.)
PROVENANCE_REFUSE=(
  "docs/experiments/"
  "docs/deploy/"
  "docs/spec/s5_lm_wire/"
  "system/boot/.primer_sources_manifest.json"
  "TASKS.vsm"
)

[[ -r "$CANONICAL" ]] || { echo "✗ canonical covenant not found: $CANONICAL"; exit 1; }

NEW="$(sha256sum "$CANONICAL" | cut -d' ' -f1)"
OLD="$(grep -oE '"covenant_hash"[[:space:]]*:[[:space:]]*"[0-9a-f]{64}"' "$POLICY" \
       | grep -oE '[0-9a-f]{64}' | head -1)"

echo "  canonical : $VSF/docs/governance/covenant.vsm"
echo "  old hash  : ${OLD:0:16}…"
echo "  new hash  : ${NEW:0:16}…"
echo

if [[ "$OLD" == "$NEW" ]]; then
  echo "  ✓ nothing to do — s5_policy already matches the covenant on disk."
  echo "    (If you expected a change, the covenant was not edited.)"
  exit 0
fi

echo "  MUTABLE — will be updated:"
echo "    core/s5_policy.default.json  _meta.covenant_hash"
echo
echo "  REFUSED — provenance / tool-managed, left untouched:"
for p in "${PROVENANCE_REFUSE[@]}"; do echo "    $p"; done
echo
echo "  MANUAL, after this and in this order:"
echo "    1. rebuild the nucleus on LXC 108   (build.rs re-derives COVENANT_SHA256)"
echo "    2. deploy                            (scripts/deploy/deploy_bundle.sh)"
echo "    3. publish LAST: echo -n $NEW > covenant.hash → vsf.u2738.org"
echo "    4. python3 scripts/state/attestation/verify_covenant_hash.py --remote"
echo

if [[ $APPLY -eq 0 ]]; then
  echo "  DRY RUN — nothing written. Re-run with --apply."
  exit 0
fi

cp "$POLICY" "$POLICY.bak.$(date +%Y%m%d%H%M%S)"
python3 - "$POLICY" "$OLD" "$NEW" <<'PY'
import json, sys, pathlib
p, old, new = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
t = p.read_text()
if t.count(old) != 1:
    sys.exit(f"✗ expected exactly 1 occurrence of the old hash in "
             f"{p.name}, found {t.count(old)} — aborting rather than "
             f"guessing which one is the operational literal.")
p.write_text(t.replace(old, new))
print(f"  ✓ {p.name} updated")
PY

echo
echo "  Now run the 4 manual steps above. The system is INCONSISTENT until"
echo "  step 3 — that is intentional: nodes fail closed against the old"
echo "  covenant meanwhile, which is the safe direction."
