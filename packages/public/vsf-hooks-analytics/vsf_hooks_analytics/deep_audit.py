"""deep_audit.py — Deep audit of VSM corpus.

Ported from child/scripts/deep_audit.py
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class DeepAudit:
    """Deep audit of VSM corpus for consistency and completeness."""

    def __init__(self, roots: List[str] | None = None):
        if roots is None:
            roots = [
                os.path.expanduser("~/vsf/child/docs"),
                os.path.expanduser("~/vsf/docs"),
                os.path.expanduser("~/vOSlab/docs"),
            ]
        self.roots = [Path(r) for r in roots if Path(r).exists()]

    def audit_all(self) -> Dict[str, Any]:
        """Run full audit and return results."""
        results = {
            "phantom_refs": self.find_phantom_refs(),
            "broken_links": self.find_broken_links(),
            "missing_headers": self.find_missing_headers(),
            "duplicate_topics": self.find_duplicate_topics(),
            "invalid_encoding": self.find_invalid_encoding(),
            "summary": {},
        }
        results["summary"] = {
            "phantom_refs": len(results["phantom_refs"]),
            "broken_links": len(results["broken_links"]),
            "missing_headers": len(results["missing_headers"]),
            "duplicate_topics": len(results["duplicate_topics"]),
            "invalid_encoding": len(results["invalid_encoding"]),
        }
        return results

    def find_phantom_refs(self) -> List[Dict[str, Any]]:
        """Find references to files that don't exist."""
        phantom = []
        for root in self.roots:
            for vsm_file in root.rglob("*.vsm"):
                try:
                    content = vsm_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                # Find file references
                refs = re.findall(r'["\']([^"\']+\.(?:vsm|py|sh))["\']', content)
                for ref in refs:
                    if ref.startswith("/") or ref.startswith("~/"):
                        ref_path = Path(ref).expanduser()
                    else:
                        ref_path = vsm_file.parent / ref
                    if not ref_path.exists():
                        phantom.append({
                            "file": str(vsm_file),
                            "reference": ref,
                            "expected_path": str(ref_path),
                        })
        return phantom

    def find_broken_links(self) -> List[Dict[str, Any]]:
        """Find broken internal links."""
        broken = []
        for root in self.roots:
            for vsm_file in root.rglob("*.vsm"):
                try:
                    content = vsm_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                # Find ⟦ /name ⟧ references
                refs = re.findall(r'⟦\s*/([^\s|]+)', content)
                for ref in refs:
                    # Check if referenced file exists
                    ref_file = root / f"{ref}.vsm"
                    if not ref_file.exists():
                        # Also check in subdirectories
                        found = False
                        for candidate in root.rglob(f"{ref}.vsm"):
                            found = True
                            break
                        if not found:
                            broken.append({
                                "file": str(vsm_file),
                                "reference": ref,
                            })
        return broken

    def find_missing_headers(self) -> List[Dict[str, Any]]:
        """Find VSM files missing proper headers."""
        missing = []
        for root in self.roots:
            for vsm_file in root.rglob("*.vsm"):
                try:
                    content = vsm_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                lines = content.split("\n")
                if not lines:
                    missing.append({"file": str(vsm_file), "reason": "empty file"})
                    continue
                first_line = lines[0].strip()
                if not first_line.startswith("⟦"):
                    missing.append({"file": str(vsm_file), "reason": "missing header"})
        return missing

    def find_duplicate_topics(self) -> List[Dict[str, Any]]:
        """Find documents with duplicate topics."""
        topics: Dict[str, List[str]] = {}
        for root in self.roots:
            for vsm_file in root.rglob("*.vsm"):
                try:
                    content = vsm_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                m = re.search(r"⟦\s*([^|\s]+)", content)
                if m:
                    topic = m.group(1).lower()
                    if topic not in topics:
                        topics[topic] = []
                    topics[topic].append(str(vsm_file))
        # Return topics with multiple files
        return [
            {"topic": topic, "files": files}
            for topic, files in topics.items()
            if len(files) > 1
        ]

    def find_invalid_encoding(self) -> List[Dict[str, Any]]:
        """Find files with encoding issues."""
        invalid = []
        for root in self.roots:
            for vsm_file in root.rglob("*.vsm"):
                try:
                    vsm_file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    invalid.append({"file": str(vsm_file), "reason": "invalid UTF-8"})
        return invalid
