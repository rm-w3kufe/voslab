#!/usr/bin/env bash
# sync_to_114.sh — repo analysis/ → LXC 114 (jupyter-lab, /root/fierro_analysis/)
# Rota conocida (2026-10-09): entrada n02-hop de ~/.ssh/config rota (túnel 2290);
# ruta funcional = ProxyJump n01,n02 directo, INTERMITENTE (banner timeouts).
# Estrategia: una sola conexión SSH por lote (tar pipe), backoff 8s, 4 intentos.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DOCS="$(cd "$HERE/../../.." && pwd)"
DEST="root@10.10.40.120"
SSHOPT=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o ProxyJump=n01,n02)

retry() {
  local desc="$1"; shift
  for i in 1 2 3 4; do
    if "$@"; then echo "OK: $desc"; return 0; fi
    echo "FAIL($i/4): $desc" >&2
    sleep 8
  done
  echo "GIVE UP: $desc" >&2
  return 1
}

# 1) carpeta analysis/ (notebooks + data local) — glob resuelto DESPUÉS del cd
retry "analysis/ → /root/fierro_analysis/" \
  bash -c "cd '$HERE' && tar -czf - . data | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'mkdir -p /root/fierro_analysis/data && tar -C /root/fierro_analysis -xzf -'" || exit 1

# 2) fuentes LaTeX (main.tex + addendum.tex) → data/
retry "tex sources → data/" \
  bash -c "tar -C '$DOCS/papers/attractor_convergence' -czf - main.tex | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis/data -xzf -'" || exit 1
retry "addendum.tex → data/" \
  bash -c "tar -C '$DOCS/correspondence/fierro/addendum_omega' -czf - addendum.tex | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis/data -xzf -'" || exit 1

# 2b) NB03 inputs: depth.py (canon) → raíz analysis/114; carta + proposal → data/
REPO="$(cd "$DOCS/.." && pwd)"
retry "depth.py (analytic_engine canon) → /root/fierro_analysis/" \
  bash -c "tar -C '$REPO/packages/public/analytic_engine' -czf - depth.py | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis -xzf -'" || exit 1
retry "carta_acompanamiento.md → data/" \
  bash -c "tar -C '$DOCS/correspondence/fierro/addendum_omega' -czf - carta_acompanamiento.md | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis/data -xzf -'" || exit 1
retry "claim_ingest_proposal.vsm → data/" \
  bash -c "tar -C '$REPO/docs/plans' -czf - claim_ingest_proposal.vsm | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis/data -xzf -'" || exit 1

# 2c) NB07 inputs: operator.rs (constantes deployed) → data/
retry "operator.rs → data/" \
  bash -c "tar -C '$REPO/projects/vsf-nucleus/src' -czf - operator.rs | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis/data -xzf -'" || exit 1

# 2d) NB07 L4: results.vsm de cada experimento → data/experiments/<dir>/
retry "experiments results.vsm → data/experiments/" \
  bash -c "find '$DOCS/experiments' -mindepth 2 -maxdepth 2 -name results.vsm -printf '%P\n' | tar -C '$DOCS/experiments' -czf - -T - | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'mkdir -p /root/fierro_analysis/data/experiments && tar -C /root/fierro_analysis/data/experiments -xzf -'" || exit 1

# 2e) NB07 L5: paper_data.vsm (fresco, raíz del repo) + patterns.py → data/
retry "paper_data.vsm → data/ (fresco)" \
  bash -c "tar -C '$DOCS/papers/attractor_convergence' -czf - paper_data.vsm | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis/data -xzf -'" || exit 1
retry "patterns.py → data/" \
  bash -c "tar -C '$REPO/packages/framework/claim_ingest/extract' -czf - patterns.py | ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=n01,n02 root@10.10.40.120 'tar -C /root/fierro_analysis/data -xzf -'" || exit 1

# 3) verificación
retry "verify listing" \
  ssh "${SSHOPT[@]}" "$DEST" 'ls -la /root/fierro_analysis/ /root/fierro_analysis/data/' || exit 1

echo "synced → /root/fierro_analysis/ (LXC 114)"
