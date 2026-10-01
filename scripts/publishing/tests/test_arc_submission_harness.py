"""Tests for the local ARC submission harness (A-5 vía 2 preparation)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arc_submission_harness import (  # noqa: E402
    build_submission,
    main,
    validate_grid,
    validate_submission,
)

GRID = [[1, 2, 3], [4, 5, 6]]
GOOD = {"0d82d65b": GRID, "deadbeef": [[7]]}


class TestValidateGrid:
    def test_valid(self):
        assert validate_grid(GRID) == []

    def test_not_list(self):
        assert validate_grid("nope")

    def test_empty(self):
        assert validate_grid([])

    def test_ragged(self):
        errs = validate_grid([[1, 2], [3]])
        assert any("ragged" in e for e in errs)

    def test_non_int_cell(self):
        errs = validate_grid([[1, "x"]])
        assert any("not an int" in e for e in errs)

    def test_bool_is_not_int(self):
        errs = validate_grid([[True]])
        assert errs  # bool must not pass as int

    def test_cell_out_of_range(self):
        errs = validate_grid([[10]])
        assert any("outside 0..9" in e for e in errs)

    def test_dim_out_of_range(self):
        errs = validate_grid([list(range(31))])
        assert any("dims" in e for e in errs)


class TestValidateSubmission:
    def test_valid(self):
        assert validate_submission(GOOD) == []

    def test_not_object(self):
        assert validate_submission([1])

    def test_empty(self):
        assert validate_submission({})

    def test_bad_task_id(self):
        errs = validate_submission({"NOTHEX!": GRID})
        assert any("8 lowercase hex" in e for e in errs)

    def test_errors_carry_task_context(self):
        errs = validate_submission({"0d82d65b": "bad"})
        assert any(e.startswith("task 0d82d65b") for e in errs)


class TestBuild:
    def test_sorts_keys(self):
        built = build_submission({"deadbeef": [[1]], "0d82d65b": [[2]]})
        assert list(built) == ["0d82d65b", "deadbeef"]

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            build_submission({"zz": GRID})


class TestCli:
    def test_validate_ok(self, tmp_path, capsys):
        f = tmp_path / "s.json"
        f.write_text(json.dumps(GOOD))
        assert main(["validate", str(f)]) == 0
        assert "OK: 2 tasks" in capsys.readouterr().out

    def test_validate_invalid_rc1(self, tmp_path, capsys):
        f = tmp_path / "s.json"
        f.write_text(json.dumps({"bad": [[1]]}))
        assert main(["validate", str(f)]) == 1
        assert "INVALID" in capsys.readouterr().err

    def test_missing_file_rc2(self, tmp_path):
        assert main(["validate", str(tmp_path / "nope.json")]) == 2

    def test_bad_json_rc2(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text("{broken")
        assert main(["validate", str(f)]) == 2

    def test_build_writes_sorted(self, tmp_path):
        f = tmp_path / "pred.json"
        f.write_text(json.dumps({"deadbeef": [[1]], "0d82d65b": [[2]]}))
        out = tmp_path / "submission.json"
        assert main(["build", str(f), "-o", str(out)]) == 0
        data = json.loads(out.read_text())
        assert list(data) == ["0d82d65b", "deadbeef"]
