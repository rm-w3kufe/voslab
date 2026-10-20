#!/bin/bash
# vsf-scheduled-suite.sh — S3 guardia horaria (SHADOW-SCHEDULED-SUITE-1).
# design: docs/spec_revision/design-sources/shadow-scheduled-suite-design.vsm
# Ciclo: run_gates (86+27) + variety_census + external_detectors run.
# Alertas algedónicas y shadow-x7 viven en el motor python; aquí sólo
# entorno + journal. Pair: vsf-scheduled-suite.{service,timer} (user units).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export KAGGLE_CONFIG_DIR="${KAGGLE_CONFIG_DIR:-$HOME/.kaggle}"
exec python3 "$REPO_ROOT/scripts/state/monitoring/scheduled_suite.py"
