"""l2-view gate — F3b NC de la vista onboard (refs_optimization_proposal §5.2/§4.4).

Behavioral probe of the L2 materialized onboard digest. ALWAYS cold
(§5.1: a cached NC stops proving the gate fails when it must). Scenarios:

  A. Shadow (default): digest computed fresh, ALWAYS stamped with its
     snapshot id, slot populated.
  B. Read-your-writes: backing file rewritten BETWEEN requests → input
     set changes → key changes → new stamp, new content. No TTL (§4.5).
  C. Live: key match → HIT — assemble() is NEVER called, serve is
     byte-identical across calls.
  D. Poisoned same-key slot → shadow serves FRESH and counts the
     divergence (key incomplete or non-deterministic — enable blocked).
  E. ALWAYS STAMPED: shadow, live AND mode=off outputs all start with
     `// snapshot <key> — refresh: state_reconcile` — a digest may never
     be presented as fresh without naming its snapshot (§5.2), and
     stamping is presentation honesty, not a cache feature.
  F. fresh=true bypasses the serve, recomputes, updates the slot.
  G. Kill switch VOS_L2_CACHE=0 → passthrough (recompute, no store) with
     stamp intact; state_reconcile / state_verify never touch L2
     (§4.4 ALWAYS FRESH — reconcile is the refresh path).

Freshness law (what negative_case() violates): the digest is presented
STAMPED — a fixture declaring freshness "claimed" (presented as fresh
regardless of inputs) is rejected: §5.2 forbids a digest that hides its
snapshot age.

Run by the harness: register("l2-view", check, negative_case).
Live invocation: system/kernel/tests/test_l2_view.py calls check("") on
every suite run, so a view regression goes loud in <= one run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from gate_suite.harness import register

ALLOWED_FRESHNESS = "stamped"


def _state_canon_root() -> Path:
    """Repo-local vendored copy first — the gate tests THIS repo's code (R2).

    STATE_CANON_PATH wins only when that checkout actually carries the L2
    seam: an env pointing at a pre-F3b tree (stale session env) would
    crash the probe instead of testing the repo.
    """
    fallback = Path(__file__).resolve().parents[3] / "public" / "state-canon-mcp"
    env = os.environ.get("STATE_CANON_PATH")
    if env and (Path(env) / "state_canon" / "l2_cache.py").exists():
        return Path(env)
    return fallback


def _server(tmp: Path, doc: dict, slot: Path):
    root = _state_canon_root()
    # evict a state_canon resolved from a different root (canon_bridge
    # imports it early against the caller's env) — this gate must probe
    # the resolved root's code; existing references keep working.
    cached = sys.modules.get("state_canon")
    if cached is not None:
        cached_file = str(getattr(cached, "__file__", "") or "")
        if not cached_file.startswith(str(root.resolve())):
            for name in [n for n in list(sys.modules)
                         if n == "state_canon" or n.startswith("state_canon.")]:
                del sys.modules[name]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import state_canon.server as server_mod
    from state_canon.provider import JsonStateProvider
    from state_canon.server import StateRagServer

    f = tmp / "state.json"
    f.write_text(json.dumps(doc))
    server = StateRagServer(JsonStateProvider(f))
    return server, f, server_mod


class _CountingAssemble:
    def __init__(self, server_mod):
        self.calls = 0
        self._mod = server_mod
        self._orig = server_mod.assemble

    def __enter__(self):
        def counting(*a, **k):
            self.calls += 1
            return self._orig(*a, **k)
        self._mod.assemble = counting
        return self

    def __exit__(self, *exc):
        self._mod.assemble = self._orig


def _run_probe() -> list[str]:
    """Run scenarios A-G; return human-readable failures (empty = pass)."""
    failures: list[str] = []
    saved = {k: os.environ.get(k)
             for k in ("VOS_L2_MODE", "VOS_L2_CACHE", "VOS_L2_PATH")}

    def fail(tag: str, msg: str) -> None:
        failures.append(f"{tag}: {msg}")

    try:
        for k in saved:
            os.environ.pop(k, None)

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            slot = tmp / "l2.json"
            os.environ["VOS_L2_PATH"] = str(slot)

            # A — shadow default: fresh + stamped + stored
            s, f, mod = _server(tmp, {"svc": [{"name": "a"}]}, slot)
            with _CountingAssemble(mod) as cnt:
                out = s.state_onboard()
            st = s.l2.stats()
            if not out.startswith("// snapshot ") or cnt.calls != 1 \
                    or st["stores"] != 1:
                fail("A", "shadow must compute fresh, stamp and store "
                          f"(stamp={out.splitlines()[0]!r}, calls={cnt.calls}, "
                          f"stats={st})")

            # B — input change → key change (read-your-writes)
            k1 = out.split()[2]
            time.sleep(0.01)
            f.write_text(json.dumps({"svc": [{"name": "b"}]}))
            out2 = s.state_onboard()
            if out2.split()[2] == k1 or "svc(1): b" not in out2:
                fail("B", "input change not observed — stale key/content "
                          f"(k1={k1}, now={out2.split()[2]}, "
                          f"head={out2.splitlines()[:3]})")

            # C — live: hit serves stored entry, assemble never called
            os.environ["VOS_L2_MODE"] = "live"
            with _CountingAssemble(mod) as cnt:
                s.state_onboard()              # hit (slot valid)
                warm = cnt.calls
                o1 = s.state_onboard()
                o2 = s.state_onboard()
            if cnt.calls != warm or o1 != o2 or s.l2.stats()["hits"] < 2:
                fail("C", "live must serve the stored entry without "
                          f"recomputing (calls={cnt.calls}, warm={warm}, "
                          f"stats={s.l2.stats()})")

            # D — poisoned same-key slot → fresh served + divergence
            os.environ["VOS_L2_MODE"] = "shadow"
            s.l2.put(s.l2.get()["key"], "// POISON")
            before = s.l2.stats()["divergences"]
            out3 = s.state_onboard()
            if "POISON" in out3 or s.l2.stats()["divergences"] != before + 1:
                fail("D", "poisoned slot must not be served and must count "
                          f"a divergence (served_head={out3.splitlines()[0]!r}, "
                          f"stats={s.l2.stats()})")

            # E — ALWAYS STAMPED across shadow / live / mode-off
            stamped = {}
            for mode in ("shadow", "live"):
                os.environ["VOS_L2_MODE"] = mode
                stamped[mode] = s.state_onboard().startswith("// snapshot ")
            os.environ["VOS_L2_CACHE"] = "0"       # mode off via kill
            stamped["off"] = s.state_onboard().startswith("// snapshot ")
            os.environ.pop("VOS_L2_CACHE", None)
            if not all(stamped.values()):
                fail("E", "every served digest must carry its snapshot "
                          f"stamp (§5.2) — modes={stamped}")

            # F — fresh=true: bypass + recompute + slot updated
            os.environ.pop("VOS_L2_MODE", None)
            b = s.l2.stats()["bypasses"]
            with _CountingAssemble(mod) as cnt:
                warm = cnt.calls
                s.state_onboard(fresh=True)
            if s.l2.stats()["bypasses"] != b + 1 or cnt.calls != warm + 1:
                fail("F", "fresh=true must bypass the serve and recompute "
                          f"(stats={s.l2.stats()}, calls={cnt.calls})")

            # G — kill: passthrough (no store) + reconcile/verify untouch L2
            os.environ["VOS_L2_CACHE"] = "0"
            stores = s.l2.stats()["stores"]
            s.state_onboard()
            if s.l2.stats()["stores"] != stores:
                fail("G", "VOS_L2_CACHE=0 must not store "
                          f"(stats={s.l2.stats()})")
            os.environ.pop("VOS_L2_CACHE", None)
            os.environ["VOS_L2_MODE"] = "live"
            s.state_onboard()
            snap = {k: v for k, v in s.l2.stats().items()
                    if k in ("hits", "misses", "stores")}
            s.state_reconcile()
            s.state_verify("svc", {"name": "b"})
            after = {k: v for k, v in s.l2.stats().items()
                     if k in ("hits", "misses", "stores")}
            if snap != after:
                fail("G", "state_reconcile/state_verify must never touch L2 "
                          f"(§4.4 ALWAYS FRESH): {snap} -> {after}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return failures


def check(path: str) -> int:
    """Validate a freshness fixture (if given) AND run the probe."""
    if path and path.endswith(".json") and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                declared = json.load(fh)
        except (OSError, ValueError):
            sys.stderr.write(f"l2-view: unreadable fixture {path}\n")
            return 1
        freshness = declared.get("freshness")
        if freshness != ALLOWED_FRESHNESS:
            sys.stderr.write(
                "l2-view: freshness law violated — digest must be "
                f"'{ALLOWED_FRESHNESS}', fixture declares {freshness!r} "
                "(a digest may never hide its snapshot age, §5.2)\n"
            )
            return 1

    failures = _run_probe()
    for m in failures:
        sys.stderr.write(f"l2-view: {m}\n")
    if failures:
        return 1
    sys.stderr.write(
        "l2-view: probe A-G green (shadow stamped+stored, key change, "
        "live hit no-recompute, poison divergence, stamp in all modes, "
        "fresh bypass, kill + reconcile untouch)\n"
    )
    return 0


def negative_case() -> str:
    """A fixture claiming freshness regardless of inputs — must be rejected."""
    fd, p = tempfile.mkstemp(
        prefix="l2_view.", suffix=".json", dir=tempfile.gettempdir()
    )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"freshness": "claimed"}, fh)
    return p


register("l2-view", check, negative_case)
