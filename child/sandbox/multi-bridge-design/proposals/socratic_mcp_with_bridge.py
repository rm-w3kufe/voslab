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
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add state-canon-mcp to path
sys.path.insert(0, "/home/rmw3/state-canon-mcp")
sys.path.insert(0, "/home/rmw3/state-canon-mcp/vendor")

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
        "/home/rmw3/vsf/child/TASKS.vsm"
    )
    provider = VsmStateProvider(vsm_path)
    bridge = MultiBridge()
    bridge.add_provider("agent-state", provider)
    return bridge


def main() -> int:
    # Resolve paths
    config_path = os.environ.get("SOCRATIC_BRIDGE_CONFIG")

    # Create multi-bridge
    bridge = load_multi_bridge(config_path)

    # Create MCP server
    # Note: SocraticMCP currently accepts a single provider.
    # We'll need to modify it to accept a bridge directly.
    # For now, create the engine and register the bridge manually.

    server = SocraticMCP()
    bridge.register(server.engine)

    # Update tools list to include canon_* tools
    canon_tools = [
        {"name": "socratic_canon_query", "description":
         "Query a data source through the multi-bridge: "
         "canon_query(domain, filter) → TRUE/UNKNOWN certified by evidence."},
        {"name": "socratic_canon_matches", "description":
         "Check if records match expected values: "
         "canon_matches(domain, filter, expected) → TRUE/FALSE."},
        {"name": "socratic_canon_field_equals", "description":
         "Check if a field equals expected value: "
         "canon_field_equals(domain, filter, field, expected)."},
        {"name": "socratic_canon_drift", "description":
         "Detect declared vs observed drift: "
         "canon_drift(domain, filter, declared_field, observed_field)."},
        {"name": "socratic_canon_domains", "description":
         "List all available domains across all providers."},
        {"name": "socratic_canon_providers", "description":
         "List all registered providers with their status."},
    ]
    server._tools.extend(canon_tools)

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
