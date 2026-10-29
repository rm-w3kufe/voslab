# design: docs/design/sources/learn-budget-v1/learn_budget_design.vsm
"""Deterministic (R10) tests for learn_budget (LEARN-BUDGET-v1).
design: docs/design/sources/learn-budget-v1/learn_budget_design.vsm

Every path arg is explicit tmp — no test may read or write the real
state/rsi/learn_* surfaces (lesson: test isolation, conftest RSI state).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Import-time path binding: CONSOLIDATIONS_PATH is read at import, so the
# sandbox MUST be set before learn_budget loads. Without it the default
# scenario_memory executor wrote fixture rows (alert-li-*, frozen NOW) into
# the live learn_consolidations.jsonl — breaking the isolation promise below.
os.environ["LEARN_CONSOLIDATIONS_FILE"] = str(
    Path(tempfile.mkdtemp(prefix="learn-budget-test-")) / "consolidations.jsonl")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # system/kernel

from learn_budget import (  # noqa: E402
    ALERT_TYPE, THRESHOLD_BOUNDS, EnvelopeError, baseline_ingest,
    canonical_params, consume, decide, envelope_sha, exec_thresholds,
    init_envelope, ledger_events, load_envelope, omega_ok, weekly_approved,
)

NOW = datetime(2026, 10, 15, 5, 17, 13, tzinfo=timezone.utc)  # ratified ts
PARAMS = {
    "ratified_at": "2026-10-15T05:17:13Z",
    "ratification": "docs/plans/autonomy_ceiling_proposals.vsm"
                    "@ratificacion_P_B",
    "cap_per_week": 2,
    "domains": ["thresholds", "scenario_memory"],
    "max_cost_l3_samples": 2,
}


def _env(tmp: Path, name: str = "env.json", **over) -> dict:
    p = {**PARAMS, **over}
    return init_envelope(p, path=tmp / name)


def _alert(i: int = 1, acked: bool = False, **over) -> dict:
    base = {
        "alert_id": f"alert-li-{i}", "ts": "2026-10-15T03:16:32Z",
        "level": "warn", "alert_type": ALERT_TYPE,
        "source": "learning-cycle-scan(S4)", "acknowledged": acked,
        "detail": "S4: N patrones novel alcanzaron umbral",
    }
    base.update(over)
    return base


def _ack_recorder():
    acked = []

    def ack_many(ids):
        ids = list(ids)
        acked.extend(ids)
        return len(ids)
    return ack_many, acked


def _ledger(tmp: Path) -> Path:
    return tmp / "ledger.jsonl"


class TestEnvelopeC1:
    def test_sha_roundtrip(self, tmp_path):
        doc = _env(tmp_path)
        assert doc["sha"] == envelope_sha(doc)
        assert load_envelope(tmp_path / "env.json") == doc

    def test_canonical_ignores_sha_field(self, tmp_path):
        doc = _env(tmp_path)
        a = canonical_params(doc)
        b = canonical_params({**doc, "sha": "deadbeef"})
        assert a == b  # the sha never feeds itself

    def test_tamper_refused(self, tmp_path):
        _env(tmp_path)
        p = tmp_path / "env.json"
        raw = json.loads(p.read_text())
        raw["cap_per_week"] = 99  # self-concession: change the cap
        p.write_text(json.dumps(raw))
        try:
            load_envelope(p)
            raise AssertionError("tampered envelope must not load")
        except EnvelopeError as e:
            assert "sha mismatch" in str(e)

    def test_init_refuses_overwrite(self, tmp_path):
        _env(tmp_path)
        try:
            _env(tmp_path)
            raise AssertionError("second init must require ceremony")
        except EnvelopeError:
            pass

    def test_missing_envelope_refused(self, tmp_path):
        try:
            load_envelope(tmp_path / "nope.json")
            raise AssertionError("missing envelope must raise")
        except EnvelopeError:
            pass


class TestDecide:
    def _decide(self, tmp_path, ledger=None, **kw):
        env = _env(tmp_path)
        base = dict(envelope=env, domain="scenario_memory", cost=1,
                    now=NOW, ledger=ledger or [], omega_pass=True,
                    omega_evidence={"reason": "ok"})
        base.update(kw)
        return decide(**base)

    def test_approve_inside(self, tmp_path):
        assert self._decide(tmp_path) == ("approved", "inside envelope")

    def test_reject_cap(self, tmp_path):
        spent = [{"event": "approved", "week": "2026-W42"}] * 2
        d, r = self._decide(tmp_path, ledger=spent)
        assert d == "rejected_cap" and "2/2" in r

    def test_cap_is_per_week_not_rolling(self, tmp_path):
        other_week = [{"event": "approved", "week": "2026-W41"}] * 5
        assert self._decide(tmp_path, ledger=other_week)[0] == "approved"

    def test_reject_domain(self, tmp_path):
        d, _ = self._decide(tmp_path, domain="L3")  # q2: L3 fuera
        assert d == "rejected_domain"

    def test_reject_cost(self, tmp_path):
        d, _ = self._decide(tmp_path, cost=3)  # > max 2
        assert d == "rejected_cost"

    def test_reject_omega(self, tmp_path):
        d, r = self._decide(tmp_path, omega_pass=False,
                            omega_evidence={"reason": "omega_breached"})
        assert d == "rejected_omega" and "omega_breached" in r

    def test_determinism_r10(self, tmp_path):
        env = _env(tmp_path)  # envelope once (C1 refuses re-init)
        base = dict(envelope=env, domain="scenario_memory", cost=1,
                    now=NOW, ledger=[], omega_pass=True,
                    omega_evidence={"reason": "ok"})
        assert decide(**base) == decide(**base)  # same inputs -> same out


class TestOmegaC3:
    def test_viable_passes(self):
        ok, ev = omega_ok(cert_runner=lambda: [{"pass": True}],
                          measure_fn=lambda **kw: {
                              "dims": {"accuracy": 1.0, "drift": 0.0,
                                       "stability": 1.0},
                              "inside": True},
                          mode_reader=lambda: "nominal")
        assert ok is True and ev["mode"] == "nominal"

    def test_drift_breach_suspends(self):
        ok, ev = omega_ok(cert_runner=lambda: [{"pass": True}],
                          measure_fn=lambda **kw: {
                              "dims": {"accuracy": 0.9, "drift": 0.5,
                                       "stability": 0.9},
                              "inside": False},
                          mode_reader=lambda: "nominal")
        assert ok is False and ev["reason"] == "omega_breached"

    def test_unknown_accuracy_fails_closed(self):
        ok, ev = omega_ok(cert_runner=lambda: None,
                          measure_fn=lambda **kw: {
                              "dims": {"accuracy": None, "drift": 0.0,
                                       "stability": 1.0},
                              "inside": None},
                          mode_reader=lambda: "nominal")
        assert ok is False and ev["reason"] == "omega_unknown"

    def test_non_nominal_mode_suspends(self):
        ok, ev = omega_ok(cert_runner=lambda: [{"pass": True}],
                          measure_fn=lambda **kw: {"dims": {}, "inside": True},
                          mode_reader=lambda: "shed")
        assert ok is False and ev["reason"] == "mode_not_nominal"


class TestConsume:
    def _consume(self, tmp_path, alerts, omega=(True, {"reason": "ok"}),
                 domain="scenario_memory", executor=None, ledger=None):
        ack_many, acked = _ack_recorder()
        r = consume(alerts=alerts, ack_many=ack_many, now=NOW,
                    envelope_path=tmp_path / "env.json",
                    ledger_path=ledger or _ledger(tmp_path),
                    omega_fn=lambda: omega, domain=domain,
                    executor=executor)
        return r, acked

    def test_approved_executes_ledgers_acks(self, tmp_path):
        _env(tmp_path)
        r, acked = self._consume(tmp_path, [_alert(1), _alert(2)])
        assert r["decision"] == "approved" and r["acked"] == 2
        assert acked == ["alert-li-1", "alert-li-2"]
        ev = ledger_events(_ledger(tmp_path))
        assert len(ev) == 1 and ev[0]["event"] == "approved"
        assert ev[0]["envelope_sha"] and ev[0]["alert_ids"] == acked

    def test_dedup_one_decision_for_lot(self, tmp_path):
        _env(tmp_path)
        r, acked = self._consume(tmp_path, [_alert(i) for i in range(3)])
        assert r["signals"] == 3 and r["decision"] == "approved"
        assert len(ledger_events(_ledger(tmp_path))) == 1  # 1 decision
        assert len(acked) == 3

    def test_outside_stays_unacked_negative_control(self, tmp_path):
        """NEGATIVE CONTROL: outside the envelope the signal MUST stay in
        the normal S5 queue — an ack here = silent self-concession."""
        _env(tmp_path, cap_per_week=0)  # no budget at all
        r, acked = self._consume(tmp_path, [_alert(1)])
        assert r["decision"] == "rejected_cap"
        assert acked == [] and r["acked"] == 0
        ev = ledger_events(_ledger(tmp_path))
        assert ev[0]["event"] == "rejected_cap"  # evidence, not silence

    def test_omega_suspended_leaves_queue(self, tmp_path):
        _env(tmp_path)
        r, acked = self._consume(tmp_path, [_alert(1)],
                                 omega=(False, {"reason": "omega_breached"}))
        assert r["decision"] == "rejected_omega" and acked == []

    def test_broken_envelope_never_approves(self, tmp_path):
        _env(tmp_path)
        p = tmp_path / "env.json"
        raw = json.loads(p.read_text())
        raw["domains"] = ["*"]  # widen by hand
        p.write_text(json.dumps(raw))
        r, acked = self._consume(tmp_path, [_alert(1)])
        assert r["decision"] == "rejected_sha" and acked == []

    def test_already_acked_batch_ignored(self, tmp_path):
        _env(tmp_path)
        r, acked = self._consume(tmp_path, [_alert(1, acked=True)])
        assert r["signals"] == 0 and r["decision"] is None
        assert acked == []

    def test_no_signal_no_writes(self, tmp_path):
        _env(tmp_path)
        r, _ = self._consume(tmp_path, [])
        assert r["signals"] == 0
        assert not _ledger(tmp_path).exists()  # nothing spent, nothing said


class TestBaselineQ3:
    def test_baseline_once_and_acks(self, tmp_path):
        _env(tmp_path)
        ack_many, acked = _ack_recorder()
        alerts = [_alert(i) for i in range(5)]
        r = baseline_ingest(alerts=alerts, ack_many=ack_many, now=NOW,
                            ledger_path=_ledger(tmp_path))
        assert r["baseline_alerts"] == 5 and r["acked"] == 5
        # idempotent: second run is a no-op (R5 — ledger decides)
        r2 = baseline_ingest(alerts=alerts, ack_many=ack_many, now=NOW,
                             ledger_path=_ledger(tmp_path))
        assert "skipped" in r2 and len(acked) == 5
        ev = ledger_events(_ledger(tmp_path))
        assert len(ev) == 1 and ev[0]["event"] == "baseline"


class TestThresholdsExecutor:
    def test_noise_raises_min_n_bounded(self, tmp_path):
        # 5 triggers > 2*cap(=2... cap kwarg below) -> raise
        alerts = [_alert(i, ts="2026-10-15T0%d:00:00Z" % (i % 10))
                  for i in range(5)]
        p = tmp_path / "th.json"
        out = exec_thresholds(alerts=alerts, now=NOW, path=p, cap=2)
        assert out["min_n"] == 4 and out["evidence"]["decision"] == \
            "raise_min_n"
        # ceiling: keep pushing -> stops at ratified hi
        for _ in range(10):
            out = exec_thresholds(alerts=alerts, now=NOW, path=p, cap=2)
        assert out["min_n"] == THRESHOLD_BOUNDS["min_n"][1]

    def test_calm_restores_sensitivity(self, tmp_path):
        p = tmp_path / "th.json"
        p.write_text(json.dumps({"min_n": 5, "window_days": 30}))
        alerts = [_alert(1)]  # 1 <= cap 2 -> restore toward default
        out = exec_thresholds(alerts=alerts, now=NOW, path=p, cap=2)
        assert out["min_n"] == 4 and \
            out["evidence"]["decision"] == "restore_min_n"

    def test_floor_never_below_ratified_lo(self, tmp_path):
        p = tmp_path / "th.json"
        p.write_text(json.dumps({"min_n": 3, "window_days": 30}))
        for _ in range(5):
            out = exec_thresholds(alerts=[_alert(1)], now=NOW, path=p,
                                  cap=2)
        lo, _ = THRESHOLD_BOUNDS["min_n"]
        assert out["min_n"] == lo  # default is 3, floor is 2: stops there

    def test_hold_band_no_flap(self, tmp_path):
        # triggers == 2*cap exactly -> band middle -> hold
        alerts = [_alert(i) for i in range(4)]  # 4 == 2*cap
        p = tmp_path / "th.json"
        out = exec_thresholds(alerts=alerts, now=NOW, path=p, cap=2)
        assert out["evidence"]["decision"] == "hold"
        assert out["min_n"] == 3


class TestWeeklyCount:
    def test_counts_current_week_only(self):
        now = NOW
        ledger = [
            {"event": "approved", "week": "2026-W42"},
            {"event": "approved", "week": "2026-W41"},
            {"event": "rejected_cap", "week": "2026-W42"},
            {"event": "baseline", "week": "2026-W42"},
        ]
        assert weekly_approved(ledger, now) == 1
