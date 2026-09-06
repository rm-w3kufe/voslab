"""vsf-tools — Shared utilities for vOSlab.

Two pieces:
  - http_mixin: silent HTTP handler/server base classes (stdlib only)
  - gen_index: deterministic MEMORY.md generator with injected storage

design: child/docs/voslab_packaging_proposal.vsm §catalog ("vsf-tools")
"""

from vsf_tools.http_mixin import SilentHTTPHandler, SilentHTTPServer, create_silent_server
from vsf_tools.gen_index import MemoryIndexGenerator

__all__ = [
    "SilentHTTPHandler",
    "SilentHTTPServer",
    "create_silent_server",
    "MemoryIndexGenerator",
]
