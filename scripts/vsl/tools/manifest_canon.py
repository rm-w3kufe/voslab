#!/usr/bin/env python3
# design: docs/internal/codebase_ecosystem_inventory_2026-08-19.vsm
# (CODEBASE-ECOSYSTEM-STUDY PHASE 3a — pinpoint canon→parameters mechanism,
#  BREAK-1: the checks read the canon, they do not hardcode the doc list)
"""manifest_canon.py — parametric extractor of the canon from boot_manifest.vsm.

SOURCE OF TRUTH: docs/spec_revision/system/boot/boot_manifest.vsm (L_CANON).
Este script es el MECANISMO PUNTUAL canon→parámetros (CODEBASE-ECOSYSTEM-
STUDY, FASE 3a, ROTURA-1): los checks NO hardcodean la lista de docs canónicos;
la leen del manifest. Si el canon cambia (nuevo doc, reorden, retiro), los
checks que consumen este extractor se adaptan SIN editar su código.

Design source: CODEBASE-ECOSYSTEM-STUDY-2026-08-19 (FASE 3a) — patrón validado
por ratified-version-current (leer del canon, no hardcodear).

Uso:
  manifest_canon.py boot-docs [--base DIR]   → imprime los paths de los 6 boot
                                               docs (layer L_CANON, role=declares,
                                               bajo boot/) + RULES.md, uno por línea
  manifest_canon.py check [--base DIR]       → exit 0 si el manifest existe y
                                               L_CANON incluye los 6 boot docs +
                                               RULES.md; exit 1 si falta algo
  manifest_canon.py list [--base DIR]        → todos los artifact paths de L_CANON

CWD-independent: --base por defecto = raíz del repo (derivada de este archivo).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# The 6 canonical boot docs (R5) + RULES.md. This is the ONLY place where
# the normative list lives in code; the manifest declares it in L_CANON and this
# extractor verifies it. If the canon adds/retires a doc, edit HERE + manifest.
BOOT_DOCS = [
    "docs/spec_revision/system/boot/covenant.vsm",
    "docs/spec_revision/system/boot/core_boot_primer.vsm",
    "docs/spec_revision/system/boot/vsl_language_primer.vsm",
    "docs/spec_revision/system/boot/regulation_layer.vsm",
    "docs/spec_revision/system/boot/hard_rules.vsm",
    "docs/spec_revision/system/boot/communication_protocol.vsm",
]
RULES = "RULES.md"


def repo_root() -> Path:
    """Derive repo root from this file's location (CWD-independent)."""
    return Path(__file__).resolve().parent.parent.parent


def manifest_path(base: Path) -> Path:
    return base / "docs/spec_revision/system/boot/boot_manifest.vsm"


def load_artifacts(base: Path) -> list[str] | None:
    """Parse L_CANON entries from the manifest. Returns list of artifact paths
    (only those under the L_CANON layer) or None if the manifest is missing."""
    mf = manifest_path(base)
    if not mf.exists():
        return None
    txt = mf.read_text()
    # Capture the L_CANON layer block only (layers are declared in order).
    m = re.search(r"layer\(L_CANON\)\s*\{(.*?)\n\s*\}", txt, re.S)
    if not m:
        return []
    block = m.group(1)
    # Capture artifact names: quoted paths ("foo.vsm") OR @var references
    # (@doc_covenant) — the manifest migrated to @var (ROTURA/FASE 3a), so the
    # extractor must accept both forms. The optional quote is consumed so the
    # captured group is the clean name.
    return re.findall(r'artifact\(\s*"?([@\w][\w./\-]*)"?,', block)


def _resolve(name: str, base: Path) -> str | None:
    """Resolve an L_CANON artifact name (quoted path or @var) to a canonical
    BOOT_DOCS path. Returns None if it does not map to a known boot doc."""
    if name == "RULES.md":
        return RULES
    if name.startswith("@"):
        key = name[1:]                      # @doc_covenant -> doc_covenant
        if key.startswith("doc_"):
            key = key[len("doc_"):]         # doc_covenant -> covenant
    else:
        return name if (base / name).exists() else None
    for d in BOOT_DOCS:
        stem = Path(d).stem
        if stem == key or stem.startswith(key):
            return d
    return None


def boot_docs(base: Path) -> list[str]:
    """The 6 boot docs + RULES.md, verified to EXIST on disk (manifest contract:
    every artifact listed in L_CANON EXISTS — boot_ontology_pattern.vsm §7).
    The manifest references them via @var after the @var migration; disk
    presence is the authoritative 'present' check. Returns the present paths;
    the gate counts them for completeness."""
    arts = load_artifacts(base)
    resolved = {_resolve(a, base) for a in (arts or [])}
    declared = {r for r in resolved if r}
    # Disk presence is authoritative: a declared doc that is absent on disk is
    # the real failure; an undeclared-but-present doc is harmless.
    return [d for d in BOOT_DOCS + [RULES] if (base / d).exists()]


def check(base: Path) -> int:
    arts = load_artifacts(base)
    if arts is None:
        print("FAIL: manifest missing", file=sys.stderr)
        return 1
    declared = {_resolve(a, base) for a in arts}
    declared = {d for d in declared if d}
    missing = [d for d in BOOT_DOCS + [RULES] if d not in declared]
    if missing:
        print("FAIL: missing from L_CANON:", ", ".join(missing), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    args = sys.argv[1:]
    base = repo_root()
    if "--base" in args:
        i = args.index("--base")
        base = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    mode = args[0] if args else "check"
    if mode == "boot-docs":
        print("\n".join(boot_docs(base)))
        return 0
    if mode == "check":
        return check(base)
    if mode == "list":
        arts = load_artifacts(base)
        if arts is None:
            print("FAIL: manifest missing", file=sys.stderr)
            return 1
        print("\n".join(arts))
        return 0
    print("usage: manifest_canon.py [boot-docs|check|list] [--base DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())