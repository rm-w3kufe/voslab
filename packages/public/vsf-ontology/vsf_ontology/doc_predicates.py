"""doc_predicates.py — Document analysis predicates.

Ported from child/scripts/vsl/classifier/vsf_hooks_predicates.py
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════
# INTERNALS
# ═══════════════════════════════════════════════════════════════════════

def _find_docs(pattern: str = None, ext: str = ".vsm", roots: List[str] | None = None) -> List[str]:
    """Search for documents in given root directories."""
    if roots is None:
        roots = [
            os.path.expanduser("~/vsf/child/docs"),
            os.path.expanduser("~/vsf/docs/spec_revision/system"),
            os.path.expanduser("~/vsf/docs"),
            os.path.expanduser("~/vOSlab/docs"),
        ]
    results = []
    for d in roots:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith(ext):
                    if pattern is None or pattern.lower() in f.lower():
                        results.append(os.path.join(root, f))
    return results


def _doc_header_name(path: str) -> Optional[str]:
    """Extract header name from a VSM file."""
    try:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline().strip()
        m = re.search(r"⟦\s*([^|\s]+)", first)
        return m.group(1) if m else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# DOCUMENT PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def doc_extract_topic(content: str) -> str:
    """Extract topic identifier from document content (header name / first line)."""
    if not content:
        return ""
    m = re.search(r"⟦\s*([^|\s]+)", content)
    if m:
        return m.group(1)
    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("//") and not line.startswith("⟦"):
            return line[:60]
    return ""


def doc_search_existing(topic: str, roots: List[str] | None = None) -> List[str]:
    """Search existing docs for the same topic (header name match)."""
    if not topic:
        return []
    topic_l = topic.lower()
    return [
        p for p in _find_docs(ext=".vsm", roots=roots)
        if _doc_header_name(p) and _doc_header_name(p).lower() == topic_l
    ]


def doc_topic_exact_match(found_docs: List[str]) -> bool:
    """True if an exact topic match was found."""
    return bool(found_docs)


def doc_topic_partial_match(scores: Any, threshold: float = 0.70) -> bool:
    """True if any similarity score >= threshold."""
    if isinstance(scores, (list, tuple)):
        return any(isinstance(s, (int, float)) and s >= threshold for s in scores)
    if isinstance(scores, (int, float)):
        return scores >= threshold
    return False


def doc_has_content(content: str) -> bool:
    """True if document has non-trivial content."""
    if not content:
        return False
    meaningful = [l for l in content.split("\n") if l.strip() and not l.strip().startswith("//")]
    return len(meaningful) > 2


def has_duplicates(found_docs: List[str]) -> bool:
    """True if more than one document matches (duplicate)."""
    return len(found_docs) > 1


def is_source(ctx: Dict[str, Any]) -> bool:
    """True if document is a FUENTE (source of truth, no approval needed)."""
    status = ctx.get("doc_status", ctx.get("status", ""))
    path = ctx.get("new_doc_path", ctx.get("file_path", ""))
    return "fuente" in path.lower() or status == "ratified"


def is_reference(ctx: Dict[str, Any]) -> bool:
    """True if document is a REFERENCIA (consult-only)."""
    status = ctx.get("doc_status", ctx.get("status", ""))
    path = ctx.get("new_doc_path", ctx.get("file_path", ""))
    return "referencia" in path.lower() or status == "reference"


def _overlap(a: str, b: str) -> float:
    """Jaccard similarity between two strings."""
    if not a or not b:
        return 0.0
    sa = set(re.findall(r"\w+", a.lower()))
    sb = set(re.findall(r"\w+", b.lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def high_overlap(a: str, b: str) -> bool:
    """True if Jaccard overlap > 0.7."""
    return _overlap(a, b) > 0.7


def low_overlap(a: str, b: str) -> bool:
    """True if Jaccard overlap < 0.3."""
    return _overlap(a, b) < 0.3


def is_doc_about_doc(content: str) -> bool:
    """True if the document is itself about documents (snowball risk)."""
    if not content:
        return False
    doc_refs = len(re.findall(r"documento|\.vsm|este documento|el doc", content, re.I))
    total_lines = len([l for l in content.split("\n") if l.strip() and not l.startswith("//")])
    if total_lines == 0:
        return False
    return doc_refs >= 3 and (doc_refs / total_lines) > 0.1


def doc_analyze(content: str) -> Dict[str, Any]:
    """Analyze document content and return metadata."""
    return {
        "topic": doc_extract_topic(content),
        "has_content": doc_has_content(content),
        "is_about_doc": is_doc_about_doc(content),
        "size": len(content or ""),
    }


def doc_classify(analysis: Dict[str, Any]) -> str:
    """Classify document based on analysis."""
    if not analysis.get("has_content"):
        return "EMPTY"
    if analysis.get("is_about_doc"):
        return "SNOWBALL"
    if analysis.get("topic"):
        return "CONTENT"
    return "UNKNOWN"


def classification_equals(a: str, b: str) -> bool:
    """True if two classifications are equal."""
    return str(a) == str(b)


def no_match_found(found_count: int) -> bool:
    """True if no match was found."""
    return int(found_count) == 0


# ═══════════════════════════════════════════════════════════════════════
# COMPOSITE / SELF-CONTAINED PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def doc_duplicate_check(content: str, roots: List[str] | None = None) -> bool:
    """Self-contained: extract topic, search, True if any existing doc matches."""
    topic = doc_extract_topic(content)
    found = doc_search_existing(topic, roots=roots)
    return bool(found)


def doc_exact_duplicate(content: str, roots: List[str] | None = None) -> bool:
    """Self-contained: True if MORE THAN ONE existing doc shares the topic."""
    topic = doc_extract_topic(content)
    found = doc_search_existing(topic, roots=roots)
    return len(found) > 1


def doc_snowball_check(content: str) -> bool:
    """Self-contained: True if the document is about documents (snowball risk)."""
    return is_doc_about_doc(content)
