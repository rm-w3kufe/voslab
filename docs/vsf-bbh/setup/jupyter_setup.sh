#!/usr/bin/env bash
# vsf-bbh — JupyterLab setup via uv
# Target: kali-n02 (Proxmox LXC)
# Run as: bash jupyter_setup.sh
# Idempotent: safe to re-run

set -euo pipefail

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_BASE="$HOME/.venvs"
JUPYTER_DATA="$HOME/.local/share/jupyter"

# ── 1. Install uv ────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo "[uv] Installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$PATH"
  echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc
fi
echo "[uv] $(uv --version)"

# ── 2. Create venvs ──────────────────────────────────────────────────────────
mkdir -p "$VENV_BASE"

for kernel in base cybersec vsf testing; do
  venv="$VENV_BASE/$kernel"
  req="$SETUP_DIR/requirements/$kernel.txt"

  if [ ! -d "$venv" ]; then
    echo "[venv] Creating $kernel..."
    uv venv "$venv" --python 3.12
  else
    echo "[venv] $kernel already exists — updating"
  fi

  echo "[pip] Installing $kernel requirements..."
  uv pip install --python "$venv/bin/python" -r "$req"
done

# ── 3. Register Jupyter kernels ──────────────────────────────────────────────
mkdir -p "$JUPYTER_DATA/kernels"

declare -A DISPLAY_NAMES=(
  [base]="Python (base)"
  [cybersec]="Python (cybersec)"
  [vsf]="Python (vsf)"
  [testing]="Python (testing)"
)

for kernel in base cybersec vsf testing; do
  venv="$VENV_BASE/$kernel"
  echo "[kernel] Registering $kernel..."
  "$venv/bin/python" -m ipykernel install \
    --user \
    --name "$kernel" \
    --display-name "${DISPLAY_NAMES[$kernel]}"
done

# ── 4. Install Ollama + Qwen2.5 (S3* audit layer) ───────────────────────────
if ! command -v ollama &>/dev/null; then
  echo "[ollama] Installing..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
echo "[ollama] $(ollama --version)"

if ! ollama list 2>/dev/null | grep -q "qwen2.5"; then
  echo "[ollama] Pulling qwen2.5..."
  ollama pull qwen2.5
else
  echo "[ollama] qwen2.5 already present"
fi

# ── 5. Install JupyterLab in base (server lives here) ────────────────────────
echo "[jupyterlab] Installing in base venv..."
uv pip install --python "$VENV_BASE/base/bin/python" jupyterlab

# ── 5. Configure JupyterLab ──────────────────────────────────────────────────
JUPYTER_CONFIG_DIR="$HOME/.jupyter"
mkdir -p "$JUPYTER_CONFIG_DIR"

cat > "$JUPYTER_CONFIG_DIR/jupyter_lab_config.py" << 'EOF'
c.ServerApp.ip = '0.0.0.0'
c.ServerApp.port = 8888
c.ServerApp.open_browser = False
c.ServerApp.token = ''
c.ServerApp.password = ''
c.ServerApp.allow_remote_access = True
c.ServerApp.root_dir = '/root'
EOF

echo ""
echo "┌─────────────────────────────────────────┐"
echo "│  vsf-bbh JupyterLab setup complete      │"
echo "│                                         │"
echo "│  Kernels: base | cybersec | vsf | test  │"
echo "│  Start:   ~/.venvs/base/bin/jupyter lab │"
echo "│  URL:     http://kali-n02:8888          │"
echo "└─────────────────────────────────────────┘"
