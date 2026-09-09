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
              "naming_conforms", "scripts_manifest"}


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
    assert rsi_cycle.FORBIDDEN_PATHS == sp.FORBIDDEN_PATHS


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
    tree = {"predicate": "action_forbidden",
            "kwargs": {"command": "rm -rf /"}}
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


def test_queue_approve_activate_flow():
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


def test_bridge_rsi_status_ok():
    out = _run_bridge("rsi-status")
    assert out["cycle_available"] is True
    assert "not_redundant" in out["predicates"]
