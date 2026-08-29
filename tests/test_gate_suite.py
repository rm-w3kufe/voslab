"""Tests for the vOSLAB gate-suite negative-control harness."""

import tempfile

from gate_suite.harness import register, run_negative_controls, GATES
from gate_suite.gates import plugin_location_valid as plv


def test_real_gate_rejects_negative_case():
    """The rebuilt plugin-location-valid actually discriminates (vsf defect fixed)."""
    p = plv.negative_case()
    assert plv.check(p) != 0  # rejects the mislocated plugin
    # cleanup
    if p.startswith(tempfile.gettempdir()):
        import os
        os.remove(p)

    good = plv.positive_case()
    assert plv.check(good) == 0  # accepts a correctly located plugin


def test_harness_passes_with_real_gates():
    """Importing the registry registers real gates; harness must pass."""
    import gate_suite.gates  # noqa: F401  (side-effect registration)
    assert run_negative_controls() == 0


def test_harness_detects_broken_gate():
    """A no-op gate (check always accepts) MUST fail the negative-control harness."""
    before = len(GATES)

    def always_accept(_path: str) -> int:
        return 0  # the vsf defect: gate that rejects nothing

    def bad_artifact() -> str:
        fd, p = tempfile.mkstemp(suffix=".ts")
        import os
        os.write(fd, b"export const handler = {};")
        os.close(fd)
        return p

    register("broken-noop-gate", always_accept, bad_artifact)
    try:
        assert run_negative_controls() == 1  # harness catches the no-op
    finally:
        # restore global registry so other tests are unaffected
        del GATES[before:]
