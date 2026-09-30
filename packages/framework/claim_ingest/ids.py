"""Deterministic source/claim identifiers (R10).

Same artifact bytes -> same source_id; extraction order -> same claim ids.
No clock, no randomness, no environment reads.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


def fingerprint(data: bytes | str) -> str:
    """SHA-256 of artifact content (str encoded utf-8)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", Path(name).stem).strip("-").upper()
    return s[:40] or "SRC"


def source_id_for(name: str, data: bytes | str) -> str:
    """SRC-<slug>-<fp8>: stable across runs for identical content."""
    return f"SRC-{_slug(name)}-{fingerprint(data)[:8]}"


def claim_id_for(source_id: str, seq: int) -> str:
    """Sequential id inside one source: <source_id>-C001, C002, ..."""
    return f"{source_id}-C{seq:03d}"
