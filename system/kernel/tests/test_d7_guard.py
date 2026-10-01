"""D-07 live check — --d7 refuses a false clean (system_backlog.vsm, 2026-10-01).

The debt: CORPUS pointed at the local mirror (1 doc after the archive
migration), so `symbol_table.py --d7` printed "0 in 0 documents" and
exited 0 on an empty tree — a pass that meant "nothing was scanned".
The fix repoints CORPUS at the live upstream corpus (env `D7_CORPUS`
overrides) and makes an empty/missing corpus exit 2 instead of 0.

These are the negative controls: a corpus that yields 0 documents must
NOT be reported as clean, whatever path is used.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
SCRIPT = VOSLAB / "scripts" / "vsl" / "parser" / "symbol_table.py"


def _run_d7(corpus: str) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ, D7_CORPUS=corpus)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--d7"],
        capture_output=True, text=True, timeout=120, env=env, cwd=VOSLAB,
    )


def test_empty_corpus_refuses_clean():
    """An existing-but-empty corpus must exit 2, not 0."""
    with tempfile.TemporaryDirectory() as d:
        r = _run_d7(d)
    assert r.returncode == 2, f"empty corpus reported rc={r.returncode}: {r.stdout}"
    assert "refusing to report clean" in r.stdout


def test_missing_corpus_refuses_clean():
    """A nonexistent corpus path must exit 2, not 0 (rglob yields nothing)."""
    r = _run_d7("/no/such/d7/corpus")
    assert r.returncode == 2, f"missing corpus reported rc={r.returncode}: {r.stdout}"
    assert "D7 — corpus empty" in r.stdout
