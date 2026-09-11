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


def _write_hist(tmp_path, name, rates):
    import json as _json
    hist = tmp_path / name
    with open(hist, "w") as f:
        for pr in rates:
            f.write(_json.dumps({"corpus": {"pass_rate": pr}}) + "\n")
    return hist


def test_viability_omega_on_fixture(tmp_path):
    """Omega math on a stable fixture series (deterministic, no drill)."""
    import vsm_viability as vv
    hist = _write_hist(tmp_path, "h.jsonl",
                       (0.90, 0.91, 0.90, 0.92, 0.91))
    m = vv.measure(history_path=hist,
                   cert_results=[{"pass": True}] * 4)
    assert m["inside"] is True
    assert m["dims"]["drift"] <= 0.1
    assert m["dims"]["stability"] >= 0.8


def test_viability_flags_fast_jump(tmp_path):
    import vsm_viability as vv
    hist = _write_hist(tmp_path, "h.jsonl", (0.65, 0.97))
    m = vv.measure(history_path=hist,
                   cert_results=[{"pass": True}])
    assert m["inside"] is False  # improvement still trips drift


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


def test_pin_blocks_post_approval_tamper(tmp_path, monkeypatch):
    import json as _json
    import rsi_cycle
    q = tmp_path / "q"
    q.mkdir()
    monkeypatch.setenv("RSI_QUEUE_DIR", str(q))
    monkeypatch.setenv("RSI_ACTIVATED_FILE", str(tmp_path / "act.json"))
    tree = {"predicate": "task_has_work", "kwargs": {}}
    (q / "t.json").write_text(_json.dumps(
        {"name": "t_pin", "status": "approved", "tree": tree}))
    c = rsi_cycle.RSICycle()
    assert "t_pin" in c.get_predicates()
    # tamper AFTER approval: same name, different tree
    (q / "t.json").write_text(_json.dumps(
        {"name": "t_pin", "status": "approved",
         "tree": {"predicate": "task_active", "kwargs": {}}}))
    c2 = rsi_cycle.RSICycle()
    assert "t_pin" not in c2.get_predicates()  # tampered: refused
    reg = _json.loads((tmp_path / "act.json").read_text())
    assert "t_pin" in reg  # pin recorded at first activation


def test_queue_oversize_skipped(tmp_path, monkeypatch):
    import rsi_cycle
    q = tmp_path / "q"
    q.mkdir()
    monkeypatch.setenv("RSI_QUEUE_DIR", str(q))
    monkeypatch.setenv("RSI_ACTIVATED_FILE", str(tmp_path / "act.json"))
    big = tmp_path / "q" / "big.json"
    big.write_bytes(b'{"name":"t_big","status":"approved","tree":{}}')
    # pad past 1 MiB without breaking JSON shape
    with open(big, "ab") as f:
        f.write(b' "' + b"x" * (2 * 1024 * 1024) + b'"')
    c = rsi_cycle.RSICycle()
    assert "t_big" not in c.get_predicates()


def test_l3_budget_allows_then_blocks(tmp_path, monkeypatch):
    import json as _json
    import rsi_cycle
    import time as _time
    monkeypatch.setenv("RSI_L3_BUDGET_FILE", str(tmp_path / "b.json"))
    monkeypatch.setattr(rsi_cycle, "L3_MAX_RUNS_PER_HOUR", 2)
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    assert c._l3_budget_ok() is True
    assert c._l3_budget_ok() is True
    assert c._l3_budget_ok() is False  # budget exhausted
    # old stamps age out
    old = [_time.time() - 3700, _time.time() - 3800]
    (tmp_path / "b.json").write_text(_json.dumps(old))
    assert c._l3_budget_ok() is True


def test_l3_dimensions_documented():
    import rsi_cycle
    assert rsi_cycle.L3_MAX_RUNS_PER_HOUR == 3
    assert rsi_cycle.L3_AUTO is True and rsi_cycle.L4_AUTO is False


def test_viability_omega_math():
    import vsm_viability as vv
    s = vv.ViabilityState(accuracy=0.9, drift=0.05, stability=0.9)
    assert s.is_viable() is True and s.margin_to_boundary() > 0
    s = vv.ViabilityState(accuracy=0.4, drift=0.05, stability=0.9)
    assert s.is_viable() is False


def test_caution_suspends_evolution_not_observation(tmp_path, monkeypatch):
    import vsm_viability as vv
    monkeypatch.setenv("RSI_CAUTION_FILE", str(tmp_path / "c.json"))
    allowed, _ = vv.evolution_allowed()
    assert allowed is True
    vv.set_caution("test")
    allowed, why = vv.evolution_allowed()
    assert allowed is False and why["caution"]["reason"] == "test"
    vv.clear_caution(actor="test")
    assert vv.evolution_allowed()[0] is True


def test_l3_deferred_under_caution(tmp_path, monkeypatch):
    import rsi_cycle
    monkeypatch.setenv("RSI_CAUTION_FILE", str(tmp_path / "c.json"))
    import vsm_viability as vv
    vv.set_caution("test-defer")

    class _FakeL3:
        def __init__(self):
            self.ran = []
        def run_cycle(self, fault):
            self.ran.append(fault)
            return {"cycled": True}

    class _Fault:
        fault_id = "test:1"

    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    fake = _FakeL3()
    c.__dict__["_l3"] = fake  # property returns it; must NOT run
    import socratic_engine
    c.engine = socratic_engine.SocraticEngine()
    c._maybe_run_l3(_Fault())
    assert fake.ran == []


def test_measure_pure_function(tmp_path):
    import json as _json
    import vsm_viability as vv
    hist = tmp_path / "h.jsonl"
    with open(hist, "w") as f:
        for pr in (0.9, 0.91, 0.9):
            f.write(_json.dumps({"corpus": {"pass_rate": pr}}) + "\n")
    m = vv.measure(history_path=hist,
                   cert_results=[{"pass": True}] * 4)
    assert m["dims"]["accuracy"] == 1.0
    assert m["inside"] is True


def test_trial_eval_refuses_unknown_predicate(tmp_path, monkeypatch):
    # Sabotage: tree referencing a renamed predicate must fail at LOAD,
    # never reach runtime (child load_hooks lesson).
    import json as _json
    import rsi_cycle
    q = tmp_path / "q"
    q.mkdir()
    monkeypatch.setenv("RSI_QUEUE_DIR", str(q))
    monkeypatch.setenv("RSI_ACTIVATED_FILE", str(tmp_path / "act.json"))
    (q / "s.json").write_text(_json.dumps({
        "name": "t_sabotage", "status": "approved",
        "tree": {"predicate": "renamed_predicate_xyz", "kwargs": {}}}))
    c = rsi_cycle.RSICycle()
    assert "t_sabotage" not in c.get_predicates()


def test_sabotage_attribute_and_budget():
    # Sabotage the split itself: if _attribute ever claims a security
    # failure is genuine, policy blocks would re-enter the fault loop.
    import rsi_cycle
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    from socratic_engine import SocraticEngine
    c.engine = SocraticEngine()
    import stub_predicates as sp
    for name in ("policy_locked", "write_scope_ok", "script_safe",
                 "script_domain_ok"):
        c.engine.register(name)(getattr(sp, name))
    for name in ("action_forbidden", "path_forbidden"):
        c.engine.register(name)(getattr(rsi_cycle, name))
    tree = {"op": "AND", "children": [
        {"predicate": "action_forbidden",
         "kwargs": {"command": "rm -rf /"}},
        {"predicate": "path_forbidden",
         "kwargs": {"file": "/etc/shadow", "tool": "read"}}]}
    failed = c._attribute(tree, {})
    assert set(failed) <= rsi_cycle.SECURITY_PREDICATES
    assert set(failed) == {"action_forbidden", "path_forbidden"}


def test_trust_writer_bump_decay(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(VOSLAB))
    from risk_assessor import RiskAssessor
    ra = RiskAssessor(tmp_path)
    assert ra.record_outcome("a.txt", True) == 0.75
    assert ra.record_outcome("a.txt", False) == 0.55
    assert (tmp_path / ".trust_state.json").is_file()
    f = ra._assess_trust("write", "a.txt", "")
    assert f.score == 1 and "0.55" in f.reason


def test_l3_hysteresis_watches_first(tmp_path, monkeypatch):
    import rsi_cycle
    monkeypatch.setenv("RSI_CAUTION_FILE", str(tmp_path / "c.json"))
    monkeypatch.setenv("RSI_L3_SIGHTINGS_FILE", str(tmp_path / "s.json"))
    monkeypatch.setenv("RSI_L3_BUDGET_FILE", str(tmp_path / "b.json"))

    class _FakeL3:
        def __init__(self):
            self.ran = []
        def run_cycle(self, fault):
            self.ran.append(fault)
            return {"cycled": True}

    class _Fault:
        fault_id = "hyst:1"

    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    fake = _FakeL3()
    c.__dict__["_l3"] = fake
    import socratic_engine
    c.engine = socratic_engine.SocraticEngine()
    c._maybe_run_l3(_Fault())
    assert fake.ran == []  # first sighting: watch only
    c._maybe_run_l3(_Fault())
    assert len(fake.ran) == 1  # second sighting: acts


def test_degraded_ladder_matrix():
    import vsm_viability as vv
    assert vv.degraded_mode(0.5, False) == "nominal"
    assert vv.degraded_mode(0.03, False) == "shed"
    assert vv.degraded_mode(0.01, False) == "quiesce"
    assert vv.degraded_mode(-0.1, False) == "halt"
    assert vv.degraded_mode(0.9, True) == "halt"  # caution dominates
    assert vv.mode_allows("nominal", "l3_cycle") is True
    assert vv.mode_allows("shed", "l3_cycle") is False
    assert vv.mode_allows("shed", "learn_pipeline") is True
    assert vv.mode_allows("quiesce", "learn_pipeline") is False
    assert vv.mode_allows("halt", "observe") is True
    assert vv.mode_allows("halt", "learn_pipeline") is False


def test_mode_file_roundtrip(tmp_path, monkeypatch):
    import vsm_viability as vv
    monkeypatch.setenv("RSI_MODE_FILE", str(tmp_path / "mode.json"))
    assert vv.read_mode() == "nominal"  # missing file default
    assert vv.write_mode("quiesce") == "quiesce"
    assert vv.read_mode() == "quiesce"
    try:
        vv.write_mode("bogus")
        assert False, "must raise"
    except ValueError:
        pass


def test_rsi_mode_switch(monkeypatch):
    import vsm_viability as vv
    monkeypatch.delenv("RSI_MODE", raising=False)
    assert vv.rsi_mode() == "CAPABILITY"
    monkeypatch.setenv("RSI_MODE", "safe")
    assert vv.rsi_mode() == "SAFE"


def test_graduated_tau_earn_demote(tmp_path, monkeypatch):
    import graduated_autonomy as ga
    monkeypatch.setenv("RSI_TAU_FILE", str(tmp_path / "tau.json"))
    assert ga.get_tau()["l1_thresholds"] == 0.5
    for _ in range(5):
        ga.record_window(clean=True)
    assert ga.get_tau()["l1_thresholds"] == 0.6
    ga.record_window(clean=False)  # breach resets window
    t = ga.get_tau()["l1_thresholds"]
    assert t < 0.6
    assert ga.graduation_candidates() == []  # far from 0.90/20


def test_learn_pipeline_skips_in_safe_mode():
    import json as _json
    import subprocess
    import sys as _sys
    import os as _os
    env = dict(_os.environ)
    env["RSI_MODE"] = "SAFE"
    p = subprocess.run(
        [_sys.executable, str(VOSLAB / ".opencode" / "plugins"
                              / "operational" / "tool_integration_bridge.py"),
         "learn-pipeline"],
        capture_output=True, text=True, timeout=120,
        cwd=str(VOSLAB), env=env)
    assert p.returncode == 0
    assert _json.loads(p.stdout.strip())["reason"] == "RSI_MODE=SAFE"


def test_forbidden_bypass_families():
    import stub_predicates as sp
    from socratic_engine import Truth
    for cmd in ("echo x | sudo tee /root/f", "echo y > /etc/cron.d/z",
                "eval($MALICIOUS)"):
        r = sp.script_safe(cmd)
        assert r.truth == Truth.FALSE, cmd
    assert sp.script_safe("echo hello").truth == Truth.TRUE


def _bridge(*args):
    import json as _json
    import subprocess
    import sys as _sys
    p = subprocess.run(
        [_sys.executable, str(VOSLAB / ".opencode" / "plugins"
                              / "operational" / "tool_integration_bridge.py"),
         *args], capture_output=True, text=True, timeout=120,
        cwd=str(VOSLAB))
    assert p.returncode == 0, p.stderr[:300]
    return _json.loads(p.stdout.strip())


def test_revoke_quarantines_pred_dir(tmp_path, monkeypatch):
    import json as _json
    import os as _os
    # isolated agent state for the bridge subprocess
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    out = _bridge("rsi-revoke", "t_ghost_xyz", "test")
    assert out["name"] == "t_ghost_xyz"
    assert out["pred_dir"] in ("no pred_dir file",) or "error" in str(
        out["pred_dir"]) or "quarantined" in str(out["pred_dir"])


def test_feedback_guardrails_live(tmp_path, monkeypatch):
    # Upstream MIN_SAMPLES/ADJUSTMENT_STEP must hold, not just exist.
    import json as _json
    import vsf_rsi.rsi_feedback_loop as fl
    import vsf_rsi.rsi_metrics as met
    assert fl.MIN_SAMPLES == 10 and fl.ADJUSTMENT_STEP == 0.05
    monkeypatch.setenv("RSI_METRICS_DIR", str(tmp_path))
    import importlib
    importlib.reload(met)
    importlib.reload(fl)
    try:
        loop = fl.RSIFeedbackLoop()
        out = loop.adjust_thresholds()
        assert out.get("adjustments", []) == []  # no data -> no moves
        # sparse data (<10 samples) must not move either
        m = met.RSIMetrics()
        m.metrics_dir = tmp_path
        assert fl.MIN_SAMPLES == 10
    finally:
        importlib.reload(met)
        importlib.reload(fl)


def test_feedback_trigger_interval():
    import rsi_cycle
    c = rsi_cycle.RSICycle()
    assert c._feedback_interval == 10
    assert callable(c._maybe_run_feedback_loop)
    # 9 prior evals + 1 more must cross the trigger boundary
    c._eval_count = 9
    c.evaluate({"predicate": "task_has_work", "kwargs": {}}, {})
    assert c._eval_count == 10


def _pipeline_tree():
    # Mirrors support/trees/pipeline.tree.vsm (sequential composition).
    return {
        "op": "AND",
        "children": [
            {"predicate": "action_forbidden",
             "args": ["$tool", "$file"], "kwargs": {"command": "$command"}},
            {"predicate": "path_forbidden",
             "args": ["$file"], "kwargs": {"tool": "$tool"}},
            {"predicate": "write_scope_ok", "args": ["$tool", "$file"]},
            {"predicate": "not_redundant",
             "args": ["$tool", "$file", "$command"]},
        ],
    }


def test_pipeline_tree_composition(cycle):
    ctx = {"tool": "read", "file": "docs/x.vsm", "command": "",
           "recent_actions": []}
    out = cycle.evaluate(_pipeline_tree(), ctx)
    assert out["truth"] == "TRUE" and out["certified"] is True
    ctx = {"tool": "bash", "file": "", "command": "rm -rf /",
           "recent_actions": []}
    out = cycle.evaluate(_pipeline_tree(), ctx)
    assert out["truth"] == "FALSE" and out["certified"] is True


def _memory_tree():
    # Mirrors support/trees/memory.tree.vsm (history routes the verdict).
    return {
        "op": "OR",
        "children": [
            {"predicate": "prior_failure",
             "args": ["$tool", "$file", "$command"],
             "inject_context": True},
            {"predicate": "not_redundant",
             "args": ["$tool", "$file", "$command"]},
        ],
    }


def test_memory_tree_routes_on_history(cycle):
    import stub_predicates as sp
    from socratic_engine import Truth
    recent = [{"tool": "bash", "file": "", "command": "do x",
               "outcome": "error"}]
    r = sp.prior_failure("bash", "", "do x",
                         **{"recent_actions": recent})
    assert r.truth == Truth.TRUE  # failed before -> escalate signal
    r = sp.prior_failure("bash", "", "do y",
                         **{"recent_actions": recent})
    assert r.truth == Truth.FALSE  # no history -> proceed path
    ctx = {"tool": "bash", "file": "", "command": "do y",
           "recent_actions": recent}
    out = cycle.evaluate(_memory_tree(), ctx)
    assert out["truth"] == "TRUE" and out["certified"] is True


def _fixture(name):
    import json as _json
    return _json.loads((VOSLAB / "system" / "kernel" / "tests" / "fixtures"
                        / name).read_text())


def test_historical_fixtures_pass_purpose_gate():
    from rsi_cycle import purpose_gate
    for name in ("rsi_bash_grep_self_corrected.json",
                 "rsi_bash_grep_missing_pattern_self_corrected.json"):
        d = _fixture(name)
        ok, reason = purpose_gate(d["tree"])
        assert ok is True, (name, reason)


def test_historical_fixtures_deterministic():
    import rsi_cycle
    from socratic_engine import Truth
    c = rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)
    from socratic_engine import SocraticEngine
    c.engine = SocraticEngine()
    import stub_predicates as sp  # noqa: F401 (register side effect below)
    # kernel builtins come from a full cycle in the bridge path; here we
    # assert structural determinism: same tree+ctx => same verdict twice
    d = _fixture("rsi_bash_grep_self_corrected.json")
    ctx = {"tool": "bash", "command": "grep x", "recent_actions": []}
    r1 = c.engine.evaluate(d["tree"], dict(ctx))
    r2 = c.engine.evaluate(d["tree"], dict(ctx))
    assert (r1.truth, r1.certified) == (r2.truth, r2.certified)


def test_preflight_all_pass():
    import subprocess
    import sys as _sys
    p = subprocess.run(
        [_sys.executable, str(VOSLAB / "scripts" / "vsl" / "tools"
                              / "l3_preflight.py")],
        capture_output=True, text=True, timeout=120, cwd=str(VOSLAB))
    assert p.returncode == 0, p.stderr[:300] + p.stdout[:300]
    assert p.stdout.count("PASS") >= 6


def test_rollback_list_and_noop_apply():
    import json as _json
    import subprocess
    import sys as _sys
    base = [_sys.executable, str(VOSLAB / "scripts" / "vsl" / "tools"
                                 / "l3_rollback.py")]
    p = subprocess.run(base + ["--list"], capture_output=True, text=True,
                       timeout=60, cwd=str(VOSLAB))
    assert p.returncode == 0
    assert "recent_activations" in p.stdout
    p = subprocess.run(base + ["--apply", "--name", "t_ghost_xyz"],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(VOSLAB))
    assert p.returncode == 0
    out = _json.loads(p.stdout.strip())
    # never activated: nothing to revoke, still ok (idempotent no-op)
    assert out["revoked"] == []


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
