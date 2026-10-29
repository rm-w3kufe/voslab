# design: docs/design/sources/vsl-encoding-cycle-design-v1/vsl_encoding_cycle_design.vsm (SUT: scripts/vsl/validator/check.py)
"""Tests flake agent-plugin-log-valid rc=124 — census v2 incremental.

El census v1 firmaba el conjunto TOTAL de .gz (basename+size+mtime): cada
rotación invalidaba todo → re-parse de ~250MB retenidos (~40s frío) →
>60s bajo contención paralela de la suite → harness TimeoutExpired
(rc=124, verificado en vivo 2026-10-15). v2 memoiza POR ARCHIVO: una
rotación AGREGA un archivo → solo el nuevo se parsea.

Estos tests bloquean el contrato R10 (mismo input → mismo resultado, sin
reloj) y el incrementalismo (abre-cuenta sobre gzip.open: frío = N,
caliente = 0, rotación = 1):

  - equivalencia con re-parse ingenuo (v2 no cambia el veredicto)
  - cache v1 (whole-set) ignorada → migra, no rompe
  - cache corrupta → recompute, no crash
  - archivo eliminado → sus sources desaparecen del censo
  - determinismo: dos corridas → mismo set
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_TOOL = _REPO / "scripts" / "state" / "attestation" / "check_agent_log.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_agent_log_under_test", _TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cag = _load()


def _rot(gz: Path, sources: list[str]) -> None:
    """Write one rotated archive with a record per source."""
    with gzip.open(gz, "wt", encoding="utf-8") as fh:
        for s in sources:
            fh.write(json.dumps({
                "ts": "2026-10-15T14:52:41Z", "source": s,
                "event_type": "e", "action": "a", "result": "ok",
            }) + "\n")


def _naive(log: Path) -> set:
    """Independent re-parse of every archive (ground truth)."""
    seen: set = set()
    for f in sorted(log.parent.glob(log.name + ".*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    seen.add(json.loads(line)["source"])
    return seen


@pytest.fixture()
def log_tree(tmp_path):
    log = tmp_path / "agent_plugin.jsonl"
    log.write_text(
        json.dumps({"ts": "2026-10-15T14:52:41Z", "source": "live-src",
                    "event_type": "e", "action": "a", "result": "ok"}) + "\n",
        encoding="utf-8",
    )
    _rot(tmp_path / "agent_plugin.jsonl.1000.jsonl.gz", ["a", "b"])
    _rot(tmp_path / "agent_plugin.jsonl.1001.jsonl.gz", ["b", "c"])
    return log


def _counting_open(monkeypatch):
    """Spy: count gzip.open calls (the incrementalism contract)."""
    real = cag.gzip.open
    calls = {"n": 0}

    def spy(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(cag.gzip, "open", spy)
    return calls


def test_census_matches_naive_recompute(log_tree):
    assert cag._census_archives(str(log_tree)) == _naive(log_tree)


def test_warm_run_opens_nothing(log_tree, monkeypatch):
    cag._census_archives(str(log_tree))          # cold: builds cache
    calls = _counting_open(monkeypatch)
    out = cag._census_archives(str(log_tree))    # warm: stat-only
    assert calls["n"] == 0, "warm census must not re-open archives"
    assert out == _naive(log_tree)


def test_rotation_parses_only_new_archive(log_tree, monkeypatch):
    cag._census_archives(str(log_tree))          # caches a+b, b+c
    _rot(log_tree.parent / "agent_plugin.jsonl.1002.jsonl.gz", ["d"])
    calls = _counting_open(monkeypatch)
    out = cag._census_archives(str(log_tree))
    assert calls["n"] == 1, "only the NEW archive may be parsed"
    assert out == _naive(log_tree)
    assert "d" in out


def test_pruned_archive_drops_its_sources(log_tree):
    cag._census_archives(str(log_tree))
    (log_tree.parent / "agent_plugin.jsonl.1001.jsonl.gz").unlink()
    out = cag._census_archives(str(log_tree))
    assert out == {"a", "b"}          # c only lived in the pruned archive
    assert out == _naive(log_tree)


def test_corrupt_cache_recomputes(log_tree):
    (log_tree.parent / "agent_plugin.jsonl.census_cache").write_text(
        "{not json", encoding="utf-8")
    assert cag._census_archives(str(log_tree)) == _naive(log_tree)


def test_v1_whole_set_cache_is_ignored(log_tree):
    """v1 shape (signature+sources) must not poison v2: full reparse."""
    (log_tree.parent / "agent_plugin.jsonl.census_cache").write_text(
        json.dumps({"signature": [["stale", 1, 1]], "sources": ["POISON"]}),
        encoding="utf-8",
    )
    out = cag._census_archives(str(log_tree))
    assert out == _naive(log_tree)
    assert "POISON" not in out


def test_deterministic_r10(log_tree):
    first = cag._census_archives(str(log_tree))
    second = cag._census_archives(str(log_tree))
    assert first == second == _naive(log_tree)
