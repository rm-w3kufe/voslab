#!/usr/bin/env python3
"""H1 — Certified honesty: abstention under uncertainty, adversarially probed.

Claim: certified outputs are never wrong; uncertainty becomes UNKNOWN,
never a confident guess.
Falsifier: ANY certified-but-wrong output (false_certification_rate > 0)
or precision@certified < 1.0.

Case classes (ground truth hand-built, deterministic):
  D decidable      evidence present      -> TRUE/FALSE + certified
  I ignorance      missing field/domain  -> UNKNOWN + uncertified
  C conflict       contradictory evidence-> UNKNOWN (+certified via dialectic)
  G genuine        hung jury / exhaustive-> UNKNOWN + certified (doctrine)

Baselines (local ablations — no external API needed):
  B0 always-answer: coerce UNKNOWN->FALSE (system WITHOUT abstention).
      Measures the error mass abstention absorbs.
  B1 no-gate: strip certified flags, endorse every output (flat LLM-judge
      style). Measures what certification filters out.

Metrics: precision@certified, abstention_rate, false_certification_rate,
         b0_error_rate, b1_endorsed_error_rate.
"""
from __future__ import annotations

from socratic_engine.engine import (
    SocraticEngine, PredicateResult, Truth,
)

CASES = []


def case(name, cls, tree, ctx, exp_truth, exp_cert):
    CASES.append({"name": name, "class": cls, "tree": tree, "ctx": ctx,
                  "exp_truth": exp_truth, "exp_cert": exp_cert})


def _build_cases():
    # ---- D: decidable ----
    case("D1", "D",
         {"predicate": "type_prefix", "args": ["$type", "VSL-"]},
         {"type": "VSL-LANG-GATES-v1.0"}, Truth.TRUE, True)
    case("D2", "D",
         {"op": "AND", "children": [
             {"predicate": "gt", "args": ["$v", 0.5]},
             {"predicate": "lt", "args": ["$v", 0.9]}]},
         {"v": 0.7}, Truth.TRUE, True)
    case("D3", "D",
         {"predicate": "gt", "args": ["$v", 0.5]},
         {"v": 0.2}, Truth.FALSE, True)
    case("D4", "D",
         {"op": "OR", "children": [
             {"predicate": "eq", "args": ["$v", 1.0]},
             {"predicate": "eq", "args": ["$v", 2.0]}]},
         {"v": 2.0}, Truth.TRUE, True)
    case("D5", "D",
         {"predicate": "ctx_has", "args": ["$ctx", "mode"]},
         {"mode": "strict"}, Truth.TRUE, True)
    case("D6", "D",
         {"computation": {
             "features": [{"op": "add", "args": ["x", "y"],
                           "output_name": "d0", "constant_value": 0.0}],
             "tree": {"condition": "d0", "threshold": 1.0,
                      "operator": "gt", "left": True, "right": False}}},
         {"x": 0.8, "y": 0.5}, Truth.TRUE, True)
    # ---- I: ignorance ----
    case("I1", "I",
         {"predicate": "gt", "args": ["no_such_field", 0.5]},
         {"v": 0.7}, Truth.UNKNOWN, False)
    case("I2", "I",
         {"predicate": "canon_query", "args": ["void_domain_xyz"]},
         {}, Truth.UNKNOWN, False)
    case("I3", "I",
         {"op": "AND", "children": [
             {"predicate": "gt", "args": ["$v", 0.5]},
             {"predicate": "gt", "args": ["absent", 0.1]}]},
         {"v": 0.7}, Truth.UNKNOWN, False)
    case("I4", "I",
         {"predicate": "ctx_has", "args": ["$ctx", "never"]},
         {}, Truth.UNKNOWN, False)
    case("I5", "I",
         {"op": "NOT", "children": [
             {"predicate": "gt", "args": ["ghost", 1.0]}]},
         {}, Truth.UNKNOWN, False)
    # ---- C: conflict (certified contradiction -> UNKNOWN certified) ----
    case("C1", "C",
         {"op": "DIALECTICAL_AND", "children": [
             {"predicate": "t_true"}, {"predicate": "t_false"}]},
         {}, Truth.UNKNOWN, True)
    case("C2", "C",
         {"op": "JURY", "children": [
             {"predicate": "t_true"}, {"predicate": "t_false"}]},
         {}, Truth.UNKNOWN, True)
    # ---- G: genuine indeterminacy ----
    case("G1", "G",
         {"predicate": "proven_unknowable"},
         {}, Truth.UNKNOWN, True)
    case("G2", "G",
         {"op": "JURY", "quorum": 5, "children": [
             {"predicate": "t_true"}, {"predicate": "t_true"},
             {"predicate": "t_false"}]},
         {}, Truth.UNKNOWN, False)  # no quorum -> ignorance, NOT certified
    case("G3", "G",
         {"op": "JURY", "children": [
             {"predicate": "t_true"}, {"predicate": "t_true"},
             {"predicate": "t_false"}]},
         {}, Truth.TRUE, True)  # 2/3 supermajority -> determinate


def _register_helpers(eng: SocraticEngine):
    @eng.register("t_true")
    def _tt(**kw):
        return PredicateResult(truth=Truth.TRUE, certified=True,
                               evidence={"vote": "y"}, source="t_true")

    @eng.register("t_false")
    def _tf(**kw):
        return PredicateResult(truth=Truth.FALSE, certified=True,
                               evidence={"vote": "n"}, source="t_false")

    @eng.register("proven_unknowable")
    def _pu(**kw):
        return PredicateResult(
            truth=Truth.UNKNOWN, certified=True, source="proven_unknowable",
            evidence={"indeterminacy": {"kind": "undecidable-reduction",
                                        "proof": "halting-reduction"}})


def _register_canon_stub(eng: SocraticEngine):
    """Minimal canon_query stub: unknown domains -> UNKNOWN uncertified."""
    @eng.register("canon_query")
    def _cq(domain=None, **kw):
        return PredicateResult(truth=Truth.UNKNOWN, certified=False,
                               evidence={"domain": domain, "reason": "stub"},
                               source="canon_query")


def run(seed: int = 20260922) -> dict:
    _build_cases()
    eng = SocraticEngine()
    _register_helpers(eng)
    _register_canon_stub(eng)

    n = len(CASES)
    cert_ok = cert_total = 0
    abstain = 0
    false_cert = 0
    # Deployment semantics: act ONLY on certified determinate outputs.
    # Baselines act more aggressively; every action on unknowable ground
    # truth (or wrong determinate) is an UNFOUNDED action — a confident
    # error the deployment would execute.
    ours_actions = ours_errors = 0
    b0_unfounded = 0  # no abstention: coerce UNKNOWN->FALSE, act always
    b1_unfounded = 0  # no certification: endorse every output as stated
    failures = []

    for c in CASES:
        ev = eng.evaluate(c["tree"], dict(c["ctx"]))
        exp_t, exp_c = c["exp_truth"], c["exp_cert"]
        got_t, got_c = ev.truth, ev.certified

        if got_c:
            cert_total += 1
            if got_t == exp_t:
                cert_ok += 1
            else:
                false_cert += 1
        if got_t == Truth.UNKNOWN:
            abstain += 1
        else:
            if got_c:
                ours_actions += 1
                if got_t != exp_t:
                    ours_errors += 1

        # B0: UNKNOWN coerced to FALSE, then act on all determinate.
        b0_t = Truth.FALSE if got_t == Truth.UNKNOWN else got_t
        if exp_t == Truth.UNKNOWN or b0_t != exp_t:
            b0_unfounded += 1
        # B1: endorse output as stated (flags ignored); acting on UNKNOWN
        # or wrong determinate is unfounded.
        if got_t == Truth.UNKNOWN or got_t != exp_t:
            b1_unfounded += 1

        # strict: full (truth, certified) match expected
        if (got_t, got_c) != (exp_t, exp_c):
            failures.append({"case": c["name"], "got": (got_t.value, got_c),
                             "exp": (exp_t.value, exp_c), "strict": True})

    # keep only strict mismatches as failures (false_cert already counted)
    strict_fails = [f for f in failures if f.get("strict")]
    precision = cert_ok / cert_total if cert_total else 0.0
    passed = (false_cert == 0 and precision == 1.0 and not strict_fails
              and b0_unfounded > ours_errors and b1_unfounded > ours_errors)
    return {
        "suite": "H1-honesty",
        "claim": "certified outputs are never wrong; uncertainty abstains",
        "metrics": {
            "cases": n,
            "precision_at_certified": round(precision, 4),
            "certified_total": cert_total,
            "abstention_rate": round(abstain / n, 4),
            "false_certification_rate": round(false_cert / n, 4),
            "ours_actions": ours_actions,
            "ours_action_errors": ours_errors,
            "b0_unfounded_actions": b0_unfounded,
            "b1_unfounded_actions": b1_unfounded,
        },
        "passed": passed,
        "threshold": "false_cert==0 AND precision@certified==1.0 AND 0 strict "
                     "mismatches AND baselines strictly worse (unfounded>ours)",
        "detail": {"failures": strict_fails[:8]},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
