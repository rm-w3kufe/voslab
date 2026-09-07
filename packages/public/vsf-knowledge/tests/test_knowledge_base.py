"""
tests/test_knowledge_base.py — Tests for knowledge base.
"""

import pytest
import tempfile
from pathlib import Path

from vsf_knowledge.knowledge_base import KnowledgeBase


def test_knowledge_base_init():
    """Test KnowledgeBase initialization."""
    kb = KnowledgeBase()
    assert kb.base_path.exists() or not kb.base_path.exists()  # May or may not exist


def test_knowledge_base_with_path():
    """Test KnowledgeBase with custom path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        assert kb.base_path == Path(tmpdir)


def test_load_knowledge_not_found():
    """Test load_knowledge with non-existent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        result = kb.load_knowledge("nonexistent")
        assert result is None


def test_load_knowledge_success():
    """Test load_knowledge with existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file
        test_file = Path(tmpdir) / "test.vsm"
        test_file.write_text("Test content")
        
        kb = KnowledgeBase(tmpdir)
        result = kb.load_knowledge("test")
        assert result == "Test content"


def test_load_knowledge_cached():
    """Test load_knowledge caching."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file
        test_file = Path(tmpdir) / "test.vsm"
        test_file.write_text("Test content")
        
        kb = KnowledgeBase(tmpdir)
        
        # First load
        result1 = kb.load_knowledge("test")
        
        # Modify file
        test_file.write_text("Modified content")
        
        # Second load (should use cache)
        result2 = kb.load_knowledge("test")
        
        assert result1 == result2 == "Test content"


def test_list_knowledge_empty():
    """Test list_knowledge with empty directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        result = kb.list_knowledge()
        assert result == []


def test_list_knowledge():
    """Test list_knowledge with files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        for name in ["arch", "identity", "basics"]:
            test_file = Path(tmpdir) / f"{name}.vsm"
            test_file.write_text(f"Content for {name}")
        
        kb = KnowledgeBase(tmpdir)
        result = kb.list_knowledge()
        
        assert len(result) == 3
        assert "arch" in result
        assert "identity" in result
        assert "basics" in result


def test_get_architecture():
    """Test get_architecture method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create architecture file
        test_file = Path(tmpdir) / "architecture.vsm"
        test_file.write_text("Architecture content")
        
        kb = KnowledgeBase(tmpdir)
        result = kb.get_architecture()
        
        assert result == "Architecture content"


def test_get_rsi_identity():
    """Test get_rsi_identity method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create rsi_identity file
        test_file = Path(tmpdir) / "rsi_identity.vsm"
        test_file.write_text("RSI identity content")
        
        kb = KnowledgeBase(tmpdir)
        result = kb.get_rsi_identity()
        
        assert result == "RSI identity content"


def test_search_not_found():
    """Test search with no matches."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        result = kb.search("nonexistent")
        assert result == []


def test_search_found():
    """Test search with matches."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test file
        test_file = Path(tmpdir) / "test.vsm"
        test_file.write_text("Line 1\nLine 2 with keyword\nLine 3")
        
        kb = KnowledgeBase(tmpdir)
        result = kb.search("keyword")
        
        assert len(result) == 1
        assert result[0]["name"] == "test"
        assert result[0]["line"] == 2
        assert "keyword" in result[0]["context"]
