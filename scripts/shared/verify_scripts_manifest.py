#!/usr/bin/env python3
"""
verify_scripts_manifest.py — Verifica que el manifiesto de scripts/state/ esté actualizado

Uso:
    python3 scripts/shared/verify_scripts_manifest.py

Este script verifica que todos los archivos en scripts/state/ estén listados en el manifiesto.
"""

import os
from pathlib import Path

# Workspace detection (vOSlab layout; walk up for current_focus.json)
def _workspace() -> Path:
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "current_focus.json").exists():
            return cand
    return here.parent.parent.parent

_WS = _workspace()
SCRIPTS_DIR = _WS / "scripts" / "state"
MANIFEST_FILE = _WS / "system" / "instance" / "vsf-instance-v1" / "scripts_state_manifest.vsm"

# Extensiones a incluir
EXTENSIONS = {'.py', '.sh', '.service', '.timer', '.sql', '.json', '.db'}

# Directorios a excluir
EXCLUDE_DIRS = {'__pycache__', '.git', 'node_modules'}

def scan_directory(directory: Path) -> set:
    """Escanea un directorio y retorna todos los archivos."""
    files = set()
    
    for item in directory.rglob("*"):
        if item.is_file() and item.suffix in EXTENSIONS:
            # Obtener ruta relativa
            rel_path = item.relative_to(SCRIPTS_DIR)
            files.add(str(rel_path))
    
    return files

def parse_manifest() -> set:
    """Parsea el manifiesto y retorna los archivos listados."""
    if not MANIFEST_FILE.exists():
        return set()
    
    content = MANIFEST_FILE.read_text()
    files = set()
    
    # Buscar líneas con archivos en formato VSM
    for line in content.split('\n'):
        line = line.strip()
        # Buscar líneas que empiezan con " y terminan con ",
        if line.startswith('"') and line.endswith('",'):
            # Extraer nombre del archivo
            filename = line[1:-2]
            # Solo incluir si parece un nombre de archivo (no es texto descriptivo)
            if ('.' in filename and 
                not filename.startswith('1.') and 
                not filename.startswith('2.') and 
                not filename.startswith('3.') and
                not filename.startswith('python3') and
                not filename.startswith('grep')):
                files.add(filename)
    
    return files

def main():
    """Función principal."""
    print("=== Verificando manifiesto de scripts/state/ ===")
    print()
    
    # Escanear archivos reales
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
