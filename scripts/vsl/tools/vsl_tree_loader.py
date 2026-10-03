#!/usr/bin/env python3
"""vsl_tree_loader — carga árboles socráticos VSL/JSON sin nodos-basura.

WHY (2026-10-03, errors.txt): socratic_engine.tree._parse_vsl_value NO
strippea comentarios `//` — dentro de un bloque `children: [ ... ]` un
comment line se parsea como nodos string sueltos ("//" y fragmentos), y
engine.evaluate lanza `ValueError: Nodo inválido ... Recibido: //` la
primera vez que un branch sin short-circuit los alcanza (doc-type que no
matchea ningún prefix temprano: REGISTRY, PLAN, vacío, ...). Repro:
  eval_tree_vsf.py classify.tree.vsm --doc-type REGISTRY → crash
  eval_tree_vsf.py classify.tree.vsm --doc-type PLAN-REGISTRY → OK
(short-circuit TRUE antes del comment).

FIX LOCAL (vOSlab): strip comments A nivel de texto, fuera de strings —
antes de parse_socratic_block. Los dos callers vOSlab (eval_tree_vsf.py
wrapper y vsf_socratic_engine.py directo) pasan por aqui; el parser
externo no se toca. vsf_socratic_engine._clean_tree queda como defensa
en capas (post-parse, filtra strings residuales).

Safety: `//` dentro de "..." (URLs: "http://x") NO se toca — se trackea
in_str con escape backslash.
"""
import json
from pathlib import Path
from typing import Optional, Union

from socratic_engine.tree import parse_socratic_block


def strip_vsl_comments(text: str) -> str:
    """Elimina comentarios `// ... fin de linea` fuera de strings dobles.

    Conserva newlines (posición irrelevante para el parser). Dentro de
    strings con `"` se respeta el contenido crudo (URLs intactas).
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                out.append(text[i:i + 2])
                i += 2
                continue
            if c == '"':
                in_str = False
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and text.startswith("//", i):
            nl = text.find("\n", i)
            if nl < 0:
                break  # comment hasta EOF
            out.append("\n")
            i = nl + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def load_tree_file(path: Union[str, Path]) -> Optional[dict]:
    """Carga árbol .vsm (comentarios strippados) o .json. None si falla."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return None
    if p.suffix == ".json":
        try:
            tree = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return tree if isinstance(tree, dict) else None
    return parse_socratic_block(strip_vsl_comments(raw))


if __name__ == "__main__":
    # smoke: python3 vsl_tree_loader.py <tree.vsm>
    import sys
    if len(sys.argv) != 2:
        print("usage: vsl_tree_loader.py <tree.vsm|tree.json>", file=sys.stderr)
        raise SystemExit(2)
    t = load_tree_file(sys.argv[1])
    if t is None:
        print("load failed", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(t, ensure_ascii=False)[:400])
