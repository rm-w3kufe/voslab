"""enforcer.py — Policy enforcement (audit-only phase).

S3 control plane, stage 2 (after the covenant seed on LXC 107).
Phased rollout by design:

  Phase 1 (this module): AUDIT-ONLY. For each event, compute what WOULD
  be blocked/allowed under covenant rules and log the counterfactual.
  Never blocks. Promotion to enforcement requires weeks of audit log
  with zero false positives on sampled review (S5 call).

  Phase 2 (future): enforce mode wraps audit + acts. Gated on phase-1
  evidence, shadow-tested like L3 strategies.

Reuses CovenantEnforcer.evaluate (A0/A0.1/TRUST/A5) — no duplicated
policy logic. Adds the action layer covenant.py lacks: mapping
(tool, file, command) events to pressure/trust/autonomy inputs.

Usage:
    from vos_kernel.enforcer import AuditEnforcer
    enf = AuditEnforcer()
    v = enf.audit({"tool": "write", "file": "x.py",
                   "s5_trust": 0.8, "autonomy": 0.5})
    v.would_block  # False
    v.rule         # None (or axiom id)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from vos_kernel.covenant import CovenantEnforcer


@dataclass
class AuditVerdict:
    """Counterfactual enforcement decision (no action taken)."""
    would_block: bool
    rule: Optional[str]  # axiom id or None
    evidence: dict = field(default_factory=dict)
    ts: str = ""

    def __post_init__(self):
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()


# Tools whose commands carry pressure semantics worth mapping.
PRESSURE_COMMANDS = ("rm -rf", "drop table", "exfiltrate", "chmod 777")


def _pressure_for(event: dict) -> Optional[str]:
    cmd = str(event.get("command", "") or "")
    for p in PRESSURE_COMMANDS:
        if p in cmd:
            return "coercion"
    return event.get("pressure")


class AuditEnforcer:
    """Audit-only policy enforcement over covenant rules."""

    def __init__(self, log_path: Optional[Path] = None):
        self._enforcer = CovenantEnforcer()
        self._log_path = Path(log_path) if log_path else None
        self._stats = {"audited": 0, "would_block": 0,
                       "by_rule": {}}

    def audit(self, event: dict) -> AuditVerdict:
        """Evaluate what WOULD happen. Never blocks, never raises."""
        try:
            s5 = float(event.get("s5_trust", 0.8))
            aut = float(event.get("autonomy", 0.5))
            verdict = self._enforcer.evaluate(
                s5_trust=s5, op_autonomy=aut,
                pressure=_pressure_for(event))
        except Exception as e:  # noqa: BLE001 — audit must not break callers
            return AuditVerdict(would_block=False, rule=None,
                                evidence={"audit_error": str(e)[:120]})
        rule = verdict.violations[0].axiom if verdict.violations else None
        out = AuditVerdict(
            would_block=not verdict.passed,
            rule=rule,
            evidence={
                "tool": event.get("tool", ""),
                "file": event.get("file", ""),
                "backend": self._enforcer._backend,
                "violations": len(verdict.violations),
            },
        )
        self._stats["audited"] += 1
        if out.would_block:
            self._stats["would_block"] += 1
            self._stats["by_rule"][rule] = \
                self._stats["by_rule"].get(rule, 0) + 1
        if self._log_path is not None:
            try:
                with open(self._log_path, "a") as f:
                    f.write(json.dumps({
                        "ts": out.ts, "would_block": out.would_block,
                        "rule": out.rule, **out.evidence}) + "\n")
            except OSError:
                pass
        return out

    def summary(self) -> dict:
        """Audit log summary for S5 promotion review."""
        s = dict(self._stats)
        s["block_rate"] = (s["would_block"] / s["audited"]
                           if s["audited"] else 0.0)
        return s
