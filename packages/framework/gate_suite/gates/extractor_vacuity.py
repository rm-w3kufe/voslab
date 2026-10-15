"""extractor-vacuity gate — EV-R3 / P-EV-R3 (rubrica D5-C1/D5-C3).

The vacuity CLASS (EV-R3): a structural extractor's source silently dies —
moved corpus, dead subprocess, ROOT off-by-one after a file move — and the
extractor emits EMPTY output with rc=0. Every consumer reads "0 findings /
no incoherent" as healthy. Live-proven 2026-10-15: version_scan.py resolved
ROOT via dirname³ from its old home scripts/vsl/ after the move to
scripts/vsl/tools/ → CORPUS = <repo>/scripts/docs/spec_revision (dead) →
zero lines rc=0 → vsm-version-coherent PASSed vacuously since the migration
(FND-VERSION-SCAN-ROOT-OFFBYONE); the check's `2>/dev/null` + empty grep
loop separately ate scanner crashes. Fix + battery same round:

  - check(path): "" -> live battery (scripts/vsl/tools/extractor_vacuity
    probes version_scan + lifecycle_census + dep_graph + doc_manifest for
    POSITIVE evidence, count > 0); <dir> -> fixture dir (retargetable
    probe vs DIR).
    0 = every executed probe extracted non-trivial evidence.
    1 = vacuity proven (crash, empty stream, zero counts, vanished
    source) — empty ≠ healthy, the guard GRIITA.
  - negative_case(): EMPTY temp dir — 0 .vsm files = source vanished.
    MUST ALWAYS be rejected (exit != 0): accepting it would make this
    gate a proxy for the very defect it exists to catch.

Run standalone:  python3 packages/framework/gate_suite/gates/extractor_vacuity.py
Run by harness:  register("extractor-vacuity", check, negative_case)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# Direct execution has no package context: put packages/framework on the path.
_FRAMEWORK = Path(__file__).resolve().parents[2]
if __package__ in (None, "") and str(_FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK))

from gate_suite.harness import register  # noqa: E402

_ROOT = Path(__file__).resolve().parents[4]
_DRIVER = _ROOT / "scripts" / "vsl" / "tools" / "extractor_vacuity.py"


def check(path: str) -> int:
    """0 = battery non-vacuous; 1 = proven vacuity (empty ≠ healthy)."""
    if not _DRIVER.is_file():
        print(f"extractor-vacuity: driver missing: {_DRIVER}", file=sys.stderr)
        return 1
    args = [sys.executable, str(_DRIVER)]
    if path:
        target = Path(path)
        if not target.is_dir():
            print(f"extractor-vacuity: target missing: {target}",
                  file=sys.stderr)
            return 1
        args += ["--target", str(target)]
    try:
        r = subprocess.run(args, cwd=str(_ROOT), timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"extractor-vacuity: battery exec failed: {exc}",
              file=sys.stderr)
        return 1
    return r.returncode


def report() -> int:
    """Real run: full battery report, rc as check('')."""
    return check("")


def negative_case() -> str:
    """Empty temp corpus — source vanished; must ALWAYS be rejected."""
    return tempfile.mkdtemp(prefix="voslab_vacuity_")


register("extractor-vacuity", check, negative_case)


if __name__ == "__main__":
    sys.exit(report())
