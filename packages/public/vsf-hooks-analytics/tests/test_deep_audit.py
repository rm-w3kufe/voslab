"""tests/test_deep_audit.py — Tests for deep audit."""

import tempfile
import os

import pytest
from vsf_hooks_analytics.deep_audit import DeepAudit


class TestDeepAudit:
    def test_init(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = DeepAudit(roots=[tmpdir])
            assert len(audit.roots) == 1

    def test_audit_all_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = DeepAudit(roots=[tmpdir])
            result = audit.audit_all()
            assert result["summary"]["phantom_refs"] == 0
            assert result["summary"]["broken_links"] == 0
            assert result["summary"]["missing_headers"] == 0

    def test_find_missing_headers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a VSM file without proper header
            with open(os.path.join(tmpdir, "test.vsm"), "w") as f:
                f.write("This is not a valid VSM file")
            audit = DeepAudit(roots=[tmpdir])
            result = audit.find_missing_headers()
            assert len(result) == 1

    def test_find_invalid_encoding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file with invalid encoding
            with open(os.path.join(tmpdir, "test.vsm"), "wb") as f:
                f.write(b"\x80\x81\x82\x83")
            audit = DeepAudit(roots=[tmpdir])
            result = audit.find_invalid_encoding()
            assert len(result) == 1

    def test_find_duplicate_topics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two files with same topic
            header = "⟦ same_topic | TYPE-v1 | vsm-1.2.1 | 2026-01-01T00:00:00Z ⟧\n\nContent"
            with open(os.path.join(tmpdir, "file1.vsm"), "w") as f:
                f.write(header)
            with open(os.path.join(tmpdir, "file2.vsm"), "w") as f:
                f.write(header)
            audit = DeepAudit(roots=[tmpdir])
            result = audit.find_duplicate_topics()
            assert len(result) == 1
            assert result[0]["topic"] == "same_topic"
