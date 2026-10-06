"""L1Cache — cross-request, version-keyed memo for state_query (F2, refs_optimization_proposal §4.2/§4.4).

Three laws (§4.5 rejections enforced structurally):

1. Invalidation by src_version ONLY — never by wall clock. No TTL: a
   clock cannot know the store changed, a version can. `cached_at` is
   observational metadata only, never an invalidation input.
2. Structural freshness: state_verify / state_reconcile / state_onboard
   call the provider directly and never consult this cache (they bypass
   state_query — §4.2). Only the cheap, frequent, read-only state_query
   path is memoized.
3. Uncacheable by default: a provider that cannot name a content version
   (version() -> None) gets L1 passthrough. Shadow is the default mode:
   it always SERVES fresh and only observes, so shipping this module
   changes no observable behavior until divergences == 0 and S5 ratifies
   the flip to live (§7.1).

Modes (env VOS_L1_MODE; kill switch VOS_L1_CACHE=0 forces off):

  shadow   default — serve fresh ALWAYS; compare against the cached
           entry on version match; count divergences (a divergence
           means versioning is unsound for that domain → live enable
           must not proceed).
  live     serve the cached entry on version match (deep-copied both
           ways so caller mutation can't poison the cache), re-read on
           miss / fresh=true.
  off      passthrough — byte-identical to the pre-L1 server.

A divergence = version said "same" but content differed. That is the
safety net for providers whose version() under-covers their backing
files; it can only ever block enablement, never serve stale data.
"""
from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

MODES = ("shadow", "live", "off")
_EVENT_LOG_MAX = 32


def file_signature(*paths: str | Path) -> str:
    """Stable content-version stamp for a set of backing files.

    mtime_ns + size per file, `absent` when missing (absence is a state
    too — creating or deleting the file must bust the cache). All-or-
    nothing: every path participates, any change changes the stamp.
    """
    parts: list[str] = []
    for p in paths:
        path = Path(p)
        try:
            st = path.stat()
        except OSError:
            parts.append(f"{path.name}:absent")
        else:
            parts.append(f"{path.name}:{st.st_mtime_ns}:{st.st_size}")
    return "|".join(parts)


def l1_mode() -> str:
    """Resolve the effective mode: off | shadow | live.

    Kill switch VOS_L1_CACHE=0 wins over everything. An unknown
    VOS_L1_MODE value resolves to shadow — never to live: the safe
    interpretation of an unrecognized mode is "observe, don't serve".
    """
    if os.environ.get("VOS_L1_CACHE", "1").strip().lower() in ("0", "false", "off", "no"):
        return "off"
    mode = os.environ.get("VOS_L1_MODE", "shadow").strip().lower()
    if mode in ("off", "disabled", "none", "0"):
        return "off"
    if mode in ("live", "on", "enabled", "enable", "1"):
        return "live"
    return "shadow"


def query_key(domain: str, filter: dict | None) -> str:
    """Canonical cache key: domain + canonicalized filter (order-free)."""
    return json.dumps({"d": domain, "f": filter or {}},
                      sort_keys=True, default=str, separators=(",", ":"))


class L1Cache:
    """The session cache: key -> {version, records, cached_at}.

    Entries are deep-copied on put AND on serve, so neither the provider's
    internal record dicts nor a caller's result list can poison what the
    next request reads back. FIFO eviction at max_entries — state slices
    are small; this is a session cache, not a store (§4.4).
    """

    MAX_ENTRIES = 512

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries: dict[str, dict[str, Any]] = {}
        self._max = max_entries
        self.hits = 0
        self.misses = 0
        self.stores = 0
        self.bypasses = 0
        self.divergences = 0
        self._events: list[dict[str, Any]] = []

    def peek(self, key: str) -> dict[str, Any] | None:
        """Raw entry (or None). Version matching is the caller's call —
        shadow mode needs the stale entry around to compare against."""
        return self._entries.get(key)

    def put(self, key: str, version: str, records: list[dict]) -> None:
        if key in self._entries:
            del self._entries[key]  # re-insertion refreshes FIFO position
        while len(self._entries) >= self._max:
            self._entries.pop(next(iter(self._entries)))
        self._entries[key] = {"version": version,
                              "records": deepcopy(records),
                              "cached_at": time.time()}  # observational only
        self.stores += 1

    def hit(self) -> None:
        self.hits += 1

    def miss(self) -> None:
        self.misses += 1

    def bypass(self) -> None:
        self.bypasses += 1

    def diverge(self, key: str, domain: str) -> None:
        """Version matched but content differed — unsound versioning."""
        self.divergences += 1
        self._events.append({"domain": domain, "key": key[:160],
                             "observed_at": time.time()})
        if len(self._events) > _EVENT_LOG_MAX:
            del self._events[:-_EVENT_LOG_MAX]

    @property
    def size(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, Any]:
        """KPI surface (state_l1_stats tool). Mode is read live — the
        dict reflects the env at call time, not construction time."""
        served = self.hits + self.misses
        return {
            "mode": l1_mode(),
            "hits": self.hits,
            "misses": self.misses,
            "stores": self.stores,
            "bypasses": self.bypasses,
            "divergences": self.divergences,
            "entries": len(self._entries),
            "max_entries": self._max,
            "hit_rate": round(self.hits / served, 4) if served else 0.0,
            # last divergences, observational (never an invalidation input)
            "divergence_events": list(self._events),
        }
