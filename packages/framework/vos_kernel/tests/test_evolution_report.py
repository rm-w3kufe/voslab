"""Tests for A-3 / CC-8.0 — evolution report generator (presentation layer).

The presentation layer is PART OF the system under test (CC-8
constraints) — it gets battery'd too (anti-pantomima).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from vos_kernel import evolution_report as er


@pytest.fixture
def fixture_ws(tmp_path, monkeypatch):
    """Minimal workspace: ledgers + focus + snapshots + reports dir."""
    ws = tmp_path / "ws"
    epi = ws / "state" / "epistemic"
    epi.mkdir(parents=True)
    (ws / "state" / "rsi" / "snapshots").mkdir(parents=True)
    (epi / "decisions.jsonl").write_text(
        json.dumps({"id": "D-old", "ts": "2026-01-01T00:00:00Z"}) + "\n"
        + json.dumps({"id": "D-new", "ts": "2026-12-31T23:59:59Z"}) + "\n"
        + json.dumps({"id": "D-no-ts"}) + "\n",
        encoding="utf-8",
    )
    (epi / "findings.jsonl").write_text(
        json.dumps({"id": "F1", "ts": "2026-12-31T10:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    (ws / "current_focus.json").write_text(json.dumps([
        {"ref": "alpha", "status": "active",
         "note": "n", "started_at": "2026-12-01T00:00:00Z",
         "updated_at": "2026-12-31T22:00:00Z"},
        {"ref": "beta", "status": "done",
         "note": "n", "started_at": "2026-11-01T00:00:00Z",
         "updated_at": "2026-11-15T00:00:00Z"},
    ]), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "-C", str(ws), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(ws), "config", "user.name", "t"], check=True)
    (ws / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(ws), "add", "."], check=True)
    subprocess.run(["git", "-C", str(ws), "commit", "-qm", "fixture commit"], check=True)

    reports = epi / "reports"
    reports.mkdir()
    monkeypatch.setattr(er, "EPISTEMIC_DIR", epi)
    monkeypatch.setattr(er, "REPORTS_DIR", reports)
    monkeypatch.setattr(er, "FOCUS_PATH", ws / "current_focus.json")
    monkeypatch.setattr(er, "SNAPSHOTS_DIR", ws / "state" / "rsi" / "snapshots")
    monkeypatch.setattr(er, "WORKSPACE", ws)
    return ws


def _cut(s: str = "2026-12-01T00:00:00Z") -> str:
    return s


class TestParseTs:
    def test_zulu(self):
        assert er._parse_ts("2026-10-01T14:07:22Z") is not None

    def test_garbage(self):
        assert er._parse_ts("not-a-date") is None

    def test_non_string(self):
        assert er._parse_ts(42) is None


class TestLedgers:
    def test_filters_by_ts_and_counts_no_ts(self, fixture_ws):
        led = er.collect_ledger("decisions", "ts", er._parse_ts(_cut()))
        assert led["total"] == 3
        assert led["new_count"] == 1
        assert led["new"][0]["id"] == "D-new"
        assert led["no_ts"] == 1

    def test_missing_ledger_is_honest_error(self, fixture_ws):
        led = er.collect_ledger("certs", "observed_at", er._parse_ts(_cut()))
        assert led["error"] == "missing ledger"


class TestGit:
    def test_commits_since_cutoff(self, fixture_ws):
        out = er.collect_git(fixture_ws, er._parse_ts("2020-01-01T00:00:00Z"))
        assert out.get("error") is None
        assert len(out["commits"]) == 1
        assert "fixture commit" in out["commits"][0]["subject"]

    def test_no_commits_since_future(self, fixture_ws):
        # NB: git approxidate mishandles year 2999 (returns everything) —
        # 2099 filters correctly and still proves the cutoff works.
        out = er.collect_git(fixture_ws, er._parse_ts("2099-01-01T00:00:00Z"))
        assert out["commits"] == []


class TestFocus:
    def test_active_and_changed(self, fixture_ws):
        out = er.collect_focus(er._parse_ts(_cut()))
        assert out["active"] == ["alpha"]
        assert [c["ref"] for c in out["changed_since"]] == ["alpha"]
        assert out["entries"] == 2


class TestRender:
    def test_sections_and_determinism(self, fixture_ws):
        report = er.collect(since=_cut(), workspace=fixture_ws)
        md1 = er.render_md(report)
        for heading in ("# Evolution report", "## Commits since", "## Ledgers",
                        "## Focus", "## Snapshots", "## Battery", "## Drift",
                        "## PLEASURE (G-34) — placer estadistico",
                        "## Delta vs previous"):
            assert heading in md1
        assert er.render_md(report) == md1


class TestMain:
    def test_writes_three_artifacts(self, fixture_ws, capsys):
        out_dir = fixture_ws / "state" / "epistemic" / "reports"
        rc = er.main(["--since", _cut(),
                      "--workspace", str(fixture_ws),
                      "--out-dir", str(out_dir)])
        assert rc == 0
        files = {p.name for p in out_dir.iterdir()}
        assert "evolution_latest.json" in files
        assert "EVOLUTION.md" in files
        assert any(f.startswith("evolution_20") for f in files)

    def test_second_run_reports_delta_vs_previous(self, fixture_ws):
        out_dir = fixture_ws / "state" / "epistemic" / "reports"
        argv = ["--since", _cut(), "--workspace", str(fixture_ws),
                "--out-dir", str(out_dir)]
        assert er.main(argv) == 0
        # ledger grows between runs
        epi = fixture_ws / "state" / "epistemic"
        with (epi / "decisions.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "D-extra", "ts": "2026-12-31T23:59:59Z"}) + "\n")
        assert er.main(argv) == 0
        latest = json.loads((out_dir / "evolution_latest.json").read_text())
        delta = latest["delta_vs_previous"]
        assert delta is not None
        assert delta["ledger_total_delta"]["decisions"] == 1

    def test_invalid_since_rc2(self, fixture_ws, capsys):
        rc = er.main(["--since", "banana", "--workspace", str(fixture_ws),
                      "--stdout"])
        assert rc == 2


class TestPleasure:
    """G-34 P4 — seccion PLEASURE del evolution report (narrativa S5)."""

    @staticmethod
    def _write_ledger(ws: Path, rows: list[dict]) -> None:
        rsi = ws / "state" / "rsi"
        rsi.mkdir(parents=True, exist_ok=True)
        (rsi / "pleasure.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8")

    def test_section_present_counts_and_determinism(self, fixture_ws):
        self._write_ledger(fixture_ws, [
            {"ts": "2026-12-20T10:00:00Z", "unit": "gate_run", "success": True,
             "streak": 3, "detail": "80/80",
             "emissions": [{"kind": "milestone", "magnitude": 4.2,
                            "magnitude_unit": "bits", "streak": 3}]},
            {"ts": "2026-12-21T10:00:00Z", "unit": "gate_run", "success": True,
             "streak": 4, "detail": "81/81",
             "emissions": [{"kind": "rpe", "magnitude": 0.5,
                            "magnitude_unit": "rpe"}]},
            {"ts": "2026-12-22T10:00:00Z", "unit": "session_close",
             "success": False, "streak": 0, "detail": "dirty", "emissions": []},
        ])
        rep1 = er.collect(since=_cut(), workspace=fixture_ws)
        rep2 = er.collect(since=_cut(), workspace=fixture_ws)
        pl = rep1["pleasure"]
        assert pl.get("error") is None
        assert pl["events"] == 3 and pl["successes"] == 2
        assert pl["emissions"] == 2
        assert pl["emissions_by_kind"] == {"milestone": 1, "rpe": 1}
        assert pl["milestones"] == 1
        assert pl["total_magnitude"] == 4.7
        assert pl["units"] == ["gate_run", "session_close"]
        assert pl["current_streaks"] == {"gate_run": 4, "session_close": 0}
        assert len(pl["samples"]) == 2
        assert rep1["pleasure"] == rep2["pleasure"]          # R10 determinismo
        md = er.render_md(rep1)
        assert "## PLEASURE (G-34)" in md
        assert "milestone 4.2" in md
        assert er.render_md(rep2) == md

    def test_cutoff_filters_old_events(self, fixture_ws):
        self._write_ledger(fixture_ws, [
            {"ts": "2026-01-01T00:00:00Z", "unit": "gate_run", "success": True,
             "streak": 1, "detail": "old", "emissions": []},
            {"ts": "2026-12-31T10:00:00Z", "unit": "gate_run", "success": True,
             "streak": 2, "detail": "new", "emissions": []},
        ])
        pl = er.collect_pleasure(er._parse_ts(_cut()), fixture_ws)
        # solo el evento nuevo sobrevive al cutoff (streak 2, no 1)
        assert pl["events"] == 1
        assert pl["current_streaks"] == {"gate_run": 2}

    def test_missing_canal_is_empty_not_error(self, fixture_ws):
        # fixture_ws no crea pleasure.jsonl — canal aun no emite
        pl = er.collect_pleasure(er._parse_ts(_cut()), fixture_ws)
        assert pl["error"] is None
        assert pl["events"] == 0 and pl["emissions"] == 0

    def test_corrupt_line_skipped_honest(self, fixture_ws):
        rsi = fixture_ws / "state" / "rsi"
        (rsi / "pleasure.jsonl").write_text(
            "not-json\n"
            + json.dumps({"ts": "2026-12-30T10:00:00Z", "unit": "evaluate",
                          "success": True, "streak": 1, "detail": "ok",
                          "emissions": []}) + "\n",
            encoding="utf-8")
        pl = er.collect_pleasure(er._parse_ts(_cut()), fixture_ws)
        assert pl["error"] is None and pl["events"] == 1


class TestLiveWorkspace:
    def test_live_collect_runs_on_real_workspace(self):
        """Live smoke: the real workspace produces every section (R10)."""
        report = er.collect(since="2026-01-01T00:00:00Z")
        assert set(report) >= {"git", "ledgers", "focus", "snapshots",
                               "battery", "journal", "fingerprint"}
        assert report["git"].get("error") is None
        assert len(report["git"]["commits"]) >= 1
        assert report["focus"]["entries"] >= 1
        assert "verdict" in report["battery"] or "error" in report["battery"]
