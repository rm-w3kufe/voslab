"""orchestrator.py — Main entry point for analysis.

Orchestrates: detect → extract → levels → analyze → ledger

Usage:
    from analytic_engine import analyze
    
    # From file
    result = analyze("/path/to/doc.pdf")
    
    # From text
    result = analyze(text="Some text", name="my_doc")
    
    # With specific level
    result = analyze("/path/to/doc.pdf", level="L1")
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

from .detector import detect_input, is_analyzable
from .extractor import extract_text, extract_sections
from .levels import get_level, available_levels


def analyze(
    source: str | Path | None = None,
    *,
    text: str | None = None,
    name: Optional[str] = None,
    subject: Optional[str] = None,
    level: str = "L1",
    sections: bool = False,
    risk: str = "exploratory",
    register: bool = False,
    route: bool = True,
    persist: bool = False,
    ledger_path: Optional[str | Path] = None,
    **kwargs,
) -> dict[str, Any]:
    """Run analysis pipeline on input.
    
    Args:
        source: File path to analyze
        text: Raw text (alternative to source)
        name: Source name (defaults to filename or "unnamed")
        subject: Subject for claims (e.g., file path)
        level: Analysis level ("L1", "L2", etc.)
        sections: Extract sections separately
        risk: Risk level for claims
        register: Register claims in EpicStore
        route: Route claims through claim-gate
        persist: Write the claim ledger sidecar (read -> explicit ledger;
            central state/epistemic/sidecars/<stem>.claims.vsm, idempotent)
        ledger_path: Explicit sidecar path (overrides persist's default)
        **kwargs: Additional context for level
        
    Returns:
        {
            "source_id": str,
            "input_type": str,
            "level": str,
            "claims": [...],
            "routes": [...],
            "coverage": {...},
            "internal": {...},
            "ledger": str,
            "ledger_path": str | None,
            "ledger_status": "written" | "unchanged" | None,
            ... (level-specific fields)
        }
        
    Raises:
        ValueError: If input not analyzable
        FileNotFoundError: If source not found
        KeyError: If level not available
    """
    # Validate level
    if level not in available_levels():
        raise KeyError(
            f"Level not available: {level}. "
            f"Available: {available_levels()}"
        )
    
    # Extract text
    if text is not None:
        extracted_text, input_type = text, "text"
        if name is None:
            name = "inline_text"
    elif source is not None:
        extracted_text, input_type = extract_text(source)
        if name is None:
            name = Path(str(source)).stem
    else:
        raise ValueError("Must provide source or text")
    
    # Check analyzable
    if not is_analyzable(input_type):
        raise ValueError(f"Input type not analyzable: {input_type}")
    
    # Build context
    context = {
        "name": name,
        "subject": subject or str(source) if source else name,
        "risk": risk,
        "register": register,
        "route": route,
        "persist": persist,
        "ledger_path": ledger_path,
        **kwargs,
    }
    
    # Run level
    level_fn = get_level(level)
    
    if sections:
        # Analyze each section separately
        section_dict = extract_sections(extracted_text)
        results = {}
        for sec_name, sec_text in section_dict.items():
            sec_context = {**context, "name": f"{name}/{sec_name}"}
            results[sec_name] = level_fn(sec_text, sec_context)
        
        # Merge results
        return {
            "source_id": results[list(results.keys())[0]].get("source_id", ""),
            "input_type": input_type,
            "level": level,
            "sections": results,
            "total_claims": sum(
                len(r.get("claims", [])) for r in results.values()
            ),
        }
    else:
        # Analyze whole document
        result = level_fn(extracted_text, context)
        
        return {
            "input_type": input_type,
            "level": level,
            **result,
        }


def analyze_batch(
    sources: list[str | Path],
    *,
    level: str = "L1",
    **kwargs,
) -> list[dict[str, Any]]:
    """Analyze multiple sources.
    
    Args:
        sources: List of file paths
        level: Analysis level
        **kwargs: Additional arguments passed to analyze()
        
    Returns:
        List of analysis results
    """
    results = []
    for source in sources:
        try:
            result = analyze(source, level=level, **kwargs)
            results.append(result)
        except Exception as e:
            results.append({
                "source": str(source),
                "error": str(e),
                "level": level,
            })
    return results
