"""boot-ontology gate — promoted from guard G-BOOT-ONTOLOGY (2026-09-30, rmw3).

verify_boot_ontology.py validates system/boot/boot_manifest.vsm against the
real filesystem: every artifact exists at its declared path, its sha256[:16]
matches the declared hash, references resolve, mechanisms carry authority,
MCP artifacts are live. The verifier was dead since the migration (19
violations — FND-BOOTOOLS-PATH-DRIFT-01); after the manifest repair it runs
clean, and this gate keeps that necessity provable via a negative control:
a fixture manifest whose artifact points at a non-existent path MUST be
rejected (the STALE-HASH/MISSING machinery is what makes manifest drift
loud — a manifest nobody checks is a memory that lies).

Inputs: a path ending in boot_manifest.vsm is verified directly (fixture);
anything else verifies THE live manifest (corpus-fixed semantics).

Negative case: temp boot_manifest.vsm with a ghost artifact — exit != 0.
Run by the harness: register("boot-ontology", check, negative_case).
The live audit is G-BOOT-ONTOLOGY in state/epistemic/guards.jsonl
(verifier main + --self).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from gate_suite.harness import register

# repo layout: <root>/packages/framework/gate_suite/gates/...
_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
_VERIFIER = os.path.join(_ROOT, "scripts", "vsl", "validator",
                         "verify_boot_ontology.py")
_LIVE = os.path.join(_ROOT, "system", "boot", "boot_manifest.vsm")

_GHOST = """⟦ ghost_manifest | BOOT-MANIFEST-v1 | vsm-1.2.1 | 2026-09-30T10:00:00Z ⟧  // hardcoded-allow: negative-control fixture

@vsm 1.2.1
@status active

artifact("ghost/nonexistent_artifact.py",
         layer=cycle, role=verifies, hash="0000000000000000",
         owner="negative-control fixture") {}

⟦ /ghost_manifest ⟧
"""


def check(path: str) -> int:
    target = _LIVE
    # mkstemp names are boot_manifest.<random>.vsm — any existing manifest
    # path that is NOT the live one is a fixture and must be verified as-is.
    if path and os.path.exists(path) and os.path.abspath(path) != _LIVE:
        target = path
    try:
        r = subprocess.run(
            [sys.executable, _VERIFIER, "--manifest", target],
            capture_output=True, text=True, timeout=120, cwd=_ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1
    if r.returncode != 0:
        # forward the violation report so the negative-control log shows WHY
        sys.stderr.write(r.stdout or r.stderr or "")
    return r.returncode


def negative_case() -> str:
    fd, p = tempfile.mkstemp(prefix="boot_manifest.", suffix=".vsm",
                             dir=tempfile.gettempdir())
    with os.fdopen(fd, "w") as fh:
        fh.write(_GHOST)
    return p


register("boot-ontology", check, negative_case)
