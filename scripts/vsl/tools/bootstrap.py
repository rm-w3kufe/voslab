#!/usr/bin/env python3
"""
bootstrap.py — Setup vOS gate infrastructure in any workspace.

Agent-agnostic: creates the necessary structure for write-time gates
regardless of agent name or path.

Usage:
    python3 bootstrap.py                    # Setup in current directory
    python3 bootstrap.py /path/to/workspace # Setup in specific directory
    python3 bootstrap.py --check            # Check if setup is complete
    python3 bootstrap.py --verify           # Verify gates work
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


# Required directory structure
REQUIRED_DIRS = [
    ".opencode/plugins/core",
    ".opencode/plugins/scripts",
    "scripts/vsl/tools",
    "scripts/vsl/validator",
    "docs/spec_revision/system/s5-policy/agent-policy/agent-write-gates-v1",
]

# Marker file content
MARKER_CONTENT = """# vOS workspace root marker
# This file identifies the workspace root for path discovery.
# Do not delete unless you know what you're doing.
"""

# Registry template
REGISTRY_TEMPLATE = """⟦ write_gates | AGENT-WRITE-GATES-v1 | vsm-1.2.1 | {timestamp} ⟧

@vsm 1.2.1
@status active
// write_gates.vsm — WRITE-TIME GATE REGISTRY
// Agent-agnostic: gates discovered via vos_discover.py

map(AGENT-WRITE-GATES) {{

  gates: [

    // R18 conformance
    gate("r18-conformance") {{
      cmd: "python3 scripts/vsl/validator/check.py",
      mode: per-file,
      label: "R18",
      block_on: "contains:R18-BLOCK",
      advisory: false,
      owner: "S3* auditor",
      desc: "R18 write-time conformance",
    }},

  ]
}}
"""


def create_directories(workspace: Path) -> List[str]:
    """Create required directory structure."""
    created = []
    
    for dir_path in REQUIRED_DIRS:
        full_path = workspace / dir_path
        if not full_path.exists():
            full_path.mkdir(parents=True, exist_ok=True)
            created.append(dir_path)
    
    return created


def create_marker(workspace: Path) -> bool:
    """Create .vos-root marker file."""
    marker_path = workspace / ".vos-root"
    
    if not marker_path.exists():
        marker_path.write_text(MARKER_CONTENT)
        return True
    
    return False


def create_registry(workspace: Path) -> bool:
    """Create gate registry if it doesn't exist."""
    from datetime import datetime, timezone
    
    registry_path = workspace / "docs/spec_revision/system/s5-policy/agent-policy/agent-write-gates-v1/write_gates.vsm"
    
    if not registry_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = REGISTRY_TEMPLATE.format(timestamp=timestamp)
        registry_path.write_text(content)
        return True
    
    return False


def copy_discover_script(workspace: Path) -> bool:
    """Copy discover.py to the workspace."""
    discover_path = workspace / "scripts/vsl/tools/vos_discover.py"
    
    if not discover_path.exists():
        # Create a minimal discover script
        script_content = '''#!/usr/bin/env python3
"""vos_discover.py — Path discovery for vOS gate infrastructure."""
import os
import subprocess
from pathlib import Path

MARKER_FILE = ".vos-root"

def discover_root(start=None):
    if start is None:
        start = Path.cwd()
    
    # 1. Environment variable
    env_root = os.environ.get("VOS_ROOT")
    if env_root and Path(env_root).exists():
        return Path(env_root)
    
    # 2. Marker file
    current = start.resolve()
    while True:
        if (current / MARKER_FILE).exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    
    # 3. Git root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            git_root = Path(result.stdout.strip())
            if (git_root / "scripts" / "vsl").exists() or (git_root / "packages").exists():
                return git_root
    except:
        pass
    
    return None

if __name__ == "__main__":
    root = discover_root()
    print(str(root) if root else "")
'''
        discover_path.write_text(script_content)
        discover_path.chmod(0o755)
        return True
    
    return False


def check_setup(workspace: Path) -> Tuple[List[str], List[str]]:
    """Check if setup is complete."""
    missing = []
    existing = []
    
    # Check directories
    for dir_path in REQUIRED_DIRS:
        full_path = workspace / dir_path
        if full_path.exists():
            existing.append(f"dir: {dir_path}")
        else:
            missing.append(f"dir: {dir_path}")
    
    # Check marker
    marker_path = workspace / ".vos-root"
    if marker_path.exists():
        existing.append("marker: .vos-root")
    else:
        missing.append("marker: .vos-root")
    
    # Check registry
    registry_path = workspace / "docs/spec_revision/system/s5-policy/agent-policy/agent-write-gates-v1/write_gates.vsm"
    if registry_path.exists():
        existing.append("registry: write_gates.vsm")
    else:
        missing.append("registry: write_gates.vsm")
    
    # Check discover script
    discover_path = workspace / "scripts/vsl/tools/vos_discover.py"
    if discover_path.exists():
        existing.append("discover: vos_discover.py")
    else:
        missing.append("discover: vos_discover.py")
    
    return existing, missing


def verify_gates(workspace: Path) -> bool:
    """Verify that gates can be discovered and run."""
    sys.path.insert(0, str(workspace / "scripts/vsl/tools"))
    
    try:
        from vos_discover import discover_root, discover_registry, discover_orchestrator
        
        root = discover_root(workspace)
        if not root:
            print("✗ Cannot discover root")
            return False
        
        print(f"✓ Root: {root}")
        
        registry = discover_registry(root)
        if registry:
            print(f"✓ Registry: {registry}")
        else:
            print("✗ Registry not found")
            return False
        
        orchestrator = discover_orchestrator(root)
        if orchestrator:
            print(f"✓ Orchestrator: {orchestrator}")
            
            # Try running orchestrator
            result = subprocess.run(
                ["python3", str(orchestrator), "--help"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                print("✓ Orchestrator runs successfully")
            else:
                print(f"✗ Orchestrator failed: {result.stderr[:100]}")
                return False
        else:
            print("✗ Orchestrator not found")
            return False
        
        return True
        
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Bootstrap vOS gate infrastructure")
    parser.add_argument("workspace", nargs="?", default=".", help="Workspace directory")
    parser.add_argument("--check", action="store_true", help="Check setup status")
    parser.add_argument("--verify", action="store_true", help="Verify gates work")
    parser.add_argument("--force", action="store_true", help="Force recreate files")
    
    args = parser.parse_args()
    
    workspace = Path(args.workspace).resolve()
    
    print(f"=== vOS Gate Bootstrap ===")
    print(f"Workspace: {workspace}")
    
    if not workspace.exists():
        print(f"✗ Workspace does not exist: {workspace}")
        sys.exit(1)
    
    if args.check:
        existing, missing = check_setup(workspace)
        
        print(f"\n✓ Found: {len(existing)} items")
        for item in existing:
            print(f"  {item}")
        
        if missing:
            print(f"\n✗ Missing: {len(missing)} items")
            for item in missing:
                print(f"  {item}")
            sys.exit(1)
        else:
            print("\n✓ Setup is complete!")
            sys.exit(0)
    
    if args.verify:
        success = verify_gates(workspace)
        sys.exit(0 if success else 1)
    
    # Bootstrap
    print("\n--- Creating directories ---")
    created = create_directories(workspace)
    if created:
        print(f"Created {len(created)} directories:")
        for d in created:
            print(f"  + {d}")
    else:
        print("All directories exist")
    
    print("\n--- Creating marker ---")
    if create_marker(workspace):
        print("Created .vos-root")
    else:
        print(".vos-root already exists")
    
    print("\n--- Creating registry ---")
    if create_registry(workspace):
        print("Created write_gates.vsm")
    else:
        print("write_gates.vsm already exists")
    
    print("\n--- Copying discover script ---")
    if copy_discover_script(workspace):
        print("Created vos_discover.py")
    else:
        print("vos_discover.py already exists")
    
    print("\n=== Bootstrap Complete ===")
    print("\nTo verify, run:")
    print(f"  python3 scripts/vsl/tools/vos_discover.py")
    print(f"  python3 bootstrap.py --verify")


if __name__ == "__main__":
    main()
