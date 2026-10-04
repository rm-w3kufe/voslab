"""Tests for AuditEnforcer (audit-only, never blocks)."""
import json

from vos_kernel.enforcer import AuditEnforcer


def test_nominal_passes():
    enf = AuditEnforcer()
    v = enf.audit({"tool": "write", "file": "x.py",
                   "s5_trust": 0.8, "autonomy": 0.5})
    assert v.would_block is False and v.rule is None


def test_coercion_command_blocks():
    enf = AuditEnforcer()
    v = enf.audit({"tool": "bash", "file": "",
                   "command": "rm -rf /",
                   "s5_trust": 0.8, "autonomy": 0.5})
    assert v.would_block is True and v.rule == "A0.1"


def test_low_trust_blocks():
    enf = AuditEnforcer()
    v = enf.audit({"tool": "write", "file": "x.py",
                   "s5_trust": 0.2, "autonomy": 0.1})
    assert v.would_block is True and v.rule == "TRUST"


def test_autonomy_exceeds_trust_blocks():
    enf = AuditEnforcer()
    v = enf.audit({"tool": "write", "file": "x.py",
                   "s5_trust": 0.5, "autonomy": 0.9})
    assert v.would_block is True and v.rule == "A5"


def test_never_raises_on_garbage():
    enf = AuditEnforcer()
    v = enf.audit({"s5_trust": "nan-x", "autonomy": object()})
    assert v.would_block is False  # audit degrades, never breaks callers


def test_log_and_summary(tmp_path):
    log = tmp_path / "audit.jsonl"
    enf = AuditEnforcer(log_path=log)
    enf.audit({"tool": "write", "file": "a.py"})
    enf.audit({"tool": "bash", "file": "", "command": "rm -rf /"})
    s = enf.summary()
    assert s["audited"] == 2 and s["would_block"] == 1
    assert s["by_rule"] == {"A0.1": 1}
    assert abs(s["block_rate"] - 0.5) < 1e-9
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(rows) == 2 and rows[1]["rule"] == "A0.1"
