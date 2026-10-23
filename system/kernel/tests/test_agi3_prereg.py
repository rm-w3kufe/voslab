# design: docs/plans/agi_prereg_bfull_r1_2026_10_23.vsm (S5 'Go+' 2026-10-23)
"""Prereg verdict harness de AGI3 (R11) — tests deterministas puros.

Los umbrales viven en PREREG del harness (extraído del doc prereg VSM —
fuente canónica). Toda decisión de S5 edita el doc Y estos tests re-verifican
que los dict y los fixtures siguen alineados (R5: canon over recall).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HARNESS = (Path(__file__).resolve().parents[3] / "scripts" / "agi3"
           / "verdict_harness.py")

_spec = importlib.util.spec_from_file_location("vh", HARNESS)
vh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vh)


def test_prereg_defaults_con_doc():
    # los umbrales embebidos no deben faltar
    for k in ("baseline_random_init_bce", "success_conservador",
              "success_ambicioso", "branch_e_markov", "zero_shot_floor",
              "lora_gate_p1_delta"):
        assert k in vh.PREREG
    # invariantes de abstención de decisión (no sobreponenminos):
    # ambicioso ⊆ conservador
    sa, sc = vh.PREREG["success_ambicioso"], vh.PREREG["success_conservador"]
    assert sa["holdout_bce_max"] < sc["holdout_bce_max"]
    assert sa["coverage_min"] > sc["coverage_min"]


def test_success_conservador():
    r = vh.verdict_b_full({"trained_holdout_bce": 0.63,
                           "coverage_out_of_sample": 0.20})
    assert r["verdict"] == "SUCCESS-CONSERVADOR"


def test_success_ambicioso_primer():
    # (0.58, 40) cumple BOTH — el veredicto debe ser el más estricto
    r = vh.verdict_b_full({"trained_holdout_bce": 0.58,
                           "coverage_out_of_sample": 0.35})
    assert r["verdict"] == "SUCCESS-AMBICIOSO"


def test_branch_e_markov():
    r = vh.verdict_b_full({"trained_holdout_bce": 1.0,
                           "coverage_out_of_sample": 0.01})
    assert r["verdict"] == "BRANCH_E_MARKOV"
    assert "EXP-MARKOV-FEATURES" in r["detalle"]


def test_gris():
    r = vh.verdict_b_full({"trained_holdout_bce": 0.70,
                           "coverage_out_of_sample": 0.12})
    assert r["verdict"] == "GRIS"


def test_incomplete_fail_loud():
    r = vh.verdict_b_full({"trained_holdout_bce": 0.63})
    assert r["verdict"] == "INCOMPLETE-DATA"
    assert "coverage_out_of_sample" in r["fields"]


def test_coverage_clamp_fail_loud():
    r = vh.verdict_b_full({"trained_holdout_bce": 0.58,
                           "coverage_out_of_sample": 1.4})
    assert r["verdict"] == "INCOMPLETE-DATA"


def test_r1_lora_gate():
    r = vh.verdict_r1({"zero_shot_correct": 20, "lora_correct": 28})
    assert r["verdict"] == "EXPAND-LORA-P2"
    assert r["lora_delta"] == 8


def test_r1_floor():
    ok = vh.verdict_r1({"zero_shot_correct": 20})
    assert ok["verdict"] == "FLOOR-OK"
    missed = vh.verdict_r1({"zero_shot_correct": 8})
    assert missed["verdict"] == "FLOOR-MISSED"
