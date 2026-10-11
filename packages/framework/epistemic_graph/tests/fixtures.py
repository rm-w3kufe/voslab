"""Synthetic mini-workspace covering all 7 sources (no runtime dependency)."""
import json
from pathlib import Path

MINI_TRACES = [
    {
        "trace_id": "t-1", "ts": "2026-10-01T10:11:12+00:00",
        "session_id": "s1", "tree_shape": "claim_gate(AND(a, b))",
        "home": "R1", "final_truth": "Truth.TRUE", "final_certified": True,
        "total_latency_ms": 1.0, "context": {"command": "x"},
        "nodes": [
            {"node_id": 0, "type": "operator", "name": "AND",
             "truth": "Truth.TRUE", "certified": True,
             "text": "AND(a, b)", "question": None, "children": [1, 2],
             "evidence": None, "args": None, "error": None},
            {"node_id": 1, "type": "predicate", "name": "a",
             "truth": "Truth.TRUE", "certified": True,
             "text": "a($x)", "question": None, "children": [],
             "evidence": None, "args": None, "error": None},
            {"node_id": 2, "type": "predicate", "name": "b",
             "truth": "Truth.FALSE", "certified": True,
             "text": "b($x)", "question": None, "children": [],
             "evidence": None, "args": None, "error": None},
        ],
    },
    {
        "trace_id": "t-2", "ts": "2026-10-01T10:12:13+00:00",
        "session_id": "s1", "tree_shape": "claim_gate(AND(a, b))",
        "final_truth": "Truth.FALSE", "final_certified": False,
        "nodes": [
            {"node_id": 0, "type": "operator", "name": "AND",
             "truth": "Truth.FALSE", "certified": True,
             "text": "AND(a, b)", "question": None, "children": [1, 2]},
            {"node_id": 1, "type": "predicate", "name": "a",
             "truth": "Truth.TRUE", "certified": True,
             "text": "a($x)", "question": None, "children": []},
            {"node_id": 2, "type": "predicate", "name": "b",
             "truth": "Truth.FALSE", "certified": True,
             "text": "b($x)", "question": None, "children": []},
        ],
    },
    # old row: no text at all (pre-F3) -> fallback keying reported
    {
        "trace_id": "t-3", "ts": "2026-09-01T00:00:01+00:00",
        "tree_shape": "claim_gate(AND(...))",
        "final_truth": "Truth.UNKNOWN", "final_certified": False,
        "nodes": [
            {"node_id": 0, "type": "operator", "name": "AND",
             "truth": "Truth.FALSE", "certified": False, "children": [1]},
            {"node_id": 1, "type": "predicate", "name": "ctx",
             "truth": "Truth.UNKNOWN", "certified": False, "children": []},
        ],
    },
    # no nodes at all
    {"trace_id": "t-4", "ts": "2026-09-01T00:00:02+00:00",
     "tree_shape": "claim_gate(AND(...))"},
    # malformed line is appended by write_workspace, not here
]

CLAIMS_MAIN = """\u27e6 main | CLAIMS-v1 | vsm-1.2.1 | 2026-10-01T10:11:12Z \u27e7

@vsm 1.2.1
@status active

claims = [
  {
    "id": "SRC-MAIN-aaaa-C001",
    "type": "number",
    "subject": "docs/x/main.tex",
    "risk": "exploratory",
    "status": "DECLARED",
    "text": "margin = 2.5 with EXP-AB-01",
    "text_hash": "111aaa222bbb333ccc444ddd555eee666fff777888999000111222333444555",
    "source_id": "SRC-MAIN-aaaa",
    "method": "deterministic",
    "certs": ["CRT-001"]
  },
  {
    "id": "SRC-MAIN-aaaa-C002",
    "type": "number",
    "subject": "docs/x/main.tex",
    "risk": "exploratory",
    "status": "DECLARED",
    "text": "margin = 2.5 with EXP-AB-01",
    "text_hash": "111aaa222bbb333ccc444ddd555eee666fff777888999000111222333444555",
    "source_id": "SRC-MAIN-aaaa",
    "method": "deterministic",
    "certs": []
  },
  {
    "id": "SRC-ORPH-eeee-C001",
    "type": "text",
    "subject": "docs/x/orphan_doc.tex",
    "status": "REFUTED",
    "text": "orphan claim without sidecar document",
    "text_hash": "999000888777666555444333222111000fffee",
    "source_id": "SRC-ORPH-eeee",
    "method": "agent",
    "certs": []
  }
]

routes = {
  "SRC-MAIN-aaaa-C001": {"route": "R1", "status": "DECLARED", "verdict": "PASS"}
}
\u27e6 /main \u27e7
"""

DEPTH_MAIN = """\u27e6 main | DEPTH-v1 | vsm-1.2.1 | 2026-10-01T10:10:10Z \u27e7

@vsm 1.2.1
@status active

levels = ["L1", "L2"]
tools = ["z3", "sympy"]
evidence = {"theorem_envs": 2}
verdict = "full stack L1-L2 required"
span = "L1-L2"
related_sources = 1
\u27e6 /main \u27e7
"""

HARD_RULES = """\u27e6 hard_rules | VSL-HARD-RULES-v1 | vsm-1.2.1 | 2026-10-01T10:10:11Z \u27e7

@vsm 1.2.1
@status ratified

rules("VSL-HARD-RULES-v1") {

  R1_locality: "
    \u2200 C: state(C) \u2286 roots",

  R5_canon_over_recall: "
    session_start: post_compact \u21d2 onboard()"
}
\u27e6 /hard_rules \u27e7
"""

PAPER_DATA = """\u27e6 paper_data | DATA-v1 | vsm-1.2.1 | 2026-10-01T10:10:12Z \u27e7

@vsm 1.2.1
@status active

binary="long run (EXP-AB-01) confirmed floor"
trilogy(EXP-LY-01, "Lyapunov spectrum"):
  status = "done"
also data at "EXP-NC-0{1,2,3}/results.vsm" (brace expansion, NOT a token)
\u27e6 /paper_data \u27e7
"""

REGISTRY = """\u27e6 plan_registry | REGISTRY-v1 | vsm-1.2.1 | 2026-10-01T10:10:13Z \u27e7

@vsm 1.2.1
@status active

plans = [
  {
    plan_id: "PLAN-TEST-1",
    status: "done",
    created_at: "2026-10-01T09:00:00Z"
  },
  {
    plan_id: "PLAN-TEST-2",
    status: "active",
    created_at: "2026-10-02T09:00:00Z"
  }
]
\u27e6 /plan_registry \u27e7
"""

FOCUS = [
    {"ref": "F-TEST-1", "status": "active", "note": "testing",
     "started_at": "2026-10-01T09:30:00Z",
     "updated_at": "2026-10-01T09:45:00Z"},
    {"ref": "F-TEST-2", "status": "done", "note": "finished",
     "updated_at": "2026-10-02T09:45:00Z"},
]

GAP = {
    "id": "sample-gap",
    "name": "Sample Gap",
    "description": "fixture gap",
    "trigger": {"type": "file-created", "patterns": ["*.py"]},
}


def write_workspace(root: Path) -> Path:
    """Materialize the mini workspace under root; returns root."""
    def w(rel: str, content: str) -> Path:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    w("state/rsi/tree_traces.jsonl",
      "\n".join(json.dumps(t) for t in MINI_TRACES) + "\n" + "{bad json\n")
    w("state/epistemic/sidecars/main.claims.vsm", CLAIMS_MAIN)
    w("state/epistemic/sidecars/main.depth.vsm", DEPTH_MAIN)
    w("docs/spec_revision/system/boot/hard_rules.vsm", HARD_RULES)
    w("docs/papers/attractor_convergence/paper_data.vsm", PAPER_DATA)
    w("docs/plans/plan_registry.vsm", REGISTRY)
    w(".opencode/plugins/operational/gap-definitions/sample.gap.json",
      json.dumps(GAP, indent=1))
    w("current_focus.json", json.dumps(FOCUS, indent=2))
    # artifact referenced by claim.subject (document fingerprint input)
    w("docs/x/main.tex", "margin $= 2.5$\n")
    return root
