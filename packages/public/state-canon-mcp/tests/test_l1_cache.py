"""L1 cache tests — version-keyed state_query memo (F2, §4.2/§4.4/§7.1).

Same structure as test_state_canon.py: stdlib-only, check() harness,
in-process server calls. Covers the proposal's §7.1 fixtures:

  - mutation of the backing file (or focus file) between requests →
    version bump → MISS → read-your-writes holds
  - shadow (default) always serves FRESH and counts divergences
  - live serves deep-copied entries, caller mutation cannot poison
  - fresh=true bypasses read but still updates the entry
  - state_verify / state_reconcile / state_onboard structurally bypass
    the cache (they never call state_query)
  - providers without version() — or whose version() raises — degrade
    to passthrough, never to a crash
  - no TTL anywhere: invalidation is version-only (§4.5)

Run:  python3 tests/test_l1_cache.py   (from state-canon-mcp/)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "instances"))

from state_canon.l1_cache import L1Cache, file_signature, l1_mode, query_key  # noqa: E402
from state_canon.provider import JsonStateProvider  # noqa: E402
from state_canon.server import StateRagServer  # noqa: E402

PASSED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED
    if not ok:
        print(f"FAIL  {name}  {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"ok    {name}")


@contextmanager
def l1_env(mode: str | None = None, cache: str | None = None):
    saved = {k: os.environ.get(k) for k in ("VOS_L1_MODE", "VOS_L1_CACHE")}
    try:
        for k in ("VOS_L1_MODE", "VOS_L1_CACHE"):
            os.environ.pop(k, None)
        if mode is not None:
            os.environ["VOS_L1_MODE"] = mode
        if cache is not None:
            os.environ["VOS_L1_CACHE"] = cache
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def make_server(tmp: Path, doc: dict, focus: bool = False):
    f = tmp / "state.json"
    f.write_text(json.dumps(doc))
    server = StateRagServer(JsonStateProvider(f),
                            focus_file=str(tmp / "focus.json") if focus else None)
    return server, f


def write_doc(f: Path, doc: dict) -> None:
    """Rewrite the backing file with a distinguishable stamp bump."""
    time.sleep(0.01)  # filesystems with coarse mtime granularity
    f.write_text(json.dumps(doc))


# ═══════════════════════════════════════════════════════════
#                    l1_cache.py UNIT LEVEL
# ═══════════════════════════════════════════════════════════

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)

    # file_signature: stable when unchanged, changes on content change,
    # `absent` participates (creating/deleting must bust the cache)
    a = tmp / "a.json"
    a.write_text("{}")
    sig1 = file_signature(a)
    check("filesig.stable", file_signature(a) == sig1)
    write_doc(a, {"x": 1})
    check("filesig.bumps-on-write", file_signature(a) != sig1)
    check("filesig.absent", file_signature(tmp / "gone.json") == "gone.json:absent")

    # l1_mode: default shadow; kill switch wins; unknown → shadow (never live)
    with l1_env():
        check("mode.default-shadow", l1_mode() == "shadow")
    with l1_env(cache="0"):
        check("mode.kill-switch", l1_mode() == "off")
    with l1_env(mode="live"):
        check("mode.live", l1_mode() == "live")
    with l1_env(mode="totally-bogus"):
        check("mode.unknown-is-shadow", l1_mode() == "shadow")
    with l1_env(mode="live", cache="0"):
        check("mode.kill-wins-over-live", l1_mode() == "off")

    # query_key canonical: filter order irrelevant
    check("key.canonical", query_key("d", {"b": 1, "a": 2}) ==
          query_key("d", {"a": 2, "b": 1}))
    check("key.none-equals-empty", query_key("d", None) == query_key("d", {}))

    # FIFO eviction, deep-copied put
    c = L1Cache(max_entries=2)
    c.put("k1", "v1", [{"n": 1}])
    recs = [{"n": 2}]
    c.put("k2", "v2", recs)
    recs[0]["n"] = 999  # caller mutation after put must not poison the entry
    check("cache.no-poison-on-put",
          c.peek("k2")["records"] == [{"n": 2}], str(c.peek("k2")))
    c.put("k3", "v3", [{"n": 3}])
    check("cache.fifo-evict", c.size == 2 and c.peek("k1") is None)

# ═══════════════════════════════════════════════════════════
#                 SERVER INTEGRATION (§7.1 fixtures)
# ═══════════════════════════════════════════════════════════

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)

    # 1. shadow is the DEFAULT: always serves fresh, counts divergence when
    #    a same-version entry disagrees (unsound versioning must be visible)
    with l1_env():
        s, f = make_server(tmp, {"svc": [{"name": "cache", "st": "up"}]})
        r = s.state_query("svc")
        check("shadow.first-read-fresh", r == [{"name": "cache", "st": "up"}])
        s.l1.put(query_key("svc", None), s._provider_version("svc"),
                 [{"name": "POISON"}])
        r = s.state_query("svc")
        check("shadow.serves-fresh-over-poison",
              r == [{"name": "cache", "st": "up"}], str(r))
        check("shadow.divergence-counted", s.l1.stats()["divergences"] == 1,
              str(s.l1.stats()))

    # 2. live: version match → hit, deep-copied both ways (caller mutation
    #    cannot poison the cache)
    with l1_env(mode="live"):
        s, f = make_server(tmp, {"svc": [{"name": "cache", "st": "up"}]})
        r1 = s.state_query("svc")
        r1[0]["name"] = "MUTATED-BY-CALLER"
        r2 = s.state_query("svc")
        check("live.hit", s.l1.stats()["hits"] >= 1, str(s.l1.stats()))
        check("live.caller-mutation-isolated",
              r2 == [{"name": "cache", "st": "up"}], str(r2))

    # 3. read-your-writes: backing file rewritten → version bump → MISS →
    #    the new content is served (no TTL — invalidation is version-only)
    with l1_env(mode="live"):
        s, f = make_server(tmp, {"svc": [{"name": "cache", "st": "up"}]})
        s.state_query("svc")
        write_doc(f, {"svc": [{"name": "cache", "st": "down"}]})
        r = s.state_query("svc")
        check("live.file-change-serves-new",
              r == [{"name": "cache", "st": "down"}], str(r))
        check("live.file-change-counted-miss",
              s.l1.stats()["misses"] >= 1, str(s.l1.stats()))

    # 4. fresh=true: bypasses serving but still re-reads AND updates the entry
    with l1_env(mode="live"):
        s, f = make_server(tmp, {"svc": [{"name": "cache", "st": "up"}]})
        s.state_query("svc")  # entry now valid
        s.state_query("svc", fresh=True)
        st = s.l1.stats()
        check("fresh.bypass-counted", st["bypasses"] == 1, str(st))
        # after fresh, the entry is still current: next normal call is a hit
        s.state_query("svc")
        check("fresh.entry-still-warm", s.l1.stats()["hits"] >= 1, str(st))

    # 5. structural bypass: verify / reconcile / onboard never touch L1
    with l1_env(mode="live"):
        s, f = make_server(tmp, {"svc": [{"name": "cache", "st": "up"}]})
        s.state_query("svc")
        before = s.l1.stats()
        s.l1.put(query_key("svc", None), s._provider_version("svc"),
                 [{"name": "POISON", "st": "x"}])
        poisoned = s.l1.stats()
        v = s.state_verify("svc", {"st": "up"})
        check("verify.bypasses-cache", v["holds"] is True and v["checked"] == 1,
              json.dumps(v))
        s.state_reconcile()
        s.state_onboard()
        after = s.l1.stats()
        check("verify-reconcile-onboard-no-cache-traffic",
              {k: after[k] for k in ("hits", "misses", "stores")} ==
              {k: poisoned[k] for k in ("hits", "misses", "stores")},
              f"before={before} poisoned={poisoned} after={after}")

    # 6. focus read-your-writes: mark() between two queries is visible —
    #    version = stat of the focus file (catches external writers too)
    with l1_env(mode="live"):
        s, f = make_server(tmp, {"svc": []}, focus=True)
        s.state_query("focus", {"ref": "A"})
        s.focus.mark("A", "active", "note-1")
        r = s.state_query("focus", {"ref": "A"})
        check("focus.read-your-writes",
              len(r) == 1 and r[0]["note"] == "note-1", str(r))
        s.focus.close("A", "done")
        r = s.state_query("focus", {"ref": "A"})
        check("focus.close-visible",
              r and r[0]["status"] == "done", str(r))

    # 7. provider WITHOUT version() → passthrough: every call re-reads,
    #    nothing is ever stored (uncacheable by default, §4.2)
    class NoVersionProvider:
        def __init__(self):
            self.calls = 0

        def list_domains(self):
            return ["svc"]

        def query(self, domain, filter=None):
            self.calls += 1
            return [{"n": self.calls}]

    with l1_env(mode="live"):
        p = NoVersionProvider()
        s = StateRagServer(p)
        s.state_query("svc")
        s.state_query("svc")
        check("noversion.always-fresh", p.calls == 2, f"calls={p.calls}")
        check("noversion.never-stored", s.l1.stats()["entries"] == 0,
              str(s.l1.stats()))

    # 8. version() that RAISES → fail-soft passthrough, never a crash
    class BrokenVersionProvider(NoVersionProvider):
        def version(self, domain):
            raise RuntimeError("boom")

    with l1_env(mode="live"):
        p = BrokenVersionProvider()
        s = StateRagServer(p)
        r = s.state_query("svc")
        check("broken-version.fails-soft", r == [{"n": 1}] and p.calls == 1,
              str(r))

    # 9. kill switch VOS_L1_CACHE=0 → off: no serving, no storing
    with l1_env(cache="0"):
        s, f = make_server(tmp, {"svc": [{"name": "cache"}]})
        s.state_query("svc")
        st = s.l1.stats()
        check("kill.off", st["mode"] == "off", str(st))
        check("kill.no-store", st["entries"] == 0 and st["stores"] == 0,
              str(st))

    # 10. MCP surface: state_query accepts fresh, state_l1_stats exposes KPI
    with l1_env():
        s, f = make_server(tmp, {"svc": [{"name": "cache"}]})

        def rpc(name, args=None):
            resp = s.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": name, "arguments": args or {}}})
            assert "error" not in resp, resp
            return json.loads(resp["result"]["content"][0]["text"])

        rpc("state_query", {"domain": "svc", "fresh": True})
        stats = rpc("state_l1_stats")
        check("mcp.fresh-arg", stats["bypasses"] == 1, str(stats))
        check("mcp.stats-shape",
              {"mode", "hits", "misses", "divergences", "entries"} <= set(stats),
              str(stats))

print(f"\nALL {PASSED} CHECKS PASSED")
