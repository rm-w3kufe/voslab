"""detector.py — Input type detection (domain-agnostic).

Detects what kind of input we're dealing with to route to the right
extractor and analyzer.

Input types:
  - pdf: PDF document (extract via pdftotext)
  - text: Plain text (already extracted)
  - vsm: VSM notation document
  - markdown: Markdown document
  - code: Source code (future)
  - json: Structured data (future)
"""

from __future__ import annotations
from pathlib import Path
from typing import Literal

InputType = Literal["pdf", "text", "vsm", "markdown", "code", "json", "unknown"]

# Extensions → type mapping
EXT_MAP = {
    ".pdf": "pdf",
    ".txt": "text",
    ".tex": "text",  # LaTeX source is text
    ".vsm": "vsm",
    ".md": "markdown",
    ".py": "code",
    ".rs": "code",
    ".ts": "code",
    ".js": "code",
    ".json": "json",
}

# Content-based detection (when extension is missing or ambiguous)
CONTENT_MARKERS = {
    "pdf": [b"%PDF-"],
    "vsm": [b"@vsm ", b"\xe2\x9f\xa6"],  # ⟦
    "markdown": [b"# ", b"## ", b"**"],
    "json": [b"{", b"["],
}


def detect_input(source: str | Path, content: bytes | None = None) -> InputType:
    """Detect input type from file extension and/or content.
    
    Args:
        source: File path or name (used for extension detection)
        content: Optional file content bytes (for content-based detection)
        
    Returns:
        Detected input type
    """
    # Extension-based detection
    if isinstance(source, (str, Path)):
        ext = Path(str(source)).suffix.lower()
        if ext in EXT_MAP:
            return EXT_MAP[ext]  # type: ignore
    
    # Content-based detection
    if content:
        for itype, markers in CONTENT_MARKERS.items():
            for marker in markers:
                if content.startswith(marker) or marker in content[:100]:
                    return itype  # type: ignore
    
    # Fallback: check if it looks like text
    if content:
        try:
            content.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            pass
    
    return "unknown"


def is_analyzable(itype: InputType) -> bool:
    """Check if this input type can be analyzed."""
    return itype in ("pdf", "text", "vsm", "markdown")
