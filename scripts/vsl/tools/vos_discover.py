#!/usr/bin/env python3
"""
discover.py — Path discovery for vOS gate infrastructure.

Agent-agnostic: discovers workspace root regardless of agent name or path.

Discovery order:
1. VOS_ROOT environment variable (explicit override)
2. .vos-marker file in current directory or parents
3. Git root (if in a git repo)
4. Script location fallback

Usage:
    from vos_discover import discover_root, discover_registry, discover_gates
    
    root = discover_root()
    registry = discover_registry(root)
    gates_dir = discover_gates(root)
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, List


# Marker file that identifies a vOS workspace root
MARKER_FILE = ".vos-root"

# Known relative paths from root
PATHS = {
    "registry": "system/s5-policy/agent-policy/agent-write-gates-v1/write_gates.vsm",
    "orchestrator": "scripts/vsl/tools/write_gate_orchestrator.py",
    "gates_dir": "scripts/vsl/validator",
    "plugins_scripts": ".opencode/plugins/scripts",
    "plugins_core": ".opencode/plugins/core",
}


def find_marker_in_parents(start: Path, marker: str = MARKER_FILE) -> Optional[Path]:
    """Walk up from `start` looking for `marker` file."""
    current = start.resolve()
    while True:
        if (current / marker).exists():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            return None
        current = parent


def find_git_root(start: Path) -> Optional[Path]:
    """Find git root from `start` directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def find_script_root(start: Path) -> Optional[Path]:
    """Find root by looking for known scripts relative to start."""
    # Walk up looking for scripts/vsl/tools/write_gate_orchestrator.py
    current = start.resolve()
    for _ in range(10):  # Max 10 levels up
        if (current / "scripts" / "vsl" / "tools" / "write_gate_orchestrator.py").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def discover_root(start: Optional[Path] = None) -> Optional[Path]:
    """
    Discover workspace root using multiple strategies.
    
    Discovery order:
    1. VOS_ROOT environment variable
    2. .vos-marker file in current directory or parents
    3. Git root
    4. Script location (looking for known paths)
    
    Args:
        start: Starting directory (defaults to cwd)
        
    Returns:
        Path to workspace root, or None if not found
    """
    if start is None:
        start = Path.cwd()
    
    # Strategy 1: Environment variable
    env_root = os.environ.get("VOS_ROOT")
    if env_root:
        root = Path(env_root)
        if root.exists():
            return root
    
    # Strategy 2: Marker file
    marker_root = find_marker_in_parents(start)
    if marker_root:
        return marker_root
    
    # Strategy 3: Git root
    git_root = find_git_root(start)
    if git_root:
        # Verify it looks like a vOS workspace
        if (git_root / "scripts" / "vsl").exists() or (git_root / "packages").exists():
            return git_root
    
    # Strategy 4: Script location
    script_root = find_script_root(start)
    if script_root:
        return script_root
    
    return None


def discover_registry(root: Optional[Path] = None) -> Optional[Path]:
    """Discover gate registry file."""
    if root is None:
        root = discover_root()
    if root is None:
        return None
    
    registry_path = root / PATHS["registry"]
    return registry_path if registry_path.exists() else None


def discover_orchestrator(root: Optional[Path] = None) -> Optional[Path]:
    """Discover orchestrator script."""
    if root is None:
        root = discover_root()
    if root is None:
        return None
    
    orch_path = root / PATHS["orchestrator"]
    return orch_path if orch_path.exists() else None


def discover_gates(root: Optional[Path] = None) -> Optional[Path]:
    """Discover gates directory."""
    if root is None:
        root = discover_root()
    if root is None:
        return None
    
    gates_path = root / PATHS["gates_dir"]
    return gates_path if gates_path.exists() else None


def get_all_paths(root: Optional[Path] = None) -> dict:
    """Get all discovered paths as a dictionary."""
    if root is None:
        root = discover_root()
    
    result = {"root": root}
    
    if root:
        for key, rel_path in PATHS.items():
            full_path = root / rel_path
            result[key] = full_path if full_path.exists() else None
    else:
        for key in PATHS:
            result[key] = None
    
    return result


def print_discovery(start: Optional[Path] = None):
    """Print discovery results for debugging."""
    root = discover_root(start)
    
    print("=== vOS Path Discovery ===")
    print(f"Start: {start or Path.cwd()}")
    print(f"Root: {root}")
    
    if root:
        paths = get_all_paths(root)
        print("\nDiscovered paths:")
        for key, path in paths.items():
            if key == "root":
                continue
            status = "✓" if path else "✗"
            print(f"  {status} {key}: {path}")
    else:
        print("\nNo workspace root found!")
        print("Checked:")
        print(f"  1. VOS_ROOT env: {os.environ.get('VOS_ROOT', '(not set)')}")
        print(f"  2. Marker file ({MARKER_FILE}): not found in parents")
        print(f"  3. Git root: not found or not a vOS workspace")
        print(f"  4. Script location: orchestrator not found")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Discover vOS workspace paths")
    parser.add_argument("path", nargs="?", help="Starting directory (default: cwd)")
    parser.add_argument("--root", action="store_true", help="Print only root path")
    parser.add_argument("--registry", action="store_true", help="Print only registry path")
    parser.add_argument("--orchestrator", action="store_true", help="Print only orchestrator path")
    
    args = parser.parse_args()
    
    start = Path(args.path) if args.path else None
    
    if args.root:
        root = discover_root(start)
        print(str(root) if root else "")
    elif args.registry:
        registry = discover_registry(start)
        print(str(registry) if registry else "")
    elif args.orchestrator:
        orchestrator = discover_orchestrator(start)
        print(str(orchestrator) if orchestrator else "")
    else:
        print_discovery(start)
