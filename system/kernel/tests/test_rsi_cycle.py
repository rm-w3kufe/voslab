"""T1.1 — regression net for RSICycle + RSI bridge (unified_tasks.vsm).

Covers the two production incidents of 2026-09-09:
  1. stub predicates crashed on positional args (TypeError -> every eval ERROR)
  2. learn-pipeline registered predicates directly (L4 ceiling hole)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

VOSLAB = Path(__file__).resolve().parents[3]
BRIDGE = VOSLAB / ".opencode" / "plugins" / "operational" / "tool_integration_bridge.py"


def _run_bridge(*args: str) -> dict:
    p = subprocess.run(
        [sys.executable, "-W", "ignore", str(BRIDGE), *args],
        capture_output=True, text=True, timeout=120, cwd=str(VOSLAB),
    )
    assert p.returncode == 0, f"bridge {args} rc={p.returncode}: {p.stderr[:300]}"
    return json.loads(p.stdout.strip())


# ─── Ceiling ────────────────────────────────────────────────────────────────

def test_autonomy_ceiling_constants():
    import rsi_cycle
    assert rsi_cycle.L3_AUTO is True  # reversible: shadow + auto-rollback
    assert rsi_cycle.L4_AUTO is False  # generated -> queue, never direct


# ─── Stubs (incident #1 regression) ─────────────────────────────────────────

STUB_NAMES = [
    "state_consistent", "state_scripts_ok", "vsl_scripts_ok",
    "audit_scripts_ok", "s1_kernel_scripts_ok", "scripts_manifest",
    "not_redundant", "pattern_known", "script_safe", "script_domain_ok",
    "script_call", "task_active", "event_router_ok", "lifecycle_valid",
    "gap_free", "onboard_complete", "hook_metrics_ok", "semantic_mapper_ok",
    "process_staging_ok", "load_hooks_ok", "naming_conforms", "vsm_has_header",
]



REAL_NAMES = {"not_redundant", "pattern_known", "script_safe",
              "script_domain_ok", "script_call",
              # T1.2 second wave
              "state_consistent", "task_active", "vsm_has_header",
              "naming_conforms", "scripts_manifest",
              # stubs audit (no remaining stubs): all real since
              "state_scripts_ok", "vsl_scripts_ok", "audit_scripts_ok",
              "s1_kernel_scripts_ok", "event_router_ok", "lifecycle_valid",
              "gap_free", "onboard_complete", "hook_metrics_ok",
              "semantic_mapper_ok", "process_staging_ok", "load_hooks_ok"}


@pytest.mark.parametrize("name", STUB_NAMES)
def test_stub_accepts_positional_and_keyword_args(name):
    import stub_predicates
    from socratic_engine import Truth
    pred = getattr(stub_predicates, name)
    # exact calling convention of socratic_engine (args + kwargs):
    # must never raise TypeError; remaining stubs stay TRUE.
    res = pred("bash", "some/file.txt", "echo hi", recent_actions=[])
    assert isinstance(res.truth, Truth)
    assert res.certified is True
    if name not in REAL_NAMES:
        assert res.truth == Truth.TRUE


# ─── T1.2: real predicate verdicts ────────────────────────────────────────────

def _repeat(tool, file, command, n, outcome="ok"):
    return [{"tool": tool, "file": file, "command": command,
             "outcome": outcome} for _ in range(n)]


def test_not_redundant_passes_first_try():
    import stub_predicates as sp
    from socratic_engine import Truth
    assert sp.not_redundant("read", "a.txt", "", recent_actions=[]).truth == Truth.TRUE


def test_not_redundant_passes_single_retry():
    import stub_predicates as sp
    from socratic_engine import Truth
    recent = _repeat("bash", "", "echo hi", 1)
    assert sp.not_redundant("bash", "", "echo hi",
                            recent_actions=recent).truth == Truth.TRUE


def test_not_redundant_blocks_triple_repeat():
    import stub_predicates as sp
    from socratic_engine import Truth
    recent = _repeat("bash", "", "echo hi", 3)
    r = sp.not_redundant("bash", "", "echo hi", recent_actions=recent)
    assert r.truth == Truth.FALSE and r.certified is True
    assert r.evidence["repeats"] == 3


def test_not_redundant_blocks_failing_retry():
    import stub_predicates as sp
    from socratic_engine import Truth
    recent = _repeat("bash", "", "do risky", 2, outcome="error")
    r = sp.not_redundant("bash", "", "do risky", recent_actions=recent)
    assert r.truth == Truth.FALSE and r.certified is True


def test_pattern_known_never_blocks():
    import stub_predicates as sp
    from socratic_engine import Truth
    r = sp.pattern_known(fault_signature="no.such.signature.xyz")
    assert r.truth == Truth.TRUE and r.certified is True
    assert r.evidence["known"] is False


def test_script_safe_blocks_forbidden():
    import stub_predicates as sp
    from socratic_engine import Truth
    r = sp.script_safe("rm -rf / tmp")
    assert r.truth == Truth.FALSE and r.certified is True
    assert sp.script_safe("echo hi").truth == Truth.TRUE


def test_script_domain_ok_blocks_shadow():
    import stub_predicates as sp
    from socratic_engine import Truth
    assert sp.script_domain_ok("/etc/shadow").truth == Truth.FALSE
    assert sp.script_domain_ok("scripts/vsl/tools/x.py").truth == Truth.TRUE


def test_script_call_requires_existence():
    import stub_predicates as sp
    from socratic_engine import Truth
    assert sp.script_call("").truth == Truth.TRUE  # no target: no verdict
    assert sp.script_call("/no/such/script.py").truth == Truth.FALSE
    assert sp.script_call(str(VOSLAB / "current_focus.json")).truth == Truth.TRUE


def test_forbidden_lists_single_sourced():
    import stub_predicates as sp
    import rsi_cycle
    assert rsi_cycle.FORBIDDEN_COMMANDS == sp.FORBIDDEN_COMMANDS
    # live denylist comes from S5 policy (hot-reload), static is the seed
    try:
        from access_policy import load
    except ImportError:
        from system.kernel.access_policy import load
    assert sp._denylist() == list(load()["read_denylist"])
    assert set(sp.FORBIDDEN_PATHS) <= set(sp._denylist())


def test_policy_locked_cli_only():
    import stub_predicates as sp
    from socratic_engine import Truth
    try:
        from access_policy import policy_path
    except ImportError:
        from system.kernel.access_policy import policy_path
    pol = str(policy_path())
    assert sp.policy_locked("write", pol).truth == Truth.FALSE
    assert sp.policy_locked("edit", pol).truth == Truth.FALSE
    assert sp.policy_locked("read", pol).truth == Truth.TRUE  # reads allowed
    assert sp.policy_locked("write", "docs/x.vsm").truth == Truth.TRUE


def test_write_scope_ok_closed_lab():
    import stub_predicates as sp
    from socratic_engine import Truth
    assert sp.write_scope_ok("write", str(VOSLAB / "docs" / "x.vsm")).truth == Truth.TRUE
    assert sp.write_scope_ok("write", "/tmp/opencode/x.txt").truth == Truth.TRUE
    r = sp.write_scope_ok("write", "/etc/cron.d/evil")
    assert r.truth == Truth.FALSE and r.certified is True
    assert sp.write_scope_ok("bash", "rm -rf /").truth == Truth.TRUE  # skipped


def test_policy_fail_closed_on_corrupt(tmp_path, monkeypatch):
    import access_policy as ap
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setenv("ACCESS_POLICY_PATH", str(bad))
    ap._cache.update(mtime=None, policy=None, path=None)
    pol = ap.load()
    assert pol["degraded"] is True
    assert "/etc/shadow" in pol["read_denylist"]


# ─── T1.2 second wave: state/tasks/naming ───────────────────────────────────

def test_state_consistent_healthy_workspace():
    import stub_predicates as sp
    from socratic_engine import Truth
    r = sp.state_consistent()
    # executed with cwd inside vOSlab by pytest -> real check runs
    assert r.certified is True
    assert r.truth == Truth.TRUE


def test_task_active_ref_lookup():
    import stub_predicates as sp
    from socratic_engine import Truth
    r = sp.task_active("no-such-ref-xyz")
    assert r.truth == Truth.FALSE and r.certified is True
    assert r.evidence["active"] is False


def test_vsm_has_header_real_files():
    import stub_predicates as sp
    from socratic_engine import Truth
    assert sp.vsm_has_header(str(VOSLAB / "docs" / "plans" / "unified_tasks.vsm")).truth == Truth.TRUE
    assert sp.vsm_has_header("").truth == Truth.TRUE  # no target: no verdict
    assert sp.vsm_has_header("/no/such/file.vsm").truth == Truth.FALSE


def test_naming_conforms_policy():
    import stub_predicates as sp
    from socratic_engine import Truth
    assert sp.naming_conforms("docs/notes.md").truth == Truth.FALSE
    assert sp.naming_conforms("docs/plans/x.vsm.md").truth == Truth.TRUE
    assert sp.naming_conforms("scripts/a.py").truth == Truth.TRUE


def test_scripts_manifest_reports_missing_updater():
    import stub_predicates as sp
    from socratic_engine import Truth
    r = sp.scripts_manifest()
    assert r.truth == Truth.FALSE and r.certified is True
    assert r.evidence["exists"] is False


# ─── Read-direction close + oversize warn (S5 2026-09-09) ────────────────────

def test_path_forbidden_blocks_credential_reads():
    import stub_predicates  # noqa: F401 (path_forbidden lives in rsi_cycle)
    import rsi_cycle
    from socratic_engine import Truth
    r = rsi_cycle.path_forbidden("/etc/shadow", tool="read")
    assert r.truth == Truth.FALSE and r.certified is True
    assert r.evidence["direction"] == "read"
    r = rsi_cycle.path_forbidden("/etc/passwd", tool="grep")
    assert r.truth == Truth.FALSE and r.certified is True


def test_path_forbidden_allows_normal_reads():
    import rsi_cycle
    from socratic_engine import Truth
    r = rsi_cycle.path_forbidden("docs/plans/x.vsm", tool="read")
    assert r.truth == Truth.TRUE
    assert r.evidence["direction"] == "read"


def test_read_size_ok_warns_never_blocks(tmp_path):
    import stub_predicates as sp
    from socratic_engine import Truth
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (sp.READ_WARN_BYTES + 1))
    r = sp.read_size_ok(str(big))
    assert r.truth == Truth.TRUE and r.certified is True
    assert "warn" in r.evidence
    small = tmp_path / "small.txt"
    small.write_text("hi")
    assert "warn" not in sp.read_size_ok(str(small)).evidence


def test_precheck_tree_includes_direction_and_size():
    import rsi_cycle
    assert "read_size_ok" in rsi_cycle.RSICycle().get_predicates()


# ─── Adversarial: traversal, prefix collision, case (2026-09-10) ─────────────

def test_path_traversal_blocked():
    import rsi_cycle
    from socratic_engine import Truth
    # ../../../root/.ssh from the workspace resolves INTO /root/.ssh
    # (a naive startswith check is blind to this — verified 2026-09-10)
    r = rsi_cycle.path_forbidden("../../../root/.ssh", tool="read")
    assert r.truth == Truth.FALSE and r.certified is True
    assert r.evidence["forbidden_path"] == "/root/.ssh"


def test_prefix_collision_not_blocked(tmp_path):
    import rsi_cycle
    from socratic_engine import Truth
    # sibling names sharing the prefix are legitimate paths
    r = rsi_cycle.path_forbidden("/root/.ssh-backup/keys", tool="read")
    assert r.truth == Truth.TRUE
    r = rsi_cycle.path_forbidden("/etc/passwd123", tool="read")
    assert r.truth == Truth.TRUE


def test_exact_and_child_still_blocked():
    import rsi_cycle
    from socratic_engine import Truth
    assert rsi_cycle.path_forbidden("/root/.ssh", tool="read").truth == Truth.FALSE
    assert rsi_cycle.path_forbidden("/root/.ssh/id_rsa", tool="read").truth == Truth.FALSE
    assert rsi_cycle.path_forbidden("/etc/shadow", tool="read").truth == Truth.FALSE


def test_traversal_outside_list_passes_with_resolved_evidence():
    # normalization is universal, but the verdict is destination-vs-list:
    # ../../../tmp/x resolves outside every forbidden root -> allowed,
    # and the resolved path travels in evidence for audit.
    import rsi_cycle
    from socratic_engine import Truth
    r = rsi_cycle.path_forbidden("../../../tmp/x", tool="read")
    assert r.truth == Truth.TRUE
    assert r.evidence["resolved"] == "/tmp/x"
    r = rsi_cycle.path_forbidden("../../../root/.ssh", tool="read")
    assert r.evidence["resolved"] == "/root/.ssh"


def test_domain_ok_uses_same_normalization():
    import stub_predicates as sp
    from socratic_engine import Truth
    assert sp.script_domain_ok("../../../root/.ssh").truth == Truth.FALSE
    assert sp.script_domain_ok("/root/.ssh-backup/x").truth == Truth.TRUE


# ─── Policy blocks are not faults (S5 2026-09-10) ─────────────────────────────

def test_policy_block_skips_pipeline_and_l3(cycle):
    from vsf_rsi.rsi_socratic_bridge import list_queue
    tree = {"predicate": "action_forbidden",
            "kwargs": {"command": "rm -rf /"}}
    for _ in range(3):
        out = cycle.evaluate(tree, {})
        assert out["truth"] == "FALSE"
    assert cycle.fault_detector.get_all_faults() == []
    assert list_queue("pending") == []


def test_genuine_failure_still_enqueues(cycle):
    from vsf_rsi.rsi_socratic_bridge import list_queue
    out = cycle.evaluate({"predicate": "task_active", "kwargs": {}}, {})
    assert out["truth"] == "FALSE" and out["certified"] is True
    names = [e["name"] for e in list_queue("pending")]
    assert "fix_task_active" in names


def test_observer_actions_persist(tmp_path, monkeypatch):
    import json as _json
    import rsi_cycle
    dest = tmp_path / "observer_actions.jsonl"
    monkeypatch.setenv("RSI_OBSERVER_FILE", str(dest))
    c = rsi_cycle.RSICycle()
    c.evaluate({"predicate": "task_has_work", "kwargs": {}}, {})
    rows = [ _json.loads(l) for l in dest.read_text().splitlines() ]
    assert rows and rows[-1]["source"]


# ─── Operating thresholds (governed, bounded) ─────────────────────────────────

def test_threshold_rules(tmp_path, monkeypatch):
    import access_policy as ap
    monkeypatch.setenv("RSI_THRESHOLDS_FILE", str(tmp_path / "th.json"))
    assert ap.set_operating_threshold("nope", 1)["ok"] is False
    r = ap.set_operating_threshold("repeat_block", 2)
    assert r == {"ok": True, "previous": 3, "value": 2}
    r = ap.set_operating_threshold("repeat_block", 5)  # loosening refused
    assert r["ok"] is False and r["previous"] == 2
    r = ap.set_operating_threshold("read_warn_bytes", 100000)
    assert r["ok"] is True
    assert ap.set_operating_threshold("read_warn_bytes", 100)["ok"] is False
    assert ap.operating_thresholds()["repeat_block"] == 2


# ─── A0 purpose gate (import plan P2.1) ───────────────────────────────────────

def test_purpose_gate_blocks_reserved_wrapping():
    from rsi_cycle import purpose_gate
    ok, reason = purpose_gate(
        {"predicate": "action_forbidden", "kwargs": {"command": "x"}})
    assert ok is False and "reserved" in reason


def test_purpose_gate_blocks_forbidden_paths_in_args():
    from rsi_cycle import purpose_gate
    ok, reason = purpose_gate(
        {"predicate": "task_has_work",
         "kwargs": {"file": "/etc/shadow"}})
    assert ok is False and "forbidden path" in reason


def test_purpose_gate_blocks_malformed():
    from rsi_cycle import purpose_gate
    assert purpose_gate("nope")[0] is False
    assert purpose_gate({"nope": 1})[0] is False
    assert purpose_gate({"op": "AND", "children": "x"})[0] is False


def test_purpose_gate_allows_clean_tree():
    from rsi_cycle import purpose_gate
    ok, reason = purpose_gate(
        {"op": "AND", "children": [
            {"predicate": "task_has_work", "kwargs": {}},
            {"predicate": "file_valid", "kwargs": {"file": "docs/x.vsm"}},
        ]})
    assert ok is True, reason


def test_load_refuses_purpose_violations(tmp_path, monkeypatch):
    import json as _json
    import rsi_cycle
    monkeypatch.setenv("RSI_QUEUE_DIR", str(tmp_path / "q"))
    (tmp_path / "q").mkdir()
    (tmp_path / "q" / "evil.json").write_text(_json.dumps({
        "name": "evil_guard", "status": "approved",
        "tree": {"predicate": "path_forbidden", "kwargs": {}},
    }))
    (tmp_path / "q" / "good.json").write_text(_json.dumps({
        "name": "t12_good", "status": "approved",
        "tree": {"predicate": "task_has_work", "kwargs": {}},
    }))
    c = rsi_cycle.RSICycle()
    assert "evil_guard" not in c.get_predicates()
    assert "t12_good" in c.get_predicates()


# ─── Cycle evaluation ───────────────────────────────────────────────────────

def test_forbidden_command_blocked(cycle):
    out = cycle.evaluate(
        {"predicate": "action_forbidden", "kwargs": {"command": "rm -rf /"}},
        {},
    )
    assert out["truth"] == "FALSE" and out["certified"] is True


def test_safe_command_allowed(cycle):
    out = cycle.evaluate(
        {"predicate": "not_redundant",
         "args": ["bash", "f.txt", "echo hi"],
         "kwargs": {"recent_actions": []}},
        {},
    )
    assert out["truth"] == "TRUE" and out["certified"] is True


def test_eval_count_increments(cycle):
    before = cycle._eval_count
    cycle.evaluate({"predicate": "task_has_work", "kwargs": {}}, {})
    assert cycle._eval_count == before + 1


# ─── L3 fault detector wiring ───────────────────────────────────────────────

def test_fault_detector_triggers_on_repeated_blocking(cycle):
    """≥3 BLOCKING errors from a NON-security predicate → complex fault."""
    # Register a custom predicate that always returns FALSE (simulating a real fault).
    # task_has_work is now in NON_FAULT_PREDICATES (correct FALSE = no active work).
    @cycle.engine.register("test_always_false")
    def test_always_false(**kw):
        from socratic_engine.engine import PredicateResult, Truth
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"test": True}, source="test_always_false",
        )
    tree = {"predicate": "test_always_false"}
    for _ in range(3):
        cycle.evaluate(tree, {})
    faults = cycle.fault_detector.get_all_faults()
    assert faults, "expected a complex fault after 3 certified FALSE"
    assert all(f.error_class == "BLOCKING" for f in faults)


def test_fault_state_scoped_to_tmp(cycle):
    from vsf_rsi.rsi_fault_detector import FAULT_FILE
    assert str(FAULT_FILE).startswith(os.environ["RSI_FAULT_DIR"])


# ─── L4 ceiling: learn never registers directly (incident #2) ───────────────

def test_learn_pipeline_enqueues_never_registers():
    # NOTE: queue/stats are session-shared on purpose (mirrors production);
    # assert the ceiling shape, never absolute counts.
    out = _run_bridge("learn-pipeline")
    assert "predicates_registered" not in out, "ceiling hole is back!"
    assert "predicates_queued" in out and "queued_names" in out
    assert len(out["queued_names"]) == out["predicates_queued"]
    assert set(out["queue_stats"]) == {"pending", "approved", "activated", "rejected"}


def test_queue_approve_activate_flow(monkeypatch):
    # Tests act as the human governor (RBAC): approve needs governor.
    monkeypatch.setenv("VOS_ROLE", "governor")
    from vsf_rsi.rsi_socratic_bridge import enqueue_predicate
    qpath = enqueue_predicate(
        "t11_probe", {"predicate": "task_has_work", "kwargs": {}},
        source="test", description="T1.1 probe",
    )
    assert str(qpath).startswith(os.environ["RSI_QUEUE_DIR"])

    pending = _run_bridge("rsi-queue")
    assert any(e["name"] == "t11_probe" for e in pending["entries"])

    approved = _run_bridge("rsi-approve", "t11_probe")
    assert approved["approved"] is True

    import rsi_cycle
    fresh = rsi_cycle.RSICycle()
    assert "t11_probe" in fresh.get_predicates()  # activation-by-approval
    out = fresh.evaluate({"predicate": "t11_probe"}, {})
    assert out["certified"] is True


def test_precheck_attributes_security_failure():
    # Regression: the AND verdict source is "op:AND" — without
    # failed_predicates the TS SECURITY_SOURCES check can never fire.
    import json as _json
    out = _run_bridge("pre-check", _json.dumps(
        {"tool": "read", "file": "/etc/shadow", "command": ""}))
    soc = out["socratic"]
    assert soc["truth"] == "FALSE" and soc["certified"] is True
    assert "path_forbidden" in soc.get("failed_predicates", [])
    assert out["ok"] is False


def test_precheck_clean_read_has_no_failed_predicates():
    import json as _json
    out = _run_bridge("pre-check", _json.dumps(
        {"tool": "read", "file": "docs/plans/x.vsm", "command": ""}))
    assert out["socratic"]["truth"] == "TRUE"
    assert out["ok"] is True


def test_vsm_check_content_flags_bad_version():
    import json as _json
    bad = ("⟦ x | T-v1 | vsm-1.2 | 2026-09-10T03:10:11Z ⟧\n\n@vsm 1.2\n"
           "@status active\n\n⟦ /x ⟧\n")
    out = _run_bridge("vsm-check-content", _json.dumps({"content": bad}))
    assert out["valid"] is False
    assert any("Wrong version" in e for e in out["errors"])


def test_vsm_check_content_passes_good_doc():
    import json as _json
    good = ("⟦ x | T-v1 | vsm-1.2.1 | 2026-09-10T03:11:22Z ⟧\n\n@vsm 1.2.1\n"
            "@status active\n\n⟦ /x ⟧\n")
    out = _run_bridge("vsm-check-content", _json.dumps({"content": good}))
    assert out["valid"] is True


def test_bridge_rsi_status_ok():
    out = _run_bridge("rsi-status")
    assert out["cycle_available"] is True
    assert "not_redundant" in out["predicates"]
