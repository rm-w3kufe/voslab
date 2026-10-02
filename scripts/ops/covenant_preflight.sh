#!/usr/bin/env bash
# covenant_preflight.sh — pre-promotion convergence baseline (read-only).
#
# Verifies the 4 independent legs of the covenant hash:
#   1. disco:      sha256 de docs/governance/covenant.vsm (port local; VSF_ROOT=upstream override)
#   2. policy:     _meta.covenant_hash en core/s5_policy.default.json
#   3. compilado:  COVENANT_SHA256 embebido en el binario desplegado (n02)
#   4. publicado:  https://vsf.u2738.org/covenant.hash
# Exit 0 = the readable legs converge; exit 1 = divergence or unreadable source.
# Never writes anything (not /root, not repos, no network except GET https).
set -u

# Local-first 2026-10-02 (transición de decomisión ~/vsf): por defecto valida
# los witness portados en vOSlab; VSF_ROOT=~/vsf sigue soportado para las
# piernas que aún viven en el upstream (compilado n02 no depende de esto).
VLAB="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
VSF="${VSF_ROOT:-$VLAB}"
N02_HOST="${VSF_N02:-n02}"
N02="ssh -o ConnectTimeout=8 -o BatchMode=yes $N02_HOST"
PASS=0; FAIL=0

# D-05: LXC container id from the single source of truth (fail loud, no default)
TOPO_JSON="$VLAB/system/instance/lxc_topology.json"
NUCLEUS_LXC="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['anchors']['nucleus'])" "$TOPO_JSON")" || {
  echo "FATAL: cannot read anchor 'nucleus' from $TOPO_JSON" >&2; exit 1; }

say() { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "  OK   $*"; }
bad()  { FAIL=$((FAIL+1)); say "  DIVERGE/UNREADABLE $*"; }

DISK=""; POLICY=""; BUILT=""; PUB=""

# 1. disco (repo local portado; VSF_ROOT apunta al upstream durante la transición)
if [ -f "$VSF/docs/governance/covenant.vsm" ]; then
  DISK="$(sha256sum "$VSF/docs/governance/covenant.vsm" | cut -d' ' -f1)"
  say "disk:     ${DISK:0:16}…"
else
  bad "disco: no existe $VSF/docs/governance/covenant.vsm"
fi

# 2. policy (literal operativo)
if [ -f "$VSF/core/s5_policy.default.json" ]; then
  POLICY="$(python3 -c "import json,sys; print(json.load(open('$VSF/core/s5_policy.default.json')).get('_meta',{}).get('covenant_hash',''))" 2>/dev/null)"
  if [ -n "$POLICY" ]; then say "policy:   ${POLICY:0:16}…"; else bad "policy: sin _meta.covenant_hash"; fi
else
  bad "policy: no existe $VSF/core/s5_policy.default.json"
fi

# 3. built (binary on LXC 101, unit vsf-nucleus-operational) + service state
#    (2026-10-02: antes apuntaba a n02 host + /usr/local/bin/vsf-nucleus —
#     nunca existieron ahí; el binario vivo es /root/vsf-nucleus-operational
#     servido por /root/nucleus-wrapper.sh dentro de LXC 101, vía pct en n02)
BUILT=""
BSVC="state=$($N02 "pct exec $NUCLEUS_LXC -- systemctl show vsf-nucleus-operational.service -p ActiveState --value" 2>/dev/null)"
say "nucleus-service: ${BSVC:-unknown}"
BHASHES="$($N02 "pct exec $NUCLEUS_LXC -- strings /root/vsf-nucleus-operational 2>/dev/null | grep -oE '[0-9a-f]{64}' | sort -u | grep -v -E '^(0+|f+|0123456789abcdef|.*(010203|1234567890))' | head -n 5" 2>/dev/null)"
if echo "$BHASHES" | grep -q .; then
  # Semántica correcta: "el binario lleva el vigente" = DISK embebido en el
  # binario (los otros hex64 del binario son artefactos de datos, no el
  # covenant; antes tomábamos el primer candidato y divagaba).
  if [ -n "$DISK" ] && echo "$BHASHES" | grep -qx "$DISK"; then
    BUILT="$DISK"
  else
    BUILT="$(echo "$BHASHES" | head -n 1 | tr -d '\r')"
  fi
  say "built candidates (no ceros/vectores):"
  echo "$BHASHES" | sed 's/^/    /'
else
  bad "compilado: sin hash real en binario (build vieja o servicio muerto)"
fi

# 4. publicado (GET https, 10s)
PUB="$(curl -sS --max-time 10 https://vsf.u2738.org/covenant.hash 2>/dev/null | tr -d ' \r\n')"
if echo "$PUB" | grep -qE '^[0-9a-f]{64}$'; then say "published:${PUB:0:16}…"; else bad "publicado: no es sha64 (red o URL)"; fi

# convergencia entre legibles (disco/policy/publicado deben coincidir)
echo "--- convergencia ---"
SEEN=""
for v in "$DISK" "$POLICY" "$PUB"; do
  [ -z "$v" ] && continue
  case "$SEEN" in
    "") SEEN="$v" ;;
    *) if [ "$v" != "$SEEN" ]; then bad "difieren: ${SEEN:0:16}… vs ${v:0:16}…"; fi ;;
  esac
done
# pata compilada: coincide, o ausencia conocida (servicio muerto ->
# rebuild en LXC108 forma parte de la promocion, no es sorpresa).
# Servicio ACTIVO con hash distinto SI seria divergencia real.
if [ -n "$BUILT" ]; then
  if [ "$BUILT" = "$SEEN" ]; then
    ok "binario lleva el hash vigente"
  elif [ "$BSVC" = "state=active" ]; then
    bad "servicio ACTIVO con hash distinto al vigente"
  else
    say "  NOTE  pata compilada ausente (servicio muerto, binario viejo):"
    say "        rebuild en LXC108 requerido en la promocion (paso 3)"
  fi
fi
if [ "$FAIL" -eq 0 ]; then ok "todas las patas legibles convergen"; fi

echo "--- resumen: PASS=$PASS FAIL=$FAIL ---"
[ "$FAIL" -eq 0 ]
