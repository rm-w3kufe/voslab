#!/bin/bash
# Start opsroom API on :8081 — φ↑ aggregation hub
set -e
cd ~/vsf
pip3 install --break-system-packages -q fastapi uvicorn pyyaml httpx
echo "Starting opsroom on http://localhost:8081 ..."
python3 -m uvicorn opsroom.api:app --port 8081 --host 127.0.0.1 --reload