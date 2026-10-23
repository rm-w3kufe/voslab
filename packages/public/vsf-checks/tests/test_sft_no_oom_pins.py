# design: commit 6d80f63 (v12 ladder FIX) + state/rsi/opportunity_ledger.jsonl
#         entry firma=except-pin-cuda-tensor-leak-ladder (2026-10-23)
"""Guard test: el driver SFT (sft_train.py) NO retiene objetos exception
OOM fuera del handler — retenerlos pina CUDA tensors via traceback frames
(v10 incident: 7.5→12.9→14.1GiB antes de train, 512/384 murieron aunque
caben). La convención v12 (6d80f63): capturar str(e) en un string y
`del e` antes de continuar; el run ab succesiva arranca con headroom full.

R10 parse-level: mismo archivo → mismo veredicto siempre (R10).
NC interno: fixture mutada que retiene `e` en dict sin del → falla
(exige discriminación real, R4.1).
"""
from __future__ import annotations

import ast
from pathlib import Path

SFT = (Path(__file__).resolve().parents[1]  # .../vsf-checks/tests
       .parent.parent                       # .../vOSlab/packages
       .parent.joinpath("projects", "arc-prize", "agi2", "sft_train.py"))


def _pins(src: str) -> list[str]:
    """Encuentra handlers `except ... as NAME:` que capturan NAME en un
    sitio que OUTLIFEAN del handler (assign a variable no-del, push a
    dict/list). Retorna lista de problemas legibles (vacía = clean)."""
    out: list[str] = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.name is None:
            continue
        name = node.name
        # statements top-level del handler body + nested try bodies
        bodies: list[ast.stmt] = list(node.body)
        deleted = False
        carried = []
        while bodies:
            st = bodies.pop()
            if isinstance(st, ast.Delete):
                for t in st.targets:
                    if isinstance(t, ast.Name) and t.id == name:
                        deleted = True
            if isinstance(st, ast.Try):
                for sub in st.body + st.orelse:
                    bodies.append(sub)
            if isinstance(st, ast.Assign):
                for t in st.targets:
                    if (isinstance(t, ast.Name)
                            and t.id != name
                            and any(isinstance(n, ast.Name)
                                    and n.id == name
                                    for n in ast.walk(st.value))):
                        carried.append(t.id)
        if carried and not deleted:
            out.append(f"{name} → carried into {carried} sin del")
    return out


def test_sft_no_oom_exception_pins():
    src = SFT.read_text(encoding="utf-8")
    hmm = _pins(src)
    assert not hmm, f"sft_train.py retiene exceptions OOM: {hmm}"


def test_guard_discriminates_nc():
    # NC: un driver mal construido que retiene e → _pins DEBE señalar
    bad = """
def go():
    oom_msg = None
    try:
        1 / 0
    except ZeroDivisionError as e:
        oom_msg = {"msg": str(e0), "obj": e}
    if res is None:
        raise RuntimeError(str(oom_msg))
"""
    import textwrap
    pins = _pins(textwrap.dedent(bad))
    assert len(pins) == 1 and "carried into" in pins[0]
