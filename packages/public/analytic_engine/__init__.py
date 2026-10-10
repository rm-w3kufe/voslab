"""analytic_engine — domain-agnostic analytic pipeline.

Automated claim extraction, routing, and analysis for any document type.
Triggered by hooks (on-read, on-write, explicit request) or self-reflection.

Levels (scalable):
  L1: claim extraction + routing (claim_ingest)
  L2: theorem parsing (hypothesis → conclusion)
  L3: symbolic verification (SymPy/Z3)
  L4: theory-experiment correlation
  L5: cross-source reasoning

Architecture:
  detector → extractor → levels → analyzers → ledger/trace

Usage:
  from analytic_engine import analyze
  result = analyze("/path/to/doc.pdf")
  result = analyze(text, name="my_doc", level="L1")
"""

from .detector import detect_input
from .extractor import extract_text
from .levels import get_level, available_levels
from .orchestrator import analyze
from .depth import estimate as estimate_depth
from .depth import persist_depth

__version__ = "0.1.0"
__all__ = [
    "analyze",
    "detect_input",
    "extract_text",
    "get_level",
    "available_levels",
    "estimate_depth",
    "persist_depth",
]
