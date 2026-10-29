#!/usr/bin/env bash
# design: docs/design/sources/r16-spec-v1/LEARNING-CYCLE-INSTRUMENTS-DESIGN.vsm
# CLAIM: LEARNING-CYCLE-AUTO-TRIGGER-2026-08-16 executed — the learning
# cycle (learning_cycle.vsm §1 loop: detect→classify→persist→fix→verify)
# gets its AUTOMATIC TRIGGER. Recursivity (rmw3 2026-08-16): "todo lo
# automatizable tiene que ir con hook, eso mismo tiene que ser un hook" —
# the instrument that forces the cycle is itself part of the cycle.
#
# What it does (SessionEnd + pre-commit):
#   (a) If learning_records/.pending/ contains a .vsm draft → a learning
#       was detected this session and NOT persisted (no IR) → BLOCK.
#   (b) A commit that touches TASKS.vsm / session close MUST either have
#       registered its learnings as IRs or explicitly deferred them
#       (trace.deferral.deferred: true). The scan looks for a marker:
#       pending drafts are placed by the S3 agent when a learning is
#       detected (echo "learning:" > .pending/<name>.vsm) and converted
#       to a real IR before session close.
#   (c) pass → no pending learnings → PASS.
#   (d) fail → a deliberately-placed pending draft BLOCKS (must exit
#       non-zero — discriminates).
#
# CWD-independent: derives ROOT from the script location (BASH_SOURCE).
set -u
MODE="${1:-pass}"
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
PENDING="$ROOT/docs/learning_records/.pending"

fail() { echo "FAIL: $*" >&2; exit 1; }

[ -d "$PENDING" ] || { echo "PASS: no pending learning drafts (dir absent)"; exit 0; }
mapfile -t DRAFTS < <(find "$PENDING" -name '*.vsm' 2>/dev/null | sort)
[ "${#DRAFTS[@]}" -gt 0 ] || { echo "PASS: no pending learning drafts"; exit 0; }

if [ "$MODE" = "fail" ]; then
  # fail-mode: any pending draft → discriminates (must NOT pass)
  if [ "${#DRAFTS[@]}" -gt 0 ]; then
    echo "FAIL: pending drafts found (discriminates)" >&2
    exit 1
  fi
  echo "PASS: no drafts in fail mode (unexpected — no discrimination)"
  exit 0
fi

echo "" >&2
echo "❌ VSF learning-cycle guard: aprendizajes detectados en sesión SIN " >&2
echo "    registrar (IR pendiente). El ciclo exige: detect → classify → " >&2
echo "    persist. Cada aprendizaje debe tener su IR en " >&2
echo "    learning_records/ (o deferral explícito trace.deferral.deferred)." >&2
echo "    Bloqueando commit/session-close. Drafts pendientes:" >&2
for d in "${DRAFTS[@]}"; do
  echo "      $d" >&2
done
echo "" >&2
echo "    Fix: convertir cada draft en IR completo con el formato v2 " >&2
echo "    (learning_record() + vsm-1.2 — campos: uuid, parent, family, " >&2
echo "    class, severity, detection, root_cause, organ, recursion, " >&2
echo "    canonical, evidence, lesson, action, trace, propagation) y " >&2
echo "    moverlo a learning_records/. Si el aprendizaje no aplica, " >&2
echo "    eliminar el draft (decisión documentada, R9)." >&2
exit 1