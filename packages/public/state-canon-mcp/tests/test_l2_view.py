"""L2 view tests — materialized onboard digest (F3b, §4.2/§4.4/§5.2).

Same structure as test_state_canon.py: stdlib-only, check() harness,
in-process server calls. Covers the proposal's §5.2 contract:

  - the digest ALWAYS carries its snapshot stamp (shadow, live, and
    mode=off — stamping is presentation honesty, not a cache feature);
  - key = set of input versions (all provider domains + focus + policy +
    reconciler set) → input change → key change → read-your-writes;
  - shadow (default) serves FRESH and observes divergences; live serves
    the stored entry on key match (assemble never called);
  - fresh=true bypasses the serve but still updates the slot;
  - state_reconcile / state_verify / state_query NEVER touch L2
    (§4.4 ALWAYS FRESH — reconcile is the refresh path);
  - unkeyable inputs → fresh compute stamped `live compute`, no store;
  - cross-session: a NEW server instance inherits the disk slot;
  - kill VOS_L2_CACHE=0 → passthrough (no store) with stamp intact.

Run:  python3 tests/test_l2_view.py   (from state-canon-mcp/)
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

import state_canon.server as server_mod  # noqa: E402
from state_canon.l2_cache import digest_key, l2_mode  # noqa: E402
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
def l2_env(mode: str | None = None, cache: str | None = None,
           path: str | None = None):
    saved = {k: os.environ.get(k)
             for k in ("VOS_L2_MODE", "VOS_L2_CACHE", "VOS_L2_PATH")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        if mode is not None:
            os.environ["VOS_L2_MODE"] = mode
        if cache is not None:
            os.environ["VOS_L2_CACHE"] = cache
        if path is not None:
            os.environ["VOS_L2_PATH"] = path
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _CountingAssemble:
    """Wraps server.assemble — counts real digest computations."""

    def __init__(self):
        self.calls = 0
        self._orig = server_mod.assemble

    def __enter__(self):
        def counting(*a, **k):
            self.calls += 1
            return self._orig(*a, **k)
        server_mod.assemble = counting
        return self

    def __exit__(self, *exc):
        server_mod.assemble = self._orig


def make_server(tmp: Path, doc: dict, name: str = "s"):
    f = tmp / f"state_{name}.json"
    f.write_text(json.dumps(doc))
    return StateRagServer(JsonStateProvider(f)), f


def write_doc(f: Path, doc: dict) -> None:
    time.sleep(0.01)
    f.write_text(json.dumps(doc))


def stamp_of(digest_text: str) -> str:
    return digest_text.splitlines()[0]


# ═══════════════════════════════════════════════════════════
#                    l2_cache.py UNIT LEVEL
# ═══════════════════════════════════════════════════════════

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)

    with l2_env():
        check("mode.default-shadow", l2_mode() == "shadow")
    with l2_env(cache="0"):
        check("mode.kill-switch", l2_mode() == "off")
    with l2_env(mode="live"):
        check("mode.live", l2_mode() == "live")
    with l2_env(mode="bogus"):
        check("mode.unknown-is-shadow", l2_mode() == "shadow")

    check("key.stable", digest_key("a=b") == digest_key("a=b"))
    check("key.differs", digest_key("a=b") != digest_key("a=c"))

    # disk roundtrip + corrupt-file fail-soft (NEW instance = new session:
    # a corrupt disk starts empty; a live instance keeps its memory slot —
    # a transient IO error must not wipe a validated entry)
    from state_canon.l2_cache import L2View  # noqa: E402
    slot = tmp / "l2.json"
    v = L2View(slot)
    v.put("k1", "DIGEST-1")
    v2 = L2View(slot)
    e = v2.get()
    check("disk.roundtrip", e is not None and e["key"] == "k1"
          and e["digest"] == "DIGEST-1", str(e))
    slot.write_text("{corrupt!!")
    check("disk.corrupt-keeps-live-slot", v2.get() is not None)
    check("disk.corrupt-new-instance-is-miss", L2View(slot).get() is None)

# ═══════════════════════════════════════════════════════════
#                 SERVER INTEGRATION (§5.2)
# ═══════════════════════════════════════════════════════════

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    slot = str(tmp / "l2.json")

    # 1. shadow default: fresh compute, ALWAYS stamped, slot populated
    with l2_env(path=slot):
        s, f = make_server(tmp, {"svc": [{"name": "a"}]})
        with _CountingAssemble() as cnt:
            out = s.state_onboard()
        st = s.l2.stats()
        check("shadow.stamped", stamp_of(out).startswith("// snapshot ")
              and "refresh: state_reconcile" in stamp_of(out), stamp_of(out))
        check("shadow.fresh+stored", cnt.calls == 1 and st["stores"] == 1
              and st["misses"] == 1, str(st))

        # 2. determinism: same inputs → divergence 0, slot key stable
        with _CountingAssemble() as cnt:
            out2 = s.state_onboard()
        st = s.l2.stats()
        check("shadow.no-divergence-on-deterministic",
              st["divergences"] == 0 and cnt.calls == 1, str(st))
        check("shadow.same-stamp", stamp_of(out) == stamp_of(out2))

        # 3. input change → key change → read-your-writes
        k1 = stamp_of(out).split()[2]
        write_doc(f, {"svc": [{"name": "b"}]})
        out3 = s.state_onboard()
        k2 = stamp_of(out3).split()[2]
        check("keychange.on-input-change", k1 != k2,
              f"{k1} -> {k2}")
        check("keychange.serves-new-content", "svc(1): b" in out3, out3[:200])

    # 4. live: key match → HIT, assemble NEVER called, byte-identical serve
    with l2_env(mode="live", path=slot):
        s, f = make_server(tmp, {"svc": [{"name": "a"}]})
        with _CountingAssemble() as cnt:
            s.state_onboard()          # miss → store
            warm = cnt.calls
            out1 = s.state_onboard()   # hit
            out2 = s.state_onboard()   # hit
        st = s.l2.stats()
        check("live.no-recompute-on-hit",
              cnt.calls == warm and st["hits"] >= 2, str(st))
        check("live.stable-serve", out1 == out2 and out1.startswith("// snapshot "))

    # 5. shadow poison: same-key poisoned entry → fresh served + divergence
    with l2_env(path=slot):
        s, f = make_server(tmp, {"svc": [{"name": "a"}]})
        s.state_onboard()                       # populate
        s.l2.put(s.l2.get()["key"], "// POISON")
        before = s.l2.stats()["divergences"]
        out = s.state_onboard()
        st = s.l2.stats()
        check("poison.fresh-served", "POISON" not in out, out.splitlines()[0])
        check("poison.divergence-counted",
              st["divergences"] == before + 1, str(st))

        # 6. fresh=true: bypass + recompute + slot updated
        with _CountingAssemble() as cnt:
            warm = cnt.calls
            s.state_onboard(fresh=True)
        st = s.l2.stats()
        check("fresh.bypass+recompute", st["bypasses"] >= 1
              and cnt.calls == warm + 1, str(st))

    # 7. kill: passthrough — no store, stamp intact (honesty independent)
    with l2_env(cache="0", path=slot):
        s, f = make_server(tmp, {"svc": [{"name": "a"}]})
        with _CountingAssemble() as cnt:
            s.state_onboard()
        st = s.l2.stats()
        check("kill.recompute-no-store", cnt.calls == 1 and st["stores"] == 0,
              str(st))
        check("kill.still-stamped",
              s.state_onboard().startswith("// snapshot "))

    # 8. unkeyable provider → live-compute stamp, nothing stored
    class NoVersionProvider:
        def list_domains(self):
            return ["svc"]

        def query(self, domain, filter=None):
            return [{"x": 1}]

        def schema(self, domain):
            return {}

    with l2_env(path=slot):
        s = StateRagServer(NoVersionProvider())
        out = s.state_onboard()
        check("unkeyed.honest-stamp",
              out.startswith("// onboard digest (live compute")
              and s.l2.stats()["stores"] == 0, out.splitlines()[0])

    # 9. cross-session: NEW server instance inherits the disk slot
    with l2_env(path=slot):
        s, f = make_server(tmp, {"svc": [{"name": "a"}]})
        with _CountingAssemble() as cnt:
            s.state_onboard()
        s2 = StateRagServer(JsonStateProvider(f))
        entry = s2.l2.get()
        check("crosssession.inherits-slot",
              entry is not None and entry["key"] == s.l2.get()["key"],
              str(entry))
        # shadow: inherited entry matches → hit counted, fresh compute
        # compares against it (divergence 0 = inherited slot was sound)
        with _CountingAssemble() as cnt:
            s2.state_onboard()
        st = s2.l2.stats()
        check("crosssession.shadow-hit-consistent",
              st["hits"] >= 1 and st["divergences"] == 0, str(st))
        # live: the whole point of L2 — serve inherited entry, NO recompute
        os.environ["VOS_L2_MODE"] = "live"
        with _CountingAssemble() as cnt:
            out = s2.state_onboard()
        check("crosssession.live-serves-without-recompute",
              cnt.calls == 0 and s2.l2.stats()["hits"] >= 2
              and out.startswith("// snapshot "), str(s2.l2.stats()))

    # 10. §4.4: reconcile / verify / query never touch L2
    with l2_env(mode="live", path=slot):
        s, f = make_server(tmp, {"svc": [{"name": "a"}]})
        s.state_onboard()
        before = {k: v for k, v in s.l2.stats().items()
                  if k in ("hits", "misses", "stores")}
        s.state_reconcile()
        s.state_verify("svc", {"name": "a"})
        s.state_query("svc")
        after = {k: v for k, v in s.l2.stats().items()
                 if k in ("hits", "misses", "stores")}
        check("reconcile-verify-query-untouch-L2", before == after,
              f"before={before} after={after}")

    # 11. MCP surface: tool + resource stamped, fresh arg, nested KPI
    with l2_env(path=slot):
        s, f = make_server(tmp, {"svc": [{"name": "a"}]})

        def rpc(name, args=None):
            resp = s.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": name, "arguments": args or {}}})
            assert "error" not in resp, resp
            return resp["result"]["content"][0]["text"]

        ob = rpc("state_onboard", {"fresh": True})
        check("mcp.tool-stamped+fresh", ob.startswith("// snapshot "),
              ob.splitlines()[0])
        stats = json.loads(rpc("state_l1_stats"))
        check("mcp.kpi-nested", "l1" in stats and "l2" in stats
              and stats["l2"]["bypasses"] == 1, str(stats))
        r = s.dispatch({"jsonrpc": "2.0", "id": 2, "method": "resources/read",
                        "params": {"uri": "state://digest"}})
        txt = r["result"]["contents"][0]["text"]
        check("mcp.resource-stamped", txt.startswith("// snapshot "),
              txt.splitlines()[0])

print(f"\nALL {PASSED} CHECKS PASSED")
