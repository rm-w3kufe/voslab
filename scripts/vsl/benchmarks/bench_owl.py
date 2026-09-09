#!/usr/bin/env python3
"""bench_owl.py — can a reasoner DERIVE the defects I found by reading?

NOT shipped. Same discipline: run it, do not assert it.

THE CLAIM UNDER TEST
I told rmw3 that OWL is the only one of RDF/SHACL/OWL that INFERS rather than
checks shape. That is a claim about our corpus, ¬about OWL in general, so it is
testable exactly one way: take defects I found BY READING, state only the
AXIOMS and the FACTS, and see whether a reasoner reaches the same verdict with
∄ rule written for that defect.

THREE CASES, each a real finding from this cycle:

  T1  D6 VIOLATION — symbiogenesis_lab declared `S4: claude-api` on sci-01,
      which is L=1. D6: S4(L).uses_LLM = ⊤ only_if L ≥ 2.
      I found this by reading. Can a reasoner?

  T2  LEVEL INVERSION — three documents wrote the child at the LOWER index.
      A1: S1(parent) = { V_i(child) }, child = parent + 1.
      Found three times, by reading, one document at a time.

  T3  A4 SIBLING COUPLING — a direct peer coupling with ∄ parent S3 mediating.

PASS means the reasoner derives a contradiction from axioms + facts alone.
FAIL means the constraint has to be written AS a check, which is what we
already do in Python — and then OWL buys nothing here.

THE KNOWN OBSTACLE, stated before running so the result cannot be
rationalised afterwards: OWL is OPEN WORLD. Undeclared is UNKNOWN, ¬false.
Our canon is the opposite — model≡reality is a bijection and undeclared is an
ORPHAN, which is a finding. So T1-T3 are deliberately POSITIVE assertions that
contradict an axiom; that is the shape open-world reasoning can decide. A test
of "nothing declares X" would be unfair to OWL and is ¬attempted.
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRATCH / "rdfvenv/lib/python3.13/site-packages"))

from rdflib import Graph, Namespace, RDF, RDFS, OWL, Literal, XSD, BNode
from rdflib.namespace import SH
import owlrl

V = Namespace("https://vsf.u2738.org/ns#")


def base_ontology() -> str:
    """The AXIOMS, as OWL. Nothing here mentions a specific system."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix v:   <VNS> .

v:ViableSystem a owl:Class .

# ── A1 — recursion direction ──────────────────────────────────────────────
# S1(parent) = { V_i(child) }.  hasChild and hasParent are inverses, and a V
# has exactly one parent. Declaring BOTH directions between the same pair is
# what an inversion looks like once it is stated as a relation.
v:hasChild  a owl:ObjectProperty ; owl:inverseOf v:hasParent .
v:hasParent a owl:ObjectProperty , owl:FunctionalProperty .
v:hasChild  owl:propertyDisjointWith v:hasParent .

# ── D6 — no LLM below level 2 ─────────────────────────────────────────────
# A system whose S4 uses an LLM is an LLMGoverned system.
# A system at level 0 or 1 is a DeterministicLevel system.
# The two classes are DISJOINT — that IS D6, stated once.
# RESTATED INSIDE OWL 2 RL. The first version used owl:oneOf over LITERALS in
# an equivalentClass, which is outside the RL profile, so the reasoner ignored
# the class definition and nothing ever got classified. hasValue and unionOf on
# the LEFT of subClassOf are in RL, and say the same thing.
v:LLMGoverned a owl:Class ;
    owl:equivalentClass [ a owl:Restriction ;
        owl:onProperty v:s4UsesLLM ; owl:hasValue true ] .
v:DeterministicLevel a owl:Class .
[ owl:unionOf (
    [ a owl:Restriction ; owl:onProperty v:atLevel ; owl:hasValue 0 ]
    [ a owl:Restriction ; owl:onProperty v:atLevel ; owl:hasValue 1 ]
  ) ] rdfs:subClassOf v:DeterministicLevel .
v:LLMGoverned owl:disjointWith v:DeterministicLevel .

# ── A4 — no direct sibling coupling ───────────────────────────────────────
# A coupling is either mediated by the parent's S3, or it is direct.
# Sibling + direct is the contradiction.
# Same correction: minCardinality in an equivalentClass is outside RL.
# someValuesFrom on the LEFT of subClassOf is in RL and states the same thing:
# "anything that couples directly to something is a DirectlyCoupledSibling".
v:DirectlyCoupledSibling a owl:Class .
[ a owl:Restriction ; owl:onProperty v:couplesDirectlyTo ;
  owl:someValuesFrom owl:Thing ] rdfs:subClassOf v:DirectlyCoupledSibling .
v:MediatedOnly a owl:Class .
v:DirectlyCoupledSibling owl:disjointWith v:MediatedOnly .
""".replace("VNS", str(V))


CASES = {
    "T1 D6: LLM as the S4 of an L1 system": f"""
@prefix v: <{V}> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
v:sci01 a v:ViableSystem ;
    v:atLevel 1 ;
    v:s4UsesLLM true .
""",
    "T2 A1: child asserted as its own parent's parent": f"""
@prefix v: <{V}> .
v:lab   a v:ViableSystem ; v:hasChild v:vosKernel .
v:vosKernel a v:ViableSystem ; v:hasChild v:lab .
""",
    "T3 A4: sibling coupled directly, and declared mediated-only": f"""
@prefix v: <{V}> .
v:clima a v:ViableSystem , v:MediatedOnly ;
    v:couplesDirectlyTo v:econ .
v:econ  a v:ViableSystem .
""",
}

CONTROL = {
    "C1 D6 respected: LLM at L2": f"""
@prefix v: <{V}> .
v:s4layer a v:ViableSystem ; v:atLevel 2 ; v:s4UsesLLM true .
""",
    "C2 A1 respected: one direction only": f"""
@prefix v: <{V}> .
v:lab a v:ViableSystem ; v:hasChild v:clima .
v:clima a v:ViableSystem .
""",
}


def run_case(facts: str) -> tuple[bool, str]:
    g = Graph()
    g.parse(data=base_ontology(), format="turtle")
    g.parse(data=facts, format="turtle")
    # DETECTION CORRECTED. The first version looked for owl:Nothing, which
    # owlrl never derives -- it collects inconsistencies in `error_messages`.
    # The instrument said 0/3 and the reason was that I was reading the wrong
    # output, ¬that OWL could not decide. Caught by a positive control: an
    # individual in two disjoint classes, which MUST be inconsistent, also
    # showed 0. A test whose textbook case fails is testing itself.
    try:
        closure = owlrl.OWLRL_Semantics(g, False, False, False)
        closure.closure()
        closure.flush_stored_triples()
    except Exception as e:
        return False, f"reasoner error: {type(e).__name__}: {e}"
    errs = list(getattr(closure, "error_messages", []) or [])
    if errs:
        return True, errs[0][:150]
    return False, "∄ contradiction derived"


def main() -> int:
    print("  ── OWL-RL: can axioms + facts DERIVE the defect? ──\n")
    print("  VIOLATIONS — a reasoner should flag these")
    hits = 0
    for name, facts in CASES.items():
        ok, why = run_case(facts)
        hits += ok
        print(f"    {'✓ DERIVED' if ok else '· missed  '}  {name}")
        print(f"                 {why}")
    print(f"\n  CONTROLS — a reasoner must NOT flag these")
    fp = 0
    for name, facts in CONTROL.items():
        ok, why = run_case(facts)
        fp += ok
        print(f"    {'✗ FALSE POSITIVE' if ok else '✓ clean  '}  {name}")
    print(f"\n  derived {hits}/{len(CASES)} violations · {fp} false positives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
