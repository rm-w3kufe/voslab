"""l0-memo gate — F1 NC de invalidación (refs_optimization_proposal §7.1).

Behavioral probe of the L0 intra-evaluate memo. ALWAYS cold (§5.1: a
cached NC stops proving the gate fails when it must). Scenarios:

  A. HIT in scope: two identical canon_query nodes in ONE evaluate ->
     1 provider read + bridge._l0.hits == 1 (memo fired).
  B. MISS across scopes (read-your-writes): provider data mutated
     BETWEEN evaluates -> evaluate#2 re-reads and SEES the mutation.
     This is the invalidation the proposal demands: the memo of
     evaluate#1 died with its scope; it cannot serve evaluate#2.
  C. No scope, no memo: predicate invoked outside evaluate -> every
     call reaches the provider (safe default).
  D. Kill switch VOS_L0_MEMO=0 -> memo fully bypassed inside evaluate.
  E. Scope law: at rest (outside evaluate) _L0_SCOPE is None — the
     finally-reset means the scope can never outlive the request.

Scope law (what negative_case() violates): the memo scope is exactly
"evaluate". A fixture declaring any other scope — "process", "session" —
is rejected: a process-lifetime memo is precisely the cross-request
staleness F1 refuses to ship (§4.5: no clock TTL, §4.4: freshness by
invalidation, never by hope).

Run by the harness: register("l0-memo", check, negative_case).
Live invocation: system/kernel/tests/test_l0_memo.py calls check("") on
every suite run, so a memo regression goes loud in <= one test run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

from gate_suite.harness import register

ALLOWED_SCOPE = "evaluate"


class _CountingProvider:
    """In-memory provider that counts query() calls — L0 ground truth."""

    def __init__(self, records: list[dict] | None = None):
        self.records = list(records or [])
        self.calls = 0

    def query(self, domain: str, filter_dict: dict | None = None) -> list[dict]:
        self.calls += 1
        recs = self.records
        if filter_dict:
            recs = [
                r for r in recs
                if all(r.get(k) == v for k, v in filter_dict.items())
            ]
        return list(recs)

    def list_domains(self) -> list[str]:
        return ["svc"]


def _fresh_bridge(records: list[dict] | None = None):
    """(engine, bridge, provider) wired exactly like production register()."""
    from socratic_engine.engine import SocraticEngine
    from socratic_engine.multi_bridge import MultiBridge

    provider = _CountingProvider(records)
    bridge = MultiBridge()
    bridge.add_provider("probe", provider, ["svc"])
    engine = SocraticEngine()
    bridge.register(engine)
    return engine, bridge, provider


def _two_query_tree() -> dict:
    # AND only short-circuits on FALSE — both TRUE nodes always run.
    return {"op": "AND", "children": [
        {"predicate": "canon_query", "args": ["svc"]},
        {"predicate": "canon_query", "args": ["svc"]},
    ]}


def _run_probe() -> list[str]:
    """Run scenarios A-E; return human-readable failures (empty = pass)."""
    failures: list[str] = []

    # Memo must be ON for A-C regardless of the caller's environment
    # (the kill-switch path is tested explicitly in D).
    saved = os.environ.get("VOS_L0_MEMO")
    os.environ.pop("VOS_L0_MEMO", None)
    try:
        # A — hit within one evaluate
        engine, bridge, provider = _fresh_bridge([{"name": "a"}])
        ev = engine.evaluate(_two_query_tree(), {})
        from socratic_engine.engine import Truth
        if ev.truth != Truth.TRUE:
            failures.append(f"A: evaluate expected TRUE, got {ev.truth}")
        if provider.calls != 1 or bridge._l0["hits"] != 1:
            failures.append(
                "A: identical query in one evaluate must hit the memo "
                f"(provider calls={provider.calls} expect 1, "
                f"hits={bridge._l0['hits']} expect 1)"
            )

        # B — mutation BETWEEN evaluates is visible (invalidación §7.1)
        engine, bridge, provider = _fresh_bridge([{"name": "a"}])
        ev1 = engine.evaluate({"predicate": "canon_query", "args": ["svc"]}, {})
        provider.records = []  # write after evaluate#1
        ev2 = engine.evaluate({"predicate": "canon_query", "args": ["svc"]}, {})
        if provider.calls != 2:
            failures.append(
                "B: memo leaked across evaluates — provider re-read missing "
                f"(calls={provider.calls} expect 2)"
            )
        if ev1.truth != Truth.TRUE or ev2.truth != Truth.UNKNOWN:
            failures.append(
                "B: read-your-writes broken — evaluate#2 must see the "
                f"mutation (truth {ev1.truth} -> {ev2.truth}, "
                "expect TRUE -> UNKNOWN)"
            )

        # C — outside evaluate: no scope, every call fresh
        engine, bridge, provider = _fresh_bridge([{"name": "a"}])
        engine.predicates["canon_query"]("svc")
        engine.predicates["canon_query"]("svc")
        if provider.calls != 2 or bridge._l0["hits"] != 0:
            failures.append(
                "C: predicate outside evaluate must never memoize "
                f"(calls={provider.calls} expect 2, hits={bridge._l0['hits']} "
                "expect 0)"
            )

        # D — kill switch bypasses the memo inside evaluate
        os.environ["VOS_L0_MEMO"] = "0"
        engine, bridge, provider = _fresh_bridge([{"name": "a"}])
        engine.evaluate(_two_query_tree(), {})
        if provider.calls != 2 or bridge._l0["hits"] != 0:
            failures.append(
                "D: VOS_L0_MEMO=0 must force fresh reads "
                f"(calls={provider.calls} expect 2, hits={bridge._l0['hits']} "
                "expect 0)"
            )
        os.environ.pop("VOS_L0_MEMO", None)

        # E — at rest there is no open scope (finally-reset)
        from socratic_engine.multi_bridge import _L0_SCOPE
        if _L0_SCOPE.get() is not None:
            failures.append("E: L0 scope still open at rest — finally-reset broken")
    finally:
        if saved is None:
            os.environ.pop("VOS_L0_MEMO", None)
        else:
            os.environ["VOS_L0_MEMO"] = saved
    return failures


def check(path: str) -> int:
    """Validate a scope fixture (if given) AND run the behavioral probe."""
    if path and path.endswith(".json") and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                declared = json.load(fh)
        except (OSError, ValueError):
            sys.stderr.write(f"l0-memo: unreadable fixture {path}\n")
            return 1
        scope = declared.get("scope")
        if scope != ALLOWED_SCOPE:
            sys.stderr.write(
                "l0-memo: scope law violated — memo scope must be "
                f"'{ALLOWED_SCOPE}', fixture declares {scope!r} "
                "(cross-request staleness is not shippable, §4.5)\n"
            )
            return 1

    failures = _run_probe()
    for f in failures:
        sys.stderr.write(f"l0-memo: {f}\n")
    if failures:
        return 1
    sys.stderr.write(
        "l0-memo: probe A-E green (hit in scope, invalidation across "
        "evaluates, no-scope fresh, kill switch, finally-reset)\n"
    )
    return 0


def negative_case() -> str:
    """A fixture declaring a process-lifetime memo scope — must be rejected."""
    fd, p = tempfile.mkstemp(
        prefix="l0_memo.", suffix=".json", dir=tempfile.gettempdir()
    )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"scope": "process"}, fh)
    return p


register("l0-memo", check, negative_case)
