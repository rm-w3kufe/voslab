"""Cache: materialization of the projection by content fingerprint.

Decision S5-A (proposal ARCH): if any input byte changes -> full rebuild
(never partial); the cache is a disposable artifact — NO-NEW-TRUTH: every
truth stays in its canonical sidecar/ledger (R5), delete the cache and
rebuild is byte-identical to the original build.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def cache_load(path: Path, fingerprint: str) -> dict | None:
    """Cached graph iff fingerprint matches; any error -> None (rebuild)."""
    try:
        obj = json.loads(Path(path).read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("fingerprint") != fingerprint:
        return None
    graph = obj.get("graph")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return None
    return graph


def cache_store(path: Path, graph: dict) -> None:
    """Atomic materialization (tmp + rename); failure never breaks build."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(
            {"fingerprint": graph["meta"]["fingerprint"], "graph": graph},
            ensure_ascii=False, sort_keys=True))
        os.replace(tmp, p)
    except OSError:
        pass
