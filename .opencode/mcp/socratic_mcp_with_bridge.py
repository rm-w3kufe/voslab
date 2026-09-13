#!/usr/bin/env python3
"""socratic_mcp_with_bridge — socratic-engine MCP server with multi-bridge support.

Runs the socratic-engine MCP server with multiple data source bridges:
  - VsmStateProvider (TASKS.vsm)
  - SshSqliteProvider (state.db via SSH)
  - VsmDocProvider (VSM documentation filesystem)

Usage:
    python3 socratic_mcp_with_bridge.py

Environment variables:
    SOCRATIC_STATE_VSM     — path to TASKS.vsm (default: child/TASKS.vsm)
    SOCRATIC_STATE_FOCUS   — path to current_focus.json (optional)
    SOCRATIC_BRIDGE_CONFIG — path to bridge_config.json (optional)
    RSI_METRICS_DIR        — path to RSI metrics directory (default: scripts/state/monitoring)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Configure RSI metrics directory (Phase P1: real data feed)
# Default: scripts/state/monitoring/ in the repo root
_rsi_metrics_dir = os.environ.get(
    "RSI_METRICS_DIR",
    str(Path(__file__).parent.parent / "scripts" / "state" / "monitoring")
)
os.environ["RSI_METRICS_DIR"] = _rsi_metrics_dir

# Add state-canon-mcp to path
_state_canon = Path(os.environ.get("STATE_CANON_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent / "state-canon-mcp")))
sys.path.insert(0, str(_state_canon))
sys.path.insert(0, str(_state_canon / "vendor"))
# Add vOSlab to path for local providers
_voslab = Path(os.environ.get("VOSLAB_PATH",
    str(Path(__file__).resolve().parent.parent.parent)))
sys.path.insert(0, str(_voslab))

from instances.tasks_provider import VsmStateProvider
from socratic_engine.engine import SocraticEngine
from socratic_engine.tree import SocraticTreeBuilder
from socratic_engine.mcp_server import SocraticMCP, RateLimiter


def load_multi_bridge(config_path: str | None = None):
    """Load multi-bridge from config or fall back to single provider."""
    from socratic_engine.multi_bridge import MultiBridge

    # Try config file
    if config_path is None:
        config_path = os.environ.get("SOCRATIC_BRIDGE_CONFIG")

    if config_path and Path(config_path).exists():
        bridge = MultiBridge.from_config(config_path)
        return bridge

    # Fallback: single provider (backward compatible)
    vsm_path = os.environ.get(
        "SOCRATIC_STATE_VSM",
        str(_voslab / "current_focus.json")
    )
    provider = VsmStateProvider(vsm_path)
    bridge = MultiBridge()
    bridge.add_provider("agent-state", provider)
    return bridge


def main() -> int:
    # Resolve config path
    config_path = os.environ.get(
        "SOCRATIC_BRIDGE_CONFIG",
        str(_voslab / "bridge_config.json")
    )

    # Create multi-bridge
    bridge = load_multi_bridge(config_path)

    # Create MCP server — pass bridge so constructor adds canon_* tools
    # WITH inputSchema (MCP spec requirement)
    server = SocraticMCP(multi_bridge=bridge)

    # Run stdio loop
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = server.handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
