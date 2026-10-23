#!/usr/bin/env python3
# design: docs/plans/agi_prereg_bfull_r1_2026_10_23.vsm (prereg S5 'Go+' 2026-10-23)
"""verdict_harness.py — consumidor determinista del prereg AGI (R10).

Evalúa el pretrain_report.json del run contra los umbrales
PRE-REGISTRADOS (PREREG abajo, derivados del doc; la fuente canónica es
el doc VSM y este dict debe moverse con él) y emite EL ÚNICO veredicto
del prereg SIN LLM en el path (R10). Fail-loud con INCOMPLETE-DATA si
falta cualquier campo pre-registrado (R9).

Uso:
    python3 scripts/agi3/verdict_harness.py <pretrain_report.json> --exp b_full
    python3 scripts/agi3/verdict_harness.py <report.json> --exp r1
    python3 scripts/agi3/verdict_harness.py --selftest
Salidas: JSON con verdict ∈ {SUCCESS-CONSERVADOR, SUCCESS-AMBICIOSO, GRIS,
BRANCH_E_MARKOV, FLOOR-OK, FLOOR-MISSED, EXPAND-LORA-P2, INCOMPLETE-DATA}.
Exit: 0 veredicto completo, 2 INCOMPLETE-DATA.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PREREG = {
    "baseline_random_init_bce": 0.654,
    "coverage_total": 120,
    "success_conservador": {"holdout_bce_max": 0.654, "coverage_min": 20},
    "success_ambicioso":   {"holdout_bce_max": 0.60, "coverage_min": 35},
    "branch_e_markov":     {"holdout_bce_min": 0.80, "coverage_max": 5},
    "zero_shot_floor":     {"correct_min": 15},
    "lora_gate_p1_delta":  5,
}


def verdict_b_full(report: dict) -> dict:
    """Veredicto determinista del pretrain contra el prereg.

    Campos esperados (schema v4 + nuevo campo del run B):
      trained_holdout_bce, coverage_out_of_sample.
    """
    missing = [k for k in ("trained_holdout_bce", "coverage_out_of_sample")
               if k not in report]
    if missing:
        return {"verdict": "INCOMPLETE-DATA", "fields": missing}
    hb = float(report["trained_holdout_bce"])
    cov = int(report["coverage_out_of_sample"])
    out = {"inputs": {"trained_holdout_bce": hb,
                      "coverage_out_of_sample": cov}}
    if not (math.isfinite(hb) and hb > 0 and 0 <= cov):
        out["verdict"] = "INCOMPLETE-DATA"
        return out
    a = PREREG["branch_e_markov"]
    if hb >= a["holdout_bce_min"] or cov <= a["coverage_max"]:
        out["verdict"] = "BRANCH_E_MARKOV"
        out["detalle"] = ("más data NO salva el mismatch (distribución); "
                          "abrir rama EXP-MARKOV-FEATURES + Ω-curriculum "
                          "(DYN-LLM-GRANT), cada uno con SU ronda ratificada")
        return out
    amb = PREREG["success_ambicioso"]
    if hb <= amb["holdout_bce_max"] and cov >= amb["coverage_min"]:
        out["verdict"] = "SUCCESS-AMBICIOSO"   # subconjunto estricto: PRIMERO
        return out
    c = PREREG["success_conservador"]
    if hb < c["holdout_bce_max"] and cov >= c["coverage_min"]:
        out["verdict"] = "SUCCESS-CONSERVADOR"
        return out
    out["verdict"] = "GRIS"
    out["detalle"] = "breakdown per-game del holdout (sin GPU extra)"
    return out


def verdict_r1(report: dict) -> dict:
    """Veredicto del r1 zero-shot + LoRA gate p1 contra el prereg.

    Campos esperados: zero_shot_correct (n), lora_correct (n, opcional);
    eval_total puede declararse (default 120).
    """
    if "zero_shot_correct" not in report:
        return {"verdict": "INCOMPLETE-DATA", "fields": ["zero_shot_correct"]}
    zero = int(report["zero_shot_correct"])
    total = int(report.get("eval_total", PREREG["coverage_total"]))
    out = {"inputs": {"zero_shot_correct": zero, "eval_total": total}}
    zz = PREREG["zero_shot_floor"]["correct_min"]
    out["zero_shot_floor_ok"] = zero >= zz
    if "lora_correct" in report:
        lv = int(report["lora_correct"])
        delta = lv - zero
        out["inputs"]["lora_correct"] = lv
        out["lora_delta"] = delta
        out["lora_gate_p1"] = (delta >= PREREG["lora_gate_p1_delta"])
        out["verdict"] = "EXPAND-LORA-P2" if out["lora_gate_p1"] else "GATE-P1-MISSED"
    else:
        out["verdict"] = "FLOOR-OK" if out["zero_shot_floor_ok"] else "FLOOR-MISSED"
    return out


def _selftest() -> int:
    fx = [
        ({"trained_holdout_bce": 0.63, "coverage_out_of_sample": 25},
         "SUCCESS-CONSERVADOR"),
        ({"trained_holdout_bce": 1.0, "coverage_out_of_sample": 2},
         "BRANCH_E_MARKOV"),
        ({"trained_holdout_bce": 0.70, "coverage_out_of_sample": 12},
         "GRIS"),
        ({"trained_holdout_bce": 0.58, "coverage_out_of_sample": 40},
         "SUCCESS-AMBICIOSO"),
    ]
    for report, want in fx:
        got = verdict_b_full(report)["verdict"]
        assert got == want, f"{report} -> '{got}' != '{want}'"
    miss = verdict_b_full({"trained_holdout_bce": 0.63})
    assert miss["verdict"] == "INCOMPLETE-DATA"
    r = verdict_r1({"zero_shot_correct": 20, "lora_correct": 28})
    assert r["verdict"] == "EXPAND-LORA-P2" and r["lora_delta"] == 8
    assert verdict_r1({"zero_shot_correct": 8})["verdict"] == "FLOOR-MISSED"
    print("selftest OK (6 fixtures deterministas, R10)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", nargs="?", help="path al pretrain_report.json")
    ap.add_argument("--exp", "-e", choices=("b_full", "r1"), default="b_full")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.report:
        ap.error("sin --selftest se necesita el path del report")
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — fail-loud report unreadable
        print(f"FATAL: report unreadable: {e}", file=sys.stderr)
        return 2
    v = verdict_b_full(report) if args.exp == "b_full" else verdict_r1(report)
    print(json.dumps(v, indent=2, sort_keys=True))
    return 2 if v.get("verdict") == "INCOMPLETE-DATA" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
