#!/usr/bin/env bash
# design: projects/arc-prize/arc_prize_design.vsm
# Push AGI-2 solver kernel to Kaggle (Fase A: valida ejecucion).
# NO puntua, NO gasta la diaria. El scoring es click/API aparte (S5).
# Credenciales DURABLES: ~/.kaggle/kaggle.json (600) + venv en ~/.local.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SOLVER="$(cd "$HERE/.." && pwd)"
KGHOME="${HOME}/.local/share/kaggle/venv/bin"
export KAGGLE_CONFIG_DIR="${KAGGLE_CONFIG_DIR:-$HOME/.kaggle}"
"$SOLVER/build_notebook.py" --out "$HERE/kaggle_notebook.ipynb"
"$KGHOME/python" -m kaggle kernels push -p "$HERE"
echo "--- siguiente (manual S5): Submit to Competition en la pagina del kernel ---"
