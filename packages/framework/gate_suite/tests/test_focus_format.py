"""Tests for the focus-format gate (A-7 / D-03)."""

from __future__ import annotations

import json
import os
import sys

# Make gate_suite importable when pytest resolves this file directly
# (same pattern as test_gate_suite.py).
_FRAMEWORK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _FRAMEWORK_DIR not in sys.path:
    sys.path.insert(0, _FRAMEWORK_DIR)

from gate_suite.gates.focus_format import (
    MAX_NOTE_CHARS,
    _looks_iso_z,
    check,
    negative_case,
    validate_focus,
)


def _entry(**over):
    entry = {
        "ref": "demo-ref",
        "status": "active",
        "note": "short note",
        "started_at": "2026-10-01T12:00:00Z",
        "updated_at": "2026-10-01T12:00:00Z",
    }
    entry.update(over)
    return entry


class TestValidateFocus:
    def test_empty_array_is_valid(self):
        assert validate_focus([]) == []

    def test_valid_entry_passes(self):
        assert validate_focus([_entry()]) == []

    def test_valid_entry_with_detail_passes(self):
        entry = _entry(detail="state/focus_details/demo-ref.md", agent_id="vos-kernel")
        assert validate_focus([entry]) == []

    def test_non_array_rejected(self):
        fails = validate_focus({"ref": "x"})
        assert any("array" in f for f in fails)

    def test_note_over_limit_rejected(self):
        entry = _entry(note="x" * (MAX_NOTE_CHARS + 1))
        fails = validate_focus([entry])
        assert any("chars" in f and str(MAX_NOTE_CHARS) in f for f in fails)

    def test_duplicate_ref_rejected(self):
        fails = validate_focus([_entry(), _entry()])
        assert any("duplicate ref" in f for f in fails)

    def test_missing_required_field_rejected(self):
        entry = _entry()
        del entry["status"]
        fails = validate_focus([entry])
        assert any("missing field status" in f for f in fails)

    def test_bad_status_rejected(self):
        fails = validate_focus([_entry(status="parked")])
        assert any("status" in f for f in fails)

    def test_unknown_field_rejected(self):
        fails = validate_focus([_entry(priority="high")])
        assert any("unknown field priority" in f for f in fails)

    def test_bad_timestamp_rejected(self):
        fails = validate_focus([_entry(updated_at="2026-10-01 12:00")])
        assert any("updated_at" in f for f in fails)


class TestIsoZ:
    def test_valid(self):
        assert _looks_iso_z("2026-10-01T14:07:22Z")

    def test_rejects_date_only(self):
        assert not _looks_iso_z("2026-10-01")

    def test_rejects_offset(self):
        assert not _looks_iso_z("2026-10-01T14:07:22+00:00")

    def test_rejects_non_string(self):
        assert not _looks_iso_z(42)


class TestCheck:
    def test_negative_case_always_rejected(self):
        path = negative_case()
        try:
            assert os.path.exists(path)
            assert check(path) != 0
        finally:
            os.unlink(path)

    def test_valid_fixture_accepted(self):
        path = negative_case()
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data[0]["note"] = "short now"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            assert check(path) == 0
        finally:
            os.unlink(path)

    def test_unreadable_json_rejected(self):
        path = negative_case()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            assert check(path) != 0
        finally:
            os.unlink(path)

    def test_missing_explicit_path_rejected(self):
        assert check("/nonexistent/focus_xyz.json") != 0

    def test_live_focus_is_clean(self):
        """The workspace focus file honours the contract — loud if drift."""
        assert check("") == 0
