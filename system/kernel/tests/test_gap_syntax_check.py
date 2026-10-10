"""F4 REFS-OPT B2 — detector SYNTAX_ERROR del gap-resolver (falso+ en .ts).

La deuda: gap-context.ts `syntax-check` usaba `node --check` plano sobre
.ts — en todo `.ts` sano falla con ERR_UNKNOWN_FILE_EXTENSION (falso+
SYNTAX_ERROR; 35 ocurrencias/8 archivos 03-oct, 0 blocks).

Verificado en esta plataforma (node v22.22 sin amaro):
- `node --check` sobre .ts sano -> rc!=0 (el falso+ original);
- `node --check` sobre .ts/.js ESM con `import` -> rc=0 VACIO incluso
  con sintaxis rota (no valida nada) — por eso no es confiable;
- esbuild (PATH o cache npx) valida de verdad: sano rc=0, roto rc!=0.

Fix: .ts/.js via esbuild si existe; sin esbuild el .ts NO setea
syntaxValid -> quality-gate => UNKNOWN honesto (nunca falso SYNTAX_ERROR
ni falso OK).
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GAP_CONTEXT = ROOT / ".opencode" / "plugins" / "operational" / "gap-context.ts"
NODE = shutil.which("node")


def _find_esbuild() -> str | None:
    """Misma resolucion que resolveEsbuild() del detector: PATH, luego npx."""
    p = shutil.which("esbuild")
    if p:
        return p
    base = Path.home() / ".npm" / "_npx"
    if base.is_dir():
        for d in sorted(base.iterdir()):
            c = d / "node_modules" / ".bin" / "esbuild"
            if c.is_file() and os.access(c, os.X_OK):
                return str(c)
    return None


ESBUILD = _find_esbuild()


def _esbuild_check(path: Path) -> int:
    """Mismos args que el detector: --outfile=/dev/null --log-level=error."""
    return subprocess.run(
        [ESBUILD, str(path), "--outfile=/dev/null", "--log-level=error"],
        capture_output=True).returncode


def test_detector_routes_ts_js_through_esbuild():
    """Contrato estático: el detector valida con esbuild, no con node."""
    src = GAP_CONTEXT.read_text()
    # el fix naive (strip-types) quedó fuera: ese check no valida nada
    assert "--experimental-strip-types" not in src
    # .ts/.js pasan por esbuild con los args probados en este test
    assert "await resolveEsbuild()" in src
    assert '"--outfile=/dev/null"' in src
    assert '"--log-level=error"' in src
    # sin esbuild: el .ts no setea syntaxValid (UNKNOWN honesto), .js si
    assert 'else if (!filePath.endsWith(".ts"))' in src
    # el path .py (py_compile) sigue intacto
    assert '"-m", "py_compile"' in src


@pytest.mark.skipif(ESBUILD is None, reason="esbuild no disponible en este env")
def test_esbuild_contract_validates_ts_js(tmp_path):
    """El contrato de args del detector valida de verdad (5/5)."""
    ok_ts = tmp_path / "ok.ts"
    ok_ts.write_text(
        'import { readFileSync } from "node:fs"\n'
        "const x: number = 1\n"
        "export function f(a: number): number { return a + x }\n")
    assert _esbuild_check(ok_ts) == 0

    bad_js = tmp_path / "bad.ts"          # error de JS dentro de .ts
    bad_js.write_text('import { x } from "y"\nconst z = ;\n')
    assert _esbuild_check(bad_js) != 0

    bad_ts = tmp_path / "bad2.ts"         # error de sintaxis TS
    bad_ts.write_text(
        'import { readFileSync } from "node:fs"\n'
        "function broken(: { return }\n")
    assert _esbuild_check(bad_ts) != 0

    ok_js = tmp_path / "ok.js"
    ok_js.write_text('import x from "y"\nconst z = 1\nexport default z\n')
    assert _esbuild_check(ok_js) == 0

    bad_js2 = tmp_path / "bad.js"
    bad_js2.write_text('import x from "y"\nconst z = ;\n')
    assert _esbuild_check(bad_js2) != 0


@pytest.mark.skipif(NODE is None, reason="node requerido")
def test_node_check_cannot_validate_ts(tmp_path):
    """Tripwire: documenta los DOS modos rotos de node --check.

    Si un node futuro arregla cualquiera de los dos, este test revienta
    y hay que re-auditar el detector (podría simplificarse a node)."""
    sano = tmp_path / "sano.ts"
    sano.write_text('import { x } from "y"\nexport const n: number = 1\n')
    # modo 1: sin flag -> ERR_UNKNOWN_FILE_EXTENSION en .ts sano (falso+)
    r1 = subprocess.run([NODE, "--check", str(sano)], capture_output=True)
    assert r1.returncode != 0
    # modo 2: con strip-types -> ESM detectado se SALTA (rc=0 vacío)
    # incluso con sintaxis rota: no valida nada
    rot = tmp_path / "rot.ts"
    rot.write_text('import { x } from "y"\nconst z = ;\nexport { z }\n')
    r2 = subprocess.run(
        [NODE, "--experimental-strip-types", "--check", str(rot)],
        capture_output=True)
    assert r2.returncode == 0
