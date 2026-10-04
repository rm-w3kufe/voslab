"""
tests/test_regen_manifest.py — S4 checks-audit-checks (failing case first).

The instrument that verifies the instrument set: declared
(checks_manifest.json) vs observed (checks/ files). Before this existed
there was no inventory regeneration command and no audit of the declared
set — 60 stale sizes went unnoticed after the S3 check repoints.
"""

import json
from pathlib import Path

import pytest

from vsf_checks import regen_manifest as rm


def _write_manifest(path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps({"checks": entries}, indent=2))


def test_audit_passes_on_fresh_manifest(tmp_path, monkeypatch):
    """Real workspace: manifest was regenerated this circle -> rc 0."""
    monkeypatch.setattr(rm, "MANIFEST",
                        Path(__file__).resolve().parents[1]
                        / "vsf_checks" / "checks_manifest.json")
    monkeypatch.setattr(rm, "CHECKS_DIR",
                        Path(__file__).resolve().parents[1] / "checks")
    assert rm.audit() == 0


def test_audit_detects_stale_size(tmp_path, monkeypatch):
    """Failing case: a check grew and the manifest still declares the
    old size -> audit must exit 1 (declared != observed)."""
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "some-check").write_text("x" * 10)
    manifest = tmp_path / "checks_manifest.json"
    _write_manifest(manifest, [{
        "name": "some-check", "category": "some",
        "path": "packages/public/vsf-checks/checks/some-check",
        "size": 3, "description": "Check: some-check",
    }])
    monkeypatch.setattr(rm, "CHECKS_DIR", checks)
    monkeypatch.setattr(rm, "MANIFEST", manifest)
    assert rm.audit() == 1


def test_audit_detects_missing_and_extra(tmp_path, monkeypatch):
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "on-disk").write_text("y")
    manifest = tmp_path / "checks_manifest.json"
    _write_manifest(manifest, [{
        "name": "ghost", "category": "ghost",
        "path": "packages/public/vsf-checks/checks/ghost",
        "size": 1, "description": "Check: ghost",
    }])
    monkeypatch.setattr(rm, "CHECKS_DIR", checks)
    monkeypatch.setattr(rm, "MANIFEST", manifest)
    assert rm.audit() == 1


def test_regen_preserves_curated_fields(tmp_path, monkeypatch):
    """Regen renews path+size but must keep curated category/description
    (e.g. covenant-ops-binds-to -> governance) and adopt new checks."""
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "covenant-ops-binds-to").write_text("v" * 50)
    (checks / "brand-new-check").write_text("z" * 7)
    manifest = tmp_path / "checks_manifest.json"
    _write_manifest(manifest, [{
        "name": "covenant-ops-binds-to", "category": "governance",
        "path": "packages/public/vsf-checks/checks/covenant-ops-binds-to",
        "size": 999, "description": "R4 guard: curated text",
    }])
    monkeypatch.setattr(rm, "CHECKS_DIR", checks)
    monkeypatch.setattr(rm, "MANIFEST", manifest)

    data = rm.build()
    by = {c["name"]: c for c in data["checks"]}
    assert by["covenant-ops-binds-to"]["category"] == "governance"
    assert by["covenant-ops-binds-to"]["description"] == "R4 guard: curated text"
    assert by["covenant-ops-binds-to"]["size"] == 50
    assert by["brand-new-check"]["category"] == "brand"
    assert by["brand-new-check"]["description"] == "Check: brand-new-check"


def test_audit_fails_on_unreadable_manifest(tmp_path, monkeypatch):
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "any").write_text("a")
    manifest = tmp_path / "checks_manifest.json"
    manifest.write_text("{not json")
    monkeypatch.setattr(rm, "CHECKS_DIR", checks)
    monkeypatch.setattr(rm, "MANIFEST", manifest)
    assert rm.audit() == 1
