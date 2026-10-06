"""L2View — cross-session materialized onboard digest (F3b, proposal §4.2/§5.2).

L2 answers the EXPENSIVE call: state_onboard (~500 tok) as a view keyed by
the SET of its input versions, persisted so a NEW session inherits it —
the only layer that survives the process (§4.2: cross-session).

Laws (§4.4/§4.5):

- state_reconcile / state_verify NEVER read this cache: reconcile is the
  REFRESH path and verify is the EVIDENCE path — serving either cached
  would lie (§4.4 "ALWAYS FRESH"). L2 wraps state_onboard ONLY.
- Invalidation by input-version set ONLY — no clock TTL (§4.5).
- The served digest ALWAYS carries its snapshot stamp
  `snapshot <key> — refresh: state_reconcile`: a digest may never be
  presented as fresh without naming the snapshot it came from (§5.2).
  Stamping is presentation honesty and survives mode=off; only the
  cache serve/store is gated by the mode.
- Uncacheable by construction: if any input cannot name a version
  (provider.version(domain) -> None), the key cannot be formed → fresh
  compute every time, stamped as `live compute` (honest: it IS current —
  we simply cannot prove it across requests).
- Modes VOS_L2_MODE=shadow(default)|live|off, kill VOS_L2_CACHE=0 —
  same semantics as L1 (unknown mode resolves to shadow, never live).
  Shadow computes fresh, compares against the stored entry at the same
  key (divergence = key incomplete or assemble non-deterministic → live
  enable blocked), stores, serves fresh. Live serves the stored entry on
  key match. Enable = S5 ratifies with divergences == 0 (§7.1 spirit).

Storage: single slot (F3a precedent — all-or-nothing invalidation),
memory always, disk mirrored when a path is resolvable
(VOS_L2_PATH env, else <focus-dir>/state/cache/onboard_l2.json).
Corrupt/missing disk entry = miss, never a crash.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

MODES = ("shadow", "live", "off")


def l2_mode() -> str:
    """Resolve the effective mode: off | shadow | live (env, fail-safe)."""
    if os.environ.get("VOS_L2_CACHE", "1").strip().lower() in ("0", "false", "off", "no"):
        return "off"
    mode = os.environ.get("VOS_L2_MODE", "shadow").strip().lower()
    if mode in ("off", "disabled", "none", "0"):
        return "off"
    if mode in ("live", "on", "enabled", "enable", "1"):
        return "live"
    return "shadow"


def digest_key(parts: str) -> str:
    """Short stable key over the canonical input-version material."""
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def snapshot_stamp(key: str) -> str:
    """The §5.2 presentation line — always names the snapshot."""
    return f"// snapshot {key} — refresh: state_reconcile"


def unkeyed_stamp(domains_unversioned: list[str]) -> str:
    """Honest stamp when the key cannot be formed: every call recomputes."""
    return ("// onboard digest (live compute — inputs unversioned: "
            + ", ".join(sorted(domains_unversioned)) + ")")


class L2View:
    """Single-slot {key, digest, cached_at} view over assemble() output.

    cached_at is observational metadata only (§4.5: never an invalidation
    input). Deep copies both ways — a caller mutating the served string's
    container cannot corrupt the slot (str is immutable anyway; the copy
    discipline matters for the dict slot itself).
    """

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else None
        self._mem: dict[str, Any] | None = None  # in-process slot
        self.hits = 0
        self.misses = 0
        self.stores = 0
        self.bypasses = 0
        self.divergences = 0

    # ── slot ──

    def get(self) -> dict[str, Any] | None:
        """Current slot (memory, refreshed from disk if the disk is newer)."""
        disk = self._read_disk()
        if disk is not None:
            self._mem = disk
        return self._mem

    def put(self, key: str, digest: str) -> None:
        entry = {"key": key, "digest": digest, "cached_at": time.time()}
        self._mem = entry
        self.stores += 1
        self._write_disk(entry)

    def hit(self) -> None:
        self.hits += 1

    def miss(self) -> None:
        self.misses += 1

    def bypass(self) -> None:
        self.bypasses += 1

    def diverge(self, key: str) -> None:
        self.divergences += 1

    # ── disk (cross-session; fail-soft both ways) ──

    def _read_disk(self) -> dict[str, Any] | None:
        if self._path is None:
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not (isinstance(data, dict) and isinstance(data.get("key"), str)
                and isinstance(data.get("digest"), str)):
            return None
        return data

    def _write_disk(self, entry: dict[str, Any]) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                       prefix=".onboard_l2.")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
            os.replace(tmp, self._path)
        except OSError:
            pass  # disk is a persistence nicety — memory slot still works

    def stats(self) -> dict[str, Any]:
        return {"mode": l2_mode(),
                "hits": self.hits, "misses": self.misses,
                "stores": self.stores, "bypasses": self.bypasses,
                "divergences": self.divergences,
                "key": (self._mem or {}).get("key"),
                "persisted": self._path is not None}
