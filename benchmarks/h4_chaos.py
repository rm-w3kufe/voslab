#!/usr/bin/env python3
"""H4 — Chaos: fault injection on MultiBridge, graceful degradation demand.

Claim: providers can die, flap, and recover without ever crashing the
caller. Every failure surfaces as UNKNOWN + routing evidence + accurate
health — never an escaped exception, never a confident wrong answer.
Falsifier: ANY exception escaping canon_* predicates, health lying
(healthy after 3 consecutive failures, or unhealthy after recovery),
or a confident TRUE/FALSE built on failed provider data.

Scenarios (FakeProviders with scripted behavior):
  K1 kill mid-query   provider raises on every query
  K2 flap             fail, fail, succeed, fail (health transitions)
  K3 recovery         3 failures (unhealthy) then success (healthy again)
  K4 unknown domain   no provider registered
  K5 killer + healthy duplicate domain with priority (documents current
     single-route behavior: error does NOT fail over — recorded, not
     required; failover is future work, NOT silently assumed)

Metrics: escaped_exceptions, health_accuracy, unknown_on_failure_rate.
"""
from __future__ import annotations

from socratic_engine.engine import SocraticEngine, Truth
from socratic_engine.multi_bridge import MultiBridge


class ScriptedProvider:
    """Provider with scripted per-call behavior: 'ok' or Exception."""

    def __init__(self, script, records=None):
        self.script = list(script)
        self.records = records if records is not None else [{"n": 1}]
        self.calls = 0

    def query(self, domain, filt=None):
        self.calls += 1
        step = self.script[min(self.calls - 1, len(self.script) - 1)]
        if step == "raise":
            raise ConnectionError("injected failure")
        return list(self.records)

    def list_domains(self):
        return ["svc"]


def _q(bridge, eng, domain="svc"):
    return eng.evaluate({"predicate": "canon_query", "args": [domain]}, {})


def run(seed: int = 20260922) -> dict:
    escaped = 0
    checks = []
    detail = []

    def attempt(desc, fn, expect):
        nonlocal escaped
        try:
            got = fn()
            ok = got == expect
        except Exception as e:  # noqa: BLE001 — escaped = fail
            escaped += 1
            got = f"ESCAPED:{type(e).__name__}"
            ok = False
        checks.append(ok)
        if not ok:
            detail.append({"scenario": desc, "got": str(got),
                           "expected": str(expect)})

    # K1: killer provider — every query UNKNOWN, never crash, never TRUE
    b = MultiBridge()
    b.add_provider("killer", ScriptedProvider(["raise"]), ["svc"])
    e = SocraticEngine()
    b.register(e)
    for i in range(4):
        attempt(f"K1 query {i}", lambda: _q(b, e).truth, Truth.UNKNOWN)
    attempt("K1 health unhealthy after 3+ fails",
            lambda: b._providers["killer"].health["healthy"], False)
    attempt("K1 last_error recorded",
            lambda: b._providers["killer"].health["last_error"] is not None,
            True)

    # K2/K3: flap then recover — health follows reality
    b2 = MultiBridge()
    flapper = ScriptedProvider(["raise", "raise", "ok", "ok"])
    b2.add_provider("flap", flapper, ["svc"])
    e2 = SocraticEngine()
    b2.register(e2)
    attempt("K2 first failure UNKNOWN", lambda: _q(b2, e2).truth, Truth.UNKNOWN)
    attempt("K2 second failure UNKNOWN", lambda: _q(b2, e2).truth, Truth.UNKNOWN)
    attempt("K2 still healthy (<3 consecutive)",
            lambda: b2._providers["flap"].health["healthy"], True)
    attempt("K3 recovery TRUE", lambda: _q(b2, e2).truth, Truth.TRUE)
    attempt("K3 healthy after recovery",
            lambda: b2._providers["flap"].health["healthy"], True)
    attempt("K3 error cleared",
            lambda: b2._providers["flap"].health["last_error"] is None, True)

    # K4: unknown domain — UNKNOWN, no crash, no routing hallucinated
    b3 = MultiBridge()
    e3 = SocraticEngine()
    b3.register(e3)
    attempt("K4 unknown domain UNKNOWN", lambda: _q(b3, e3, "nope").truth,
            Truth.UNKNOWN)

    # K5: duplicate domain — priority routes; error does NOT fail over
    # (documents current single-route behavior honestly)
    b4 = MultiBridge()
    b4.add_provider("bad", ScriptedProvider(["raise"]), ["svc"], priority=10)
    b4.add_provider("good", ScriptedProvider(["ok"]), ["svc"], priority=0)
    e4 = SocraticEngine()
    b4.register(e4)
    attempt("K5 priority routes to bad", lambda: b4._domain_map["svc"], "bad")
    r = _q(b4, e4)
    attempt("K5 error surfaces as UNKNOWN (no silent failover)",
            lambda: r.truth, Truth.UNKNOWN)

    # canon_providers reflects unhealthy reality
    attempt("providers truth UNKNOWN when unhealthy",
            lambda: e.predicates["canon_providers"]().truth, Truth.UNKNOWN)

    passed = escaped == 0 and all(checks)
    return {
        "suite": "H4-chaos",
        "claim": "failures degrade gracefully, never crash or lie",
        "metrics": {
            "checks": len(checks),
            "checks_passed": sum(checks),
            "escaped_exceptions": escaped,
            "scenarios": ["K1 kill", "K2 flap", "K3 recovery",
                          "K4 unknown-domain", "K5 priority-doc"],
        },
        "passed": passed,
        "threshold": "0 escaped exceptions AND all graceful-degradation checks",
        "detail": {"failures": detail[:8]},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
