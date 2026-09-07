"""bridge.py — VSL validators bridge for vOSlab.

Imports from child/scripts/vsl/validator/verify_*.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Ensure child validator scripts are importable
_VALIDATOR_DIR = Path.home() / "vsf" / "scripts" / "vsl" / "validator"
if _VALIDATOR_DIR.exists() and str(_VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATOR_DIR))


def _import_validator(module_name: str):
    """Lazy import from child validator scripts."""
    try:
        import importlib
        return importlib.import_module(module_name)
    except ImportError:
        return None


# ═══════════════════════════════════════════════════════════════════════
# BINDINGS VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_bindings(file_path: str) -> Dict[str, Any]:
    """Verify binding completeness for system/ documents."""
    mod = _import_validator("verify_bindings")
    if mod is None:
        return {"error": "verify_bindings not available"}
    if hasattr(mod, "verify_file"):
        result = mod.verify_file(Path(file_path))
        return {"valid": result == 0, "errors": result, "file": file_path}
    if hasattr(mod, "verify"):
        return mod.verify(Path(file_path))
    if hasattr(mod, "main"):
        # Script-style validator
        return {"status": "delegated", "file": file_path}
    return {"error": "verify_bindings.verify not found"}


# ═══════════════════════════════════════════════════════════════════════
# STATUS VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_status(file_path: str) -> Dict[str, Any]:
    """Verify @status fields and transitions."""
    mod = _import_validator("verify_status")
    if mod is None:
        return {"error": "verify_status not available"}
    if hasattr(mod, "verify_file"):
        result = mod.verify_file(Path(file_path))
        return {"valid": result == 0, "errors": result, "file": file_path}
    if hasattr(mod, "verify"):
        return mod.verify(Path(file_path))
    return {"error": "verify_status.verify not found"}


# ═══════════════════════════════════════════════════════════════════════
# MIGRATION VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_migration(file_path: str) -> Dict[str, Any]:
    """Verify paths in system/ documents."""
    mod = _import_validator("verify_migration")
    if mod is None:
        return {"error": "verify_migration not available"}
    if hasattr(mod, "verify_file"):
        result = mod.verify_file(Path(file_path))
        return {"valid": result == 0, "errors": result, "file": file_path}
    if hasattr(mod, "verify"):
        return mod.verify(Path(file_path))
    return {"error": "verify_migration.verify not found"}


# ═══════════════════════════════════════════════════════════════════════
# CLAIM VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_claim(check_ids: List[str] | None = None, message_file: str | None = None) -> Dict[str, Any]:
    """Verify claims using check-based interface.
    
    Args:
        check_ids: List of check IDs to run (e.g., ['ds001', 'ds002'])
        message_file: Path to git message file for --trailers mode
        
    Returns:
        Dict with validity status and check results
    """
    mod = _import_validator("verify_claim")
    if mod is None:
        return {"error": "verify_claim not available"}
    
    # Use --trailers mode if message_file provided
    if message_file:
        if hasattr(mod, "from_trailers"):
            result = mod.from_trailers(message_file)
            return {"valid": result == 0, "errors": result, "mode": "trailers"}
        return {"error": "verify_claim.from_trailers not available"}
    
    # Use check IDs mode
    if check_ids:
        if hasattr(mod, "collect") and hasattr(mod, "verify"):
            checks = mod.collect(check_ids)
            if any(c is None for c in checks):
                return {"valid": False, "errors": "missing checks", "checks": check_ids}
            results = {check.name: mod.verify(check) for check in checks if check}
            return {"valid": all(results.values()), "results": results, "mode": "checks"}
        return {"error": "verify_claim.collect/verify not available"}
    
    # List available checks
    if hasattr(mod, "CHECKS"):
        checks_dir = mod.CHECKS
        if checks_dir.exists():
            checks = [f.name for f in checks_dir.iterdir() 
                     if f.is_file() and not f.name.startswith(".") and f.name != "README.md"]
            return {"status": "available", "checks": sorted(checks)}
        return {"status": "no checks directory"}
    
    return {"error": "verify_claim interface not found"}


# ═══════════════════════════════════════════════════════════════════════
# DIR SCHEMA VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_dir_schema(file_path: str) -> Dict[str, Any]:
    """Verify directory schema compliance."""
    mod = _import_validator("verify_dir_schema")
    if mod is None:
        return {"error": "verify_dir_schema not available"}
    if hasattr(mod, "verify_file"):
        result = mod.verify_file(Path(file_path))
        return {"valid": result == 0, "errors": result, "file": file_path}
    if hasattr(mod, "verify"):
        return mod.verify(Path(file_path))
    return {"error": "verify_dir_schema.verify not found"}


# ═══════════════════════════════════════════════════════════════════════
# PRIMER CLOSURE VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_primer_closure(file_path: str) -> Dict[str, Any]:
    """Verify primer closure compliance."""
    mod = _import_validator("verify_primer_closure")
    if mod is None:
        return {"error": "verify_primer_closure not available"}
    if hasattr(mod, "verify_file"):
        result = mod.verify_file(Path(file_path))
        return {"valid": result == 0, "errors": result, "file": file_path}
    if hasattr(mod, "verify"):
        return mod.verify(Path(file_path))
    return {"error": "verify_primer_closure.verify not found"}


# ═══════════════════════════════════════════════════════════════════════
# BOOT ONTOLOGY VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_boot_ontology(file_path: str) -> Dict[str, Any]:
    """Verify boot ontology compliance."""
    mod = _import_validator("verify_boot_ontology")
    if mod is None:
        return {"error": "verify_boot_ontology not available"}
    if hasattr(mod, "verify_file"):
        result = mod.verify_file(Path(file_path))
        return {"valid": result == 0, "errors": result, "file": file_path}
    if hasattr(mod, "verify"):
        return mod.verify(Path(file_path))
    return {"error": "verify_boot_ontology.verify not found"}


# ═══════════════════════════════════════════════════════════════════════
# BOOT PRIMER VALIDATOR
# ═══════════════════════════════════════════════════════════════════════

def verify_boot_primer(file_path: str) -> Dict[str, Any]:
    """Verify boot primer compliance."""
    mod = _import_validator("verify_boot_primer")
    if mod is None:
        return {"error": "verify_boot_primer not available"}
    if hasattr(mod, "verify_file"):
        result = mod.verify_file(Path(file_path))
        return {"valid": result == 0, "errors": result, "file": file_path}
    if hasattr(mod, "verify"):
        return mod.verify(Path(file_path))
    return {"error": "verify_boot_primer.verify not found"}


# ═══════════════════════════════════════════════════════════════════════
# BATCH VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def validate_all(file_path: str) -> Dict[str, Any]:
    """Run all validators on a file."""
    results = {}
    validators = [
        ("bindings", verify_bindings),
        ("status", verify_status),
        ("migration", verify_migration),
        ("claim", verify_claim),
        ("dir_schema", verify_dir_schema),
        ("primer_closure", verify_primer_closure),
        ("boot_ontology", verify_boot_ontology),
        ("boot_primer", verify_boot_primer),
    ]
    for name, validator in validators:
        try:
            result = validator(file_path)
            results[name] = result
        except Exception as e:
            results[name] = {"error": str(e)}
    return results


# ═══════════════════════════════════════════════════════════════════════
# AVAILABILITY CHECK
# ═══════════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """Check if child validator scripts are available."""
    return _VALIDATOR_DIR.exists()


def list_validators() -> List[str]:
    """List available validators."""
    return [
        "verify_bindings",
        "verify_status",
        "verify_migration",
        "verify_claim",
        "verify_dir_schema",
        "verify_primer_closure",
        "verify_boot_ontology",
        "verify_boot_primer",
    ]
