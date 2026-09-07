"""
check_runner — Ejecutor de checks VSF.

Proporciona functions para ejecutar checks de validación.
"""

import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def run_check(check_path: str, args: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Ejecuta un check individual.
    
    Args:
        check_path: Ruta al ejecutable del check
        args: Argumentos adicionales para el check
        
    Returns:
        Tuple de (éxito, salida)
    """
    try:
        cmd = [check_path] + (args or [])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Check timeout (30s)"
    except Exception as e:
        return False, f"Error ejecutando check: {e}"


def run_all_checks(checks_dir: str, pattern: Optional[str] = None) -> Dict[str, Tuple[bool, str]]:
    """
    Ejecuta todos los checks en un directorio.
    
    Args:
        checks_dir: Directorio con los checks
        pattern: Patrón de filtrado (opcional)
        
    Returns:
        Diccionario con resultados {nombre_check: (éxito, salida)}
    """
    results = {}
    checks_path = Path(checks_dir)
    
    if not checks_path.exists():
        return {"error": (False, f"Directorio no encontrado: {checks_dir}")}
    
    for check_file in checks_path.iterdir():
        if check_file.is_file() and os.access(check_file, os.X_OK):
            if pattern and pattern not in check_file.name:
                continue
            success, output = run_check(str(check_file))
            results[check_file.name] = (success, output)
    
    return results


def get_check_status(check_name: str, results: Dict[str, Tuple[bool, str]]) -> str:
    """
    Obtiene el estado de un check específico.
    
    Args:
        check_name: Nombre del check
        results: Resultados de ejecución
        
    Returns:
        Estado del check: "PASS", "FAIL", o "NOT_FOUND"
    """
    if check_name not in results:
        return "NOT_FOUND"
    
    success, _ = results[check_name]
    return "PASS" if success else "FAIL"


def format_check_report(results: Dict[str, Tuple[bool, str]]) -> str:
    """
    Formatea un reporte de resultados.
    
    Args:
        results: Resultados de ejecución
        
    Returns:
        Reporte formateado
    """
    lines = ["=== REPORTE DE CHECKS ===\n"]
    
    passed = sum(1 for success, _ in results.values() if success)
    failed = sum(1 for success, _ in results.values() if not success)
    
    lines.append(f"Total: {len(results)} | Pass: {passed} | Fail: {failed}\n")
    
    for check_name, (success, output) in sorted(results.items()):
        status = "✓" if success else "✗"
        lines.append(f"{status} {check_name}")
        if not success and output:
            lines.append(f"  Error: {output[:100]}...")
    
    return "\n".join(lines)
