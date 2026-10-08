"""Tests P1 — pleasure_emitter core (G-34 / PLEASURE-CHANNEL-001).

Cubre: R10 (determinismo puro + event_id estable), baseline rolling con
ventana, RPE (silencio en p=1, sorpresa maxima sin historial), hitos de
la escalera fibonacci N>=3 {3,5,8,13,...} (G-36b S5 2026-10-08: fib +
Laplace — logro eterno, sin muerte por certeza), bits = N*(-log2 p_m)
exactos (p_m registrado) y crecientes a p fijo, reinicio de racha en
fallo, cadena de racha fuera de ventana (sin -log2(0)), storage espejo
+ rotacion y CLI. F2: jamas importa el lado del dolor (alerting).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vos_kernel import pleasure_emitter as pe

WORKSPACE = pe.WORKSPACE  # vOSlab root (repositorio, no packages/)


def _rec(ts, ok, i, unit="gate_run"):
    return {
        "event_id": f"pev-{i:012d}", "ts": ts, "unit": unit,
        "success": ok, "p": 0.0, "streak": 0, "rpe": None,
        "emissions": [], "detail": "", "source": "test", "connection": "",
    }


def _hist(pairs, unit="gate_run"):
    return [_rec(ts, ok, i, unit) for i, (ts, ok) in enumerate(pairs)]


def _ev(ts, success=True, unit="gate_run"):
    return {"ts": ts, "unit": unit, "success": success, "detail": "x"}


def _h(base_day, hour):
    """ts horaria dentro de la misma semana (para no salirse de la ventana 7d)."""
    return f"2026-10-{base_day:02d}T{hour:02d}:00:00Z"


# ── baseline + RPE ──────────────────────────────────────────────────────

def test_rpe_silent_when_routine_all_green():
    # rpe puro muere en p=1 (anti-inundacion intacta); el MILESTONE no:
    # Laplace G-36b -> p_m = (2+1)/(2+2) = 0.75 < 1 -> el hito cobra
    # aunque todo este en verde (logro eterno, firma S5 2026-10-08).
    hist = _hist([("2026-10-01T00:00:00Z", True), ("2026-10-02T00:00:00Z", True)])
    res = pe.evaluate(hist, _ev("2026-10-03T00:00:00Z"))
    assert res["p"] == 1.0
    assert res["rpe"] == 0.0
    kinds = [e["kind"] for e in res["emissions"]]
    assert "rpe" not in kinds                  # sorpresa: silencio en verde
    ms = [e for e in res["emissions"] if e["kind"] == "milestone"]
    assert len(ms) == 1 and ms[0]["streak"] == 3
    assert ms[0]["p"] == 0.75
    assert ms[0]["magnitude"] == round(3 * (-math.log2(0.75)), 6)


def test_rpe_first_event_is_max_surprise():
    res = pe.evaluate([], _ev("2026-10-03T00:00:00Z"))
    assert res["p"] == 0.0
    assert res["emissions"] == [
        {"kind": "rpe", "magnitude": 1.0, "magnitude_unit": "rpe"}
    ]


def test_rpe_partial_baseline():
    hist = _hist([("2026-10-01T00:00:00Z", True),
                  ("2026-10-02T00:00:00Z", False)])
    res = pe.evaluate(hist, _ev("2026-10-03T00:00:00Z"))
    assert res["p"] == 0.5
    assert res["emissions"][0]["magnitude"] == 0.5


def test_failure_never_emits_but_baseline_computed():
    hist = _hist([("2026-10-01T00:00:00Z", True)])
    res = pe.evaluate(hist, _ev("2026-10-02T00:00:00Z", success=False))
    assert res["emissions"] == []
    assert res["streak"] == 0
    assert res["p"] == 1.0  # baseline tambien en fallo (audit F2)


# ── hitos de racha ──────────────────────────────────────────────────────

def _drive_streak(n_success, seed_failures=2, day=5):
    """seed_failures fallos seguidos de n_success exitos (ts horarios, misma semana)."""
    hist = []
    hour = 0
    for i in range(seed_failures):
        hist.append(_rec(_h(day, hour), False, i))
        hour += 1
    steps = []
    for i in range(n_success):
        ts = _h(day, hour)
        res = pe.evaluate(hist, _ev(ts))
        steps.append(res)
        hist.append(_rec(ts, True, 1000 + i))
        hour += 1
    return steps


def test_milestones_follow_fibonacci_ladder():
    # G-36b: escalera fib {3,5,8,13,...} — 9,10,11,12 NO disparan.
    steps = _drive_streak(13)
    milestone_steps = [
        i + 1 for i, s in enumerate(steps)
        if any(e["kind"] == "milestone" for e in s["emissions"])
    ]
    assert milestone_steps == [3, 5, 8, 13]
    assert [s["streak"] for s in steps] == list(range(1, 14))


def test_milestone_bits_formula_exact_organic():
    # bits = N * (-log2 p_m) con el p registrado en la emision (R10)
    for s in _drive_streak(8):
        for e in s["emissions"]:
            if e["kind"] == "milestone":
                assert e["magnitude"] == round(
                    e["streak"] * (-math.log2(e["p"])), 6
                )
                assert e["magnitude"] > 0


def test_milestone_bits_grow_with_streak_at_fixed_p():
    # placer CRECE con la racha a baseline fijo p=0.5 (proposal METRIC.racha):
    # N parejas (F,S) previas -> Laplace (n-1+1)/(2n-2+2) = 0.5 exacto
    # en los hitos — la suavizacion NO deforma el 50/50 (G-36b).
    def prior_with_streak(n):
        hist = []
        idx = 0
        for _ in range(n - 1):          # (n-1) fallos
            hist.append(_rec(_h(5, idx), False, idx)); idx += 1
        for _ in range(n - 1):          # (n-1) exitos previos (cadena)
            hist.append(_rec(_h(5, idx), True, idx)); idx += 1
        ts = _h(5, idx)
        res = pe.evaluate(hist, _ev(ts))
        ms = [e for e in res["emissions"] if e["kind"] == "milestone"]
        assert res["streak"] == n and len(ms) == 1
        assert ms[0]["p"] == 0.5
        return ms[0]["magnitude"]

    bits3, bits5, bits8 = prior_with_streak(3), prior_with_streak(5), prior_with_streak(8)
    assert bits3 == 3.0 and bits5 == 5.0 and bits8 == 8.0
    assert bits3 < bits5 < bits8


def test_failure_resets_streak_then_rebuild():
    hist = []
    day_hour = [0]

    def add(ok):
        ts = _h(5, day_hour[0]); day_hour[0] += 1
        res = pe.evaluate(hist, _ev(ts, success=ok))
        hist.append(_rec(ts, ok, day_hour[0]))
        return res

    assert add(True)["streak"] == 1
    assert add(True)["streak"] == 2
    assert add(False)["streak"] == 0           # fallo reinicia
    r = add(True)
    assert r["streak"] == 1                     # reconstruye desde 1
    assert not any(e["kind"] == "milestone" for e in r["emissions"])


# ── ventana rolling ─────────────────────────────────────────────────────

def test_window_excludes_old_events_from_baseline():
    hist = _hist([("2026-09-20T00:00:00Z", False),   # fuera de 7d
                  ("2026-10-06T00:00:00Z", True)])
    res = pe.evaluate(hist, _ev("2026-10-07T00:00:00Z"), window_days=7.0)
    assert res["p"] == 1.0
    assert res["emissions"] == []


def test_chain_outside_window_preserves_streak_without_inf():
    # cadena de exitos mas vieja que la ventana: racha NO se trunca,
    # p_m sobre (ventana ∪ cadena) nunca es 0 (sin -log2(0)); cadena
    # 100% exitosa -> Laplace G-36b p_m=3/4 -> el hito COBRA (logro
    # eterno): el silencio por certeza era el bug que firma S5 cerro.
    hist = _hist([("2026-08-01T00:00:00Z", True),
                  ("2026-08-15T00:00:00Z", True)])
    res = pe.evaluate(hist, _ev("2026-10-07T00:00:00Z"), window_days=7.0)
    assert res["streak"] == 3
    ms = [e for e in res["emissions"] if e["kind"] == "milestone"]
    assert len(ms) == 1
    assert ms[0]["p"] == 0.75                  # (2+1)/(2+2) Laplace
    assert ms[0]["magnitude"] == round(3 * (-math.log2(0.75)), 6)
    # ventana vacia -> p=0 -> RPE maximo (primer dato tras silencio)
    rpe = [e for e in res["emissions"] if e["kind"] == "rpe"]
    assert rpe == [
        {"kind": "rpe", "magnitude": 1.0, "magnitude_unit": "rpe"}
    ]
    for e in res["emissions"]:
        assert math.isfinite(e["magnitude"])


def test_same_second_burst_chains_and_fires_milestone_once():
    # Fix G-36b (bug visto en vivo con la ráfaga que cruzó 1597): los
    # eventos de un MISMO segundo se encadenan entre si (ts <=, orden
    # de append) — sin el fix, 3 paralelos veian el mismo prior y el
    # hito disparaba 3 veces.
    hist = [_rec(_h(5, i), True, i) for i in range(6)]   # base: streak 6
    ts = _h(5, 6)
    r1 = pe.evaluate(hist, _ev(ts)); hist.append(_rec(ts, True, 601))
    r2 = pe.evaluate(hist, _ev(ts)); hist.append(_rec(ts, True, 602))
    r3 = pe.evaluate(hist, _ev(ts))
    # encadenados: 7, 8 (fib -> UNICO hito), 9 (no fib -> silencio)
    assert [r1["streak"], r2["streak"], r3["streak"]] == [7, 8, 9]
    ms = [
        [e for e in r["emissions"] if e["kind"] == "milestone"]
        for r in (r1, r2, r3)
    ]
    assert ms[0] == [] and len(ms[1]) == 1 and ms[2] == []


def test_logro_eterno_sin_fallos_laplace_g36b():
    # G-36b: racha verde pura mas alla de8 — sin la suavizacion, p_m=1
    # daria 0 bits y la racha larga no cobraria NUNCA (muerte por
    # certeza). Con Laplace, todo hito fib cobra con 0 < p_m < 1.
    steps = _drive_streak(14, seed_failures=0)
    ms_at = {
        i + 1: [e for e in s["emissions"] if e["kind"] == "milestone"]
        for i, s in enumerate(steps)
    }
    for n in (3, 5, 8, 13):
        assert len(ms_at[n]) == 1, f"hito fib {n} no disparo"
        assert ms_at[n][0]["p"] < 1.0 and ms_at[n][0]["magnitude"] > 0
    for n in (9, 10, 11, 12):
        assert ms_at[n] == [], f"streak {n} no es fib: debe ser silencio"


def test_milestone_emits_when_window_has_failure():
    hist = _hist([
        ("2026-10-01T00:00:00Z", False),
        ("2026-10-05T00:00:00Z", True),
        ("2026-10-06T00:00:00Z", True),
    ])
    res = pe.evaluate(hist, _ev("2026-10-07T00:00:00Z"))
    assert res["streak"] == 3
    ms = [e for e in res["emissions"] if e["kind"] == "milestone"]
    assert len(ms) == 1
    assert ms[0]["p"] == 0.6                   # Laplace G-36b: (2+1)/(3+2)
    # formula exacta desde el p REGISTRADO (consistencia R10)
    assert ms[0]["magnitude"] == round(3 * (-math.log2(ms[0]["p"])), 6)


# ── determinismo R10 ────────────────────────────────────────────────────

def test_determinism_r10_same_input_same_output():
    hist = _hist([("2026-10-01T00:00:00Z", True),
                  ("2026-10-02T00:00:00Z", False)])
    a = pe.evaluate(hist, _ev("2026-10-03T00:00:00Z"))
    b = pe.evaluate(hist, _ev("2026-10-03T00:00:00Z"))
    assert a == b
    assert pe._event_id("2026-10-03T00:00:00Z", "gate_run", True, "x") \
        == pe._event_id("2026-10-03T00:00:00Z", "gate_run", True, "x")


def test_units_are_independent_baselines():
    hist = _hist([("2026-10-01T00:00:00Z", False)])  # unit=gate_run
    res = pe.evaluate(hist, _ev("2026-10-02T00:00:00Z", unit="evaluate"))
    assert res["p"] == 0.0


def test_invalid_ts_raises_deterministically():
    with pytest.raises(ValueError):
        pe.evaluate([], {"ts": "no-es-fecha", "unit": "gate_run",
                         "success": True})


# ── storage (espejo alerts: append + rotacion) ──────────────────────────

def test_emit_storage_roundtrip(tmp_path):
    ledger = tmp_path / "pleasure.jsonl"
    r1 = pe.emit("gate_run", True, ts="2026-10-07T01:00:00Z",
                 detail="81/81", path=ledger)
    r2 = pe.emit("gate_run", False, ts="2026-10-07T02:00:00Z",
                 detail="red", path=ledger)
    r3 = pe.emit("gate_run", True, ts="2026-10-07T03:00:00Z",
                 detail="back green", path=ledger)
    back = pe.read_history(ledger)
    assert [x["event_id"] for x in back] == \
        [r1["event_id"], r2["event_id"], r3["event_id"]]
    assert back[1]["success"] is False and back[1]["emissions"] == []
    # baseline PRE-evento: T,F -> p = 1/2
    assert back[2]["p"] == 0.5


def test_emit_is_deterministic_for_fixed_ts(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    ra = pe.emit("evaluate", True, ts="2026-10-07T10:00:00Z",
                 detail="cert", path=a)
    rb = pe.emit("evaluate", True, ts="2026-10-07T10:00:00Z",
                 detail="cert", path=b)
    assert ra == rb
    assert a.read_text() == b.read_text()


def test_rotation_keeps_last_5000(tmp_path):
    ledger = tmp_path / "pleasure.jsonl"
    lines = [
        json.dumps({"event_id": f"pev-{i:012d}", "ts": "2026-01-01T00:00:00Z",
                    "unit": "gate_run", "success": True, "p": 1.0,
                    "streak": 0, "rpe": None, "emissions": [],
                    "detail": "", "source": "", "connection": ""})
        for i in range(10001)
    ]
    ledger.write_text("\n".join(lines) + "\n")
    pe.emit("gate_run", True, ts="2026-10-07T00:00:00Z", path=ledger)
    assert len(ledger.read_text().splitlines()) == 5000  # rotacion espejo-alerts


def test_corrupt_lines_are_skipped(tmp_path):
    ledger = tmp_path / "pleasure.jsonl"
    ledger.write_text("garbage\n{\"not_unit\": true}\n" + json.dumps({
        "event_id": "pev-1", "ts": "2026-10-07T00:00:00Z",
        "unit": "gate_run", "success": True, "p": 0.0, "streak": 1,
        "rpe": 1.0, "emissions": [], "detail": "", "source": "",
        "connection": "",
    }) + "\n")
    assert len(pe.read_history(ledger)) == 1


def test_stats_deterministic(tmp_path):
    ledger = tmp_path / "pleasure.jsonl"
    pe.emit("gate_run", True, ts="2026-10-07T01:00:00Z", path=ledger)
    pe.emit("evaluate", False, ts="2026-10-07T02:00:00Z", path=ledger)
    s1, s2 = pe.stats(ledger), pe.stats(ledger)
    assert s1 == s2
    assert s1["events"] == 2 and s1["successes"] == 1
    assert s1["units"] == ["evaluate", "gate_run"]


# ── CLI (E2E minima) ────────────────────────────────────────────────────

def _env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(WORKSPACE / "packages" / "framework")
    return env


def test_cli_emit_and_stats(tmp_path):
    ledger = tmp_path / "pleasure.jsonl"
    base = [sys.executable, "-m", "vos_kernel.pleasure_emitter",
            "--file", str(ledger)]
    out = subprocess.run(
        base + ["--emit", "gate_run", "--ok", "--detail", "81/81",
                "--source", "run_gates"],
        capture_output=True, text=True, env=_env(),
    )
    assert out.returncode == 0, out.stderr
    rec = json.loads(out.stdout)
    assert rec["unit"] == "gate_run" and rec["success"] is True

    out2 = subprocess.run(base + ["--stats"], capture_output=True,
                          text=True, env=_env())
    assert out2.returncode == 0, out2.stderr
    assert json.loads(out2.stdout)["events"] == 1


def test_cli_emit_requires_ok_or_fail(tmp_path):
    ledger = tmp_path / "pleasure.jsonl"
    out = subprocess.run(
        [sys.executable, "-m", "vos_kernel.pleasure_emitter",
         "--file", str(ledger), "--emit", "gate_run"],
        capture_output=True, text=True, env=_env(),
    )
    assert out.returncode == 2  # exactamente --ok o --fail


# ── F2: jamas toca el lado del dolor ────────────────────────────────────

def test_pleasure_never_touches_pain_side():
    src = (WORKSPACE / "packages" / "framework" / "vos_kernel"
           / "pleasure_emitter.py").read_text()
    assert "import alerting" not in src
    assert "AlertMonitor" not in src
    assert "state/rsi/alerts" not in src
    # el core no aborta flujos (sys.exit solo en el entrypoint CLI)
    core = src.split("def _main")[0]
    assert "sys.exit" not in core
