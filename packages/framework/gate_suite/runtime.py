"""Runtime gate runner for vOSLAB gate-suite.

Runs gates on actual files during runtime (not just negative control tests).
Can be called from the tool-integration bridge to validate files before/after operations.
"""
import os
from pathlib import Path
from typing import List, Dict, Any

# Import gate registry
from gate_suite.harness import GATES
from gate_suite.gates import (
    vsm_version_enforcer,
    timestamp_no_hardcoded,
)


def run_gates_on_file(file_path: str) -> Dict[str, Any]:
    """
    Run all applicable gates on a file.
    
    Args:
        file_path: Path to the file to validate
        
    Returns:
        Dict with gate results:
        {
            "file": str,
            "gates_run": int,
            "gates_passed": int,
            "gates_failed": int,
            "results": [
                {"gate": str, "passed": bool, "message": str}
            ]
        }
    """
    path = Path(file_path)
    if not path.exists():
        return {
            "file": file_path,
            "error": f"File not found: {file_path}",
            "gates_run": 0,
            "gates_passed": 0,
            "gates_failed": 0,
            "results": [],
        }
    
    results = []
    gates_run = 0
    gates_passed = 0
    gates_failed = 0
    
    # Run vsm-version-enforcer if it's a .vsm file
    if path.suffix == ".vsm":
        gates_run += 1
        try:
            rc = vsm_version_enforcer.check(str(path))
            passed = rc == 0
            results.append({
                "gate": "vsm-version-enforcer",
                "passed": passed,
                "message": "VSM version is correct" if passed else "VSM version mismatch",
            })
            if passed:
                gates_passed += 1
            else:
                gates_failed += 1
        except Exception as e:
            results.append({
                "gate": "vsm-version-enforcer",
                "passed": False,
                "message": f"Error: {str(e)}",
            })
            gates_failed += 1
    
    # Run timestamp-no-hardcoded if it's a .vsm file
    if path.suffix == ".vsm":
        gates_run += 1
        try:
            rc = timestamp_no_hardcoded.check(str(path))
            passed = rc == 0
            results.append({
                "gate": "timestamp-no-hardcoded",
                "passed": passed,
                "message": "No hardcoded timestamps" if passed else "Hardcoded timestamps detected",
            })
            if passed:
                gates_passed += 1
            else:
                gates_failed += 1
        except Exception as e:
            results.append({
                "gate": "timestamp-no-hardcoded",
                "passed": False,
                "message": f"Error: {str(e)}",
            })
            gates_failed += 1
    
    return {
        "file": file_path,
        "gates_run": gates_run,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "results": results,
    }


def run_gates_on_directory(dir_path: str, recursive: bool = True) -> Dict[str, Any]:
    """
    Run gates on all applicable files in a directory.
    
    Args:
        dir_path: Path to the directory
        recursive: Whether to scan subdirectories
        
    Returns:
        Dict with aggregate results
    """
    path = Path(dir_path)
    if not path.exists():
        return {
            "directory": dir_path,
            "error": f"Directory not found: {dir_path}",
            "files_scanned": 0,
            "total_gates_run": 0,
            "total_gates_passed": 0,
            "total_gates_failed": 0,
        }
    
    files_scanned = 0
    total_gates_run = 0
    total_gates_passed = 0
    total_gates_failed = 0
    file_results = []
    
    # Find all .vsm files
    pattern = "**/*.vsm" if recursive else "*.vsm"
    for vsm_file in path.glob(pattern):
        files_scanned += 1
        result = run_gates_on_file(str(vsm_file))
        total_gates_run += result["gates_run"]
        total_gates_passed += result["gates_passed"]
        total_gates_failed += result["gates_failed"]
        file_results.append(result)
    
    return {
        "directory": dir_path,
        "files_scanned": files_scanned,
        "total_gates_run": total_gates_run,
        "total_gates_passed": total_gates_passed,
        "total_gates_failed": total_gates_failed,
        "file_results": file_results,
    }
