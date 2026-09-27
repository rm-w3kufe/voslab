#!/usr/bin/env python3
"""
verify_scripts_manifest.py — Verifica que el manifiesto de scripts/state/ esté actualizado

Uso:
    python3 scripts/shared/verify_scripts_manifest.py

Este script verifica que todos los archivos en scripts/state/ estén listados en el manifiesto.
"""

import os
from pathlib import Path

# Configuration
SCRIPTS_DIR = Path(__file__).parent.parent / "state"
MANIFEST_FILE = Path(__file__).parent.parent.parent / "docs/spec_revision/system/instance/vsf-instance-v1/scripts_state_manifest.vsm"

# Extensions to include
EXTENSIONS = {'.py', '.sh', '.service', '.timer', '.sql', '.json', '.db'}

# Directorios a excluir
EXCLUDE_DIRS = {'__pycache__', '.git', 'node_modules'}

def scan_directory(directory: Path) -> set:
    """Scans a directory and returns all the files."""
    files = set()
    
    for item in directory.rglob("*"):
        if item.is_file() and item.suffix in EXTENSIONS:
            # relative path
            rel_path = item.relative_to(SCRIPTS_DIR)
            files.add(str(rel_path))
    
    return files

def parse_manifest() -> set:
    """Parses the manifest and returns the listed files."""
    if not MANIFEST_FILE.exists():
        return set()
    
    content = MANIFEST_FILE.read_text()
    files = set()
    
    # Find lines carrying files in VSM format
    for line in content.split('\n'):
        line = line.strip()
        # Find lines that start with " and end with ",
        if line.startswith('"') and line.endswith('",'):
            # Extract the file name
            filename = line[1:-2]
            # Only include it if it looks like a file name (not descriptive text)
            if ('.' in filename and 
                not filename.startswith('1.') and 
                not filename.startswith('2.') and 
                not filename.startswith('3.') and
                not filename.startswith('python3') and
                not filename.startswith('grep')):
                files.add(filename)
    
    return files

def main():
    """Main function."""
    print("=== Verificando manifiesto de scripts/state/ ===")
    print()
    
    # Scan real files
    print("1. Escaneando scripts/state/...")
    actual_files = scan_directory(SCRIPTS_DIR)
    print(f"   Encontrados: {len(actual_files)} archivos")
    
    # Parsear manifiesto
    print("2. Parseando manifiesto...")
    manifest_files = parse_manifest()
    print(f"   Listados: {len(manifest_files)} archivos")
    
    # Comparar
    print("3. Comparando...")
    missing_in_manifest = actual_files - manifest_files
    missing_on_disk = manifest_files - actual_files
    
    if missing_in_manifest:
        print(f"\n❌ Archivos en disco pero no en manifiesto: {len(missing_in_manifest)}")
        for f in sorted(missing_in_manifest):
            print(f"   - {f}")
    
    if missing_on_disk:
        print(f"\n❌ Archivos en manifiesto pero no en disco: {len(missing_on_disk)}")
        for f in sorted(missing_on_disk):
            print(f"   - {f}")
    
    if not missing_in_manifest and not missing_on_disk:
        print("\n✅ Manifiesto está actualizado")
        return 0
    else:
        print("\n💡 Ejecuta: python3 scripts/shared/update_scripts_manifest.py")
        return 1

if __name__ == "__main__":
    exit(main())
