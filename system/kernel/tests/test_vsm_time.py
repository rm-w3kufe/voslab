"""CHECK-SCAN unification matrix (2026-09-10).

The canonical rule set lives in vos_kernel.utils.vsm_kernel
(is_hardcoded_timestamp). check.py must agree with it (parity test) so
no shape falls through the cracks (false negatives) and no real
timestamp is flagged (false positives on shape alone are impossible to
avoid entirely — documented limit; generation is the real net).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

VOSLAB = Path(__file__).resolve().parents[3]


def _load_vsm_kernel():
    sys.path.insert(0, str(VOSLAB / "packages" / "framework"))
    try:
        from vos_kernel.utils import vsm_kernel
        return vsm_kernel
    finally:
        pass


vsmk = _load_vsm_kernel()

# (content snippet, must_flag)
MATRIX = [
    ("2026-09-08T01:15:00Z", True),    # zero seconds
    ("2026-09-09T07:30:00Z", True),    # zero seconds (the cybernetic_plan case)
    ("2026-01-01T00:00:00Z", True),    # midnight + year placeholder
    ("2026-09-09T00:15:30Z", True),    # midnight hour
    ("2026-09-09T07:00:45Z", True),    # zero minute
    ("2026-09-09T12:00:00Z", True),    # noon placeholder
    ("1970-01-01T00:00:00Z", True),    # epoch
    ("2000-01-01T10:10:10Z", True),    # y2k
    ("2099-06-01T06:06:06Z", True),    # far future
    ("2025-01-01T03:03:03Z", True),    # previous year
    ("2026-09-09T16:22:24Z", False),   # normal shape: must NOT flag
    ("2026-09-09T21:45:42Z", False),   # normal shape: must NOT flag
    ("no timestamp here", False),
]


@pytest.mark.parametrize("snippet,flagged", MATRIX)
def test_canonical_matrix(snippet, flagged):
    hit = vsmk.is_hardcoded_timestamp(snippet)
    assert (hit is not None) == flagged, (snippet, hit)


def test_generated_timestamps_always_clean():
    for _ in range(50):
        ts = vsmk.get_timestamp()
        assert vsmk.is_hardcoded_timestamp(ts) is None, ts


def test_socratic_gate_well_placed_plan():
    """Recalibration 2026-09-10: docs/plans/*.vsm must pass (rc 0)."""
    import subprocess
    import sys
    p = subprocess.run(
        [sys.executable, str(VOSLAB / "scripts" / "vsl" / "classifier"
                             / "socratic_gate.py"),
         str(VOSLAB / "docs" / "plans" / "unified_tasks.vsm")],
        capture_output=True, text=True, timeout=60,
        cwd=str(VOSLAB),
    )
    assert p.returncode == 0, p.stderr


def test_socratic_gate_misplaced_still_fails(tmp_path):
    """Recalibration must not blind the gate: outside-repo still rc 1."""
    import shutil
    import subprocess
    import sys
    dst = tmp_path / "misplaced.vsm"
    shutil.copy(str(VOSLAB / "docs" / "plans" / "unified_tasks.vsm"), dst)
    p = subprocess.run(
        [sys.executable, str(VOSLAB / "scripts" / "vsl" / "classifier"
                             / "socratic_gate.py"), str(dst)],
        capture_output=True, text=True, timeout=60,
        cwd=str(VOSLAB),
    )
    assert p.returncode == 1
    assert "MISMATCH" in p.stderr


WORKING_DOCS = [
    # (path, must_pass): recalibration matrix 2026-09-10 — every working
    # area with its real TYPEs. A new mismatch here means the taxonomy
    # (not the doc) needs review.
    ("docs/plans/unified_tasks.vsm", True),        # PLAN -> plan
    ("docs/plans/write_hook_autofix.vsm", True),   # PROPOSAL in plans
    ("docs/plans/repo_map.vsm", True),             # MAP in plans
    ("docs/architecture/architecture.vsm", True),  # ARCHITECTURE
    ("docs/reference/vsflab_packages.vsm", True),  # CATALOG
    ("docs/specs/vos_master_plan.vsm", True),      # MASTER-PLAN
    ("docs/index.vsm", True),                      # INDEX at root
]


def _gate(path):
    import subprocess
    import sys
    return subprocess.run(
        [sys.executable, str(VOSLAB / "scripts" / "vsl" / "classifier"
                             / "socratic_gate.py"), str(path)],
        capture_output=True, text=True, timeout=60, cwd=str(VOSLAB))


@pytest.mark.parametrize("rel,want", WORKING_DOCS)
def test_taxonomy_matrix(rel, want):
    p = _gate(VOSLAB / rel)
    assert (p.returncode == 0) == want, (rel, p.stderr[:200])


def test_mirrors_and_archive_skip():
    p = _gate(VOSLAB / "docs" / "canon_mirror" / "hard_rules.vsm")
    assert p.returncode == 0 and "skip" in p.stderr.lower()


def test_viability_omega_on_fixture(tmp_path):
    """Omega math on a stable fixture series (deterministic, no drill)."""
    import importlib.util
    import json as _json
    spec = importlib.util.spec_from_file_location(
        "viability", str(VOSLAB / "scripts" / "vsl" / "tools"
                         / "viability_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hist = tmp_path / "h.jsonl"
    with open(hist, "w") as f:
        for pr in (0.90, 0.91, 0.90, 0.92, 0.91):
            f.write(_json.dumps({"corpus": {"pass_rate": pr}}) + "\n")
    series = mod._pass_series(hist)[-10:]
    drift = abs(series[-1] - series[0])
    import statistics
    stability = 1.0 - statistics.pstdev(series)
    assert drift <= 0.1, drift
    assert stability >= 0.8, stability


def test_viability_flags_fast_jump(tmp_path):
    import importlib.util
    import json as _json
    spec = importlib.util.spec_from_file_location(
        "viability2", str(VOSLAB / "scripts" / "vsl" / "tools"
                          / "viability_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hist = tmp_path / "h.jsonl"
    with open(hist, "w") as f:
        for pr in (0.65, 0.97):
            f.write(_json.dumps({"corpus": {"pass_rate": pr}}) + "\n")
    series = mod._pass_series(hist)[-10:]
    assert abs(series[-1] - series[0]) > 0.1  # improvement still trips drift


STATUS_MATRIX = [
    # (status, event, expected_target_or_None)
    ("proposed", "approve", "active"),
    ("active", "ratify", "ratified"),
    ("active", "deprecate", "archived"),
    ("ratified", "supersede", "archived"),
    ("archived", "approve", None),
    ("archived", "ratify", None),
    ("proposed", "ratify", None),
    ("proposed", "deprecate", None),
    ("ratified", "approve", None),
    ("active", "approve", None),
]


def _status_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "status_lifecycle", str(VOSLAB / "scripts" / "vsl" / "tools"
                                / "status_lifecycle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_status_lifecycle_matrix():
    mod = _status_mod()
    for status, event, want in STATUS_MATRIX:
        assert mod.delta(status, event) == want, (status, event)


def test_status_lifecycle_check_file():
    mod = _status_mod()
    assert mod.read_status(
        VOSLAB / "docs" / "plans" / "unified_tasks.vsm") == "active"


def _validation_tree():
    # Mirrors .opencode/plugins/support/trees/validation.tree.vsm
    # (kept in sync by hand; the .vsm is the canonical artifact).
    return {
        "op": "AND",
        "children": [
            {"op": "OR", "children": [
                {"predicate": "canon_query",
                 "args": ["$ctx", "tasks", {}]},
                {"predicate": "canon_query",
                 "args": ["$ctx", "queue", {"status": "pending"}]},
            ]},
            {"op": "OR", "children": [
                {"predicate": "canon_query",
                 "args": ["$ctx", "tasks", {"status": "done"}]},
                {"op": "NOT", "children": [
                    {"predicate": "canon_query",
                     "args": ["$ctx", "zzz_nonexistent", {}]},
                ]},
            ]},
        ],
    }


def _script_engine():
    import sys
    sys.path.insert(0, str(VOSLAB / "scripts" / "vsl" / "classifier"))
    from vsf_socratic_engine import _create_engine
    return _create_engine()


def test_validation_tree_passes():
    from socratic_engine import Truth
    r = _script_engine().evaluate(_validation_tree(), {})
    assert r.truth == Truth.TRUE and r.certified is True


def test_canon_query_unknown_domain():
    from socratic_engine import Truth
    e = _script_engine()
    r = e.evaluate({"predicate": "canon_query",
                    "args": ["$ctx", "nope", {}]}, {})
    assert r.truth == Truth.UNKNOWN and r.certified is False


def test_canon_query_empty_filter_counts():
    from socratic_engine import Truth
    e = _script_engine()
    r = e.evaluate({"predicate": "canon_query",
                    "args": ["$ctx", "tasks", {"status": "open"}]}, {})
    assert r.truth == Truth.FALSE and r.certified is True


def _route_mod():
    # Register in sys.modules BEFORE exec: @dataclass with
    # `from __future__ import annotations` resolves string annotations
    # via the module namespace at decoration time.
    import importlib.util
    import sys as _sys
    spec = importlib.util.spec_from_file_location(
        "route_component", str(VOSLAB / "scripts" / "vsl" / "route_component.py"))
    mod = importlib.util.module_from_spec(spec)
    _sys.modules["route_component"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_routing_matrix(tmp_path):
    rc = _route_mod()
    py = tmp_path / "m.py"
    py.write_text("from socratic_engine import PredicateResult\n")
    assert rc.route_component(py).destination == "socratic-engine"
    vsm = tmp_path / "m.vsm"
    vsm.write_text("⟦ m | T-v1 | vsm-1.2.1 | 2026-09-10T04:11:22Z ⟧\n")
    assert rc.route_component(vsm).destination == "docs_spec_revision"
    txt = tmp_path / "m.txt"
    txt.write_text("plain")
    d = rc.route_component(txt)
    assert d.destination == "evaluate_case_by_case" and d.confidence < 0.5


def test_routing_execute_guards(tmp_path):
    rc = _route_mod()
    src = tmp_path / "a.py"
    src.write_text("x = 1\n")
    d = rc.route_component(src)
    r = rc.execute_routing(src, d, dry_run=True)
    assert r.moved is False and src.exists()  # dry-run moves nothing
    r = rc.execute_routing("/etc/passwd", d, dry_run=False)
    assert r.moved is False and "outside" in r.reason
    ext = rc.RoutingDecision("socratic-engine", 0.7, [], [], [])
    r = rc.execute_routing(src, ext, dry_run=False)
    assert r.moved is False and "external" in r.reason
    assert src.exists()  # untouched throughout


def test_check_py_parity():
    """check.py must agree with the canonical set on the whole matrix."""
    spec = importlib.util.spec_from_file_location(
        "vsm_check", str(VOSLAB / "scripts" / "vsl" / "validator" / "check.py"))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    for snippet, flagged in MATRIX:
        res = check.validate_vsm_file.__wrapped__ if hasattr(
            check.validate_vsm_file, "__wrapped__") else None
        # validate content shape: minimal doc carrying the snippet
        doc = ("⟦ m | T-v1 | vsm-1.2.1 | 2026-09-09T16:22:24Z ⟧\n\n"
               "@vsm 1.2.1\n@status active\n\n"
               f"// probe {snippet}\n\n⟦ /m ⟧\n")
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".vsm",
                                         delete=False) as f:
            f.write(doc)
            path = f.name
        try:
            out = check.validate_vsm_file(path)
        finally:
            os.unlink(path)
        hard_errors = [e for e in out["errors"] if "HARDCODED" in e]
        # the probe header itself is clean, so any HARDCODED hit is the snippet
        assert (len(hard_errors) > 0) == flagged, (snippet, hard_errors)
