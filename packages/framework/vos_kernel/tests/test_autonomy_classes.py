"""Tests for A-3 — per-class activation registry (nothing self-promotes)."""

from __future__ import annotations

import json

import pytest

from vos_kernel import autonomy_classes as ac


def _class(**over):
    entry = {
        "id": "demo",
        "name": "Demo class",
        "scope": ["docs/*.vsm"],
        "max_blast_radius": "docs-only",
        "trial_cycles": 3,
        "status": "proposed",
        "auto_execute": False,
        "rationale": "test seed",
    }
    entry.update(over)
    return entry


class TestValidateClass:
    def test_proposed_class_valid(self):
        assert ac.validate_class(_class()) == []

    def test_missing_field(self):
        entry = _class()
        del entry["scope"]
        assert any("missing field scope" in v for v in ac.validate_class(entry))

    def test_bad_status(self):
        fails = ac.validate_class(_class(status="auto"))
        assert any("not in" in v for v in fails)

    def test_auto_execute_true_rejected(self):
        """No class may declare auto_execute=true — ever (R17)."""
        fails = ac.validate_class(_class(auto_execute=True))
        assert any("auto_execute must be false" in v for v in fails)

    def test_ratified_requires_sha_and_signature(self):
        fails = ac.validate_class(_class(status="ratified"))
        assert any("sha_pin" in v for v in fails)
        assert any("s5_signed_at" in v for v in fails)

    def test_ratified_complete_valid(self):
        entry = _class(status="ratified", sha_pin="abc1234",
                       s5_signed_at="2026-10-01T12:00:00Z")
        assert ac.validate_class(entry) == []

    def test_empty_scope_rejected(self):
        assert any("scope" in v for v in ac.validate_class(_class(scope=[])))


class TestValidateRegistry:
    def test_duplicate_ids(self):
        reg = {"classes": [_class(), _class()]}
        assert any("duplicate" in v for v in ac.validate_registry(reg))


class TestCanExecute:
    def test_unknown_class_blocked(self):
        allowed, reason = ac.can_execute("nope", {"classes": []})
        assert not allowed and "unknown" in reason

    def test_proposed_blocked(self):
        """The seed state: proposed classes never execute (S5 must sign)."""
        allowed, reason = ac.can_execute("demo", {"classes": [_class()]})
        assert not allowed
        assert "proposed" in reason and "R17" in reason

    def test_ratified_signed_sha_match_allowed(self):
        reg = {"classes": [_class(status="ratified", sha_pin="abc1234",
                                  s5_signed_at="2026-10-01T12:00:00Z")]}
        allowed, reason = ac.can_execute("demo", reg, head_sha="abc1234")
        assert allowed and "ratified by S5" in reason

    def test_ratified_sha_mismatch_blocked(self):
        reg = {"classes": [_class(status="ratified", sha_pin="abc1234",
                                  s5_signed_at="2026-10-01T12:00:00Z")]}
        allowed, reason = ac.can_execute("demo", reg, head_sha="deadbeef")
        assert not allowed and "sha_pin mismatch" in reason

    def test_schema_violations_block_even_if_ratified(self):
        entry = _class(status="ratified", sha_pin="a", s5_signed_at="t")
        entry["auto_execute"] = True  # forged
        allowed, reason = ac.can_execute("demo", {"classes": [entry]})
        assert not allowed and "schema violations" in reason


class TestLiveRegistry:
    def test_live_registry_valid_and_seed_blocked(self):
        """The committed registry: schema OK, seed class BLOCKED (proof)."""
        registry = ac.load_registry()
        assert ac.validate_registry(registry) == []
        allowed, reason = ac.can_execute("doc-hash-refresh", registry)
        assert not allowed
        assert "proposed" in reason

    def test_live_registry_seed_has_zero_runtime_blast(self):
        registry = ac.load_registry()
        seed = registry["classes"][0]
        assert seed["id"] == "doc-hash-refresh"
        assert seed["auto_execute"] is False
        assert seed["status"] == "proposed"
        assert all("state/rsi" not in g for g in seed["scope"])


class TestCli:
    def test_validate_ok(self, capsys):
        assert ac.main([]) == 0
        assert "schema OK" in capsys.readouterr().out

    def test_check_proposed_rc1(self, capsys):
        assert ac.main(["--check", "doc-hash-refresh"]) == 1
        assert capsys.readouterr().out.startswith("BLOCK ")

    def test_malformed_registry_rc2(self, tmp_path, capsys):
        bad = tmp_path / "reg.json"
        bad.write_text("{not json")
        assert ac.main(["--registry", str(bad)]) == 2
