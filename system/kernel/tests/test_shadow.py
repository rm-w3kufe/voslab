"""Tests for the CC-8.1 counterfactual shadow harness (vos_kernel/shadow.py).

Negative controls included: malformed entries MUST be rejected (a shadow
that accepts garbage would rubber-stamp anything).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent
                       / "packages/framework/vos_kernel"))

import shadow  # noqa: E402


def _repo_with_commit(tmp_path: Path, filename: str = "target.txt",
                      commit_ts: str = "2026-10-03T01:00:00Z") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ,
           "GIT_AUTHOR_DATE": commit_ts, "GIT_COMMITTER_DATE": commit_ts}

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args],
                       check=True, capture_output=True,
                       env={**env, "GIT_CONFIG_GLOBAL": str(tmp_path / "gconfig"),
                            "GIT_CONFIG_SYSTEM": os.devnull})

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    (repo / filename).write_text("v1\n", encoding="utf-8")
    git("add", filename)
    git("commit", "-q", "-m", "materialize target")
    return repo


BOUNDS_OK = {"pass": True, "reasons": ["guard=G-TEST", "guard_status=live"]}
BOUNDS_BLOCK = {"pass": False, "reasons": ["guard=G-TEST", "guard_status=dead"]}


def test_record_load_roundtrip(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    entry = shadow.record("audit-findings", {"fix": "x = 1"}, BOUNDS_OK,
                          ledger=ledger, entry_id="SHD-TEST-1")
    assert entry["id"] == "SHD-TEST-1"
    assert entry["target"] is None
    loaded = shadow.load(ledger)
    assert len(loaded) == 1
    assert loaded[0]["bounds"]["pass"] is True
    assert loaded[0]["ts"].endswith("Z")


def test_record_rejects_missing_bounds(tmp_path: Path) -> None:
    """Negative control: an entry without a bounds-check must not enter."""
    ledger = tmp_path / "shadow.jsonl"
    with pytest.raises(ValueError, match="bounds"):
        shadow.record("audit-findings", {"fix": "x = 1"},
                      {"reasons": []}, ledger=ledger)


def test_record_rejects_empty_source(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    with pytest.raises(ValueError, match="source"):
        shadow.record("", {"fix": "x = 1"}, BOUNDS_OK, ledger=ledger)


def test_record_dict_action_is_canonicalized(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    entry = shadow.record("audit-findings", {"b": 2, "a": 1}, BOUNDS_OK,
                          ledger=ledger)
    assert entry["action"] == '{"a": 1, "b": 2}'  # sort_keys → deterministic id


def test_analyze_blocked_and_deterministic(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    shadow.record("s", {"fix": "would"}, BOUNDS_BLOCK, ledger=ledger,
                  entry_id="SHD-BLOCKED")
    shadow.record("s", {"fix": "ok"}, BOUNDS_OK, ledger=ledger,
                  entry_id="SHD-OK")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    a = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path)
    b = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path)
    assert a == b  # R10: same inputs → same output
    assert a["new_count"] == 2
    assert a["blocked_count"] == 1
    assert a["blocked_ids"] == ["SHD-BLOCKED"]


def test_divergence_classification(tmp_path: Path) -> None:
    """blocked-but-materialized vs aligned-executed vs would-run-not-mat."""
    # TIME-RELATIVE (2026-10-03): absolute stamps expired — with
    # cutoff = now - 1d, old=2026-10-02T12:00:00Z fell OUT of the window
    # once wall clock passed 12:00:00Z (pre-commit blocked the suite at
    # 12:2x). Windows now relative and ordering preserved:
    #   old (12h ago) < commit (6h ago) < now, all inside cutoff (1d).
    now = dt.datetime.now(dt.timezone.utc)
    commit_ts = (now - dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo = _repo_with_commit(tmp_path, commit_ts=commit_ts)
    ledger = tmp_path / "shadow.jsonl"
    old = (now - dt.timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")  # before commit
    # 1) blocked by bounds, yet materialized in reality
    shadow.record("s", {"fix": "bad"}, BOUNDS_BLOCK, target="target.txt",
                  ledger=ledger, entry_id="SHD-DIV-1")
    lines = ledger.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["ts"] = old
    ledger.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    # 2) would-run and materialized → aligned
    shadow.record("s", {"fix": "good"}, BOUNDS_OK, target="target.txt",
                  ledger=ledger, entry_id="SHD-ALIGNED")
    lines = ledger.read_text(encoding="utf-8").splitlines()
    aligned = json.loads(lines[1])
    aligned["ts"] = old
    ledger.write_text(json.dumps(entry) + "\n" + json.dumps(aligned) + "\n",
                      encoding="utf-8")

    # 3) would-run, never materialized (target never existed)
    shadow.record("s", {"fix": "future"}, BOUNDS_OK, target="ghost.txt",
                  ledger=ledger, entry_id="SHD-NOTMAT")

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    report = shadow.analyze(cutoff, ledger=ledger, repo_root=repo)
    kinds = {d["id"]: d["kind"] for d in report["divergences"]}
    assert kinds["SHD-DIV-1"] == "blocked-but-materialized"
    assert kinds["SHD-NOTMAT"] == "would-run-not-materialized"
    assert "SHD-ALIGNED" not in kinds  # aligned, not a divergence
    assert report["aligned_count"] == 1


def test_analyze_unverifiable_without_git(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    shadow.record("s", {"fix": "x"}, BOUNDS_OK, target="t.txt",
                  ledger=ledger, entry_id="SHD-NOGIT")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    report = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path)
    assert report["divergences"][0]["kind"] == "unverifiable"


def test_collect_shadow_reads_live_ledger() -> None:
    """Integration: evolution_report.collect_shadow over the real workspace."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent
                            / "packages/framework/vos_kernel"))
    import evolution_report as er
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    report = er.collect_shadow(cutoff)
    assert "error" not in report
    assert report["total"] >= 50  # live ledger seeded by shadow_cycle


# ── CC-8.1(b)+(c) — explanation machinery + execution-record semantics ──


def _gap_log_write(path: Path, rows: list[tuple[str, str, str, bool]]) -> None:
    """rows: (gapId, decision, iso_ts, autoExecuted)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for gap, decision, ts, executed in rows:
            fh.write(json.dumps({
                "gapId": gap, "decision": decision, "timestamp": ts,
                "autoExecuted": executed, "actions": ["OK"],
                "home": decision, "trigger": "test", "truth": "TRUE",
            }) + "\n")


def test_gap_execution_semantics(tmp_path: Path) -> None:
    """CC-8.1(c): gap entries judged by autoExecuted, not file git noise."""
    ledger = tmp_path / "shadow.jsonl"
    now = dt.datetime.now(dt.timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        ("g1", "OK_DIR", ts, False),   # would-run, not executed -> deferred
        ("g2", "UNKNOWN", ts, False),  # blocked, not executed -> aligned
        ("g3", "ERROR", ts, True),     # blocked, yet EXECUTED -> alarm
    ]
    # g4: would-run with NO log row -> unverifiable
    shadow.record("gap-resolver", {"gap": "g1", "decision": "OK_DIR",
                                   "actions": ["OK"]}, BOUNDS_OK,
                  target="t.py", ledger=ledger, entry_id="SHD-G1")
    shadow.record("gap-resolver", {"gap": "g2", "decision": "UNKNOWN",
                                   "actions": ["OK"]}, BOUNDS_BLOCK,
                  target="t.py", ledger=ledger, entry_id="SHD-G2")
    shadow.record("gap-resolver", {"gap": "g3", "decision": "ERROR",
                                   "actions": ["OK"]}, BOUNDS_BLOCK,
                  target="t.py", ledger=ledger, entry_id="SHD-G3")
    shadow.record("gap-resolver", {"gap": "g4", "decision": "OK_DIR",
                                   "actions": ["OK"]}, BOUNDS_OK,
                  target="t.py", ledger=ledger, entry_id="SHD-G4")
    gap_log = tmp_path / "gap-resolution.jsonl"
    _gap_log_write(gap_log, rows)
    cutoff = now - dt.timedelta(hours=1)
    report = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path,
                            gap_log=gap_log)
    kinds = {d["id"]: d["kind"] for d in report["divergences"]}
    assert kinds["SHD-G1"] == "would-run-deferred"
    assert kinds["SHD-G3"] == "blocked-but-executed"   # the real alarm
    assert kinds["SHD-G4"] == "unverifiable"
    assert "SHD-G2" not in kinds                       # aligned-blocked
    assert report["kind_counts"]["aligned-blocked"] == 1
    assert report["divergences_unexplained"] == 3


def test_explanations_class_and_id(tmp_path: Path) -> None:
    """CC-8.1(b): class rules explain classes; exact-id rules beat them."""
    ledger = tmp_path / "shadow.jsonl"
    now = dt.datetime.now(dt.timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    shadow.record("gap-resolver", {"gap": "g1", "decision": "OK_DIR",
                                   "actions": ["OK"]}, BOUNDS_OK,
                  target="t.py", ledger=ledger, entry_id="SHD-DEFER")
    shadow.record("gap-resolver", {"gap": "g3", "decision": "ERROR",
                                   "actions": ["OK"]}, BOUNDS_BLOCK,
                  target="t.py", ledger=ledger, entry_id="SHD-ALARM")
    shadow.record("gap-resolver", {"gap": "g9", "decision": "OK_DIR",
                                   "actions": ["OK"]}, BOUNDS_OK,
                  target="t.py", ledger=ledger, entry_id="SHD-SPECIAL")
    gap_log = tmp_path / "gap-resolution.jsonl"
    _gap_log_write(gap_log, [
        ("g1", "OK_DIR", ts, False),
        ("g3", "ERROR", ts, True),
        ("g9", "OK_DIR", ts, False),
    ])
    expl = tmp_path / "divergence_explanations.jsonl"
    expl.write_text("\n".join([
        json.dumps({"rule_id": "RX-CLASS", "match": {"kind": "would-run-deferred",
                   "source": "gap-resolver"}, "explanation": "semi-auto deferral"}),
        json.dumps({"rule_id": "RX-ID", "id": "SHD-SPECIAL",
                   "explanation": "specific id rule"}),
        json.dumps({"rule_id": "RX-BROKEN"}),          # no explanation -> skipped
        json.dumps({"rule_id": "RX-EMPTY", "match": {},                  # empty match -> skipped
                   "explanation": "nothing to match"}),
    ]) + "\n", encoding="utf-8")
    cutoff = now - dt.timedelta(hours=1)
    report = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path,
                            gap_log=gap_log, explanations=expl)
    by_id = {d["id"]: d for d in report["divergences"]}
    assert by_id["SHD-DEFER"]["explained"] is True
    assert by_id["SHD-DEFER"]["explained_by"] == "class:RX-CLASS"
    # id rule wins over the class rule that also matches
    assert by_id["SHD-SPECIAL"]["explained"] is True
    assert by_id["SHD-SPECIAL"]["explained_by"] == "id:RX-ID"
    # blocked-but-executed has NO rule on purpose -> stays unexplained (alarm)
    assert by_id["SHD-ALARM"]["explained"] is False
    assert report["divergences_explained"] == 2
    assert report["divergences_unexplained"] == 1


def test_explanations_validation(tmp_path: Path) -> None:
    """Negative control: rules that explain nothing must not count."""
    expl = tmp_path / "expl.jsonl"
    expl.write_text("\n".join([
        json.dumps({"rule_id": "RX-NO-EXPL", "id": "X"}),            # no explanation
        json.dumps({"explanation": "no rule_id", "id": "X"}),        # no rule_id
        json.dumps({"rule_id": "RX-NO-MATCH", "explanation": "hi"}),  # neither id nor match
        json.dumps({"rule_id": "RX-OK", "id": "X", "explanation": "ok"}),
        "not-json-at-all",
    ]) + "\n", encoding="utf-8")
    rules = shadow.load_explanations(expl)
    assert [r["rule_id"] for r in rules] == ["RX-OK"]
