#!/usr/bin/env bash
# covenant_preflight.sh — baseline de convergencia pre-promoción (solo lectura).
#
# Verifica las 4 patas independientes del hash covenant:
#   1. disco:      sha256 de docs/governance/covenant.vsm (upstream repo)
#   2. policy:     _meta.covenant_hash en core/s5_policy.default.json
#   3. compilado:  COVENANT_SHA256 embebido en el binario desplegado (n02)
#   4. publicado:  https://vsf.u2738.org/covenant.hash
# Exit 0 = convergen las legibles; exit 1 = divergencia o fuente ilegible.
# Nunca escribe nada (ni /root, ni repos, ni red salvo GET https).
set -u

VSF="${VSF_ROOT:-/home/rmw3/vsf}"
N02="ssh -o ConnectTimeout=8 -o BatchMode=yes n02"
PASS=0; FAIL=0

say() { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "  OK   $*"; }
bad()  { FAIL=$((FAIL+1)); say "  DIVERGE/UNREADABLE $*"; }

DISK=""; POLICY=""; BUILT=""; PUB=""

# 1. disco (repo upstream, solo lectura)
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

# 3. compilado (binario en n02) + estado del servicio nucleus
BUILT=""
BSVC="state=$($N02 'systemctl show vsf-nucleus-operational.service -p ActiveState --value' 2>/dev/null)"
say "nucleus-service: ${BSVC:-unknown}"
BHASHES="$($N02 "strings /usr/local/bin/vsf-nucleus 2>/dev/null | grep -oE '[0-9a-f]{64}' | sort -u | grep -v -E '^(0+|f+|0123456789abcdef|.*(010203|1234567890))' | head -n 5" 2>/dev/null)"
if echo "$BHASHES" | grep -q .; then
  BUILT="$(echo "$BHASHES" | head -n 1 | tr -d '\r')"
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
