"""Fase-3c tests: matriz gate/advisory disjunta (invariant ratified S5),
q1 contradicts interpretation (SIMETRICA + refutes dirigida), enmienda
proposal amended."""
import json
import re
from pathlib import Path

import pytest

from epistemic_graph import build
from epistemic_graph.graph_health import ACYCLIC_KINDS


# ---------------------------------------------------------------- matrix

def _proposal_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "plans" / \
        "graph_epistemic_proposal.vsm"


def _c3_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "plans" / \
        "graph_phase3_3c_proposal.vsm"


def test_gate_advisory_disjoint_in_c3():
    """Invariant ratified: gate y advisory keys are disjoint (no overlap)."""
    text = _c3_path().read_text()
    # extract gate block and advisory block from GATE-ADVISORY-MATRIX
    m = re.search(r'design\("GATE-ADVISORY-MATRIX"\)\s*=\s*\{(.*?)\n\}',
                  text, re.S)
    assert m, "GATE-ADVISORY-MATRIX not found in c3 proposal"
    block = m.group(1)
    gm = re.search(r'gate:\s*\{(.*?)\},', block, re.S)
    am = re.search(r'advisory:\s*\{(.*?)\},', block, re.S)
    assert gm and am, "gate/advisory sub-blocks not found"
    gate_keys = set(re.findall(r'^\s{4}(\w+):', gm.group(1), re.M))
    advisory_keys = set(re.findall(r'^\s{4}(\w+):', am.group(1), re.M))
    assert gate_keys, "gate block empty"
    assert advisory_keys, "advisory block empty"
    overlap = gate_keys & advisory_keys
    assert not overlap, f"gate/advisory overlap: {overlap}"


def test_gate_kinds_match_acyclic_check():
    """Gate set == ACYCLIC_KINDS enforced by graph_health (consistency)."""
    text = _c3_path().read_text()
    m = re.search(r'design\("GATE-ADVISORY-MATRIX"\)\s*=\s*\{.*?'
                  r'gate:\s*\{(.*?)\},', text, re.S)
    assert m
    gate_keys = set(re.findall(r'^\s{4}acyclic_(\w+):', m.group(1), re.M))
    assert gate_keys == set(ACYCLIC_KINDS), (gate_keys, ACYCLIC_KINDS)


# ---------------------------------------------------------------- q1

def test_q1_contradicts_decision_registered():
    """q1 decision recorded: SIMETRICA + refutes dirigida (S5 2026-10-11)."""
    text = _c3_path().read_text()
    assert "SIMETRICA" in text
    assert "refutes" in text
    assert "decision_s5" in text
    # interpretation: no code change, phase-2 model confirmed
    assert "no hay cambio de codigo" in text or \
           "no hay cambio de código" in text


def test_contradicts_symmetric_refutes_directed_in_code():
    """Live graph: contradicts edges come in symmetric pairs; refutes (if
    any) are one-directional. Enforces the ratified q1 model in data."""
    g = build(use_cache=False)
    contra = [(e["source"], e["target"]) for e in g["edges"]
              if e["kind"] == "contradicts"]
    refute = [(e["source"], e["target"]) for e in g["edges"]
              if e["kind"] == "refutes"]
    # contradicts: every (a,b) must have (b,a)
    pair_set = set(contra)
    for a, b in contra:
        assert (b, a) in pair_set, f"contradicts not symmetric: {a}->{b}"
    # refutes: if present, must NOT be symmetric (directed)
    refute_set = set(refute)
    for a, b in refute:
        assert (b, a) not in refute_set, \
            f"refutes must be directed (asymmetric): {a}<->{b}"


# ---------------------------------------------------------------- proposal amended

def test_proposal_has_3c_amendment():
    """graph_epistemic_proposal.vsm carries the 3C amendment blocks."""
    text = _proposal_path().read_text()
    assert "LAYERS-AMENDMENT-3C" in text
    assert "GATE-ADVISORY-MATRIX-3C" in text
    assert "Q1-CONTRADICTS-3C" in text
    assert "FASE-3C" in text
