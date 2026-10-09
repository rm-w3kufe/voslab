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


class TestPersist:
    """read -> explicit ledger sidecar (claim_ingest proposal line 9).

    The read-hook contract: every analysis PERSISTS its ledger, and
    re-reading the same artifact NEVER rewrites it (tree-clean invariant —
    gate 5 measures uncommitted work, a timestamp-only rewrite would keep
    the repo dirty forever).
    """

    _TEXT = (
        "The panel reports 24/24 checks passed. "
        "Convergence reaches n = 10 after the update."
    )

    @pytest.fixture()
    def isolated(self, tmp_path, monkeypatch):
        """Redirect ledger root + sidecar store to tmp (write_ledger guards
        on ledger.repo_root; find_sidecar resolves via epistemic.repo_root)."""
        sidecars = tmp_path / "state" / "epistemic" / "sidecars"
        sidecars.mkdir(parents=True)
        import claim_ingest.ledger.ledger as L
        import vos_kernel.epistemic as E
        monkeypatch.setattr(L, "repo_root", lambda: tmp_path)
        monkeypatch.setattr(E, "repo_root", lambda: tmp_path)
        return tmp_path

    def test_persist_writes_sidecar(self, isolated):
        result = analyze(
            text=self._TEXT,
            name="docs/papers/demo_artifact.pdf",
            route=False,
            persist=True,
        )
        lp = Path(result["ledger_path"])
        # raw-stem name, case preserved — find_sidecar()'s central candidate
        assert lp == (isolated / "state" / "epistemic" / "sidecars"
                      / "demo_artifact.claims.vsm")
        assert lp.exists()
        assert result["ledger_status"] == "written"
        # sidecar is loadable CLAIMS-v1 with the extracted claims
        from vos_kernel.epistemic import load_sidecar
        loaded = load_sidecar(lp)
        assert {c["id"] for c in loaded} == \
            {c["id"] for c in result["claims"]}
        assert "coverage = " in lp.read_text()

    def test_persist_idempotent_reread(self, isolated):
        first = analyze(
            text=self._TEXT, name="demo_artifact.pdf",
            route=False, persist=True,
        )
        assert first["ledger_status"] == "written"
        lp = Path(first["ledger_path"])
        bytes_1 = lp.read_bytes()
        # same artifact re-read: body identical -> NO rewrite (no new
        # timestamp, tree stays clean)
        second = analyze(
            text=self._TEXT, name="demo_artifact.pdf",
            route=False, persist=True,
        )
        assert second["ledger_status"] == "unchanged"
        assert lp.read_bytes() == bytes_1

    def test_persist_false_writes_nothing(self, isolated):
        result = analyze(
            text=self._TEXT, name="demo_artifact.pdf",
            route=False, persist=False,
        )
        assert result["ledger_path"] is None
        assert result["ledger_status"] is None
        assert not (isolated / "state" / "epistemic" / "sidecars"
                    / "demo_artifact.claims.vsm").exists()

    def test_explicit_ledger_path_overrides_persist(self, isolated):
        custom = isolated / "out" / "custom.claims.vsm"
        result = analyze(
            text=self._TEXT, name="demo_artifact.pdf",
            route=False, persist=True, ledger_path=custom,
        )
        assert Path(result["ledger_path"]) == custom
        assert custom.exists()
