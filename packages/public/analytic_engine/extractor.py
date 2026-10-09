"""extractor.py — Text extraction from various input types.

Domain-agnostic: handles PDF, text, VSM, markdown.
Returns plain text ready for claim extraction.
"""

from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Optional

from .detector import detect_input, InputType


def extract_text(
    source: str | Path | None = None,
    *,
    text: str | None = None,
    content: bytes | None = None,
) -> tuple[str, InputType]:
    """Extract text from source.
    
    Args:
        source: File path (extract from file)
        text: Raw text (if already extracted)
        content: Raw bytes (for content-based extraction)
        
    Returns:
        (extracted_text, input_type)
        
    Raises:
        ValueError: If source is not analyzable
        FileNotFoundError: If source file doesn't exist
    """
    # Case 1: Raw text provided
    if text is not None:
        return text, "text"
    
    # Case 2: File path
    if source is not None:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Source not found: {path}")
        
        itype = detect_input(path)
        
        if itype == "pdf":
            return _extract_pdf(path), "pdf"
        elif itype in ("text", "vsm", "markdown", "code", "json"):
            return path.read_text(encoding="utf-8", errors="replace"), itype
        else:
            raise ValueError(f"Unsupported input type: {itype}")
    
    # Case 3: Raw bytes
    if content is not None:
        itype = detect_input("unknown", content=content)
        if itype == "pdf":
            # Would need temp file for pdftotext
            raise ValueError("PDF content extraction requires file path")
        try:
            return content.decode("utf-8", errors="replace"), itype
        except Exception as e:
            raise ValueError(f"Failed to decode content: {e}")
    
    raise ValueError("Must provide source, text, or content")


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF using pdftotext.
    
    Args:
        path: Path to PDF file
        
    Returns:
        Extracted text
        
    Raises:
        RuntimeError: If pdftotext fails
    """
    try:
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout
    except FileNotFoundError:
        raise RuntimeError("pdftotext not found. Install: apt install poppler-utils")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"pdftotext failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"pdftotext timeout on {path}")


def extract_sections(text: str) -> dict[str, str]:
    """Split text into sections (for structured documents).
    
    Heuristic: looks for headers (markdown #, section numbers, etc.)
    
    Returns:
        Dict of {section_name: section_text}
    """
    sections = {}
    current_name = "body"
    current_lines = []
    
    for line in text.split("\n"):
        # Detect section headers
        if _is_header(line):
            if current_lines:
                sections[current_name] = "\n".join(current_lines)
            current_name = line.strip().lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    
    # Don't forget last section
    if current_lines:
        sections[current_name] = "\n".join(current_lines)
    
    return sections if sections else {"body": text}


def _is_header(line: str) -> bool:
    """Check if line is a section header."""
    stripped = line.strip()
    # Markdown headers
    if stripped.startswith("#"):
        return True
    # Section numbers (e.g., "1.", "2.3", "Section 4")
    if stripped and stripped[0].isdigit():
        if "." in stripped[:4] or stripped.startswith("Section"):
            return True
    return False
