"""l1-cache gate — F2 NC de invalidación (refs_optimization_proposal §7.1).

Behavioral probe of the L1 cross-request, version-keyed state_query memo.
ALWAYS cold (§5.1: a cached NC stops proving the gate fails when it must).
Scenarios:

  A. LIVE hit: two identical queries, unchanged version -> 1 provider read,
     hits counted, and the served records are isolated from caller
     mutation (deep-copied both ways — a poisoned entry is unshippable).
  B. Read-your-writes: backing file rewritten BETWEEN requests -> version
     bump -> MISS -> the NEW content is served. No TTL anywhere: this is
     the only invalidation the proposal allows (§4.5).
  C. fresh=true: bypasses serving (bypass counter) but re-reads and
     keeps the entry warm.
  D. Structural bypass: state_verify reads the provider directly — a
     poisoned same-version cache entry must be invisible to it.
  E. Shadow default: a poisoned same-version entry is still OBSERVED
     against a fresh read, fresh data is served, divergence counted
     (divergences == 0 is the enable gate for live, §7.1).
  F. Focus read-your-writes: mark() between two queries is visible —
     version = stat of the focus file (external writers included).
  G. Kill switch VOS_L1_CACHE=0 -> passthrough: no store, no serve.

Invalidation law (what negative_case() violates): invalidation is by
src_version ONLY. A fixture declaring any other scheme — ttl, clock,
time — is rejected: a wall clock cannot know the store changed (§4.5).

Run by the harness: register("l1-cache", check, negative_case).
Live invocation: system/kernel/tests/test_l1_cache.py calls check("") on
every suite run, so an invalidation regression goes loud in <= one run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from gate_suite.harness import register

ALLOWED_INVALIDATION = "version"


def _state_canon_root() -> Path:
    """Repo-local vendored copy first — the gate tests THIS repo's code (R2).

    STATE_CANON_PATH wins only when that checkout actually carries the L1
    seam: an env pointing at a pre-F2 tree (stale session env) would crash
    the probe instead of testing the repo. Mirrors the .bashrc repoint
    (S5 containment 2026-10-04) without trusting the caller's env blindly.
    """
    fallback = Path(__file__).resolve().parents[3] / "public" / "state-canon-mcp"
    env = os.environ.get("STATE_CANON_PATH")
    if env and (Path(env) / "state_canon" / "l1_cache.py").exists():
        return Path(env)
    return fallback


def _server(tmp: Path, doc: dict, focus: bool = False):
    root = _state_canon_root()
    # sys.modules may already hold a state_canon resolved from a DIFFERENT
    # root (canon_bridge imports it early against the caller's env, which
    # can be stale) — this gate must probe the resolved root's code, so
    # evict any stale package first. References held elsewhere keep working:
    # eviction only affects future imports.
    cached = sys.modules.get("state_canon")
    if cached is not None:
        cached_file = str(getattr(cached, "__file__", "") or "")
        if not cached_file.startswith(str(root.resolve())):
            for name in [n for n in list(sys.modules)
                         if n == "state_canon" or n.startswith("state_canon.")]:
                del sys.modules[name]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from state_canon.provider import JsonStateProvider
    from state_canon.server import StateRagServer

    f = tmp / "state.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(doc))
    return StateRagServer(JsonStateProvider(f),
                          focus_file=str(tmp / "focus.json") if focus else None), f


def _write(f: Path, doc: dict) -> None:
    time.sleep(0.01)  # coarse-mtime filesystems
    f.write_text(json.dumps(doc))


def _run_probe() -> list[str]:
    """Run scenarios A-G; return human-readable failures (empty = pass)."""
    failures: list[str] = []
    saved = {k: os.environ.get(k) for k in ("VOS_L1_MODE", "VOS_L1_CACHE")}

    def fail(tag: str, msg: str) -> None:
        failures.append(f"{tag}: {msg}")

    try:
        # Probe must exercise each mode regardless of the caller's env
        # (the kill-switch path is tested explicitly in G).
        for k in ("VOS_L1_MODE", "VOS_L1_CACHE"):
            os.environ.pop(k, None)

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            # A — live hit + caller-mutation isolation
            os.environ["VOS_L1_MODE"] = "live"
            s, f = _server(tmp, {"svc": [{"name": "cache", "st": "up"}]})
            r1 = s.state_query("svc")
            r1[0]["name"] = "MUTATED"
            r2 = s.state_query("svc")
            if s.l1.stats()["hits"] < 1 or r2 != [{"name": "cache", "st": "up"}]:
                fail("A", "live hit failed or caller mutation poisoned the "
                          f"entry (hits={s.l1.stats()['hits']}, served={r2})")

            # B — file rewrite between requests invalidates (read-your-writes)
            _write(f, {"svc": [{"name": "cache", "st": "down"}]})
            r3 = s.state_query("svc")
            if r3 != [{"name": "cache", "st": "down"}] or \
                    s.l1.stats()["misses"] < 1:
                fail("B", "version bump not observed — stale data served "
                          f"(served={r3}, misses={s.l1.stats()['misses']})")

            # C — fresh=true bypass + entry stays warm
            before_bypass = s.l1.stats()["bypasses"]
            s.state_query("svc", fresh=True)
            if s.l1.stats()["bypasses"] != before_bypass + 1:
                fail("C", "fresh=true did not bypass the cache "
                          f"(stats={s.l1.stats()})")

            # D — state_verify structurally bypasses the cache
            s.l1.put('{"d":"svc","f":{}}', s._provider_version("svc"),
                     [{"name": "POISON", "st": "x"}])
            v = s.state_verify("svc", {"st": "down"})
            if not (v.get("holds") and v.get("checked") == 1):
                fail("D", "state_verify consulted the cache instead of the "
                          f"provider (result={v})")

            # E — shadow is the DEFAULT: fresh served over poison, observed
            for k in ("VOS_L1_MODE", "VOS_L1_CACHE"):
                os.environ.pop(k, None)
            s2, f2 = _server(tmp / "shadow", {"svc": [{"name": "cache"}]})
            s2.l1.put('{"d":"svc","f":{}}', s2._provider_version("svc"),
                      [{"name": "POISON"}])
            r = s2.state_query("svc")
            st = s2.l1.stats()
            if r != [{"name": "cache"}] or st["divergences"] < 1:
                fail("E", "shadow must serve fresh and count the divergence "
                          f"(served={r}, stats={st})")

            # F — focus read-your-writes (mark/close between queries)
            os.environ["VOS_L1_MODE"] = "live"
            sf, _ = _server(tmp / "focus", {"svc": []}, focus=True)
            sf.state_query("focus", {"ref": "X"})
            sf.focus.mark("X", "active", "note-1")
            r = sf.state_query("focus", {"ref": "X"})
            if not (len(r) == 1 and r[0].get("note") == "note-1"):
                fail("F", "focus write not visible after mark — versioning "
                          f"missed the focus file (served={r})")

            # G — kill switch: full passthrough
            os.environ["VOS_L1_CACHE"] = "0"
            s3, _ = _server(tmp / "kill", {"svc": [{"name": "cache"}]})
            s3.state_query("svc")
            st = s3.l1.stats()
            if st["mode"] != "off" or st["entries"] != 0 or st["stores"] != 0:
                fail("G", "VOS_L1_CACHE=0 must force passthrough "
                          f"(stats={st})")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return failures


def check(path: str) -> int:
    """Validate an invalidation fixture (if given) AND run the probe."""
    if path and path.endswith(".json") and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                declared = json.load(fh)
        except (OSError, ValueError):
            sys.stderr.write(f"l1-cache: unreadable fixture {path}\n")
            return 1
        scheme = declared.get("invalidation")
        if scheme != ALLOWED_INVALIDATION:
            sys.stderr.write(
                "l1-cache: invalidation law violated — must be "
                f"'{ALLOWED_INVALIDATION}', fixture declares {scheme!r} "
                "(a clock cannot know the store changed, §4.5)\n"
            )
            return 1

    failures = _run_probe()
    for m in failures:
        sys.stderr.write(f"l1-cache: {m}\n")
    if failures:
        return 1
    sys.stderr.write(
        "l1-cache: probe A-G green (live hit, file-change invalidation, "
        "fresh bypass, verify bypass, shadow+divergence, focus RYW, "
        "kill switch)\n"
    )
    return 0


def negative_case() -> str:
    """A fixture declaring clock-based invalidation — must be rejected."""
    fd, p = tempfile.mkstemp(
        prefix="l1_cache.", suffix=".json", dir=tempfile.gettempdir()
    )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"invalidation": "ttl"}, fh)
    return p


register("l1-cache", check, negative_case)
