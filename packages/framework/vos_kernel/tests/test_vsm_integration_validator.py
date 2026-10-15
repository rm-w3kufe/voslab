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
