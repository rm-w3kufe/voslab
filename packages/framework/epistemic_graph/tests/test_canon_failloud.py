# design: docs/plans/structural_tensions_plan_2026_10_20.vsm (T5: canon fail-loud)
"""T5 — LEDGER vs CANON inventory + fail-loud detector (plan 2026-10-20).

F1 inventory (classification of the ~12 candidates, ~25 sites reviewed
across packages/ on 2026-10-20 — the classification IS this docstring,
R9: nothing silently unclassified):

CANON — absent must be LOUD:
  - bridge._parse_tasks_vsm (TASKS.vsm): RAISE (F2 fix in bridge.py —
    the silent [] was the live=0 incident; VOSLAB_PATH poison made
    "wrong root" look like "zero tasks").
  - epistemic_graph.load_rules (hard_rules.vsm): signal = exists=False
    flag; raising would crash snapshot builders mid-write, the flag is
    the fail-visible contract (consumers must honor it).
  - epistemic_graph.load_experiments (paper_data.vsm): exists=False flag.
  - tasks_provider focus reads (current_focus.json): absence SIGNALED at
    three layers — domain omitted from list_domains() (R4-ratified test
    focus.no_file), version() stamps "<name>:absent" (L1 busts), and the
    reconciler zero-drift on missing focus is itself test-ratified.
    Blunt raising would flip three R4 specs (tests ARE the spec).
  - tasks_provider._reload_if_changed (TASKS.vsm): stat() already raises.

CANON-BOOTSTRAP (absent = first-run create; file is git-tracked, so a
  deletion surfaces as dirty — recovery + visibility without raising):
  - focus_extended.ExtendedFocusTracker._load.

CANON-SCAN (absent file inside an arbitrary-root scan = skip, by design:
  recall indexes whatever roots it is given):
  - recall._index_focus.

LEDGER — absent = empty OK. This test LOCKS that side too, so a future
  "fix" cannot turn ledgers into raisers (they would explode on first run):
  - epistemic EpicStore (claims/certs/reports jsonl), handoff
    _load_processed (handoff_ledger.jsonl), backbone/canon_bridge events,
    pleasure.jsonl, shadow.jsonl, round_runner _read_jsonl,
    evolution_report views (carry their own error= fields), delivery
    manifest audit (issue=missing fields), trace_graph, agent_results,
    derived_writers gate (stderr + rc=1 already loud), covenant_hash
    file_sha256 (generic util; promotion_plan raises = exemplar).

F3 detector: canon reader + missing file -> EXCEPTION, not []; ledger
reader + missing file -> the empty value still.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]  # packages/framework
_ROOT = _FW.parent.parent
for _p in (str(_FW), str(_ROOT / "packages" / "public" / "state-canon-mcp"),
           str(_ROOT / "packages" / "public" / "state-canon-mcp" / "instances")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from epistemic_graph import load as egl  # noqa: E402
from epistemic_graph.bridge import _parse_tasks_vsm  # noqa: E402
from vos_kernel.epistemic import EpicStore  # noqa: E402
from vos_kernel.handoff import _load_processed  # noqa: E402
from vos_kernel.utils.focus_extended import ExtendedFocusTracker  # noqa: E402


# ── CANON: missing file must raise, never return [] ─────────────────────────

def test_tasks_vsm_missing_raises():
    """The live=0 class: wrong root must FAIL, not look like zero tasks."""
    with pytest.raises(FileNotFoundError, match="CANON missing"):
        _parse_tasks_vsm(Path("/nonexistent/canon-root/TASKS.vsm"))


def test_hard_rules_absence_signalled(monkeypatch, tmp_path):
    """CANON-flag set: absence must be visible via exists=False (not silence)."""
    monkeypatch.setattr(egl, "hard_rules_path", lambda: tmp_path / "hard_rules.vsm")
    res = egl.load_rules()
    assert res["exists"] is False and res["rules"] == [], res


def test_paper_data_absence_signalled(monkeypatch, tmp_path):
    monkeypatch.setattr(egl, "paper_data_path", lambda: tmp_path / "paper_data.vsm")
    res = egl.load_experiments()
    assert res["exists"] is False and res["ids"] == [], res


def test_provider_focus_absence_signalled_not_silent(tmp_path):
    """CANON-graceful: focus absence surfaces as a missing domain + stamp."""
    from instances.tasks_provider import VsmStateProvider, _load_focus

    tasks = tmp_path / "TASKS.vsm"
    tasks.write_text(
        '@vsm 1.0\n'
        'task("ALPHA-OPEN", priority=P1, agent=ds, status=open) = {\n'
        '  what: "still open",\n'
        '}\n',
        encoding="utf-8",
    )
    # inner reader stays tolerant (ratified reconciler path)...
    assert _load_focus(tasks) == []
    # ...but the ABSENCE is loud at the provider surface:
    prov = VsmStateProvider(tasks)
    domains = prov.list_domains()
    assert "focus" not in domains and "tasks" in domains, domains
    assert "current_focus.json:absent" in prov.version("focus"), prov.version("focus")


# ── BOOTSTRAP / SCAN: documented tolerant classes, locked as-is ─────────────

def test_focus_tracker_bootstraps_empty(tmp_path):
    """First-run creator semantics: absent file -> {} entries (git-tracked)."""
    tracker = ExtendedFocusTracker(focus_file=str(tmp_path / "current_focus.json"))
    assert tracker.entries == {}


def test_recall_focus_scan_skips_absent(tmp_path):
    """Scan context: an absent file inside an arbitrary root is a skip."""
    from vos_kernel.recall import _index_focus

    items: list = []
    dropped: dict = {}
    _index_focus(tmp_path, items, dropped)  # must not raise
    assert items == []


# ── LEDGER: absent = empty OK — locked so "fixes" cannot break first run ────

def test_epistemic_store_ledger_absent_is_empty(tmp_path):
    store = EpicStore(root=tmp_path)
    assert store.load("claims") == []
    assert store.load("certs") == []


def test_handoff_ledger_absent_is_empty(tmp_path):
    assert _load_processed(tmp_path) == set()
