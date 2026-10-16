"""derived-state-writers gate — P4 negative control (R16 fase 2).

From docs/plans/scripts_r16_policy_proposal.vsm (ratified S5 2026-10-16):
every instrument that (re)writes derived state must be DECLARED in
DERIVED_STATE_WRITERS inside scripts/vsl/tools/derived_resync.py.

The LIVE check (packages/public/vsf-checks/checks/derived-state-writers-
valid) enforces the full claim on the workspace (registry consistency +
AST writer-scan coverage). THIS gate proves the structural half is
NECESSARY: a registry that points at a PHANTOM writer, or that is EMPTY,
must be REJECTED. If either is accepted, the gate is a no-op — exactly
the defect class the harness exists to catch (vsf plugin-location).

R10: deterministic structural validation; no randomness.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

from gate_suite.harness import register

_ROOT = Path(__file__).resolve().parents[4]
_REGISTRY = _ROOT / "scripts" / "vsl" / "tools" / "derived_resync.py"


def _load(path: Path):
    """Import a registry module; return (writers, exempt) or None."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_dsw_probe", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    writers = getattr(mod, "DERIVED_STATE_WRITERS", None)
    exempt = getattr(mod, "PRIMARY_OR_EXTERNAL_WRITERS", None)
    if writers is None:
        return None
    return writers, (exempt or ())


def check(path: str) -> int:
    """0 = registry valid; !=0 = rejected (phantom/malformed/empty)."""
    target = Path(path) if path else _REGISTRY
    loaded = _load(target)
    if loaded is None:
        print(f"derived-state-writers: registry inimportable o sin "
              f"DERIVED_STATE_WRITERS: {target}", file=sys.stderr)
        return 1
    writers, exempt = loaded
    if not writers:
        print("derived-state-writers: DERIVED_STATE_WRITERS vacío "
              "(anti-vacuous — registro sin escritores)", file=sys.stderr)
        return 1
    seen = set()
    for entry in writers:
        if not (isinstance(entry, tuple) and len(entry) == 2
                and all(isinstance(x, str) and x.strip() for x in entry)):
            print(f"derived-state-writers: entrada malformada "
                  f"(se espera (script, target-desc)): {entry!r}",
                  file=sys.stderr)
            return 1
        script, desc = entry
        if script in seen:
            print(f"derived-state-writers: writer duplicado: {script}",
                  file=sys.stderr)
            return 1
        seen.add(script)
        if not (_ROOT / script).is_file():
            print(f"derived-state-writers: writer registrado NO existe "
                  f"(phantom): {script}", file=sys.stderr)
            return 1
        if not desc.strip():
            print(f"derived-state-writers: target-desc vacío: {script}",
                  file=sys.stderr)
            return 1
    seen_e = set()
    for entry in exempt:
        if not (isinstance(entry, tuple) and len(entry) == 2
                and all(isinstance(x, str) and x.strip() for x in entry)):
            print(f"derived-state-writers: exención malformada: {entry!r}",
                  file=sys.stderr)
            return 1
        if entry[0] in seen_e:
            print(f"derived-state-writers: exención duplicada: {entry[0]}",
                  file=sys.stderr)
            return 1
        seen_e.add(entry[0])
    return 0


def negative_case() -> str:
    """Registry whose writer points at a phantom script — MUST be rejected."""
    d = tempfile.mkdtemp(prefix="voslab_dsw_")
    fixture = Path(d) / "derived_resync.py"
    fixture.write_text(
        'DERIVED_STATE_WRITERS = (\n'
        '    ("scripts/vsl/tools/__phantom_writer__.py",\n'
        '     "state/phantom.jsonl — fixture"),\n'
        ')\n'
        "PRIMARY_OR_EXTERNAL_WRITERS = ()\n",
        encoding="utf-8",
    )
    return str(fixture)


register("derived-state-writers", check, negative_case)


if __name__ == "__main__":
    sys.exit(check(sys.argv[1] if len(sys.argv) > 1 else str(_REGISTRY)))
