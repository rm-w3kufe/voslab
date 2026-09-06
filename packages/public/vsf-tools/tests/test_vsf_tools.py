"""tests/test_vsf_tools.py — Tests for vsf-tools utilities."""

import tempfile
import os
from pathlib import Path

import pytest
from vsf_tools import (
    SilentHTTPHandler,
    SilentHTTPServer,
    create_silent_server,
    MemoryIndexGenerator,
)


class TestSilentHTTPHandler:
    """Tests for SilentHTTPHandler."""

    def test_import(self):
        """SilentHTTPHandler can be imported."""
        assert SilentHTTPHandler is not None

    def test_is_subclass(self):
        """SilentHTTPHandler is a subclass of BaseHTTPRequestHandler."""
        import http.server
        assert issubclass(SilentHTTPHandler, http.server.BaseHTTPRequestHandler)

    def test_log_message_suppressed(self):
        """SilentHTTPHandler suppresses log messages."""
        # Create a mock handler
        handler = SilentHTTPHandler.__new__(SilentHTTPHandler)
        # Should not raise
        handler.log_message("test %s", "message")


class TestSilentHTTPServer:
    """Tests for SilentHTTPServer."""

    def test_import(self):
        """SilentHTTPServer can be imported."""
        assert SilentHTTPServer is not None

    def test_is_subclass(self):
        """SilentHTTPServer is a subclass of HTTPServer."""
        import http.server
        assert issubclass(SilentHTTPServer, http.server.HTTPServer)


class TestCreateSilentServer:
    """Tests for create_silent_server."""

    def test_import(self):
        """create_silent_server can be imported."""
        assert create_silent_server is not None

    def test_callable(self):
        """create_silent_server is callable."""
        assert callable(create_silent_server)


class TestMemoryIndexGenerator:
    """Tests for MemoryIndexGenerator."""

    def test_import(self):
        """MemoryIndexGenerator can be imported."""
        assert MemoryIndexGenerator is not None

    def test_init(self):
        """MemoryIndexGenerator can be initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = MemoryIndexGenerator(tmpdir)
            assert gen.memory_dir == tmpdir
            assert gen.memory_file == os.path.join(tmpdir, "MEMORY.md")

    def test_parse_frontmatter(self):
        """MemoryIndexGenerator parses frontmatter correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file with frontmatter
            test_file = os.path.join(tmpdir, "test.md")
            with open(test_file, "w") as f:
                f.write("---\nname: Test\ndescription: A test file\nmetadata:\n  type: project\n---\nContent here")

            gen = MemoryIndexGenerator(tmpdir)
            result = gen.parse_frontmatter(test_file)
            assert result["name"] == "Test"
            assert result["description"] == "A test file"
            assert result["type"] == "project"

    def test_parse_frontmatter_missing(self):
        """MemoryIndexGenerator handles missing frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file without frontmatter
            test_file = os.path.join(tmpdir, "test.md")
            with open(test_file, "w") as f:
                f.write("Content without frontmatter")

            gen = MemoryIndexGenerator(tmpdir)
            result = gen.parse_frontmatter(test_file)
            assert result["name"] == "test"
            assert result["description"] == ""
            assert result["type"] == "reference"

    def test_scan(self):
        """MemoryIndexGenerator scans directory correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            with open(os.path.join(tmpdir, "file1.md"), "w") as f:
                f.write("---\nname: File1\n---\n")
            with open(os.path.join(tmpdir, "file2.md"), "w") as f:
                f.write("---\nname: File2\n---\n")
            # Create MEMORY.md (should be excluded)
            with open(os.path.join(tmpdir, "MEMORY.md"), "w") as f:
                f.write("# Memory Index")

            gen = MemoryIndexGenerator(tmpdir)
            entries = gen.scan()
            assert len(entries) == 2
            names = {e["name"] for e in entries}
            assert "File1" in names
            assert "File2" in names

    def test_generate(self):
        """MemoryIndexGenerator generates correct output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = MemoryIndexGenerator(tmpdir)
            entries = [
                {"name": "Test", "description": "A test", "type": "project", "file": "test.md", "_frontmatter_missing": False},
            ]
            output = gen.generate(entries)
            assert "# Memory Index" in output
            assert "Test" in output
            assert "project" in output

    def test_write(self):
        """MemoryIndexGenerator writes MEMORY.md correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("---\nname: Test\n---\n")

            gen = MemoryIndexGenerator(tmpdir)
            gen.write()
            assert os.path.exists(gen.memory_file)
            with open(gen.memory_file) as f:
                content = f.read()
            assert "# Memory Index" in content
            assert "Test" in content

    def test_check_drift(self):
        """MemoryIndexGenerator detects drift correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("---\nname: Test\n---\n")

            gen = MemoryIndexGenerator(tmpdir)
            # No MEMORY.md yet → drift
            assert gen.check_drift() == 1
            # Write MEMORY.md → no drift
            gen.write()
            assert gen.check_drift() == 0
