"""Tests for the O-6 trajectory distill (R-3, propose-only) — §6.2.

Hermetic (VOSLAB_PATH fixtures — never production logs/ or
state/distill/). The K5 hard limit is under test: the ONLY write
targets a full run may touch are candidates.jsonl and the archive
feature cache.
"""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

VOS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VOS_ROOT / "scripts" / "state" / "monitoring"))

import log_distill as ld  # noqa: E402

DISTILL = VOS_ROOT / "scripts" / "state" / "monitoring" / "log_distill.py"


# ── fixtures ────────────────────────────────────────────────────────────────

def _rec(source="tool-integration", event_type="tool.execute.after",
         event_id="e1", action="tool: bash git status", result="ok",
         detail="", cls="operational", ts="2026-10-07T01:00:00+00:00",
         session_id=None, duration_ms=None) -> dict:
    r = {"ts": ts, "pid": 1, "level": "activation", "source": source,
         "event_type": event_type, "event_id": event_id, "action": action,
         "result": result, "detail": detail, "class": cls}
    if session_id:
        r["session_id"] = session_id
    if duration_ms is not None:
        r["duration_ms"] = duration_ms
    return r


def _root_with(tmp: Path, live: list[dict] | None = None,
               archives: dict[str, list[dict]] | None = None) -> Path:
    root = tmp / "vos"
    (root / "logs").mkdir(parents=True, exist_ok=True)
    if live is not None:
        (root / "logs" / ld.LOG_NAME).write_text(
            "\n".join(json.dumps(r) for r in live) + "\n", encoding="utf-8")
    for name, recs in (archives or {}).items():
        payload = ("\n".join(json.dumps(r) for r in recs) + "\n").encode("utf-8")
        with gzip.open(root / "logs" / name, "wb") as fh:
            fh.write(payload)
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOSLAB_PATH": str(root)}
    return subprocess.run([sys.executable, str(DISTILL), "--json", *args],
                          capture_output=True, text=True, timeout=60, env=env)


# ── schema normalization + extraction (pure) ───────────────────────────────

def test_normalize_dual_schema_a_and_b():
    a = {"ts": "2026-08-01T00:00:00+00:00", "instrument": "old-thing",
         "hook": "write", "action": "x", "result": "ok"}
    na = ld.normalize(a)
    assert na["source"] == "old-thing" and na["event_type"] == "write"
    b = _rec()
    nb = ld.normalize(b)
    assert nb["source"] == "tool-integration"
    assert nb["event_type"] == "tool.execute.after"


def test_extract_counts_and_excludes_test_class():
    recs = [
        _rec(event_id="1", action="tool: bash git status"),
        _rec(event_id="2", action="tool: bash git status"),
        _rec(event_id="3", action="tool: read foo.vsm", cls="test"),
    ]
    f = ld.extract(recs)
    assert f["records"] == 2 and f["test_excluded"] == 1
    assert f["tool_freq"] == {"bash": 2}  # class=test "read" excluded
    assert f["cmd_heads"]["git status"] == 2


def test_fanout_vs_collision_split():
    # true fan-out: same id, two sources
    multi = [_rec(source="a", event_id="X"), _rec(source="b", event_id="X")]
    # collision: same id, same source (second-grain id)
    single = [_rec(source="c", event_id="Y", ts="2026-10-07T01:00:01+00:00"),
              _rec(source="c", event_id="Y", ts="2026-10-07T01:00:02+00:00")]
    rep = ld._events_report(ld.extract(multi + single)["fanout"])
    assert rep["fanout_groups"] == 1 and rep["collision_groups"] == 1
    assert rep["fanout_top"][0][0] == "X"
    assert sorted(rep["fanout_top"][0][2]) == ["a", "b"]


def test_is_failure_excludes_evaluate_false_and_evidence():
    ev = _rec(source="rsi-cycle", event_type="evaluate.evaluate",
              result="error", detail='{"truth": FALSE}')
    assert ld._is_failure(ld.normalize(ev)) is False
    tool_err = _rec(result="error", detail="boom stderr")
    assert ld._is_failure(ld.normalize(tool_err)) is True
    ok = _rec()
    assert ld._is_failure(ld.normalize(ok)) is False
    # evidence-style JSON detail never becomes an error signature
    ev2 = _rec(source="x", result="error", detail='{"a": 1}')
    assert ld._error_sig("x", ld.normalize(ev2)) is None


def test_merge_associative_with_extract():
    # both units group the id internally (n≥2 → stored) → sums are exact:
    # merge == extract(concat).
    a = [_rec(event_id="1", action="tool: bash ls"),
         _rec(event_id="1", source="other"),
         _rec(event_id="2")]
    b = [_rec(event_id="3", action="tool: bash ls"),
         _rec(event_id="1", source="third", result="error", detail="e"),
         _rec(event_id="1", source="third")]
    left = ld.merge(ld.extract(a), ld.extract(b))
    right = ld.extract(a + b)
    assert left["records"] == right["records"] == 6
    assert left["errors"] == right["errors"] == 1
    assert left["tool_freq"] == right["tool_freq"]
    assert left["fanout"]["1"]["n"] == right["fanout"]["1"]["n"] == 4
    assert sorted(left["fanout"]["1"]["sources"]) == \
        sorted(right["fanout"]["1"]["sources"])
    # ids seen once per unit but twice globally: NOT grouped (documented
    # unit-local limitation — report-only stat, candidates unaffected)
    c1 = ld.extract([_rec(event_id="z", source="s1")])
    c2 = ld.extract([_rec(event_id="z", source="s2")])
    assert ld.merge(c1, c2)["fanout"] == {}
    assert ld.extract([_rec(event_id="z", source="s1"),
                       _rec(event_id="z", source="s2")])["fanout"]["z"]["n"] == 2


# ── candidates (propose-only) ───────────────────────────────────────────────

def test_propose_thresholds_deterministic():
    sig = "src|boom"
    below = ld._empty_features()
    below["error_sigs"][sig] = {"n": ld.MIN_ERROR_SIG - 1,
                                "examples": [], "sources": {"src": 1}}
    assert ld.propose(below) == []
    above = ld._empty_features()
    above["error_sigs"][sig] = {"n": ld.MIN_ERROR_SIG,
                                "examples": ["e1"], "sources": {"src": 1}}
    out = ld.propose(above)
    assert len(out) == 1 and out[0]["kind"] == "error_pattern"
    assert out[0]["status"] == "proposed"
    # R10: same features → same ids, same order
    assert [c["id"] for c in out] == [c["id"] for c in ld.propose(above)]


def test_propose_session_health_rate_gate():
    f = ld._empty_features()
    f["days"]["2026-10-07"] = {"n": 10, "err": 4, "dur_sum": 0, "dur_n": 0,
                               "sources": {"s": 10}}  # 40% but only 4 errs
    assert ld.propose(f) == []
    f["days"]["2026-10-07"]["err"] = ld.MIN_SESSION_ERRORS
    kinds = [c["kind"] for c in ld.propose(f)]
    assert kinds == ["session_health"]


# ── CLI end-to-end (hermetic) ───────────────────────────────────────────────

def _err_live(n: int = ld.MIN_ERROR_SIG) -> list[dict]:
    # spread across 3 days (4/4/2 errs each < MIN_SESSION_ERRORS) so the
    # fixture yields exactly ONE candidate (error_pattern), not
    # session_health — keeps idempotency/veto assertions crisp.
    days = (["2026-10-05"] * 4 + ["2026-10-06"] * 4 + ["2026-10-07"] * 2)
    return [_rec(event_id=f"e{i}", result="error",
                 detail="ConnectionError: boom at /tmp/x",
                 ts=f"{days[i % len(days)]}T01:00:{i % 60:02d}+00:00")
            for i in range(n)]


def test_cli_proposes_idempotently(tmp_path):
    root = _root_with(tmp_path, live=_err_live())
    proc = _run(root)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["propose_only"] is True
    assert report["input"]["live_records"] == ld.MIN_ERROR_SIG
    assert len(report["candidates"]["new"]) == 1
    cand = root / "state" / "distill" / "candidates.jsonl"
    lines_1 = cand.read_text(encoding="utf-8").splitlines()
    assert len(lines_1) == 1
    assert json.loads(lines_1[0])["status"] == "proposed"
    # second run: idempotent — no duplicate line
    proc2 = _run(root)
    assert proc2.returncode == 0
    assert json.loads(proc2.stdout)["candidates"]["new"] == []
    assert cand.read_text(encoding="utf-8").splitlines() == lines_1


def test_cli_respects_s5_veto(tmp_path):
    root = _root_with(tmp_path, live=_err_live())
    cand = root / "state" / "distill" / "candidates.jsonl"
    # pre-seed a rejected candidate with the id this fixture will produce
    seed = ld.propose(ld.extract(_err_live()))[0]
    seed["status"] = "rejected"
    cand.parent.mkdir(parents=True, exist_ok=True)
    cand.write_text(json.dumps(seed) + "\n", encoding="utf-8")
    proc = _run(root)
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["candidates"]["new"] == []  # never re-proposed
    assert "rejected" in cand.read_text(encoding="utf-8")


def test_cli_dry_run_writes_nothing(tmp_path):
    root = _root_with(tmp_path, live=_err_live())
    proc = _run(root, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["dry_run"] is True
    assert len(report["candidates"]["new"]) == 1
    assert not (root / "state" / "distill" / "candidates.jsonl").exists()


def test_cli_archives_cache_miss_then_hit(tmp_path):
    live = [_rec(event_id="1")]
    arch = {"agent_plugin.jsonl.1790000000000.jsonl.gz":
            [_rec(event_id=f"a{i}", ts=f"2026-10-0{i % 6 + 1}T00:00:00+00:00")
             for i in range(5)]}
    root = _root_with(tmp_path, live=live, archives=arch)
    first = json.loads(_run(root).stdout)
    assert first["input"]["cache"] == "miss"
    assert first["input"]["archives"] == 1
    assert first["input"]["archive_records"] == 5
    second = json.loads(_run(root).stdout)
    assert second["input"]["cache"] == "hit"
    # archive mtime change → recompute
    arc = root / "logs" / "agent_plugin.jsonl.1790000000000.jsonl.gz"
    os.utime(arc, (1790000099, 1790000099))
    third = json.loads(_run(root).stdout)
    assert third["input"]["cache"] == "miss"


def test_cli_schema_a_archives_counted(tmp_path):
    a_rec = {"ts": "2026-08-01T00:00:00+00:00", "pid": 1,
             "instrument": "vsf-agent-vsl-gate", "hook": "write",
             "action": "gate write", "result": "ok"}
    root = _root_with(tmp_path, live=[],
                      archives={"agent_plugin.jsonl.1789000000000.jsonl.gz":
                                [a_rec, a_rec]})
    report = json.loads(_run(root).stdout)
    assert report["input"]["archive_records"] == 2
    # A-normalized source participates in fanout (same event_id empty → no id)
    assert report["input"]["live_records"] == 0


def test_cli_rc_contract_and_bad_top(tmp_path):
    root = _root_with(tmp_path, live=[])
    assert _run(root).returncode == 0
    env = {**os.environ, "VOSLAB_PATH": str(root)}
    bad = subprocess.run([sys.executable, str(DISTILL), "--json", "--top", "0"],
                         capture_output=True, text=True, timeout=30, env=env)
    assert bad.returncode == 2


def test_cli_empty_root_graceful(tmp_path):
    root = tmp_path / "empty"
    (root / "logs").mkdir(parents=True)
    report = json.loads(_run(root).stdout)
    assert report["input"]["live_records"] == 0
    assert report["candidates"]["new"] == []
    assert not (root / "state").exists()


# ── K5 hard limit (write set) ───────────────────────────────────────────────

def test_k5_safe_write_rejects_skills(tmp_path):
    with pytest.raises(PermissionError):
        ld._safe_write(Path("/tmp/learned-skill.vsm"), "x")
    with pytest.raises(PermissionError):
        ld._safe_append(Path("predicados.jsonl"), ["{}"])
    # allowed names pass the guard (paths arbitrary)
    ok = tmp_path / "candidates.jsonl"
    ld._safe_append(ok, ['{"id": "x"}'])
    assert json.loads(ok.read_text(encoding="utf-8"))["id"] == "x"


def test_k5_full_run_write_set(tmp_path):
    """After a real run the only new files are candidates + cache."""
    root = _root_with(tmp_path, live=_err_live(),
                      archives={"agent_plugin.jsonl.1790000000000.jsonl.gz":
                                _err_live(ld.MIN_ERROR_SIG)})
    before = {p.relative_to(root) for p in root.rglob("*") if p.is_file()}
    assert _run(root).returncode == 0
    after = {p.relative_to(root) for p in root.rglob("*") if p.is_file()}
    created = after - before
    assert created == {Path("state/distill/candidates.jsonl"),
                       Path("logs/agent_plugin.jsonl.distill_cache")}


def test_write_allowed_constant_is_k5():
    assert ld.WRITE_ALLOWED == {"candidates.jsonl",
                                f"{ld.LOG_NAME}.distill_cache"}
