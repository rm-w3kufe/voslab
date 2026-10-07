"""NC-22 recall-budget — F5 presupuesto de recall (r4_lote2 §5.6).

Behavioral probe of S3: con k+3 hits sólo salen k; el tope por hit y el
tope total se respetan; el corte queda VISIBLE en truncated=True (nunca
silencioso); el kill switch apaga por completo. ALWAYS cold.

Scenarios:
  A. Corpus con 6 hits (k+3 con k=3) ⇒ exactamente 3 bloques servidos.
  B. Doc gigante + VOS_RECALL_MAX_HIT=200 ⇒ ningún contenido de bloque
     supera el tope por hit.
  C. VOS_RECALL_MAX_TOTAL apretado ⇒ corta antes de k y truncated=True
     (§5.5: 'corta y marca truncated=true — visible, no silencioso').
  D. Kill VOS_RECALL=0 ⇒ sin bloque, sin indexar (rollback completo).
  E. Mismo corpus+query ⇒ mismos bloques (E3/R10: el presupuesto es
     función de la corpus, no del reloj).

Lo que negative_case() viola: el presupuesto declarado — una fixture
declarando truncated='silent' (cortes ocultos) se rechaza: §5.5 exige
visibilidad del corte.

Run by the harness: register("recall-budget", check, negative_case).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from gate_suite.harness import register

_FW = Path(__file__).resolve().parents[2]        # packages/framework
if str(_FW) not in sys.path:
    sys.path.insert(0, str(_FW))

from vos_kernel.recall import PREAMBLE, recall  # noqa: E402

_QUERY = "budgetword"


def _mk_root(tmp: Path, n: int = 6, huge: bool = True) -> Path:
    docs = tmp / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        body = f"budgetword item numero {i} " + ("detalle " * (i + 3))
        if huge and i == 0:
            body += "X" * 8000                 # hit que fuerza el tope
        (docs / f"budget_{i}.vsm").write_text(
            f"⟦ budget_{i} | DOC-v1 | vsm-1.2.1 | 2026-10-07T0{i}:00:00Z ⟧\n"
            f"{body}\n⟦ /budget_{i} ⟧\n",
            encoding="utf-8",
        )
    (tmp / "current_focus.json").write_text("[]", encoding="utf-8")
    return tmp


def _headers(block: str) -> list[str]:
    return [l for l in block.splitlines()
            if l.startswith("<<<VOS-RECALL ")]


def _run_probe() -> list[str]:
    failures: list[str] = []
    saved = {k: os.environ.get(k) for k in
             ("VOS_RECALL", "VOS_RECALL_MODE", "VOS_RECALL_K",
              "VOS_RECALL_MAX_HIT", "VOS_RECALL_MAX_TOTAL")}

    def fail(tag: str, msg: str) -> None:
        failures.append(f"{tag}: {msg}")

    try:
        for k in saved:
            os.environ.pop(k, None)
        with tempfile.TemporaryDirectory() as td:
            root = _mk_root(Path(td))

            # A — k=3 con 6 hits ⇒ solo 3 bloques
            os.environ["VOS_RECALL_K"] = "3"
            res = recall(_QUERY, root=root, mode="live")
            if len(_headers(res.block)) != 3:
                fail("A", f"k=3 con 6 hits debe servir exactamente 3 "
                          f"(sirvió {len(_headers(res.block))})")

            # B — tope por hit: ningún renglón de contenido > MAX_HIT
            os.environ["VOS_RECALL_MAX_HIT"] = "200"
            os.environ["VOS_RECALL_K"] = "6"
            os.environ["VOS_RECALL_MAX_TOTAL"] = "100000"
            res_b = recall(_QUERY, root=root, mode="live")
            inside = False
            for line in res_b.block.splitlines():
                if line.startswith("<<<VOS-RECALL "):
                    inside = True
                    continue
                if line == "<<</VOS-RECALL>>>":
                    inside = False
                    continue
                if inside and len(line) > 200:
                    fail("B", f"contenido de bloque {len(line)} chars > "
                              f"MAX_HIT 200")
                    break

            # C — tope total apretado ⇒ corte visible
            os.environ["VOS_RECALL_MAX_TOTAL"] = "900"
            res_c = recall(_QUERY, root=root, mode="live")
            n = len(_headers(res_c.block))
            if not res_c.truncated or n >= 6:
                fail("C", f"corte total debe marcar truncated=True y servir "
                          f"< k (truncated={res_c.truncated}, headers={n})")

            # D — kill switch: apagado total
            os.environ["VOS_RECALL"] = "0"
            res_d = recall(_QUERY, root=root, mode="live")
            if res_d.mode != "off" or res_d.block or res_d.hits or \
                    res_d.indexed != 0:
                fail("D", f"VOS_RECALL=0 debe apagar todo "
                          f"(mode={res_d.mode}, indexed={res_d.indexed})")

            # E — determinismo con presupuesto activo
            os.environ.pop("VOS_RECALL", None)
            os.environ["VOS_RECALL_MAX_TOTAL"] = "100000"
            e1 = recall(_QUERY, root=root, mode="live")
            e2 = recall(_QUERY, root=root, mode="live")
            if e1.block != e2.block or e1.truncated != e2.truncated:
                fail("E", "presupuesto no determinista (E3/R10)")
            if not e1.block.startswith(PREAMBLE):
                fail("E", "falta preamble con presupuesto activo")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return failures


def check(path: str) -> int:
    """Validate a budget fixture (if given) AND run the probe."""
    if path and path.endswith(".json") and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                declared = json.load(fh)
        except (OSError, ValueError):
            sys.stderr.write(f"recall-budget: unreadable fixture {path}\n")
            return 1
        policy = declared.get("truncated")
        if policy != "visible":
            sys.stderr.write(
                f"recall-budget: política de corte declarada {policy!r} — "
                "§5.5: si el presupuesto no alcanza, corta y marca "
                "truncated=true (visible, no silencioso); solo "
                "'visible' es válido\n"
            )
            return 1
    failures = _run_probe()
    for m in failures:
        sys.stderr.write(f"recall-budget: {m}\n")
    if failures:
        return 1
    sys.stderr.write(
        "recall-budget: probe A-E green (k+3→k, tope por hit, corte "
        "truncated visible, kill switch total, determinismo)\n"
    )
    return 0


def negative_case() -> str:
    """A fixture declaring silent truncation — must be rejected (§5.5)."""
    fd, p = tempfile.mkstemp(prefix="recall_budget.", suffix=".json",
                             dir=tempfile.gettempdir())
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"truncated": "silent"}, fh)
    return p


register("recall-budget", check, negative_case)
