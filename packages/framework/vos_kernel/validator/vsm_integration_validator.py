#!/usr/bin/env python3
"""vsm_integration_validator.py — Validador Obligatorio de Integración Autónoma.

Este validador se ejecuta TODOS los git commit (via pre-commit hook kernel-managed)
y BLOQUEA el commit si una nueva herramienta/no cumple los 3 requisitos mínimos:

1. HEAD VSM CANÓNICO con las 3 fields obligatorias: ROL, DRIVER, CANAL.
2. BACKBONE MANIFEST — herramienta registrada en backbone route.
3. GATE CHECKS — tests negativos controls asociados.

Diseñado bajo el modelo VSM recursivo S1-S5 con drivers únicos por nivel.
"""

import sys
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # /home/rmw3/vOSlab/packages/framework/vos_kernel
TOOLS_DIR = REPO  # tools are .py or .vsm files in vos_kernel or scripts/


# ──────────────────────────────────────────────────────────────────────
# 1. CONFIGURACIÓN DE CATEGORÍAS VSM Y DRIVERS APROBADOS
# ──────────────────────────────────────────────────────────────────────
ALLOWED_DRIVERS = {
    "S1": "φ↑_direct",
    "S2": "event_coordinator",
    "S3": "invariant_guard",
    "S3*": "audit_scanner",
    "S4": "LLM_probe",
    "S4": "socratic_engine",  # note: S4 has two valid drivers
    "S5": "consent_gate",
}

# Mapeo S3 duplicado - permitimos ambos
ALLOWED_DRIVERS_S3 = {"S3": "invariant_guard", "S3*": "audit_scanner"}

# Patrones VSM header obligatorios
VSM_HEADER_RE = re.compile(
    r"⟦\s*([^|]+)\|\s*([^|]+)\s*\|\s*vsm-1\.2(?:\.\d)?\s*\|\s*([^\s⟧]+)\s*⟧"
)

# Campos obligatorios en el header VSM
REQUIRED_FIELDS = ["ROL", "DRIVER", "CANAL"]

# ──────────────────────────────────────────────────────────────────────
# 2. FUNCIONES AUXILIARES
# ──────────────────────────────────────────────────────────────────────

def read_vsm_header(filepath: Path) -> dict | None:
    """Lee el header VSM de un archivo y retorna dict con los 3 fields obligatorios."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    m = VSM_HEADER_RE.search(text)
    if not m:
        return None

    name, typ, version = m.group(1), m.group(2), m.group(3)
    # Los próximos 3 lines deben contener @status, @vsm y los fields
    lines = text.splitlines()

    # Extraer @status
    status = ""
    for line in lines:
        if line.startswith("@status"):
            status = line.split("@status")[1].strip()
            break

    # Buscar los 3 fields obligatorios en las primeras líneas
    fields_found = {}
    for line in lines[:15]:  # solo revisar primeras 15 líneas
        line = line.strip()
        if line.startswith("@"):
            continue
        for field in REQUIRED_FIELDS:
            if field in line.upper() and field not in fields_found:
                # Extraer valor después del nombre del field
                match = re.search(rf"{field}\s*[:=]?\s*(\S+)", line, re.IGNORECASE)
                if match:
                    fields_found[field] = match.group(1)

    return {
        "name": name.strip() if name else "",
        "type": typ.strip() if typ else "",
        "version": version.strip() if version else "",
        "status": status,
        "fields": fields_found,
    }


def check_backbone_manifest(tool_path: Path) -> bool:
    """Verifica que la herramienta tenga manifiesto de backbone registrado."""
    # Buscar comentarios o docs que indiquen route registration
    # Por ahora: check si el archivo tiene referencias a backbone o route
    try:
        text = tool_path.read_text(encoding="utf-8", errors="replace")
        # Heurística: tool que menciona backbone, route, o tiene patrón known
        backbone_keywords = ["backbone", "route", "register", "entry_point"]
        kb_lower = text.lower()
        return any(kw in kb_lower for kw in backbone_keywords)
    except Exception:
        return False


def check_gate_tests(tool_path: Path) -> bool:
    """Verifica que el tool tenga tests de gate asociados (test_gate*.py)."""
    try:
        # Buscar en el mismo directorio o hermano tests
        tool_name = tool_path.stem
        # Buscar test_gate*.py en directories hermanos
        test_patterns = [
            tool_path.parent / f"test_{tool_name}_*.py",
            tool_path.parent.parent / f"test_{tool_name}_*.py",
        ]
        for tp in test_patterns:
            if tp.exists():
                return True
        # También check si el archivo mismo tiene referencias a gate checks
        text = tool_path.read_text(encoding="utf-8", errors="replace")
        gate_keywords = ["gate", "negative", "test", "verify"]
        return any(kw in text.lower() for kw in gate_keywords)
    except Exception:
        return False


def determine_vsn_level(fields: dict) -> str | None:
    """Determina el nivel Sn basándose en el campo ROL."""
    rol = fields.get("ROL", "").strip()
    # Mapeo de rol a nivel
    level_map = {
        "S1": "S1",
        "S2": "S2",
        "S3": "S3",
        "S3*": "S3*",
        "S4": "S4",
        "S5": "S5",
    }
    return level_map.get(rol)


def check_driver_valid(driver: str, level: str) -> bool:
    """Verifica que el driver sea válido para el nivel Sn."""
    # Drivers permitidos por nivel
    drivers_s3 = {"S3": "invariant_guard", "S3*": "audit_scanner"}
    drivers_others = {
        "S1": "φ↑_direct",
        "S2": "event_coordinator",
        "S4": ["LLM_probe", "socratic_engine"],
        "S5": "consent_gate",
    }

    if level in drivers_s3:
        return driver in drivers_s3

    if level in drivers_others:
        allowed = drivers_others[level]
        if isinstance(allowed, list):
            return driver in allowed
        return driver == allowed

    return False


# ──────────────────────────────────────────────────────────────────────
# 3. FUNCIÓN PRINCIPAL DE VALIDACIÓN
# ──────────────────────────────────────────────────────────────────────

def validate_tool_integration(tool_path: Path) -> dict:
    """
    Valida la integración de una herramienta nueva.

    Retorna: {valid: bool, reasons: [str], level: str, driver: str}
    """
    reasons = []

    # 1. Leer header VSM
    header = read_vsm_header(tool_path)
    if header is None:
        return {
            "valid": False,
            "reasons": ["✗ No se pudo leer header VSM ↔⟦ ... ⟧"],
            "level": None,
            "driver": None,
            "name": tool_path.name,
        }

    # 2. Verificar fields obligatorios
    missing_fields = [f for f in REQUIRED_FIELDS if f not in header.get("fields", {})]
    if missing_fields:
        reasons.append(f"✗ Faltan fields obligatorios: {', '.join(missing_fields)}")

    # 3. Determinar nivel Sn
    level = determine_vsn_level(header.get("fields", {}))
    if level is None:
        reasons.append(f"✗ No se pudo determinar nivel Sn desde field ROL: {header.get('fields', {}).get('ROL', 'N/A')}")
    else:
        # 4. Verificar driver para ese nivel
        driver = header.get("fields", {}).get("DRIVER", "")
        if not check_driver_valid(driver, level):
            allowed = (
                {"invariant_guard", "audit_scanner"}
                if level in {"S3", "S3*"}
                else {
                    "S1": "φ↑_direct",
                    "S2": "event_coordinator",
                    "S4": "LLM_probe|socratic_engine",
                    "S5": "consent_gate",
                }
            )
            reasons.append(
                f"✗ Driver '{driver}' no válido para nivel {level}. Drivers permitidos: {allowed}"
            )

    # 5. Verificar backbone manifest
    if not check_backbone_manifest(tool_path):
        reasons.append("✗ No registrada en backbone manifest (falta route/entry_point)")

    # 6. Verificar tests de gate
    if not check_gate_tests(tool_path):
        reasons.append("✗ No tiene tests de gate asociados (test_gate*.py o referencias)")

    # 7. Determinar driver principal
    driver = header.get("fields", {}).get("DRIVER", "")

    valid = len([r for r in reasons if r.startswith("✗")]) == 0

    return {
        "valid": valid,
        "reasons": reasons,
        "level": level,
        "driver": driver,
        "name": header.get("name", tool_path.name),
    }


# ──────────────────────────────────────────────────────────────────────
# 4. EJECUCIÓN DIRECTA Y PRE-COMMIT HOOK
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    """Punto de entrada cuando se llama directamente o por pre-commit hook."""
    if len(sys.argv) < 2:
        print("Uso: python3 vsm_integration_validator.py <ruta_a_tool>")
        sys.exit(2)

    tool_path = Path(sys.argv[1])

    if not tool_path.exists():
        print(f"✗ Archivo no encontrado: {tool_path}")
        sys.exit(1)

    result = validate_tool_integration(tool_path)

    if result["valid"]:
        print(f"✓ {result['name']} — Válida (nivel {result['level']}, driver {result['driver']})")
        sys.exit(0)
    else:
        print(f"✗ {result['name']} — Fallos de integración:")
        for reason in result["reasons"]:
            print(f"  {reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()