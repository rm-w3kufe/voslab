# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/vsf-rsi/vsf_rsi/arc_dsl.py)
"""Tests for arc_dsl: totality, known transforms, program apply."""
import pytest

from vsf_rsi.arc_dsl import (
    OPS, OP_NAMES, apply, flip_h, flip_v, identity, invert, program_to_str,
    recolor, rot90, rot180, rot270, shift, transpose,
)

G = [[1, 2, 3], [4, 5, 6]]  # 2x3


def test_geometric_known():
    assert rot90(G) == [[4, 1], [5, 2], [6, 3]]
    assert rot180(G) == [[6, 5, 4], [3, 2, 1]]
    assert rot270(G) == [[3, 6], [2, 5], [1, 4]]
    assert flip_h(G) == [[3, 2, 1], [6, 5, 4]]
    assert flip_v(G) == [[4, 5, 6], [1, 2, 3]]
    assert transpose(G) == [[1, 4], [2, 5], [3, 6]]


def test_rot_cycle_returns():
    from vsf_rsi.arc_dsl import rot90 as r
    g = r(r(r(r(G))))
    assert g == G


def test_recolor_shift_invert():
    assert recolor([[1, 2], [1, 3]], 1, 9) == [[9, 2], [9, 3]]
    assert shift([[1, 2], [3, 4]], 0, 1) == [[0, 1], [0, 3]]
    assert shift([[1, 2], [3, 4]], 5, 5) == [[0, 0], [0, 0]]
    assert invert([[0, 9], [1, 8]]) == [[9, 0], [8, 1]]
    assert identity(G) == G


def test_totality_never_raises():
    bad_inputs = [None, [], [[]], "x", 42, {}, [[1], "nope"]]
    fns = [rot90, rot180, rot270, flip_h, flip_v, transpose,
           invert, identity]
    for fn in fns:
        for bad in bad_inputs:
            assert fn(bad) == bad  # passthrough, no raise
    assert recolor(None, 1, 2) is None
    assert shift("x", 1, 1) == "x"
    # unknown op steps are skipped by apply
    assert apply([("nope", []), ("flip_h", [])], G) == flip_h(G)
    assert apply([], G) == G


def test_apply_composes():
    prog = [("flip_h", []), ("recolor", [3, 7])]
    assert apply(prog, G) == [[7, 2, 1], [6, 5, 4]]
    assert program_to_str(prog) == "flip_h -> recolor(3, 7)"
    assert program_to_str([]) == "identity"
    assert set(OP_NAMES) == set(OPS) and len(OP_NAMES) >= 10


def test_object_ops():
    from vsf_rsi.arc_dsl import (keep_color, crop_content, fill_enclosed,
                                 symmetrize_h, tile2x2, _components)
    assert keep_color([[1, 2], [2, 1]], 1) == [[1, 0], [0, 1]]
    assert crop_content([[0, 0, 0], [0, 5, 0], [0, 0, 0]]) == [[5]]
    assert crop_content([[1, 2], [3, 4]]) == [[1, 2], [3, 4]]
    assert fill_enclosed([[1, 1, 1], [1, 0, 1], [1, 1, 1]]) == \
        [[1, 1, 1], [1, 1, 1], [1, 1, 1]]
    assert fill_enclosed([[1, 1, 0], [1, 0, 0]]) == \
        [[1, 1, 0], [1, 0, 0]]  # open to border: untouched
    assert symmetrize_h([[1, 2, 9], [3, 4, 9]]) == \
        [[1, 2, 1], [3, 4, 3]]
    assert tile2x2([[1, 2]]) == [[1, 2, 1, 2], [1, 2, 1, 2]]
    comps = _components([[1, 0, 2], [0, 0, 2]])
    assert sorted(len(c) for c in comps) == [1, 2]
    # totality
    for fn in (keep_color, crop_content, fill_enclosed,
               symmetrize_h, tile2x2):
        assert fn(None) is None
        assert fn([]) == []
