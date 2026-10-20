# design: docs/plans/epistemic_certification_plan.vsm (SUT: packages/framework/vos_kernel/round_runner.py)
"""Tests for EP-5 — round protocol runner (metrics M1-M8 + closure)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vos_kernel import round_runner as rr

NOW = datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_log(ws: Path, events: list[dict]) -> None:
    log = ws / "logs" / "agent_plugin.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _base_event(**over) -> dict:
    e = {
        "ts": _iso(NOW - timedelta(minutes=5)),
        "pid": 1,
        "level": "info",
        "source": "test",
        "event_type": "evaluate.evaluate",
        "event_id": "test:1",
        "action": "noop",
        "result": "ok",
        "detail": "",
    }
    e.update(over)
    return e


def fixture_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "state" / "rsi").mkdir(parents=True)
    (ws / "state" / "epistemic").mkdir(parents=True)
    (ws / ".opencode" / "plugins" / "support" / "trees").mkdir(parents=True)
    _write_log(ws, [
        _base_event(event_type="learn", source="rsi-cycle"),
        _base_event(event_type="evaluate.failure", level="error"),
        _base_event(event_type="evaluate.l3_audit", source="rsi-cycle"),
    ])
    (ws / "state" / "rsi" / "tree_traces.jsonl").write_text(
        json.dumps({"ts": _iso(NOW - timedelta(minutes=4)), "trace_id": "t1"}) + "\n"
    )
    (ws / "state" / "epistemic" / "decisions.jsonl").write_text(
        json.dumps({"ts": _iso(NOW - timedelta(minutes=3)), "id": "d1"}) + "\n"
    )
    (ws / "state" / "epistemic" / "claims.jsonl").write_text(
        json.dumps({"id": "c1", "status": "OBSERVED"}) + "\n"
        + json.dumps({"id": "c2", "status": "DECLARED"}) + "\n"
    )
    (ws / ".opencode" / "plugins" / "support" / "trees" / "ok.tree.vsm").write_text(
        "// clean tree\n"
    )
    return ws


def fake_route():
    return {"routed": 2, "routes": {"R1": 2}, "failed": []}


def fake_guards(ok: bool = True):
    return {
        "findings": 2, "fixeados": 2, "guarded": 2,
        "coverage": 1.0 if ok else 0.5,
        "missing": [] if ok else ["f1"],
        "liveness": {"G1": "live"},
        "errors": [] if ok else ["finding f1: no guard"],
        "ok": ok,
    }


class TestLogMetrics:
    def test_m1_counts_learn_in_window(self, tmp_path):
        ws = fixture_ws(tmp_path)
        out = rr.collect_log_metrics(NOW - timedelta(hours=1),
                                     ws / "logs" / "agent_plugin.jsonl")
        assert out["M1"] == 1

    def test_old_events_ignored(self, tmp_path):
        ws = fixture_ws(tmp_path)
        out = rr.collect_log_metrics(NOW - timedelta(seconds=1),
                                     ws / "logs" / "agent_plugin.jsonl")
        assert out["M1"] == 0  # all fixture events are 3-5 min old

    def test_m6_errors_with_consumer_not_silent(self, tmp_path):
        ws = fixture_ws(tmp_path)
        out = rr.collect_log_metrics(NOW - timedelta(hours=1),
                                     ws / "logs" / "agent_plugin.jsonl")
        assert out["errors"] >= 1 and out["consumers"] >= 2
        assert out["M6"] == 0

    def test_m6_silent_without_consumer(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_log(ws, [
            _base_event(event_type="evaluate.failure", level="error"),
        ])
        out = rr.collect_log_metrics(NOW - timedelta(hours=1),
                                     ws / "logs" / "agent_plugin.jsonl")
        assert out["consumers"] == 0 and out["M6"] == 1

    def test_m5_detects_manual_digest_ritual(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_log(ws, [
            _base_event(source="tool-integration",
                        action='tool: bash "md5sum state/claims.jsonl"'),
        ])
        out = rr.collect_log_metrics(NOW - timedelta(hours=1),
                                     ws / "logs" / "agent_plugin.jsonl")
        assert out["M5"] == 1

    def test_m7_undeclared_external_write(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_log(ws, [
            _base_event(source="gap-resolution",
                        detail="UNDECLARED external write /elsewhere"),
        ])
        out = rr.collect_log_metrics(NOW - timedelta(hours=1),
                                     ws / "logs" / "agent_plugin.jsonl")
        assert out["M7"] == 1


class TestWindowEvents:
    def test_m2_counts_new_traces_and_decisions(self, tmp_path):
        ws = fixture_ws(tmp_path)
        out = rr.collect_window_events(NOW - timedelta(hours=1), ws)
        assert out["M2_traces"] == 1 and out["M2_decisions"] == 1

    def test_zero_when_empty(self, tmp_path):
        ws = fixture_ws(tmp_path)
        (ws / "state" / "rsi" / "tree_traces.jsonl").write_text("")
        out = rr.collect_window_events(NOW - timedelta(hours=1), ws)
        assert out["M2_traces"] == 0


class TestSubstrateScan:
    def test_clean_tree_no_hits(self, tmp_path):
        ws = fixture_ws(tmp_path)
        assert rr.scan_substrate(ws) == []

    def test_planted_noun_detected(self, tmp_path):
        """Negative control: a planted noun in a CORE tree must be found."""
        ws = fixture_ws(tmp_path)
        (ws / ".opencode" / "plugins" / "support" / "trees" / "bad.tree.vsm")\
            .write_text("// run it in the note" + "book panel\n")
        hits = rr.scan_substrate(ws)
        assert len(hits) == 1 and hits[0]["noun"] == "note" + "book"

    def test_live_workspace_core_is_clean(self):
        """M8 on the real workspace must be 0 (round record evidence)."""
        assert rr.scan_substrate(rr.WORKSPACE) == []


class TestVerdict:
    def _metrics(self, **over):
        base = {
            "M1": {"value": 1, "target": ">=1", "ok": True},
            "M2": {"value": 5, "target": ">0", "ok": True},
            "M3": {"value": 1.0, "target": "==1.0", "ok": True},
            "M4": {"value": 1.0, "target": "==1.0", "ok": True},
            "M5": {"value": 0, "target": "==0", "ok": True},
            "M6": {"value": 0, "target": "==0", "ok": True},
            "M7": {"value": 0, "target": "==0", "ok": True},
            "M8": {"value": 0, "target": "==0", "ok": True},
        }
        base.update(over)
        return base

    def test_all_ok_green(self):
        assert rr.verdict(self._metrics()) == ("GREEN", [])

    def test_m1_fail_not_green(self):
        m = self._metrics(M1={"value": 0, "target": ">=1", "ok": False})
        v, reasons = rr.verdict(m)
        assert v == "NOT_GREEN" and any("M1" in r for r in reasons)

    def test_m2_zero_not_green_even_if_flagged_ok(self):
        # closure rule: no green without M2>0, regardless of ok flags
        m = self._metrics(M2={"value": 0, "target": ">0", "ok": True})
        v, reasons = rr.verdict(m)
        assert v == "NOT_GREEN" and any("M2" in r for r in reasons)


class TestRunRound:
    def test_round_green_and_emitted(self, tmp_path):
        ws = fixture_ws(tmp_path)
        rec = rr.run_round(window_hours=1, run_guards=True,
                           route_fn=fake_route, guards_fn=fake_guards(),
                           workspace=ws)
        assert rec["verdict"] == "GREEN"
        assert all(rec["metrics"][f"M{i}"]["ok"] for i in range(1, 9))
        # persisted record + canonical round.closure event
        record = ws / "state" / "epistemic" / "rounds" / f"{rec['round_id']}.json"
        assert record.exists()
        events = [json.loads(l) for l in
                  (ws / "logs" / "agent_plugin.jsonl").read_text().splitlines()]
        closers = [e for e in events if e.get("event_type") == "round.closure"]
        assert len(closers) == 1
        assert closers[0]["source"] == "round-runner"
        assert closers[0]["result"] == "green"

    def test_simulate_no_learn_never_green(self, tmp_path):
        """Plan EP-5 negative control: M1=0 => closure NOT green."""
        ws = fixture_ws(tmp_path)
        rec = rr.run_round(window_hours=1, simulate_no_learn=True,
                           route_fn=fake_route, guards_fn=fake_guards(),
                           workspace=ws)
        assert rec["verdict"] == "NOT_GREEN"
        assert rec["metrics"]["M1"]["value"] == 0
        assert any("M1" in r for r in rec["reasons"])
        events = [json.loads(l) for l in
                  (ws / "logs" / "agent_plugin.jsonl").read_text().splitlines()]
        assert not [e for e in events
                    if e.get("event_type") == "round.closure"
                    and e.get("result") == "green"]

    def test_dead_guard_blocks_green(self, tmp_path):
        ws = fixture_ws(tmp_path)
        guards = fake_guards(ok=True)
        guards["liveness"] = {"G1": "dead:rc1"}
        rec = rr.run_round(window_hours=1, route_fn=fake_route,
                           guards_fn=guards, workspace=ws, emit_round=False)
        assert rec["verdict"] == "NOT_GREEN"
        assert rec["metrics"]["M4"]["ok"] is False

    def test_m8_hit_blocks_green(self, tmp_path):
        ws = fixture_ws(tmp_path)
        # non-contiguous spelling (as in the runner source) must NOT match:
        (ws / "state" / "epistemic" / "artifact.json").write_text(
            '{"x": "note" "book"}')
        assert rr.scan_substrate(ws) == []
        # a real contiguous noun in a CORE schema blocks the round:
        noun = "note" + "book"
        (ws / "state" / "epistemic" / "artifact.json").write_text(
            json.dumps({"x": f"run in the {noun}"}))
        rec = rr.run_round(window_hours=1, route_fn=fake_route,
                           guards_fn=fake_guards(), workspace=ws,
                           emit_round=False)
        assert rec["verdict"] == "NOT_GREEN"
        assert rec["metrics"]["M8"]["value"] == 1


class TestCli:
    def _canned(self, verdict: str):
        def _run(**kwargs):
            return {
                "round_id": "ROUND-canned",
                "verdict": verdict,
                "reasons": [] if verdict == "GREEN" else ["M1: forced"],
                "metrics": {f"M{i}": {"value": i} for i in range(1, 9)},
                "simulated_no_learn": kwargs.get("simulate_no_learn", False),
            }
        return _run

    def test_cli_rc0_when_green(self, monkeypatch, capsys):
        monkeypatch.setattr(rr, "run_round", self._canned("GREEN"))
        assert rr.main(["--skip-guards", "--no-emit"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["verdict"] == "GREEN"

    def test_cli_rc1_when_not_green(self, monkeypatch, capsys):
        monkeypatch.setattr(rr, "run_round", self._canned("NOT_GREEN"))
        assert rr.main(["--simulate-no-learn"]) == 1

    def test_cli_flags_reach_runner(self, monkeypatch):
        seen = {}

        def _run(**kwargs):
            seen.update(kwargs)
            return {"round_id": "x", "verdict": "GREEN", "reasons": [],
                    "metrics": {"M1": {"value": 1}}}

        monkeypatch.setattr(rr, "run_round", _run)
        rr.main(["--window-hours", "2", "--skip-guards", "--no-emit",
                 "--simulate-no-learn"])
        assert seen["window_hours"] == 2.0
        assert seen["run_guards"] is False
        assert seen["emit_round"] is False
        assert seen["simulate_no_learn"] is True


class TestLiveRounds:
    def test_live_round_records_green(self):
        """Evidence: the two EP-5 exit rounds closed GREEN (committed)."""
        rounds_dir = rr.WORKSPACE / "state" / "epistemic" / "rounds"
        records = sorted(rounds_dir.glob("ROUND-*.json"))
        assert records, "no round records emitted"
        verdicts = [json.loads(p.read_text())["verdict"] for p in records]
        assert verdicts[-2:] == ["GREEN", "GREEN"]
