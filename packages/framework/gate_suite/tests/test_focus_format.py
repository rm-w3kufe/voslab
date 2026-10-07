"""Tests for the focus-format gate (A-7 / D-03 / D-30a)."""

from __future__ import annotations

import json
import os
import sys
import tempfile

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
    round_seconds_findings,
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


class TestRoundSecondsFindings:
    """D-30a: hard (post-cutoff hand-typed) vs advisory (historical)."""

    @staticmethod
    def _entry(ref, started, updated):
        return {
            "ref": ref,
            "status": "active",
            "note": "short note",
            "started_at": started,
            "updated_at": updated,
        }

    def test_post_cutoff_round_seconds_is_hard(self):
        entry = self._entry(
            "new-entry", "2026-10-07T09:30:00Z", "2026-10-08T14:05:00Z"  # hardcoded-allow: NC fixture
        )
        hard, advisory = round_seconds_findings([entry])
        assert len(hard) == 2
        assert advisory == []
        # And validate_focus must reject it (hard leg wired in).
        fails = validate_focus([entry])
        assert any("`:00` seconds" in f for f in fails)

    def test_pre_cutoff_round_seconds_is_advisory(self):
        entry = self._entry(
            "old-entry", "2026-09-22T08:00:00Z", "2026-10-03T00:12:00Z"  # hardcoded-allow: grandfathered (D-30 0b)
        )
        hard, advisory = round_seconds_findings([entry])
        assert hard == []
        assert len(advisory) == 2
        # Advisory never fails validation (0b: not rewritten, not red).
        assert validate_focus([entry]) == []

    def test_clean_timestamps_no_findings(self):
        entry = self._entry(
            "clean-entry", "2026-10-07T09:30:41Z", "2026-10-07T11:12:13Z"
        )
        hard, advisory = round_seconds_findings([entry])
        assert hard == [] and advisory == []

    def test_malformed_timestamps_left_to_iso_check(self):
        # Non-ISO values are validate_focus's job; findings skip them.
        entry = self._entry("bad-entry", "not-a-ts", "2026-10-07T09:30:00Z")  # hardcoded-allow: NC fixture
        hard, advisory = round_seconds_findings([entry])
        assert len(hard) == 1  # only the well-formed `:00` one
        assert validate_focus([entry])  # malformed still rejected


class TestCheck:
    def test_negative_case_always_rejected(self):
        path = negative_case()
        try:
            assert os.path.exists(path)
            assert check(path) != 0
        finally:
            os.unlink(path)

    def test_valid_fixture_accepted(self):
        # The NC fixture fails on `:00` seconds (D-30); repairing the
        # timestamps (as code generation would emit) makes it valid.
        path = negative_case()
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data[0]["started_at"] = "2026-10-07T09:30:41Z"
            data[0]["updated_at"] = "2026-10-07T09:30:41Z"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            assert check(path) == 0
        finally:
            os.unlink(path)

    def test_wall_note_still_rejected(self):
        # D-30a took the harness NC slot, but the wall-note leg must
        # stay enforced (one NC per gate, both legs tested).
        fd, p = tempfile.mkstemp(prefix="focus_format.wall.", suffix=".json")
        entry = {
            "ref": "wall-note",
            "status": "active",
            "note": "x" * (MAX_NOTE_CHARS + 1),
            "started_at": "2026-10-01T12:34:56Z",
            "updated_at": "2026-10-01T12:34:56Z",
        }
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump([entry], fh)
        try:
            assert check(p) != 0
        finally:
            os.unlink(p)

    def test_historical_round_seconds_advisory_only(self):
        # Pre-cutoff `:00` (the 16 grandfathered entries, 0b): reported
        # as advisory, never a failure — check passes.
        fd, p = tempfile.mkstemp(prefix="focus_format.hist.", suffix=".json")
        entry = {
            "ref": "old-entry",
            "status": "done",
            "note": "short note",
            "started_at": "2026-09-22T08:00:00Z",  # hardcoded-allow: grandfathered fixture (D-30 0b)
            "updated_at": "2026-10-03T00:12:00Z",  # hardcoded-allow: grandfathered fixture (D-30 0b)
        }
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump([entry], fh)
        try:
            assert check(p) == 0
        finally:
            os.unlink(p)

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
