#!/usr/bin/env python3
# design: docs/plans/automation_integration_plan_2026_10_13.vsm (SUT: packages/framework/vos_kernel/validator/vsm_integration_validator.py)
"""Tests for Fase-2 slice 1: B4-parametric validator, doc/executable split.

Design reference: driver_topology.vsm (validator reads its §10 table instead
of duplicating it) + R16 rule (design: headers, same as impl-with-design-valid).

Covers: B4 table loads with exact row count + spot mappings; .vsm docs take
the doc path (format validity governs, B4 mapping is informational, unmapped
TYPE is advisory-not-failure); executables take the R16 path (design: header
required, declared ROL/DRIVER coherence conditional, route+tests heuristics
unchanged); no VSM-header demand on executables (nothing in the corpus has
them — demanding them would block the world).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.normpath(os.path.join(_HERE, ".."))
_FW = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_PKG, _FW):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from vos_kernel.validator.vsm_integration_validator import (
    load_b4_table,
    validate_tool_integration,
)

REPO = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", ".."))


def test_b4_table_loads_full():
    table = load_b4_table()
    assert len(table) == 102
    assert table["S3-ALLOCATION-01"]["sn"] == "S3"
    assert table["S3-ALLOCATION-01"]["driver"] == "invariant_guard"
    assert table["PLAN-v1"]["sn"] == "S5"
    assert table["DIR-CLASSIFICATION-LOCAL"]["sn"] == "META"
    assert table["PLAN-v1"]["driver"] == "consent_gate"


def test_b4_table_missing_file_empty(tmp_path):
    table = load_b4_table(spec_path=os.path.join(str(tmp_path), "nope.vsm"))
    assert table == {}


def test_doc_valid_mapped_reports_b4():
    path = os.path.join(
        REPO, "docs/spec_revision/system/plan/strategy_plan.vsm")
    if not os.path.isfile(path):
        path = os.path.join(
            REPO, "docs/spec_revision/plan/strategy_plan.vsm")
    result = validate_tool_integration(path)
    assert result["valid"] is True
    assert result["level"] == "S5"
    assert any(r.startswith("○ B4:") for r in result["reasons"])


def test_doc_invalid_format_fails(tmp_path):
    p = os.path.join(str(tmp_path), "broken.vsm")
    with open(p, "w") as fh:
        fh.write("this is not a vsm document at all\n")
    result = validate_tool_integration(p)
    assert result["valid"] is False
    assert any(r.startswith("✗") for r in result["reasons"])


def test_doc_unmapped_type_advisory_not_failure(tmp_path):
    p = os.path.join(str(tmp_path), "mystery.vsm")
    with open(p, "w") as fh:
        fh.write("⟦ mystery_doc | MYSTERY-TYPE-99 | vsm-1.2.1 | 2026-10-13T04:31:07Z ⟧\n"
                 "\n@vsm 1.2.1\n@status active\n\nfact(\"x\") = { v: 1 }\n\n"
                 "⟦ /mystery_doc ⟧\n")
    result = validate_tool_integration(p)
    assert result["valid"] is True
    assert any("coverage candidate" in r for r in result["reasons"])


def _exe_fixture(tmp_path, name, body):
    p = os.path.join(str(tmp_path), name)
    with open(p, "w") as fh:
        fh.write(body)
    return p


_DESIGN_LINE = ("# design: docs/spec_revision/design-sources/"
                "driver-topology-v1/driver_topology.vsm")


def test_executable_full_pass(tmp_path):
    p = _exe_fixture(tmp_path, "tool.py",
                     f"# tool\n{_DESIGN_LINE}\n# route entry_point\n# gate tests\n"
                     "def handle():\n    pass\n")
    result = validate_tool_integration(p)
    assert result["valid"] is True, result["reasons"]


def test_executable_missing_design_fails(tmp_path):
    p = _exe_fixture(tmp_path, "nodesign.py",
                     "# tool with route and tests mentioned\n"
                     "def handle():\n    pass\n")
    result = validate_tool_integration(p)
    assert result["valid"] is False
    assert any("R16" in r for r in result["reasons"])


def test_executable_declared_coherence(tmp_path):
    ok = _exe_fixture(tmp_path, "good.py",
                      f"# tool\n{_DESIGN_LINE}\n# ROL: S1\n# DRIVER: phi_up_direct\n"
                      "# route\n# test\n")
    assert validate_tool_integration(ok)["valid"] is True
    bad = _exe_fixture(tmp_path, "bad.py",
                       f"# tool\n{_DESIGN_LINE}\n# ROL: S1\n# DRIVER: consent_gate\n"
                       "# route\n# test\n")
    result = validate_tool_integration(bad)
    assert result["valid"] is False
    assert any("incoherente" in r for r in result["reasons"])


def test_s3_drivers_validate():
    # Regression: an earlier revision tested `driver in {S3: ..., S3*: ...}`
    # (dict membership = KEYS), so every S3/S3* check silently failed.
    from vos_kernel.validator.vsm_integration_validator import (
        check_driver_valid, normalize_driver)
    assert normalize_driver("phi_up_direct") == "φ↑_direct"
    assert normalize_driver("consent_gate") == "consent_gate"
    assert check_driver_valid("invariant_guard", "S3") is True
    assert check_driver_valid("audit_scanner", "S3*") is True
    assert check_driver_valid("consent_gate", "S3") is False
    assert check_driver_valid("phi_up_direct", "S1") is True
    assert check_driver_valid("socratic_engine", "S4") is True
    assert check_driver_valid("LLM_probe", "S4") is True
    assert check_driver_valid("consent_gate", "S5") is True
    assert check_driver_valid("anything", "S9") is False


def test_executable_no_header_no_fields_passes_if_rest_ok(tmp_path):
    # No ROL/DRIVER declared anywhere: coherence is conditional, not demanded.
    p = _exe_fixture(tmp_path, "plain.py",
                     f"# plain tool\n{_DESIGN_LINE}\n# route entry_point\n# gate tests\n")
    result = validate_tool_integration(p)
    assert result["valid"] is True
