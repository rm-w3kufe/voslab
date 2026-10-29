#!/bin/bash
# run_bg.sh — wrapper canonico de jobs background (T9-F2, plan structural-tensions 2026-10-20).
# design: system/boot/core_boot_primer.vsm (seccion ops_background)
# route: core_boot_primer §ops_background — la convencion background vive en el primer;
#        este wrapper es su mecanizacion (systemd-run transient + markers fail-loud)
# verify: bash -n + smoke real con sleep 1 (marker .done esperado, T9-F2);
#         jobs reales verifican via journalctl --user -u vosbg-<name> + marker
#
# Uso: run_bg.sh <name> <cmd> [args...]
#   name : identificador — unit transient vosbg-<name>, markers
#          /tmp/opencode/<name>.{done,failed} (usar nombre unico por corrida,
#          p.ej. con fecha; este wrapper NUNCA borra markers previos, R17)
#   cmd  : comando a ejecutar (sobrevive la sesion; detalle en
#          journalctl --user -u vosbg-<name>)
# Convencion completa (retry law T10, ∄nohup): core_boot_primer §ops_background.
NAME="${1:?usage: run_bg.sh <name> <cmd> [args...]}"; shift
CMD="$*"
MK=/tmp/opencode
DONE="$MK/$NAME.done"; FAILED="$MK/$NAME.failed"
mkdir -p "$MK"
if systemctl --user list-units "vosbg-$NAME.service" --no-legend 2>/dev/null | grep -q running; then
  echo "REFUSED: vosbg-$NAME ya esta corriendo (¬duplicar job)" >&2
  exit 1
fi
systemd-run --user --unit="vosbg-$NAME" --collect \
  bash -c "$CMD; rc=\$?; ts=\$(date -u +%FT%TZ); \
    if [ \$rc -eq 0 ]; then echo \"\$ts rc=0\" > '$DONE'; \
    else printf '%s rc=%s (detalle: journalctl --user -u vosbg-%s)\n' \"\$ts\" \"\$rc\" '$NAME' > '$FAILED'; fi" \
  >/dev/null
echo "launched vosbg-$NAME (markers: $DONE | $FAILED)"
