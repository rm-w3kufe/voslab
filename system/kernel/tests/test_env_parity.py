# design: docs/plans/system_backlog.vsm (SUT: packages/framework/gate_suite/gates/env_parity.py)
"""D-01 live check — env parity (system_backlog.vsm, 2026-10-01).

The gate suite proves the env-parity gate can CATCH drift (negative
control, run_gates.py); this test makes the live declaration actually RUN
on every suite invocation, so the next 3.13->3.14 flip fails a test in
seconds instead of hiding until something else breaks.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
if str(VOSLAB / "packages" / "framework") not in sys.path:
    sys.path.insert(0, str(VOSLAB / "packages" / "framework"))

from gate_suite.gates import env_parity  # noqa: E402


def test_live_env_parity():
    """Embedded declaration (python pin + critical imports) vs observed env."""
    rc = env_parity.check("")
    assert rc == 0, (
        "env-parity drift — update EXPECTED_PYTHON deliberately (committed) "
        "or repair user-site installs"
    )


def test_negative_fixture_rejected():
    """The fixture path of check() must reject a never-matching manifest."""
    fd, p = tempfile.mkstemp(suffix=".json", dir=tempfile.gettempdir())
    with os.fdopen(fd, "w") as fh:
        json.dump({"python": "9.99",
                   "imports": ["definitely_missing_module_xyz"]}, fh)
    try:
        assert env_parity.check(p) != 0
    finally:
        os.unlink(p)
