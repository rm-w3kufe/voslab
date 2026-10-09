"""Tests for analytic_engine core."""

import pytest
from pathlib import Path

from analytic_engine import analyze, detect_input, extract_text, available_levels
from analytic_engine.detector import is_analyzable
from analytic_engine.extractor import extract_sections


class TestDetector:
    """Test input type detection."""
    
    def test_detect_pdf_by_extension(self):
        assert detect_input("doc.pdf") == "pdf"
    
    def test_detect_vsm_by_extension(self):
        assert detect_input("doc.vsm") == "vsm"
    
    def test_detect_text_by_extension(self):
        assert detect_input("doc.txt") == "text"
        assert detect_input("doc.tex") == "text"
    
    def test_detect_markdown_by_extension(self):
        assert detect_input("README.md") == "markdown"
    
    def test_detect_by_content_pdf(self):
        assert detect_input("unknown", b"%PDF-1.4 ...") == "pdf"
    
    def test_detect_by_content_vsm(self):
        assert detect_input("unknown", b"@vsm 1.2.1") == "vsm"
    
    def test_unknown_type(self):
        assert detect_input("file.xyz") == "unknown"
    
    def test_is_analyzable(self):
        assert is_analyzable("pdf") == True
        assert is_analyzable("text") == True
        assert is_analyzable("unknown") == False


class TestExtractor:
    """Test text extraction."""
    
    def test_extract_from_text(self):
        text, itype = extract_text(text="Hello world")
        assert text == "Hello world"
        assert itype == "text"
    
    def test_extract_sections(self):
        text = """# Section 1
Content 1

# Section 2
Content 2
"""
        sections = extract_sections(text)
        assert "Section 1" in sections
        assert "Section 2" in sections
    
    def test_extract_sections_no_headers(self):
        text = "Just some text without headers"
        sections = extract_sections(text)
        assert "body" in sections


class TestLevels:
    """Test level registry."""
    
    def test_available_levels(self):
        levels = available_levels()
        assert "L1" in levels
    
    def test_get_level_l1(self):
        from analytic_engine.levels import get_level
        fn = get_level("L1")
        assert callable(fn)
    
    def test_get_unknown_level(self):
        from analytic_engine.levels import get_level
        with pytest.raises(KeyError):
            get_level("L99")


class TestOrchestrator:
    """Test main analyze() function."""
    
    def test_analyze_text(self):
        result = analyze(
            text="Arrow [1951] provided a rigorous proof.",
            name="test_doc",
            route=False,  # Skip routing for speed
        )
        assert "claims" in result
        assert "coverage" in result
        assert result["level"] == "L1"
        assert result["input_type"] == "text"
    
    def test_analyze_with_invalid_level(self):
        with pytest.raises(KeyError):
            analyze(text="test", level="L99")
    
    def test_analyze_no_input(self):
        with pytest.raises(ValueError):
            analyze()


class TestFierroIntegration:
    """Integration test with real Fierro PDF."""
    
    @pytest.fixture
    def fierro_pdf(self):
        """Path to Fierro review PDF."""
        return Path.home() / "vOSlab/docs/correspondence/fierro/Rev_Prof_Raul_Fierro.pdf"
    
    @pytest.mark.skipif(
        not (Path.home() / "vOSlab/docs/correspondence/fierro/Rev_Prof_Raul_Fierro.pdf").exists(),
        reason="Fierro PDF not found"
    )
    def test_fierro_pdf_analysis(self, fierro_pdf):
        """Analyze Fierro review PDF."""
        result = analyze(
            fierro_pdf,
            name="Rev_Prof_Raul_Fierro",
            route=True,
        )
        
        assert result["input_type"] == "pdf"
        assert result["level"] == "L1"
        assert len(result["claims"]) > 0
        assert "coverage" in result
        print(f"\nExtracted {len(result['claims'])} claims from Fierro review")
        for claim in result["claims"][:3]:
            print(f"  - {claim['id']}: {claim['text'][:60]}...")
