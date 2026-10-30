"""Tests for the kernel DOC-HOME resolver (F4 DOC-HOME-POLICY, 2026-10-29).

The resolver is the write-time contract for NEW documents: a typed doc must
land in the policy home; a new doc outside the approved homes is blocked; a
tracked legacy doc stays editable (advisory) until its cleanup wave.
"""
from pathlib import Path
from uuid import uuid4

import pytest

from vos_kernel.utils import doc_home


ROOT = doc_home.ROOT


def _write_doc(path: Path, doc_type: str = "UNKNOWN-TYPE-v1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"⟦ doc_home_test | {doc_type} | vsm-1.2.1 | 2026-10-29T10:30:00Z ⟧\n\n"
        "@vsm 1.2.1\n@status active\n\n// test fixture\n\n"
        "⟦ /doc_home_test ⟧\n",
        encoding="utf-8",
    )


def test_home_policy_loads_records_and_outputs():
    C = doc_home.classifier()
    assert C.physical_home("papers") == ROOT / "docs/papers"
    assert C.physical_home("sessions") == ROOT / "docs/sessions"
    assert C.physical_home("audit") == ROOT / "docs/audit"
    assert "papers" in C.APPROVED_HOMES
    assert "archive" not in C.APPROVED_HOMES
    assert "docs/experiments" in C.LEGACY_AREAS


def test_suggest_known_type_returns_policy_home():
    d = doc_home.suggest("PLUGIN-CLASS-TAXONOMY-v1", "active", "x.vsm")
    assert d.ok
    assert d.expected == ROOT / "docs/design/sources/plugin-class-taxonomy-v1"
    assert "plugin-class-taxonomy-v1" in d.message


def test_suggest_unknown_type_lists_approved_homes():
    d = doc_home.suggest("ZZZ-NO-SUCH-TYPE-v1", "active", "x.vsm")
    assert not d.ok
    assert "docs/papers" in d.message
    assert "docs/experiments" not in d.message


def test_check_canonical_doc_ok():
    d = doc_home.check_path(ROOT / "system/s5-policy/vsl-language/definitions_theory.vsm")
    assert d.ok
    assert not d.advisory
    assert d.reason == "canonical"


def test_check_typed_doc_outside_home_blocks(tmp_path):
    f = tmp_path / "misplaced.vsm"
    src = ROOT / "system/s5-policy/vsl-language/definitions_theory.vsm"
    f.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    d = doc_home.check_path(f)
    assert not d.ok
    assert d.reason == "mismatch"
    assert "system/s5-policy/vsl-language" in d.message


def test_check_new_doc_in_approved_home_ok():
    f = ROOT / "docs/papers" / f"__doc_home_test_{uuid4().hex}.vsm"
    try:
        _write_doc(f)
        d = doc_home.check_path(f)
        assert d.ok
        assert d.reason == "approved-area"
    finally:
        f.unlink(missing_ok=True)


def test_check_new_doc_in_legacy_area_blocks():
    f = ROOT / "docs/experiments" / f"__doc_home_test_{uuid4().hex}.vsm"
    try:
        _write_doc(f)
        d = doc_home.check_path(f)
        assert not d.ok
        assert d.reason == "legacy-new"
        assert "docs/experiments" in d.message
    finally:
        f.unlink(missing_ok=True)


@pytest.mark.skipif(
    not (ROOT / "docs/experiments/calibration.vsm").exists(),
    reason="legacy fixture moved by the F4 cleanup",
)
def test_check_tracked_legacy_doc_is_advisory():
    d = doc_home.check_path(ROOT / "docs/experiments/calibration.vsm")
    assert d.ok
    assert d.advisory
    assert d.reason in ("legacy-area", "legacy-mismatch")


def test_check_state_artefact_is_skipped():
    d = doc_home.check_path(ROOT / "TASKS.vsm")
    assert d.ok
    assert d.reason == "skip"
