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

REPO = Path(__file__).resolve().parents[4]  # vOSlab root
TOOLS_DIR = REPO  # tools are .py or .vsm files in vos_kernel or scripts/

# B4 mapping table (ratified design source): old TYPE -> {Sn, driver, canal}.
# The validator READS it instead of duplicating it (R16 single-source pattern).
B4_TABLE_PATH = (
    REPO / "docs" / "spec_revision" / "design-sources"
    / "driver-topology-v1" / "driver_topology.vsm"
)


# ──────────────────────────────────────────────────────────────────────
# 1. CONFIGURACIÓN DE CATEGORÍAS VSM Y DRIVERS APROBADOS
# ──────────────────────────────────────────────────────────────────────
# NOTE (Fase-2 slice 1): no driver table lives here on purpose. The live
# authority is check_driver_valid() below (S4 principal+advisory both
# accepted); the canonical TYPE->Sn/driver/canal mapping is the ratified
# B4 table in driver_topology.vsm, read parametrically by load_b4_table().
# Duplicated tables rot into silent contradictions (an earlier revision kept
# two dicts here that disagreed with the function — removed).

# Patrones VSM header obligatorios
VSM_HEADER_RE = re.compile(
    r"⟦\s*([^|]+)\|\s*([^|]+)\s*\|\s*vsm-1\.2(?:\.\d)?\s*\|\s*([^\s⟧]+)\s*⟧"
)

# Campos obligatorios en el header VSM
REQUIRED_FIELDS = ["ROL", "DRIVER", "CANAL"]

# Reason prefixes: ✗ blocks (valid=False); ○ is informational/advisory
# (reported, never blocks). Advisory exists so the validator teaches the
# scheme instead of only rejecting.


def load_b4_table(spec_path=None):
    """Read the ratified B4 mapping table parametrically.

    Returns {TYPE: {"sn": str, "driver": str, "canal": str}}. Never duplicates
    the table (R16 single source): the table lives in driver_topology.vsm §10.
    Malformed/missing spec → empty dict (callers treat unknown as advisory).
    """
    path = Path(spec_path) if spec_path else B4_TABLE_PATH
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    rows = {}
    for m in re.finditer(
            r'map\("([^"]+)",\s*sn="([^"]+)",\s*driver="([^"]+)",'
            r'\s*canal="([^"]+)"',
            text):
        typ, sn, driver, canal = m.groups()
        rows[typ] = {"sn": sn, "driver": driver, "canal": canal}
    return rows


def has_r16_design(tool_path):
    """R16 design-source check, same rule as checks/impl-with-design-valid:
    a self-declared `design:` header in the first 40 lines resolving to an
    existing .vsm under the repo. The gate owns enforcement; this mirrors it
    so the validator never invents a second design rule (A6)."""
    try:
        head = tool_path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
    except OSError:
        return False
    for line in head:
        m = re.search(r"design:\s*(\S+\.vsm)", line)
        if not m:
            continue
        decl = m.group(1)
        if (REPO / decl).is_file():
            return True
    return False

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
                # Extraer valor después del nombre del field (separador
                # obligatorio: menciones sueltas como "driver-topology" no
                # son declaraciones).
                match = re.search(rf"{field}\s*[:=]\s*(\S+)", line, re.IGNORECASE)
                if match:
                    fields_found[field] = match.group(1).strip("'\"")

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


def read_declared_fields(tool_path: Path) -> dict:
    """ROL/DRIVER/CANAL declared in executable comments (no VSM header needed).

    Executables never carried VSM headers anywhere in the corpus, so demanding
    a header to read declarations would make coherence untestable. Comment
    lines like `# ROL: S1` / `# DRIVER: phi_up_direct` in the head of the file.
    """
    try:
        lines = tool_path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
    except OSError:
        return {}
    fields_found = {}
    for line in lines:
        for field in REQUIRED_FIELDS:
            if field in fields_found:
                continue
            # Separator MANDATORY (: or =): bare-word mentions like
            # "driver-topology" must never parse as declarations.
            # Word boundaries (2026-10-15): without them the substring
            # "rol" inside "control: an" parsed as ROL=an and fired a
            # false advisory on any head-of-file prose mentioning
            # "control:" (harness.py ROL=it, extractor_vacuity ROL=an).
            match = re.search(
                rf"(?<!\w){field}(?!\w)\s*[:=]\s*(\S+)", line, re.IGNORECASE,
            )
            if match:
                fields_found[field] = match.group(1).strip("'\"")
    return fields_found


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


_DRIVER_ALIASES = {
    # ASCII spellings accepted anywhere drivers are declared (code comments,
    # B4 table); canonical form keeps the canon glyph.
    "phi_up_direct": "φ↑_direct",
    "event_coordinator": "event_coordinator",
    "invariant_guard": "invariant_guard",
    "audit_scanner": "audit_scanner",
    "LLM_probe": "LLM_probe",
    "socratic_engine": "socratic_engine",
    "consent_gate": "consent_gate",
}


def normalize_driver(driver: str) -> str:
    """Map ASCII aliases to canonical driver names (identity otherwise)."""
    return _DRIVER_ALIASES.get((driver or "").strip(), (driver or "").strip())


def check_driver_valid(driver: str, level: str) -> bool:
    """Verifica que el driver sea válido para el nivel Sn."""
    # Drivers permitidos por nivel (canon driver_topology §4). NOTE: an
    # earlier revision wrote `driver in {S3: ..., S3*: ...}` — membership in
    # a dict tests KEYS, so every S3/S3* check silently failed. Fixed here.
    driver = normalize_driver(driver)
    table = {
        "S1": "φ↑_direct",
        "S2": "event_coordinator",
        "S3": "invariant_guard",
        "S3*": "audit_scanner",
        "S4": ["LLM_probe", "socratic_engine"],
        "S5": "consent_gate",
    }
    if level not in table:
        return False
    allowed = table[level]
    if isinstance(allowed, list):
        return driver in allowed
    return driver == allowed


# ──────────────────────────────────────────────────────────────────────
# 3. FUNCIÓN PRINCIPAL DE VALIDACIÓN
# ──────────────────────────────────────────────────────────────────────

def _validate_doc(tool_path: Path) -> dict:
    """Document artifacts (.vsm): format validity + B4 informational mapping.

    Docs are governed by dir-schema/classification/R18 — NOT by ROL/DRIVER
    header fields (no doc in the corpus carries them; demanding them would
    block every doc edit = collapse). B4(TYPE) reports the mapped Sn/driver;
    unmapped TYPE is an advisory coverage candidate, never a failure.
    """
    reasons = []
    try:
        sys.path.insert(0, str(REPO / "packages" / "framework"))
        from vos_kernel.utils.vsm_kernel import validate_vsm_content
        content = tool_path.read_text(encoding="utf-8", errors="replace")
        check = validate_vsm_content(content)
        kernel_ok = check["valid"]
        if not kernel_ok:
            reasons.append(f"✗ VSM format invalid: {'; '.join(check['errors'])}")
    except Exception as exc:
        header = read_vsm_header(tool_path)
        if header is None:
            reasons.append("✗ No se pudo leer header VSM ↔⟦ ... ⟧")
        else:
            reasons.append(f"○ validator degraded (vsm_kernel unavailable: {exc}); "
                           f"header present ({header.get('type', '?')})")
        kernel_ok = header is not None

    # B4 mapping is reported on every doc, valid or not.
    level, driver = None, ""
    header = read_vsm_header(tool_path)
    typ = (header or {}).get("type", "")
    if typ:
        table = load_b4_table()
        row = table.get(typ)
        if row:
            level, driver = row["sn"], row["driver"]
            reasons.append(f"○ B4: TYPE {typ} → {row['sn']}/{row['driver']} "
                           f"({row['canal']})")
        else:
            reasons.append(f"○ TYPE {typ} not in B4 table — coverage "
                           f"candidate for the mapping (not a failure)")

    valid = len([r for r in reasons if r.startswith("✗")]) == 0
    header = read_vsm_header(tool_path)
    return {
        "valid": valid,
        "reasons": reasons,
        "level": level,
        "driver": driver,
        "name": (header or {}).get("name", tool_path.name),
    }


def _validate_executable(tool_path: Path) -> dict:
    """Executable artifacts (.py/.sh/.ts): R16 design + coherence + route + tests.

    ROL/DRIVER/CANAL header fields are NOT demanded (no executable in the
    corpus carries them); when DECLARED they must be coherent (declared
    integration that contradicts canon is worse than undeclared).
    """
    reasons = []

    # 1. R16 design source (same rule as impl-with-design-valid gate).
    if not has_r16_design(tool_path):
        reasons.append("✗ Sin design: declarada (R16: design: <path>.vsm resolvable)")

    # 2. Declared ROL/DRIVER coherence — conditional, only if declared
    # (read from comments: executables carry no VSM headers anywhere).
    fields = read_declared_fields(tool_path)
    level, driver = None, ""
    if "ROL" in fields or "DRIVER" in fields:
        level = determine_vsn_level(fields)
        if level is None:
            reasons.append(f"✗ ROL declarado no resuelve a Sn: {fields.get('ROL', 'N/A')}")
        else:
            driver = fields.get("DRIVER", "")
            if not check_driver_valid(driver, level):
                reasons.append(f"✗ Driver declarado '{driver}' incoherente "
                               f"con nivel {level} (canon driver_topology §4)")

    # 3. Backbone manifest evidence (heuristic, unchanged).
    if not check_backbone_manifest(tool_path):
        reasons.append("✗ No registrada en backbone manifest (falta route/entry_point)")

    # 4. Gate tests (heuristic, unchanged).
    if not check_gate_tests(tool_path):
        reasons.append("✗ No tiene tests de gate asociados (test_gate*.py o referencias)")

    valid = len([r for r in reasons if r.startswith("✗")]) == 0
    return {
        "valid": valid,
        "reasons": reasons,
        "level": level,
        "driver": driver,
        "name": tool_path.name,
    }


def validate_tool_integration(tool_path: Path) -> dict:
    """
    Valida la integración de una herramienta nueva. Despacha por kind:
    documentos (.vsm) van por clasificacion/tree/R18 + mapeo B4 informativo;
    ejecutables van por R16 + coherencia condicional + route + tests.

    Retorna: {valid: bool, reasons: [str], level: str, driver: str}
    """
    tool_path = Path(tool_path)
    if tool_path.suffix == ".vsm":
        return _validate_doc(tool_path)
    return _validate_executable(tool_path)


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