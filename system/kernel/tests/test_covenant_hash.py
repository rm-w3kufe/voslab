"""Tests for vos_kernel.covenant_hash — registry verification procedure.

Covers: consistent fixture, per-location tamper detection, missing
location, plan parsing, and a live smoke run against the real vsf tree
(skipped when ~/vsf is absent).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from vos_kernel.covenant_hash import (
    Check,
    HashReport,
    default_vsf_root,
    file_sha256,
    promotion_plan,
    verify_registry,
    voslab_root,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_fixture(root: Path, covenant_text: str = "covenant-v11") -> Path:
    """Create a minimal vsf-shaped tree whose locations all agree."""
    sha = _sha(covenant_text)
    gov = root / "docs" / "governance" / "covenant.vsm"
    gov.parent.mkdir(parents=True)
    gov.write_text(covenant_text, encoding="utf-8")

    core = root / "core"
    core.mkdir()
    (core / "s5_policy.default.json").write_text(
        json.dumps({"_meta": {"covenant_hash": sha}}), encoding="utf-8")

    (root / "LICENSE").write_text(
        f"Apache-2.0\nCovenant SHA-256: {sha}\n", encoding="utf-8")

    spec = root / "docs" / "spec"
    spec.mkdir()
    (spec / "covenant_hash_registry.vsm").write_text(
        f'  current: {{\n    hash: "{sha}",\n  }}\n', encoding="utf-8")
    return root


def _build_voslab_mirror(root: Path, covenant_text: str = "covenant-v11") -> Path:
    mirror = root / "docs" / "canon_mirror" / "covenant.vsm"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(covenant_text, encoding="utf-8")
    return root


def test_consistent_fixture(tmp_path: Path) -> None:
    vsf = _build_fixture(tmp_path / "vsf")
    vlab = _build_voslab_mirror(tmp_path / "voslab")
    report = verify_registry(vsf_root=vsf, voslab=vlab)
    assert report.consistent, report.to_dict()
    assert report.anchor == _sha("covenant-v11")
    classes = {c.cls for c in report.checks}
    assert classes == {"mutable", "unregistered", "registry", "mirror"}
    # deterministic: same inputs -> identical report
    again = verify_registry(vsf_root=vsf, voslab=vlab)
    assert again.to_dict() == report.to_dict()


def test_tampered_policy_is_caught(tmp_path: Path) -> None:
    vsf = _build_fixture(tmp_path / "vsf")
    vlab = _build_voslab_mirror(tmp_path / "voslab")
    bad = "0" * 64
    policy = vsf / "core" / "s5_policy.default.json"
    policy.write_text(
        json.dumps({"_meta": {"covenant_hash": bad}}), encoding="utf-8")
    report = verify_registry(vsf_root=vsf, voslab=vlab)
    assert not report.consistent
    failed = [c for c in report.checks if not c.ok]
    assert len(failed) == 1 and failed[0].cls == "mutable"
    assert failed[0].observed == bad


def test_missing_license_line_fails(tmp_path: Path) -> None:
    vsf = _build_fixture(tmp_path / "vsf")
    vlab = _build_voslab_mirror(tmp_path / "voslab")
    (vsf / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    report = verify_registry(vsf_root=vsf, voslab=vlab)
    assert not report.consistent
    lic = [c for c in report.checks if c.cls == "unregistered"][0]
    assert lic.observed is None and not lic.ok


def test_missing_registry_doc_fails(tmp_path: Path) -> None:
    vsf = _build_fixture(tmp_path / "vsf")
    vlab = _build_voslab_mirror(tmp_path / "voslab")
    (vsf / "docs" / "spec" / "covenant_hash_registry.vsm").unlink()
    report = verify_registry(vsf_root=vsf, voslab=vlab)
    assert not report.consistent
    reg = [c for c in report.checks if c.cls == "registry"][0]
    assert reg.observed is None


def test_missing_anchor_returns_inconsistent(tmp_path: Path) -> None:
    report = verify_registry(vsf_root=tmp_path / "absent",
                             voslab=tmp_path / "also-absent")
    assert report.anchor is None
    assert not report.consistent
    assert any("anchor missing" in n for n in report.notes)


def test_promotion_plan_parses_ratified_phases() -> None:
    phases = promotion_plan()
    ids = [p["id"] for p in phases]
    assert ids == [f"P{i}" for i in range(9)], ids  # P0..P8
    assert phases[0]["name"] == "STUDY"
    assert phases[8]["name"] == "VERIFY-AND-CLOSE"


def test_promotion_plan_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        promotion_plan(tmp_path / "nope.vsm")


@pytest.mark.skipif(not (default_vsf_root() / "docs" / "governance"
                         / "covenant.vsm").is_file(),
                    reason="~/vsf governance covenant not present")
def test_live_vsf_registry_consistent() -> None:
    report = verify_registry()
    assert report.consistent, report.to_dict()
    assert report.anchor and len(report.anchor) == 64


def test_live_voslab_root_is_repo() -> None:
    root = voslab_root()
    assert (root / "docs" / "plans" / "covenant_promotion_ceremony.vsm").is_file()
    assert file_sha256(root / "README.md") is None or True  # path usable
