#!/usr/bin/env bash
# design: projects/arc-prize/arc_prize_design.vsm
# Run diario AGI-2: rebuild + push kernel + espera COMPLETE + scoring.
# GASTA la diaria. Si ya hay submit hoy, aborta (protege la diaria).
# Uso: ./daily.sh "mensaje"   (credenciales: ~/.kaggle — durables)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export KAGGLE_CONFIG_DIR="${KAGGLE_CONFIG_DIR:-$HOME/.kaggle}"
KG="$HOME/.local/share/kaggle/venv/bin/kaggle"
COMP=arc-prize-2026-arc-agi-2
KERNEL=rmw3kufe/arc-agi-2-solver-v1-symbolic
MSG="${1:-daily run}"
TODAY=$(date -u +%Y-%m-%d)
if "$KG" competitions submissions -c "$COMP" 2>/dev/null | grep -q "$TODAY"; then
  echo "ABORT: ya hay submit hoy ($TODAY). Revisar antes de gastar manana."
  exit 1
fi
VER=$("$HERE/push.sh" 2>&1 | grep -oP 'Kernel version \K[0-9]+' | head -n 1)
[ -n "$VER" ] || { echo "ABORT: push sin version"; exit 1; }
echo "kernel v$VER pusheado, esperando COMPLETE..."
for _ in $(seq 1 30); do
  ST=$("$KG" kernels status "$KERNEL" 2>/dev/null | grep -oP '".*?"' | tail -n 1 || true)
  echo "  status: $ST"
  case "$ST" in *COMPLETE*) break;; *FAILED*|*ERROR*) echo "ABORT: kernel fallo"; exit 1;; esac
  sleep 60
done
# el submission.json del run vive en el output del kernel: descargar y copiar
TMPD=$(mktemp -d)
"$KG" kernels output "$KERNEL" -p "$TMPD" >/dev/null 2>&1 || { echo "ABORT: sin output"; exit 1; }
[ -f "$TMPD/submission.json" ] || { echo "ABORT: output sin submission.json"; exit 1; }
cp "$TMPD/submission.json" "$HERE/submission.json"
"$KG" competitions submit -c "$COMP" -k "$KERNEL" -v "$VER" \
  -f "$HERE/submission.json" -m "$MSG"
echo "diaria gastada. Ver score: kernels status / competitions submissions."
