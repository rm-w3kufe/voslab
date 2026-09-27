#!/usr/bin/env python3
"""
update_scripts_manifest.py — Regenerates the scripts/state/ manifest.

Usage:
    python3 scripts/shared/update_scripts_manifest.py

This script scans scripts/state/ and generates an updated manifest.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone

# Configuration
SCRIPTS_DIR = Path(__file__).parent.parent.absolute() / "state"
MANIFEST_FILE = Path(__file__).parent.parent.parent.absolute() / "docs/spec_revision/system/instance/vsf-instance-v1/scripts_state_manifest.vsm"

# Extensions to include
EXTENSIONS = {'.py', '.sh', '.service', '.timer', '.sql', '.json', '.db'}

# Directorios a excluir
EXCLUDE_DIRS = {'__pycache__', '.git', 'node_modules'}

def scan_directory(directory: Path) -> dict:
    """Escanea un directorio y retorna su contenido."""
    result = {}
    
    for item in sorted(directory.iterdir()):
        if item.is_dir() and item.name not in EXCLUDE_DIRS:
            subdir_result = scan_directory(item)
            if subdir_result:
                result[item.name] = subdir_result
        elif item.is_file() and item.suffix in EXTENSIONS:
            if directory.name not in result:
                result[directory.name] = []
            result[directory.name].append(item.name)
    
    return result

def get_dependencies(files: list) -> list:
    """Analyze basic file dependencies."""
    deps = []
    for f in files:
        if f.endswith('.py'):
            deps.append("python")
        elif f.endswith('.sh'):
            deps.append("bash")
        elif f.endswith('.sql'):
            deps.append("sqlite3")
        elif f.endswith('.service') or f.endswith('.timer'):
            deps.append("systemd")
    return list(set(deps))

def generate_manifest(structure: dict) -> str:
    """Generate the manifest content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    manifest = f"""⟦ scripts_state_manifest | SCRIPTS-STATE-MANIFEST-v1 | vsm-1.2.1 | {now} ⟧

@vsm 1.2.1
@status active

// ═══════════════════════════════════════════════════════════════════════════
// SCRIPTS/STATE/ MANIFEST
// scripts/state/ MANIFEST — registry of all files and their dependencies
// ═══════════════════════════════════════════════════════════════════════════

// PURPOSE
// ═══════════════════════════════════════════════════════════════════════════
//
// This manifest documents the structure of scripts/state/ and its
// dependencies. It is updated automatically when scripts are modified.
//
// ═══════════════════════════════════════════════════════════════════════════
// STRUCTURE
// ═══════════════════════════════════════════════════════════════════════════

estructura() {{
"""
    
    for dir_name, content in structure.items():
        if isinstance(content, dict):
            # Subdirectorio
            manifest += f"  {dir_name}: {{\n"
            manifest += f"    files: [\n"
            for sub_item, sub_content in content.items():
                if isinstance(sub_content, list):
                    for f in sub_content:
                        manifest += f'      "{sub_item}/{f}",\n'
            manifest += f"    ],\n"
            deps = get_dependencies([f for sub_content in content.values() if isinstance(sub_content, list) for f in sub_content])
            manifest += f"    dependencies: {deps},\n"
            manifest += f"  }},\n"
        elif isinstance(content, list):
            # Direct files
            manifest += f"  {dir_name}: {{\n"
            manifest += f"    files: [\n"
            for f in content:
                manifest += f'      "{f}",\n'
            manifest += f"    ],\n"
            deps = get_dependencies(content)
            manifest += f"    dependencies: {deps},\n"
            manifest += f"  }},\n"
    
    manifest += """}

// ═══════════════════════════════════════════════════════════════════════════
// AUTOMATIC UPDATE
// ═══════════════════════════════════════════════════════════════════════════

automatic_update() {
  script: "scripts/shared/update_scripts_manifest.py",
  usage: "Run after modifying scripts/state/ to update this manifest",
  command: "python3 scripts/shared/update_scripts_manifest.py",
}

// ═══════════════════════════════════════════════════════════════════════════
// VERIFICATION
// ═══════════════════════════════════════════════════════════════════════════

verification() {
  checks: [
    "1. All listed files exist",
    "2. No unlisted files exist under scripts/state/",
    "3. Dependencies are wired correctly",
  ],
  commands: [
    "python3 scripts/shared/verify_scripts_manifest.py → PASS",
    "grep -rn 'scripts/state/' checks/ | grep -v '# →' → EMPTY",
  ],
}

"""
    manifest += f"⟦ /scripts_state_manifest ⟧\n"
    
    return manifest

def count_files(structure: dict) -> int:
    """Count the total number of files in the structure."""
    count = 0
    for value in structure.values():
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += count_files(value)
    return count

def main():
    """Main entry point."""
    print(f"Scanning {SCRIPTS_DIR}...")
    structure = scan_directory(SCRIPTS_DIR)
    
    print(f"Generating manifest...")
    manifest_content = generate_manifest(structure)
    
    print(f"Saving to {MANIFEST_FILE}...")
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(manifest_content)
    
    print("✅ Manifest updated successfully")
    print(f"   Files found: {count_files(structure)}")

if __name__ == "__main__":
    main()
