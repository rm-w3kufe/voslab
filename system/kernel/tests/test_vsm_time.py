"""CHECK-SCAN unification matrix (2026-09-10).

The canonical rule set lives in vos_kernel.utils.vsm_kernel
(is_hardcoded_timestamp). check.py must agree with it (parity test) so
no shape falls through the cracks (false negatives) and no real
timestamp is flagged (false positives on shape alone are impossible to
avoid entirely — documented limit; generation is the real net).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

VOSLAB = Path(__file__).resolve().parents[3]


def _load_vsm_kernel():
    sys.path.insert(0, str(VOSLAB / "packages" / "framework"))
    try:
        from vos_kernel.utils import vsm_kernel
        return vsm_kernel
    finally:
        pass


vsmk = _load_vsm_kernel()

# (content snippet, must_flag)
MATRIX = [
    ("2026-09-08T01:15:00Z", True),    # zero seconds
    ("2026-09-09T07:30:00Z", True),    # zero seconds (the cybernetic_plan case)
    ("2026-01-01T00:00:00Z", True),    # midnight + year placeholder
    ("2026-09-09T00:15:30Z", True),    # midnight hour
    ("2026-09-09T07:00:45Z", True),    # zero minute
    ("2026-09-09T12:00:00Z", True),    # noon placeholder
    ("1970-01-01T00:00:00Z", True),    # epoch
    ("2000-01-01T10:10:10Z", True),    # y2k
    ("2099-06-01T06:06:06Z", True),    # far future
    ("2025-01-01T03:03:03Z", True),    # previous year
    ("2026-09-09T16:22:24Z", False),   # normal shape: must NOT flag
    ("2026-09-09T21:45:42Z", False),   # normal shape: must NOT flag
    ("no timestamp here", False),
]


@pytest.mark.parametrize("snippet,flagged", MATRIX)
def test_canonical_matrix(snippet, flagged):
    hit = vsmk.is_hardcoded_timestamp(snippet)
    assert (hit is not None) == flagged, (snippet, hit)


def test_generated_timestamps_always_clean():
    for _ in range(50):
        ts = vsmk.get_timestamp()
        assert vsmk.is_hardcoded_timestamp(ts) is None, ts


def test_socratic_gate_well_placed_plan():
    """Recalibration 2026-09-10: docs/plans/*.vsm must pass (rc 0)."""
    import subprocess
    import sys
    p = subprocess.run(
        [sys.executable, str(VOSLAB / "scripts" / "vsl" / "classifier"
                             / "socratic_gate.py"),
         str(VOSLAB / "docs" / "plans" / "unified_tasks.vsm")],
        capture_output=True, text=True, timeout=60,
        cwd=str(VOSLAB),
    )
    assert p.returncode == 0, p.stderr


def test_socratic_gate_misplaced_still_fails(tmp_path):
    """Recalibration must not blind the gate: outside-repo still rc 1."""
    import shutil
    import subprocess
    import sys
    dst = tmp_path / "misplaced.vsm"
    shutil.copy(str(VOSLAB / "docs" / "plans" / "unified_tasks.vsm"), dst)
    p = subprocess.run(
        [sys.executable, str(VOSLAB / "scripts" / "vsl" / "classifier"
                             / "socratic_gate.py"), str(dst)],
        capture_output=True, text=True, timeout=60,
        cwd=str(VOSLAB),
    )
    assert p.returncode == 1
    assert "MISMATCH" in p.stderr


WORKING_DOCS = [
    # (path, must_pass): recalibration matrix 2026-09-10 — every working
    # area with its real TYPEs. A new mismatch here means the taxonomy
    # (not the doc) needs review.
    ("docs/plans/unified_tasks.vsm", True),        # PLAN -> plan
    ("docs/plans/write_hook_autofix.vsm", True),   # PROPOSAL in plans
    ("docs/plans/repo_map.vsm", True),             # MAP in plans
    ("docs/architecture/architecture.vsm", True),  # ARCHITECTURE
    ("docs/reference/vsflab_packages.vsm", True),  # CATALOG
    ("docs/specs/vos_master_plan.vsm", True),      # MASTER-PLAN
    ("docs/index.vsm", True),                      # INDEX at root
]


def _gate(path):
    import subprocess
    import sys
    return subprocess.run(
        [sys.executable, str(VOSLAB / "scripts" / "vsl" / "classifier"
                             / "socratic_gate.py"), str(path)],
        capture_output=True, text=True, timeout=60, cwd=str(VOSLAB))


@pytest.mark.parametrize("rel,want", WORKING_DOCS)
def test_taxonomy_matrix(rel, want):
    p = _gate(VOSLAB / rel)
    assert (p.returncode == 0) == want, (rel, p.stderr[:200])


def test_mirrors_and_archive_skip():
    p = _gate(VOSLAB / "docs" / "canon_mirror" / "hard_rules.vsm")
    assert p.returncode == 0 and "skip" in p.stderr.lower()


def test_check_py_parity():
    """check.py must agree with the canonical set on the whole matrix."""
    spec = importlib.util.spec_from_file_location(
        "vsm_check", str(VOSLAB / "scripts" / "vsl" / "validator" / "check.py"))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    for snippet, flagged in MATRIX:
        res = check.validate_vsm_file.__wrapped__ if hasattr(
            check.validate_vsm_file, "__wrapped__") else None
        # validate content shape: minimal doc carrying the snippet
        doc = ("⟦ m | T-v1 | vsm-1.2.1 | 2026-09-09T16:22:24Z ⟧\n\n"
               "@vsm 1.2.1\n@status active\n\n"
               f"// probe {snippet}\n\n⟦ /m ⟧\n")
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".vsm",
                                         delete=False) as f:
            f.write(doc)
            path = f.name
        try:
            out = check.validate_vsm_file(path)
        finally:
            os.unlink(path)
        hard_errors = [e for e in out["errors"] if "HARDCODED" in e]
        # the probe header itself is clean, so any HARDCODED hit is the snippet
        assert (len(hard_errors) > 0) == flagged, (snippet, hard_errors)
