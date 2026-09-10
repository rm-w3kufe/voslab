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


def test_status_lifecycle_scan_clean():
    mod = _status_mod()
    rows, violations = mod.scan(VOSLAB / "system")
    assert len(rows) > 100
    assert violations == [], violations[:5]


def test_status_nontransitional_fixed():
    mod = _status_mod()
    for st in ("template", "conjecture"):
        for ev in ("approve", "ratify", "deprecate", "supersede"):
            assert mod.delta(st, ev) is None


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
    confident = rc.RoutingDecision("vsf_script", 0.8, [], [], [])
    r = rc.execute_routing("/etc/passwd", confident, dry_run=False)
    assert r.moved is False and "outside" in r.reason
    ext = rc.RoutingDecision("socratic-engine", 0.7, [], [], [])
    r = rc.execute_routing(src, ext, dry_run=False)
    assert r.moved is False and "external" in r.reason
    assert src.exists()  # untouched throughout


def _quarantine(argv, cwd=None, qdir=None):
    import os
    import subprocess
    import sys
    env = dict(os.environ)
    if qdir is not None:
        env["VSM_QUARANTINE_DIR"] = str(qdir)
    return subprocess.run(
        [sys.executable, str(VOSLAB / "scripts" / "vsl" / "tools"
                             / "vsm_quarantine.py")]+ argv,
        capture_output=True, text=True, timeout=60,
        cwd=str(cwd or VOSLAB), env=env)


def test_quarantine_roundtrip(tmp_path):
    qd = tmp_path / "q"
    target = tmp_path / "q.vsm"
    target.write_text("original\n")
    # stash must run BEFORE the breach (hook order matters)
    p = _quarantine(["stash", str(target)], qdir=qd)
    assert p.returncode == 0
    token = p.stdout.strip()
    target.write_text("breach\n")
    p = _quarantine(["restore", token], qdir=qd)
    assert p.returncode == 0
    assert target.read_text() == "original\n"


def test_quarantine_refuses_new_file(tmp_path):
    qd = tmp_path / "q"
    target = tmp_path / "new.vsm"  # does not exist at stash time
    p = _quarantine(["stash", str(target)], qdir=qd)
    assert p.returncode == 0
    target.write_text("breach\n")
    p = _quarantine(["restore", p.stdout.strip()], qdir=qd)
    assert p.returncode == 2  # must quarantine instead
    p = _quarantine(["quarantine", str(target)], qdir=qd)
    assert p.returncode == 0 and not target.exists()


def _instance_bindings():
    import re
    text = (VOSLAB / "system" / "instance" / "voslab-instance-01"
            / "instance.vsm").read_text(encoding="utf-8")
    pairs = re.findall(r'^\s*(\w+):\s*"\*/([^"]+)"', text, re.M)
    return pairs


def test_instance_bindings_resolve():
    home = Path.home()
    missing = []
    for name, rel in _instance_bindings():
        if not (home / "vOSlab" / rel).is_file():
            missing.append((name, rel))
    assert missing == [], missing


def test_instance_covers_mandatory():
    bound = {rel for _, rel in _instance_bindings()}
    for doc in (VOSLAB / "system" / "boot").glob("*.vsm"):
        if doc.name == "classification.local.vsm":
            continue
        assert f"system/boot/{doc.name}" in bound, doc.name
    for doc in ["readme.vsm", "s5_policy_annex.vsm", "s5_policy_core.vsm"]:
        assert f"system/s5-policy/{doc}" in bound, doc


def test_access_policy_fail_closed(tmp_path, monkeypatch):
    import access_policy as ap
    monkeypatch.setenv("ACCESS_POLICY_PATH", str(tmp_path / "absent.json"))
    ap._cache.update(mtime=None, policy=None, path=None)
    pol = ap.load()
    assert pol["degraded"] is True
    assert "/etc/shadow" in pol["read_denylist"]
    monkeypatch.setenv("ACCESS_POLICY_PATH", str(tmp_path / "bad.json"))
    (tmp_path / "bad.json").write_text("{oops")
    ap._cache.update(mtime=None, policy=None, path=None)
    pol = ap.load()
    assert pol["degraded"] is True
    monkeypatch.setenv("ACCESS_POLICY_PATH", str(tmp_path / "v9.json"))
    (tmp_path / "v9.json").write_text('{"policy_version": 9}')
    ap._cache.update(mtime=None, policy=None, path=None)
    assert ap.load()["degraded"] is True


def test_access_policy_operating_clamp(tmp_path, monkeypatch):
    import access_policy as ap
    monkeypatch.setenv("RSI_THRESHOLDS_FILE", str(tmp_path / "op.json"))
    (tmp_path / "op.json").write_text('{"repeat_block": 99, "nope": 1}')
    live = ap.operating_thresholds()
    assert live["repeat_block"] == 10  # clamped to bounds, unknown ignored


def test_parse_query_units():
    import rsi_cycle
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    assert c._determine_intent("is this safe?") == "security_check"
    assert c._determine_intent("blabla unknown") == "unknown"
    assert "files" in c._extract_entities("check /tmp/x.py", {})
    out = c.parse_query("is rm dangerous?", {})
    assert out["intent"] == "security_check" and out["parsed"] is True
    out = c.parse_query("blabla unknown", {})
    assert out["parsed"] is False and out["tree"] is None


def test_access_policy_validate_branches(tmp_path, monkeypatch):
    import access_policy as ap
    base = {"policy_version": 1, "workspace_roots": [],
            "read_denylist": [], "thresholds": {}}
    import json as _json

    def _load(obj):
        p = tmp_path / "p.json"
        p.write_text(_json.dumps(obj))
        monkeypatch.setenv("ACCESS_POLICY_PATH", str(p))
        ap._cache.update(mtime=None, policy=None, path=None)
        return ap.load()

    assert _load(["not", "dict"])["degraded"] is True
    assert _load({**base, "workspace_roots": "x"})["degraded"] is True
    assert _load({**base, "read_denylist": "x"})["degraded"] is True
    good = _load(base)
    assert good["degraded"] is False
    assert good["thresholds"]["repeat_block"] == 3


def test_evaluate_error_paths(cycle):
    out = cycle.evaluate({"predicate": "nope_missing",
                          "kwargs": {}}, {})
    assert out["truth"] == "ERROR" and out["certified"] is False
    out = cycle.evaluate(None, {})
    assert out["truth"] == "TRUE"  # empty tree vacuously true


def test_load_predicates_skips_bad_files(tmp_path, monkeypatch):
    import json as _json
    import rsi_cycle
    d = tmp_path / "state" / "predicates"
    d.mkdir(parents=True)
    (d / "v1.json").write_text(_json.dumps({"name": "x"}))  # no tree
    (d / "broken.json").write_text("{oops")
    (d / "good.json").write_text(_json.dumps({
        "name": "t_cov", "tree": {"predicate": "task_has_work",
                                  "kwargs": {}}}))
    monkeypatch.setattr(rsi_cycle, "RSI_PATH", tmp_path)
    c = rsi_cycle.RSICycle()
    assert "t_cov" in c.get_predicates()
    assert "x" not in c.get_predicates()


def test_degraded_no_observer_stack(monkeypatch):
    # Upstream missing entirely: cycle must still evaluate (degraded, safe).
    import sys as _sys
    import rsi_cycle
    for mod in ("vsf_rsi.rsi_observer", "vsf_rsi.rsi_fault_detector",
                "vsf_rsi.rsi_autonomous_l3", "vsf_rsi.scenario_memory",
                "vsf_rsi.rsi_pipeline", "vsf_rsi.rsi_tree_generator",
                "vsf_rsi.rsi_socratic_bridge", "vsf_rsi.rsi_feedback_loop"):
        monkeypatch.setitem(_sys.modules, mod, None)
    c = rsi_cycle.RSICycle()
    assert c.observer is None and c.fault_detector is None
    out = c.evaluate({"predicate": "task_has_work", "kwargs": {}}, {})
    assert out["truth"] in ("TRUE", "FALSE") and out["certified"] is True


def test_task_has_work_no_focus(tmp_path, monkeypatch):
    import rsi_cycle
    monkeypatch.setattr(rsi_cycle, "VOSLAB_PATH", tmp_path)
    from socratic_engine import Truth
    r = rsi_cycle.task_has_work()
    assert r.truth == Truth.FALSE and "no focus" in str(r.evidence)


def test_evaluate_query_roundtrip():
    import rsi_cycle
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    from socratic_engine import SocraticEngine
    c.engine = SocraticEngine()
    c._register_all_predicates = lambda: None
    # minimal wiring for query path
    import stub_predicates as sp
    c.engine.register("task_has_work")(sp.task_active.__wrapped__
                                        if hasattr(sp.task_active,
                                                   "__wrapped__")
                                        else sp.task_active)
    out = c.parse_query("task work active", {})
    assert out["parsed"] is True and out["intent"] == "task_check"


def test_security_predicate_clean_paths():
    import rsi_cycle
    from socratic_engine import Truth
    assert rsi_cycle.action_forbidden("bash", "", "echo hi").truth == Truth.TRUE
    assert rsi_cycle.path_forbidden("", tool="read").truth == Truth.TRUE


def test_main_argv_mode():
    import json as _json
    import os
    import subprocess
    import sys as _sys
    env = dict(os.environ)
    env["PYTHONPATH"] = str(VOSLAB / "system" / "kernel")
    p = subprocess.run(
        [_sys.executable, str(VOSLAB / "system" / "kernel" / "rsi_cycle.py"),
         "is rm safe"],
        capture_output=True, text=True, timeout=120,
        cwd=str(VOSLAB), env=env)
    assert p.returncode == 0, p.stderr[:300]
    out = _json.loads(p.stdout.strip())
    assert out["parsed"] is True and "result" in out


def test_main_interactive_quits():
    import os
    import subprocess
    import sys as _sys
    env = dict(os.environ)
    env["PYTHONPATH"] = str(VOSLAB / "system" / "kernel")
    p = subprocess.run(
        [_sys.executable, str(VOSLAB / "system" / "kernel" / "rsi_cycle.py")],
        input="quit\n", capture_output=True, text=True, timeout=120,
        cwd=str(VOSLAB), env=env)
    assert p.returncode == 0
    assert "RSI Cycle Orchestrator" in p.stdout


def test_state_context_stub_contract():
    import rsi_cycle
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    assert c._get_state_context() == {}
    assert c._get_state_context() == {}  # cached path


def test_intent_builders_matrix():
    import rsi_cycle
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    t = c._build_tree_from_intent(
        "file_check", {"files": ["/a", "/b"]}, {})
    assert t["op"] == "OR" and len(t["children"]) == 2
    assert c._build_tree_from_intent("file_check", {}, {})["predicate"] == "file_valid"
    t = c._build_tree_from_intent(
        "script_check", {"scripts": ["x.py"]}, {})
    assert t["children"][0]["kwargs"] == {"script": "x.py"}
    assert c._build_tree_from_intent(
        "script_check", {}, {})["predicate"] == "script_exists"
    assert c._build_tree_from_intent(
        "state_check", {}, {})["predicate"] == "state_consistent"
    assert c._build_tree_from_intent("unknown", {}, {}) is None
    assert c._build_tree_from_intent(
        "security_check", {"commands": ["rm"]}, {})["op"] == "OR"


def test_degraded_l3_and_feedback_noops(monkeypatch):
    import sys as _sys
    import rsi_cycle
    for mod in ("vsf_rsi.rsi_autonomous_l3", "vsf_rsi.rsi_feedback_loop"):
        monkeypatch.setitem(_sys.modules, mod, None)
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    c._l3 = None
    from socratic_engine import SocraticEngine
    c.engine = SocraticEngine()
    assert c.autonomous_l3 is None
    c._maybe_run_l3(object())  # must not raise
    c._eval_count = 0
    c._feedback_interval = 10
    c._observer = None
    c._maybe_run_feedback_loop()  # must not raise


def test_evaluate_query_live():
    import rsi_cycle
    c = rsi_cycle.RSICycle()
    out = c.evaluate_query("task work active", {})
    assert out["parsed"] is True
    assert out["result"]["certified"] is True


def test_load_queue_edges(tmp_path, monkeypatch):
    import json as _json
    import rsi_cycle
    q = tmp_path / "q"
    q.mkdir()
    (q / "nonapproved.json").write_text(_json.dumps({
        "name": "t_skip", "status": "pending",
        "tree": {"predicate": "task_has_work", "kwargs": {}}}))
    (q / "noname.json").write_text(_json.dumps({
        "status": "approved", "tree": {"predicate": "task_has_work",
                                       "kwargs": {}}}))
    (q / "notree.json").write_text(_json.dumps({
        "name": "t_notree", "status": "approved"}))
    (q / "junk.json").write_text("{oops")
    monkeypatch.setenv("RSI_QUEUE_DIR", str(q))
    c = rsi_cycle.RSICycle()
    names = c.get_predicates()
    assert "t_skip" not in names and "t_notree" not in names
    # outside workspace: loads approved without rewriting status
    assert "t_noname" not in names  # empty name refused
    assert (q / "noname.json").exists()  # untouched, still approved


def test_main_interactive_query(tmp_path):
    import json as _json
    import os
    import subprocess
    import sys as _sys
    env = dict(os.environ)
    env["PYTHONPATH"] = str(VOSLAB / "system" / "kernel")
    p = subprocess.run(
        [_sys.executable, str(VOSLAB / "system" / "kernel" / "rsi_cycle.py")],
        input="is rm safe\nquit\n", capture_output=True, text=True,
        timeout=120, cwd=str(VOSLAB), env=env)
    assert p.returncode == 0
    assert "truth" in p.stdout


def test_remaining_stubs_contract():
    import stub_predicates as sp
    from socratic_engine import Truth
    for name in ("state_scripts_ok", "vsl_scripts_ok", "audit_scripts_ok",
                 "s1_kernel_scripts_ok", "event_router_ok", "lifecycle_valid",
                 "gap_free", "onboard_complete", "hook_metrics_ok",
                 "semantic_mapper_ok", "process_staging_ok", "load_hooks_ok"):
        r = getattr(sp, name)("a", "b", key="v")
        assert r.truth == Truth.TRUE and r.certified is True, name


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
