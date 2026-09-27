#!/usr/bin/env python3
# design: docs/spec_revision/sandbox/exp-socratic-tree/socratic_proposal_tree.vsm (EXP-SOCRATIC-TREE)
"""
socratic_proposal.py — PROPUESTA de estructura desde el cuestionario socrático.
Lee el corpus REAL (solo lectura — no toca nada) y propone el árbol completo.

La pregunta socrática POR NIVEL (no global): "¿mis subcarpetas son 1:1
(una carpeta por un doc) y comparten la raíz del TYPE?" — el patrón común
que la versión literal (SEED 1:1) perdió.

Regla de colapso: un directorio con >= 2 subcarpetas, cada una con UN solo
doc, cuyos TYPEs comparten el token raíz (VSL-LANG-* y VSL-LANGUAGE-* →
misma familia del lenguaje) propone fusionarse: los docs suben a docs
directos del directorio. La jerarquía de órganos de la raíz se RESPETA:
la pregunta es local al nivel, nunca global (THEORY-VC-01 en s3-control NO
se fusiona con THEORY-AP-01 en s4-intelligence).

La propuesta se IMPRIME — NO se aplica (materializar = acto declarado,
y aquí presentamos ANTES).
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from socratic_engine import SocraticEngine, tree_home

SR = Path(__file__).resolve().parent.parent.parent / "docs" / "spec_revision"
SKIP = ("README.vsm", "INDEX.vsm", "classification.local.vsm")


def read_type(p: Path) -> str:
    try:
        first = p.read_text(encoding="utf-8").split("\n", 1)[0]
    except Exception:
        return ""
    m = re.match(r"⟦\s*([^|]+)\|\s*([^|]+)\s*\|", first)
    return m.group(2).strip() if m else ""


def root_token(type_: str) -> str:
    """Root token of the TYPE: the first part (VSL-LANG-GATES-v1.0 → VSL).
    For semantic families it also accepts the short-suffix variant:
    VSL-LANG* and VSL-LANGUAGE* → 'VSL-LANG'."""
    parts = type_.split("-")
    if not parts:
        return ""
    return parts[0]


def family_key(type_: str) -> str:
    """Family key: root + first suffix if any.
    VSL-LANG-GATES-v1.0 → VSL-LANG ; VSL-LANGUAGE-INDEX-v1.0 → VSL-LANGUAGE.
    Normalizes LANG(LUAGE): VSL-LANGUAGE is treated as VSL-LANG (same token)."""
    parts = type_.split("-")
    if len(parts) < 2:
        return parts[0]
    first = parts[0]
    second = parts[1]
    if first == "VSL" and second.startswith("LANG"):
        second = "LANG"
    return f"{first}-{second}"


def docs_in(p: Path) -> list[Path]:
    return sorted(f for f in p.iterdir() if f.is_file() and f.suffix == ".vsm" and f.name not in SKIP)


def subdirs_in(p: Path) -> list[Path]:
    return sorted(d for d in p.iterdir() if d.is_dir() and d.name != "__pycache__")


def propose_collapses(dirp: Path) -> list[dict]:
    """Collapse proposals in THIS directory: 1:1 subfolders sharing a family.
    Returns [{dir, family, members:[(subdir, doc, type)]}]."""
    subs = subdirs_in(dirp)
    one2one = [s for s in subs if len(docs_in(s)) == 1 and len(subdirs_in(s)) == 0]
    if len(one2one) < 2:
        return []
    # agrupar por familia
    fams = {}
    for s in one2one:
        d = docs_in(s)[0]
        t = read_type(d)
        k = family_key(t)
        fams.setdefault(k, []).append((s, d, t))
    out = []
    for k, members in fams.items():
        if len(members) >= 2:
            out.append({"family": k, "dir": dirp, "members": members})
    return out


def main() -> int:
    eng = SocraticEngine()

    print("═" * 78)
    print("PROPUESTA DEL CUESTIONARIO SOCRÁTICO — estructura que propone")
    print("(aplicar = acto declarado; esto es SOLO la propuesta, no toca nada)")
    print("═" * 78)

    # ── A. collapses proposed per level (local question) ───────────────────
    print("\n▶ A. COLAPSOS PROPUESTOS (subcarpetas 1:1 de la misma familia):")
    all_collapses = []

    def walk(p: Path, depth: int = 0):
        if depth > 5:
            return
        props = propose_collapses(p)
        for prop in props:
            all_collapses.append(prop)
            fam = prop["family"]
            n = len(prop["members"])
            parent = prop["dir"]
            print(f"\n   📁 {parent.relative_to(SR)}/  ← fusiona {n} subcarpetas en docs directos")
            print(f"      familia: {fam}*")
            for s, d, t in sorted(prop["members"], key=lambda x: x[0].name):
                print(f"        · {s.name}/ ({t}) → {d.name}")
        for sd in subdirs_in(p):
            walk(sd, depth + 1)

    walk(SR)
    if not all_collapses:
        print("   (ningún colapso propuesto — la estructura ya es compacta)")

    # ── B. resumen ─────────────────────────────────────────────────────────
    total_fused = sum(len(c["members"]) for c in all_collapses)
    total_dirs = sum(1 for c in all_collapses for _ in c["members"])
    print(f"\n▶ RESUMEN: {len(all_collapses)} colapsos propuestos, {total_fused} docs que")
    print(f"   suben de subcarpeta 1:1 a docs directos, {total_dirs} carpetas que se fusionan.")

    # ── C. selftest of the socratic engine (R4.1) ─────────────────────────
    print("\n▶ C. SELFTEST — el motor socrático discrimina:")
    demo = {"op": "OR", "children": [
        {"predicate": "type_prefix", "args": ["$type", "VSL-LANG-"], "home": "vsl-language"},
        {"predicate": "type_prefix", "args": ["$type", "VSL-LANGUAGE-"], "home": "vsl-language"},
        {"predicate": "type_prefix", "args": ["$type", "THEORY-VC-"], "home": "s3-control/theory-vc-01"},
        {"predicate": "type_prefix", "args": ["$type", "THEORY-AP-"], "home": "s4-intelligence/theory-ap-01"},
        {"predicate": "type_glob", "args": ["$type", "*"], "home": "sandbox"},
    ]}
    for t in ["VSL-LANG-GATES-v1.0", "VSL-LANGUAGE-INDEX-v1.0",
              "THEORY-VC-01", "THEORY-AP-01", "UNKNOWN-X"]:
        print(f"      {t} → {tree_home(demo, t, eng)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
