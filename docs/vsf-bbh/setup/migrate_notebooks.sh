#!/usr/bin/env bash
# vsf-bbh — migrate notebooks from Parrot disk
# Requires: Parrot disk mounted at /mnt/parrot
# Run as: bash migrate_notebooks.sh

set -euo pipefail

PARROT_HOME="/mnt/parrot/@home/rmw3"
BBH_TARGET="$HOME/vsf-bbh/notebooks"

# ── Verify mount ─────────────────────────────────────────────────────────────
if [ ! -d "$PARROT_HOME" ]; then
  echo "ERROR: Parrot disk not mounted at /mnt/parrot"
  echo "Run: sudo mount /dev/sde2 /mnt/parrot"
  exit 1
fi

mkdir -p "$BBH_TARGET/archive/vsm"
mkdir -p "$BBH_TARGET/archive/bbh"
mkdir -p "$BBH_TARGET/archive/training"
mkdir -p "$BBH_TARGET/active"

# ── VSM notebooks (archivo — material teórico) ────────────────────────────────
echo "[migrate] VSM notebooks..."
cp -r "$PARROT_HOME/Notebooks/vsm/"*.ipynb "$BBH_TARGET/archive/vsm/" 2>/dev/null || true
cp -r "$PARROT_HOME/Notebooks/vsm/"*_log.json "$BBH_TARGET/archive/vsm/" 2>/dev/null || true
cp "$PARROT_HOME/Notebooks/vsm/vsm_telemetry.jsonl" "$BBH_TARGET/archive/vsm/" 2>/dev/null || true

# ── BBH notebooks ─────────────────────────────────────────────────────────────
echo "[migrate] BBH notebooks..."
cp -r "$PARROT_HOME/bbh/notebooks/"* "$BBH_TARGET/archive/bbh/" 2>/dev/null || true

# ── Training material (archivo) ───────────────────────────────────────────────
echo "[migrate] Training notebooks..."
cp "$PARROT_HOME/Notebooks/"*.ipynb "$BBH_TARGET/archive/training/" 2>/dev/null || true
cp "$PARROT_HOME/Notebooks/IBM_Labs/"*.ipynb "$BBH_TARGET/archive/training/" 2>/dev/null || true

# ── BBH state + telemetry (histórico) ─────────────────────────────────────────
echo "[migrate] BBH telemetry + state..."
mkdir -p "$BBH_TARGET/archive/telemetry"
cp "$PARROT_HOME/bbh/state_snapshot.json" "$BBH_TARGET/archive/telemetry/" 2>/dev/null || true
cp -r "$PARROT_HOME/bbh/telemetry/"* "$BBH_TARGET/archive/telemetry/" 2>/dev/null || true
cp "$PARROT_HOME/bbh/stride_history.jsonl" "$BBH_TARGET/archive/telemetry/" 2>/dev/null || true
cp "$PARROT_HOME/bbh/_SESSION_SUMMARY.md" "$BBH_TARGET/archive/telemetry/" 2>/dev/null || true

# ── Tool configs (mantener calibración) ───────────────────────────────────────
echo "[migrate] Tool configs..."
mkdir -p "$BBH_TARGET/archive/configs"
cp -r "$PARROT_HOME/bbh/targets/" "$BBH_TARGET/archive/configs/targets/" 2>/dev/null || true

echo ""
echo "┌─────────────────────────────────────────┐"
echo "│  Migration complete                     │"
echo "│                                         │"
echo "│  archive/vsm/      ← VSM notebooks      │"
echo "│  archive/bbh/      ← BBH notebooks      │"
echo "│  archive/training/ ← IBM + training     │"
echo "│  archive/telemetry/← state + history    │"
echo "│  archive/configs/  ← tool configs       │"
echo "│  active/           ← nueva implementación│"
echo "└─────────────────────────────────────────┘"
