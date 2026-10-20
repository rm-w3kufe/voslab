# design: docs/plans/automation_integration_plan_2026_10_13.vsm (SUT: packages/framework/vos_kernel/validator/vsm_integration_validator.py)
"""Tests del ROL/DRIVER field reader (false-advisory fix 2026-10-15).

Bug vivido: el regex sin \\b parseaba la SUBCADENA "rol" de
"control: an" como declaracion ROL con valor "an" (harness.py
valor "it", extractor_vacuity valor "an") y disparaba "ROL declarado
no resuelve a Sn" en cada pre-commit que tocaba archivos con prosa
"control:" en sus primeras 40 lineas. Ahora: declaraciones reales
(ROL con separador y valor S2) con boundaries sí parsean;
"control:" / "controllers:" / "ROL-v2" no.

Nota: esta prosa evita a proposito escribir la declaracion literal
con valor "an" — el parser la tomaria (first-declaration-wins).

R10 deterministico: parser puro sobre tmp files, sin reloj.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FRAMEWORK = str(Path(__file__).resolve().parents[2])
if _FRAMEWORK not in sys.path:
    sys.path.insert(0, _FRAMEWORK)

from vos_kernel.validator.vsm_integration_validator import (  # noqa: E402
    determine_vsn_level,
    read_declared_fields,
    validate_tool_integration,
)


def _head(tmp_path: Path, *lines: str) -> Path:
    p = tmp_path / "tool.py"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_control_colon_does_not_parse_as_rol(tmp_path):
    """The harness.py / extractor_vacuity false-positive: control: it."""
    p = _head(tmp_path,
              '"""Docstring.',
              "negative control: it could not discriminate a violating",
              "the gate's negative control: an EMPTY target must be",
              '"""')
    fields = read_declared_fields(p)
    assert "ROL" not in fields, f"substring false-positive: {fields}"


def test_real_rol_declaration_parses(tmp_path):
    p = _head(tmp_path, "# ROL: S2", "# DRIVER: phi_up_direct")
    fields = read_declared_fields(p)
    assert fields.get("ROL") == "S2"
    assert fields.get("DRIVER") == "phi_up_direct"
    assert determine_vsn_level(fields) == "S2"


def test_rol_equals_separator_also_parses(tmp_path):
    p = _head(tmp_path, "# ROL = S4")
    fields = read_declared_fields(p)
    assert fields.get("ROL") == "S4"


def test_bare_word_mention_does_not_parse(tmp_path):
    """No separator -> no declaration (the original contract)."""
    p = _head(tmp_path, "# see driver-topology for the mapping")
    assert "DRIVER" not in read_declared_fields(p)


def test_rol_with_hyphenated_value_does_not_resolve(tmp_path):
    """A boundary'd ROL whose value is not an Sn fails loudly (not silently)."""
    p = _head(tmp_path, "# ROL: coordinator")
    fields = read_declared_fields(p)
    assert fields.get("ROL") == "coordinator"
    assert determine_vsn_level(fields) is None


def test_first_declaration_wins(tmp_path):
    """Later mentions cannot override the first parsed field (stable)."""
    p = _head(tmp_path, "# ROL: S1", "# ROL: S5")
    assert read_declared_fields(p).get("ROL") == "S1"


# ── D-SA1 (rmw3 S5, 2026-10-20, voto A): advisory tests/** = solo P3 ──
# Canon: P3 de scripts_r16_policy_proposal.vsm (ratificado 2026-10-16).

_P3_DESIGN = "# design: docs/plans/scripts_r16_policy_proposal.vsm"


def _write(tmp_path, name, *lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_test_file_without_design_reports_only_p3_reason(tmp_path):
    """Sin design -> UN solo ✗ (P3); nunca manifest/gate/coherencia."""
    p = _write(tmp_path, "test_sample.py", '"""Doc."""', "assert True")
    r = validate_tool_integration(p)
    assert r["valid"] is False
    errs = [x for x in r["reasons"] if x.startswith("✗")]
    assert len(errs) == 1 and "P3" in errs[0], errs
    joined = "\n".join(r["reasons"])
    assert "backbone manifest" not in joined, joined
    assert "tests de gate" not in joined, joined
    assert "DRIVER" not in joined and "coherente" not in joined, joined


def test_test_file_with_topline_design_is_valid(tmp_path):
    p = _write(tmp_path, "test_sample.py", _P3_DESIGN, "assert True")
    assert validate_tool_integration(p)["valid"] is True


def test_test_file_shebang_design_on_line2_valid(tmp_path):
    """Shebang conserva byte-0; la declaracion P3 va en la line siguiente."""
    p = _write(tmp_path, "test_sample.py", "#!/usr/bin/env python3", _P3_DESIGN, "assert True")
    assert validate_tool_integration(p)["valid"] is True


def test_test_file_design_deeper_than_topline_flagged(tmp_path):
    """P3 nombra line 1: prosa/docstring con design: adentro NO declara."""
    p = _write(tmp_path, "test_sample.py", '"""Doc.', "", _P3_DESIGN, '"""', "assert True")
    assert validate_tool_integration(p)["valid"] is False


def test_non_test_executable_keeps_full_checks(tmp_path):
    """Regression: un .py que no es test conserva design+manifest+gate."""
    p = _write(tmp_path, "helper_tool.py", '"""No design."""', "assert True")
    r = validate_tool_integration(p)
    assert r["valid"] is False
    joined = "\n".join(r["reasons"])
    assert "Sin design" in joined and "backbone manifest" in joined
    assert "tests de gate" in joined, joined
