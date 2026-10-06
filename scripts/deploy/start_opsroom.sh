#!/bin/bash
# Start opsroom API on :8081 — φ↑ aggregation hub
# S5 external-paths 2026-10-06: cd repointed ~/vsf → ~/vOSlab.
# NOTE: opsroom.api is NOT in this tree — the live API runs on n02
# (HANDOFF restart cmd, port 8080); local start fails until the API is
# ported here. See backlog D-26.
set -e
cd ~/vOSlab
pip3 install --break-system-packages -q fastapi uvicorn pyyaml httpx
echo "Starting opsroom on http://localhost:8081 ..."
python3 -m uvicorn opsroom.api:app --port 8081 --host 127.0.0.1 --reload