#!/usr/bin/env bash
# Deploy covenant seed to LXC 107. Idempotent. Rollback: see DEPLOY.md.
set -euo pipefail
HERE="$(dirname "$0")"
pct push 107 "$HERE/package/covenant_cli.py" /opt/vsf-covenant/covenant_cli.py
pct exec 107 -- mkdir -p /opt/vsf-covenant
# (package tree pushed file-by-file below by deploy driver)
echo "stage 1 ok: cli staged"
