# design: docs/plans/structural_tensions_plan_2026_10_20.vsm (T3-F2: dedup-attenuator)
"""T3-F2 — algedonic dedup-attenuator: misma clase+detail en <24h = 1 fila
+ contador en sidecar, jamás drop (R9), fail-open.

Plan 2026-10-20 T3 evidencia: el backlog "220 errores 7d sin triage" estaba
inflado por spam idéntico (81 filas E2BIG de la misma clase+detail). El
writer TS era puro appendFileSync sin dedup (el emitter python ya tenía el
suo). Fix: `algedonicAlert` suprime el repeat dentro de 24h y acumula
`count` en `state/rsi/alerts_dedup.json` (escritura atómica tmp+rename,
contrato T6-F1). La PRIMERA fila siempre queda en alerts.jsonl (señal
presente = nunca drop); cualquier error de sidecar cae a append crudo
(attenuation = optimización, jamás path de pérdida).

Ejecución del .ts real: node de esta plataforma NO compila TypeScript
(ERR_NO_TYPESCRIPT, ver test_gap_syntax_check) → se empaqueta el harness +
modulo con esbuild (mismo resolvedor que el detector gap) y se corre el
bundle con node. Sin esbuild/node el test skipea honesto (nunca falso+).
R16: design heredado del SUT (plan que ordena la fix).
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / ".opencode" / "shared" / "algedonic-alert.ts"
NODE = shutil.which("node")


def _find_esbuild() -> str | None:
    """Mismo resolvedor que resolveEsbuild() del detector gap (PATH, npx)."""
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

_HARNESS = (
    '// T3-F2 harness (empaquetado con esbuild): emite N señales y vuelca el estado.\n'
    '// argv: <root> <n>   stdin: JSON {type, source, detail}\n'
    'import { algedonicAlert } from "%s";\n'
    'import { readFileSync } from "node:fs";\n'
    'import { join } from "node:path";\n'
    "const [root, nStr] = process.argv.slice(2);\n"
    "const n = parseInt(nStr, 10);\n"
    'const cfg = JSON.parse(readFileSync(0, "utf-8"));\n'
    "for (let i = 0; i < n; i++) {\n"
    '  algedonicAlert(root, cfg.type, cfg.source, "error", cfg.detail);\n'
    "}\n"
    "const out = {};\n"
    'try {\n  out.rows = readFileSync(join(root, "state", "rsi", "alerts.jsonl"), "utf-8")\n'
    '    .split("\\n").filter((l) => l.trim() !== "").map((l) => JSON.parse(l));\n'
    "} catch { out.rows = []; }\n"
    'try {\n  out.dedup = JSON.parse(readFileSync(join(root, "state", "rsi", "alerts_dedup.json"), "utf-8"));\n'
    "} catch { out.dedup = null; }\n"
    "console.log(JSON.stringify(out));\n"
) % str(MODULE)


def _bundle(tmp_path: Path) -> Path:
    """Harness + modulo → bundle ESM ejecutable por node."""
    harness = tmp_path / "harness.ts"
    harness.write_text(_HARNESS, encoding="utf-8")
    out = tmp_path / "bundle.mjs"
    r = subprocess.run(
        [ESBUILD, str(harness), "--bundle", "--format=esm", "--platform=node",
         f"--outfile={out}", "--log-level=error"],
        capture_output=True, text=True)
    assert r.returncode == 0, f"esbuild failed: {r.stderr}"
    return out


def _run(bundle: Path, root: Path, n: int, type_: str, source: str,
         detail: str) -> dict:
    r = subprocess.run(
        [NODE, str(bundle), str(root), str(n)],
        input=json.dumps({"type": type_, "source": source, "detail": detail}),
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"harness failed: {r.stderr}"
    return json.loads(r.stdout)


def _key(type_: str, source: str, detail: str) -> str:
    """Mismo formato que JSON.stringify de TS (ASCII, sin espacios)."""
    return json.dumps([type_, source, detail], separators=(",", ":"))


pytestmark = [
    pytest.mark.skipif(NODE is None, reason="node requerido"),
    pytest.mark.skipif(ESBUILD is None, reason="esbuild no disponible en este env"),
]


def test_repeat_same_triple_attenuates_to_one_row(tmp_path):
    """3 emisiones idénticas → 1 fila + count:3 (backlog cuenta clases)."""
    b = _bundle(tmp_path)
    root = tmp_path / "repo"
    st = _run(b, root, 3, "t_e2big", "tool-bridge", "same detail")
    assert len(st["rows"]) == 1
    entry = st["dedup"][_key("t_e2big", "tool-bridge", "same detail")]
    assert entry["count"] == 3
    # la fila ES la señal de la entrada (contador ligado a su alert_id)
    assert st["rows"][0]["alert_id"] == entry["alert_id"]


def test_distinct_detail_not_attenuated(tmp_path):
    """Detail distinto = clase distinta → 2 filas, 2 contadores."""
    b = _bundle(tmp_path)
    root = tmp_path / "repo"
    _run(b, root, 1, "t", "src", "detail A")
    st = _run(b, root, 1, "t", "src", "detail B")
    assert len(st["rows"]) == 2
    assert sorted(st["dedup"].keys()) == sorted(
        [_key("t", "src", "detail A"), _key("t", "src", "detail B")])


def test_window_expiry_appends_fresh_row(tmp_path):
    """last_ts >24h → ventana nueva: fila fresca + contador reset a 1."""
    b = _bundle(tmp_path)
    root = tmp_path / "repo"
    st = _run(b, root, 1, "t", "src", "d")
    first_id = st["rows"][0]["alert_id"]
    # envejecer la entrada 25h (wall-clock cutoff, determinista R10)
    dedup_path = root / "state" / "rsi" / "alerts_dedup.json"
    dedup = json.loads(dedup_path.read_text(encoding="utf-8"))
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    dedup[_key("t", "src", "d")]["last_ts"] = old
    dedup_path.write_text(json.dumps(dedup, indent=1), encoding="utf-8")
    st2 = _run(b, root, 1, "t", "src", "d")
    assert len(st2["rows"]) == 2
    entry = st2["dedup"][_key("t", "src", "d")]
    assert entry["count"] == 1
    assert entry["alert_id"] != first_id  # señal fresca, no update vieja


def test_fail_open_sidecar_is_directory(tmp_path):
    """Sidecar inutilizable (es un dir) → append crudo en cada emisión:
    la señal NUNCA se pierde aunque el attenuator esté roto."""
    b = _bundle(tmp_path)
    root = tmp_path / "repo"
    (root / "state" / "rsi" / "alerts_dedup.json").mkdir(parents=True)
    st1 = _run(b, root, 1, "t", "src", "d")
    assert len(st1["rows"]) == 1  # readFileSync(dir) falla → fail-open append
    st2 = _run(b, root, 1, "t", "src", "d")
    assert len(st2["rows"]) == 2  # sin atenuación, jamás drop


def test_fail_open_malformed_sidecar(tmp_path):
    """Sidecar corrupto → tratado como {}: emisión append + reescritura sana."""
    b = _bundle(tmp_path)
    root = tmp_path / "repo"
    side = root / "state" / "rsi"
    side.mkdir(parents=True)
    (side / "alerts_dedup.json").write_text("{not json", encoding="utf-8")
    st = _run(b, root, 1, "t", "src", "d")
    assert len(st["rows"]) == 1
    assert st["dedup"][_key("t", "src", "d")]["count"] == 1


def test_atomic_writer_contract():
    """Pin estático del contrato (T6-F1 + ventana 24h + fail-open)."""
    src = MODULE.read_text(encoding="utf-8")
    assert "renameSync" in src                      # escritura atómica
    assert "alerts_dedup.json" in src               # sidecar canónico
    assert "DEDUP_WINDOW_MS = 24 * 60 * 60 * 1000" in src  # ventana 24h
    assert "never break" in src                     # never-throws
    assert ".tmp.${process.pid}" in src             # tmp único por pid
