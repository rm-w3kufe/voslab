#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_covenant.vsm
"""Negative controls for the RSI tool pipeline + gates (R10, stdlib-only).

    python3 tests/test_rsi_tools.py

Tool certify mechanics: identity-task tools must certify (LOO=1.0),
wrong-answer tools must be rejected (LOO=0.0), sandbox must block
disallowed imports, memory roundtrip must persist in the write path.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import rsi_bridge as RB  # noqa: E402
import llm_serialize as LS  # noqa: E402
import checks as CK  # noqa: E402
import covenant as C  # noqa: E402

# identity task: out == inp for every pair (a certified tool is trivial)
TRAINS = [([[1, 2], [3, 4]], [[1, 2], [3, 4]]),
          ([[5, 0], [0, 5]], [[5, 0], [0, 5]])]
TEST = [[9, 8], [7, 6]]

GOOD_TOOL = (
    "def solve(trains, test):\n"
    "    return [row[:] for row in test]\n")

BAD_TOOL = (
    "def solve(trains, test):\n"
    "    return [[9, 9], [9, 9]]\n")

EVIL_IMPORT = (
    "import os\n"
    "def solve(trains, test):\n"
    "    return test\n")


def test_sandbox_blocks_disallowed_import():
    assert RB._try_rsi_strategy(EVIL_IMPORT, TRAINS, TEST) is None


def test_sandbox_rejects_non_solve():
    assert RB._try_rsi_strategy("x = 1", TRAINS, TEST) is None


def test_good_tool_certifies():
    loo = RB.certify_tool(GOOD_TOOL, TRAINS)
    assert loo >= 0.5, f"identity tool must certify, got {loo}"


def test_bad_tool_rejected():
    loo = RB.certify_tool(BAD_TOOL, TRAINS)
    assert loo < 0.5, f"wrong-answer tool must fail certify, got {loo}"


def test_propose_tools_filters_uncertified():
    cands = RB.propose_tools(TRAINS, TEST, [BAD_TOOL, GOOD_TOOL])
    assert len(cands) == 1, "only the certified tool may compete"
    assert cands[0]["grid"] == TEST
    assert cands[0]["loo_frac"] >= 0.5
    assert cands[0]["dynamic"].startswith("rsi:")


def test_memory_roundtrip_in_write_path():
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        old = RB.MEMORY_CANDIDATES
        try:
            RB.MEMORY_CANDIDATES = [Path(td) / "pattern_memory.json"]
            assert RB.append_pattern("t1", GOOD_TOOL,
                                     extra={"loo_frac": 1.0})
            pats = RB._load_rsi_patterns()
            assert "t1" in pats and pats["t1"]["status"] == "active"
            assert RB.has_rsi_strategies() is True
        finally:
            RB.MEMORY_CANDIDATES = old


def test_parse_tool_code_extracts_block():
    text = "```python\n" + GOOD_TOOL + "\n```\nthanks"
    assert LS.parse_tool_code(text) == GOOD_TOOL.strip()


def test_parse_tool_code_rejects_no_def():
    assert LS.parse_tool_code("```python\nx=1\n```") is None
    assert LS.parse_tool_code("no code here") is None


def test_gates_pass_clean_submission():
    st = C.RuntimeState()
    sub = {"t1": [{"attempt_1": [[1]], "attempt_2": [[2]],
                   "source": "symbolic", "loo": 1.0}]}
    results = CK.run_gates(sub, st, {"symbolic": 1}, ["solve.py"])
    assert all(r.passed for r in results), \
        [str(r) for r in results if not r.passed]


def test_gates_catch_hole():
    st = C.RuntimeState()
    sub = {"t1": [{"attempt_1": None, "attempt_2": [[2]],
                   "source": "shim", "loo": None}]}
    results = CK.run_gates(sub, st, {}, ["solve.py"])
    names_fail = {r.name for r in results if not r.passed}
    assert "two-attempts" in names_fail
    assert "schema-valid" in names_fail


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"OK: {len(fns)}/{len(fns)} rsi-tool controls green")


if __name__ == "__main__":
    main()
