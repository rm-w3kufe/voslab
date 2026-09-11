#!/usr/bin/env python3
"""risk_assessor.py — Pre-action risk assessment for the cognitive pipeline.

Evaluates every state-changing action before execution and returns:
  - risk_score: numeric (0-20+)
  - risk_level: LOW | MEDIUM | HIGH | CRITICAL | BLOCKED
  - confidence: 0.0-1.0 (how much we know about this action)
  - factors: detailed breakdown of what contributed
  - recommendation: what to do (proceed | warn | confirm | block)

Integration: called by tool-integration.ts via bridge, or directly.

Design principle: R17 (destructive explicit consent) + new RISK-ASSESSMENT.
Every action that could harm the system gets a risk score BEFORE execution.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


# ─── Risk Levels ──────────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW = "LOW"           # 0-3:  proceed (advisory log)
    MEDIUM = "MEDIUM"     # 4-7:  proceed with warning
    HIGH = "HIGH"         # 8-11: require explicit confirmation
    CRITICAL = "CRITICAL" # 12-15: block + require S5 approval
    BLOCKED = "BLOCKED"   # 16+:  hard block, never proceed


# ─── Criticality Maps ─────────────────────────────────────────────────────────

# File patterns → criticality score (0-4)
CRITICALITY_MAP = {
    # Canon docs (4 = highest)
    r"docs/spec_revision/": 4,
    r"RULES\.md$": 4,
    r"hard_rules\.vsm$": 4,
    r"boot_manifest\.vsm$": 4,

    # Plugins (3)
    r"\.opencode/plugins/": 3,
    r"opencode\.json$": 3,

    # Config files (2)
    r"TASKS\.vsm$": 2,
    r"HANDOFF\.vsm\.md$": 2,
    r"current_focus\.json$": 2,
    r"state_journal.*\.db$": 2,
    r"AGENTS\.md$": 2,

    # Scripts (1)
    r"scripts/": 1,
    r"\.py$": 1,
    r"\.sh$": 1,

    # Regular files (0)
}

# Paths that are destructive to modify
DESTRUCTIVE_PATHS = [
    r"\.opencode/plugins/.*\.ts$",     # plugins
    r"opencode\.json$",                 # config
    r"state_journal.*\.db$",            # state databases
    r"\.vsm$",                          # canon documents
]

# Bash patterns that are destructive
DESTRUCTIVE_BASH_PATTERNS = [
    (r"rm\s+-rf", "recursive delete"),
    (r"rm\s+-r\b", "recursive delete"),
    (r"git\s+reset\s+--hard", "hard reset"),
    (r"git\s+clean\s+-fd", "clean untracked"),
    (r"git\s+push.*--force", "force push"),
    (r"git\s+push.*-f\b", "force push"),
    (r"drop\s+table", "database drop"),
    (r"drop\s+database", "database drop"),
    (r"truncate", "table truncate"),
    (r"kill\s+-9", "force kill"),
    (r"systemctl\s+stop", "service stop"),
    (r"systemctl\s+disable", "service disable"),
    (r"pct\s+stop", "LXC stop"),
    (r"pct\s+destroy", "LXC destroy"),
]


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class RiskFactor:
    name: str
    score: int
    max_score: int
    reason: str
    details: dict = field(default_factory=dict)


@dataclass
class RiskAssessment:
    risk_score: int
    risk_level: str
    confidence: float
    factors: list[dict]
    recommendation: str
    summary: str
    verbose: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Assessor ─────────────────────────────────────────────────────────────────

class RiskAssessor:
    """Evaluates risk of a proposed action before execution."""

    def __init__(self, workspace_root: str | Path | None = None):
        self.workspace = Path(workspace_root) if workspace_root else Path.cwd()

    def assess(
        self,
        tool: str,
        file: str = "",
        command: str = "",
        content: str = "",
        extra: dict | None = None,
        verbose: bool = False,
    ) -> RiskAssessment:
        """Full risk assessment of a proposed action.

        Args:
            tool: tool name (write, edit, bash, read, etc.)
            file: target file path
            command: bash command (if tool=bash)
            content: file content being written (if available)
            extra: additional context (batch size, etc.)
            verbose: include full reasoning chain
        """
        factors: list[RiskFactor] = []
        extra = extra or {}

        # 1. Action type risk
        factors.append(self._assess_action_type(tool, command))

        # 2. Target criticality
        factors.append(self._assess_target_criticality(file))

        # 3. Scope (batch operations)
        factors.append(self._assess_scope(tool, file, command, extra))

        # 4. Reversibility
        factors.append(self._assess_reversibility(tool, file, command))

        # 5. Blast radius
        factors.append(self._assess_blast_radius(file, command))

        # 6. Destructive patterns
        factors.append(self._assess_destructive_patterns(file, command))

        # 7. Historical risk (from integration log)
        factors.append(self._assess_historical_risk(tool, file))

        # 8. Trust level (S5 trust in this action context)
        factors.append(self._assess_trust(tool, file, command))

        # Calculate totals
        total_score = sum(f.score for f in factors)
        max_possible = sum(f.max_score for f in factors)

        # Confidence: based on how many factors we could evaluate
        evaluated = sum(1 for f in factors if f.score > 0 or f.max_score > 0)
        confidence = evaluated / len(factors) if factors else 0.0

        # Risk level
        risk_level = self._score_to_level(total_score)

        # Recommendation
        recommendation = self._recommend(risk_level, confidence)

        # Summary
        summary = self._build_summary(total_score, risk_level, factors)

        # Verbose chain
        verbose_data = {}
        if verbose:
            verbose_data = {
                "factors": [asdict(f) for f in factors],
                "total_score": total_score,
                "max_possible": max_possible,
                "confidence": confidence,
                "risk_level": risk_level,
                "recommendation": recommendation,
                "reasoning_chain": self._build_reasoning_chain(factors),
            }

        return RiskAssessment(
            risk_score=total_score,
            risk_level=risk_level,
            confidence=confidence,
            factors=[asdict(f) for f in factors],
            recommendation=recommendation,
            summary=summary,
            verbose=verbose_data,
        )

    # ─── Factor Assessors ─────────────────────────────────────────────────

    def _assess_action_type(self, tool: str, command: str) -> RiskFactor:
        """Risk from the type of action being performed."""
        READ_TOOLS = {"read", "glob", "grep", "list_mcp_resources"}
        WRITE_TOOLS = {"write", "edit"}
        BASH_TOOLS = {"bash"}

        if tool in READ_TOOLS:
            score = 0
            reason = "read-only action, no state change"
        elif tool in WRITE_TOOLS:
            score = 2
            reason = "state-modifying action (write/edit)"
        elif tool in BASH_TOOLS:
            score = 3
            reason = "bash execution — arbitrary command"
        elif tool == "task":
            score = 1
            reason = "task dispatch — creates subagent"
        else:
            score = 1
            reason = f"unknown tool: {tool}"

        return RiskFactor(
            name="action_type",
            score=score,
            max_score=3,
            reason=reason,
            details={"tool": tool},
        )

    def _assess_target_criticality(self, file: str) -> RiskFactor:
        """Risk from WHAT is being modified."""
        if not file:
            return RiskFactor(
                name="target_criticality",
                score=0, max_score=4,
                reason="no file target",
            )

        max_criticality = 0
        matched_pattern = None

        for pattern, criticality in CRITICALITY_MAP.items():
            if re.search(pattern, file):
                if criticality > max_criticality:
                    max_criticality = criticality
                    matched_pattern = pattern

        reasons = {
            0: "regular file",
            1: "script — affects automation",
            2: "config/state — affects system behavior",
            3: "plugin/opencode config — affects all sessions",
            4: "canon document — affects system-wide rules",
        }

        return RiskFactor(
            name="target_criticality",
            score=max_criticality,
            max_score=4,
            reason=reasons.get(max_criticality, "unknown"),
            details={"file": file, "matched_pattern": matched_pattern},
        )

    def _assess_scope(self, tool: str, file: str, command: str, extra: dict) -> RiskFactor:
        """Risk from how many things are affected."""
        batch_size = extra.get("batch_size", 1)

        if batch_size > 10:
            score = 3
            reason = f"batch operation: {batch_size} items"
        elif batch_size > 3:
            score = 2
            reason = f"multi-file operation: {batch_size} items"
        elif batch_size > 1:
            score = 1
            reason = f"small batch: {batch_size} items"
        else:
            score = 0
            reason = "single target"

        # Bash commands that affect multiple files
        if tool == "bash" and command:
            if re.search(r"find.*-exec", command):
                score = max(score, 3)
                reason = "find -exec: affects matching files"
            elif re.search(r"\*\.\w+", command):
                score = max(score, 2)
                reason = "glob pattern in command"
            elif re.search(r"sed\s+-i", command):
                score = max(score, 2)
                reason = "in-place sed: modifies files"

        return RiskFactor(
            name="scope",
            score=score,
            max_score=3,
            reason=reason,
            details={"batch_size": batch_size},
        )

    def _assess_reversibility(self, tool: str, file: str, command: str) -> RiskFactor:
        """Risk from how hard it is to undo."""
        if tool == "bash" and command:
            # Check for destructive bash patterns
            for pattern, desc in DESTRUCTIVE_BASH_PATTERNS:
                if re.search(pattern, command):
                    return RiskFactor(
                        name="reversibility",
                        score=3,
                        max_score=3,
                        reason=f"destructive: {desc}",
                        details={"pattern": pattern},
                    )

        # File operations
        if file:
            # Git-revertable files
            if self._is_in_git(file):
                return RiskFactor(
                    name="reversibility",
                    score=0,
                    max_score=3,
                    reason="git-tracked, revertable",
                    details={"file": file},
                )

            # State databases (hard to undo)
            if re.search(r"\.db$", file):
                return RiskFactor(
                    name="reversibility",
                    score=3,
                    max_score=3,
                    reason="database file, difficult to undo",
                    details={"file": file},
                )

        return RiskFactor(
            name="reversibility",
            score=1,
            max_score=3,
            reason="unknown reversibility",
        )

    def _assess_blast_radius(self, file: str, command: str) -> RiskFactor:
        """Risk from how far the effects spread."""
        if not file and not command:
            return RiskFactor(
                name="blast_radius",
                score=0, max_score=4,
                reason="no target identified",
            )

        # System-wide effects
        if command and any(p in command for p in ["systemctl", "nats", "opencode"]):
            return RiskFactor(
                name="blast_radius",
                score=4, max_score=4,
                reason="system-wide effect",
            )

        # Shared workspace (resolved dynamically — no hardcoded usernames;
        # self_maintaining hygiene 2026-09-10)
        _ws = os.path.expanduser("~/vOSlab/")
        if file and _ws in file and "/child/" not in file:
            return RiskFactor(
                name="blast_radius",
                score=3, max_score=4,
                reason="shared workspace (parent repo)",
            )

        # Child workspace only
        if file and "/child/" in file:
            return RiskFactor(
                name="blast_radius",
                score=2, max_score=4,
                reason="child workspace",
            )

        # Self-only
        return RiskFactor(
            name="blast_radius",
            score=1, max_score=4,
            reason="self-contained effect",
        )

    def _assess_destructive_patterns(self, file: str, command: str) -> RiskFactor:
        """Risk from known destructive patterns."""
        score = 0
        reasons = []

        # Check file path for destructive targets
        if file:
            for pattern in DESTRUCTIVE_PATHS:
                if re.search(pattern, file):
                    score += 1
                    reasons.append(f"destructive target: {pattern}")

        # Check bash for destructive commands
        if command:
            for pattern, desc in DESTRUCTIVE_BASH_PATTERNS:
                if re.search(pattern, command):
                    score += 2
                    reasons.append(f"destructive command: {desc}")

        return RiskFactor(
            name="destructive_patterns",
            score=min(score, 3),
            max_score=3,
            reason="; ".join(reasons) if reasons else "no destructive patterns detected",
            details={"matched": reasons},
        )

    def _assess_historical_risk(self, tool: str, file: str) -> RiskFactor:
        """Risk from past failures with similar actions."""
        log_path = self.workspace / "state" / "integration_log.jsonl"
        if not log_path.exists():
            return RiskFactor(
                name="historical_risk",
                score=0, max_score=2,
                reason="no history available",
            )

        try:
            failures = 0
            recent_total = 0
            with open(log_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("phase") != "after":
                            continue
                        recent_total += 1
                        if (entry.get("tool") == tool and
                            entry.get("outcome") == "failure"):
                            failures += 1
                    except json.JSONDecodeError:
                        continue

            if failures >= 3:
                return RiskFactor(
                    name="historical_risk",
                    score=2, max_score=2,
                    reason=f"{failures} recent failures with {tool}",
                    details={"failures": failures, "total": recent_total},
                )
            elif failures >= 1:
                return RiskFactor(
                    name="historical_risk",
                    score=1, max_score=2,
                    reason=f"{failures} recent failure(s) with {tool}",
                    details={"failures": failures, "total": recent_total},
                )

            return RiskFactor(
                name="historical_risk",
                score=0, max_score=2,
                reason="no recent failures",
                details={"total": recent_total},
            )
        except Exception:
            return RiskFactor(
                name="historical_risk",
                score=0, max_score=2,
                reason="history check failed",
            )

    def record_outcome(self, file: str, ok: bool) -> float:
        """Update per-file trust from an observed outcome (A4 writer).

        Success +0.05 (cap 1.0), failure -0.20 (floor 0.0), new files
        start at 0.7. Best-effort: IO errors keep memory state only.
        Returns the new trust score.
        """
        trust_path = self.workspace / ".trust_state.json"
        try:
            data = json.loads(trust_path.read_text())
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        key = file or "__global__"
        try:
            current = float(data.get(key, data.get("__global__", 0.7)))
        except (TypeError, ValueError):
            current = 0.7
        new = min(1.0, current + 0.05) if ok else max(0.0, current - 0.20)
        data[key] = round(new, 3)
        try:
            trust_path.write_text(json.dumps(data, indent=2))
        except OSError:
            pass
        return new

    def _assess_trust(self, tool: str, file: str, command: str) -> RiskFactor:
        """Risk from trust level in this action context.

        Trust is tracked per-file in .trust_state.json (see record_outcome).
        Low trust = higher risk (action might exceed allowed bounds).
        """
        trust_path = self.workspace / ".trust_state.json"
        if not trust_path.exists():
            return RiskFactor(
                name="trust",
                score=1, max_score=3,
                reason="no trust state — assuming medium (0.7)",
                details={"trust_score": 0.7, "source": "default"},
            )

        try:
            with open(trust_path) as f:
                trust_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return RiskFactor(
                name="trust",
                score=1, max_score=3,
                reason="trust state unreadable — assuming medium",
                details={"trust_score": 0.7, "source": "error"},
            )

        file_trust = trust_data.get(file, trust_data.get("__global__", 0.7))
        trust_score = float(file_trust)

        if trust_score < 0.3:
            return RiskFactor(
                name="trust",
                score=3, max_score=3,
                reason=f"trust critically low ({trust_score:.2f}) — action likely exceeds bounds",
                details={"trust_score": trust_score, "threshold": 0.3},
            )
        elif trust_score < 0.5:
            return RiskFactor(
                name="trust",
                score=2, max_score=3,
                reason=f"trust low ({trust_score:.2f}) — action may exceed bounds",
                details={"trust_score": trust_score, "threshold": 0.5},
            )
        elif trust_score < 0.7:
            return RiskFactor(
                name="trust",
                score=1, max_score=3,
                reason=f"trust moderate ({trust_score:.2f})",
                details={"trust_score": trust_score, "threshold": 0.7},
            )
        else:
            return RiskFactor(
                name="trust",
                score=0, max_score=3,
                reason=f"trust adequate ({trust_score:.2f})",
                details={"trust_score": trust_score, "threshold": 0.7},
            )

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _is_in_git(self, file: str) -> bool:
        """Check if file is tracked by git."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "ls-files", "--error-unmatch", file],
                capture_output=True, text=True, timeout=5,
                cwd=str(self.workspace),
            )
            return result.returncode == 0
        except Exception:
            return False

    def _score_to_level(self, score: int) -> str:
        """Convert numeric score to risk level."""
        if score <= 3:
            return RiskLevel.LOW.value
        elif score <= 7:
            return RiskLevel.MEDIUM.value
        elif score <= 11:
            return RiskLevel.HIGH.value
        elif score <= 15:
            return RiskLevel.CRITICAL.value
        else:
            return RiskLevel.BLOCKED.value

    def _recommend(self, level: str, confidence: float) -> str:
        """Generate recommendation based on risk level."""
        recommendations = {
            RiskLevel.LOW: "proceed",
            RiskLevel.MEDIUM: "proceed_with_warning",
            RiskLevel.HIGH: "require_confirmation",
            RiskLevel.CRITICAL: "block_require_s5",
            RiskLevel.BLOCKED: "hard_block",
        }
        base = recommendations.get(level, "require_confirmation")

        # Low confidence → more cautious
        if confidence < 0.5 and level in (RiskLevel.MEDIUM, RiskLevel.HIGH):
            base = "require_confirmation"

        return base

    def _build_summary(self, score: int, level: str, factors: list[RiskFactor]) -> str:
        """Build human-readable summary."""
        top_factors = sorted(factors, key=lambda f: f.score, reverse=True)[:3]
        drivers = [f"{f.name}: {f.reason}" for f in top_factors if f.score > 0]

        return (
            f"Risk {level} (score={score}). "
            f"Top factors: {'; '.join(drivers) if drivers else 'none'}"
        )

    def _build_reasoning_chain(self, factors: list[RiskFactor]) -> list[dict]:
        """Build verbose reasoning chain for debugging."""
        chain = []
        for i, f in enumerate(factors, 1):
            chain.append({
                "step": i,
                "factor": f.name,
                "score": f"{f.score}/{f.max_score}",
                "reason": f.reason,
                "details": f.details,
            })
        return chain


# ─── CLI Interface ────────────────────────────────────────────────────────────

def main():
    """CLI: python3 risk_assessor.py <tool> [file] [command] [--verbose]"""
    import sys

    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: risk_assessor.py <tool> [file] [command] [--verbose]"}))
        sys.exit(1)

    tool = sys.argv[1]
    file = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else ""
    command = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("-") else ""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    # Parse extra from stdin if available
    extra = {}
    if not sys.stdin.isatty():
        try:
            extra = json.loads(sys.stdin.read())
        except Exception:
            pass

    assessor = RiskAssessor()
    result = assessor.assess(tool, file, command, extra=extra, verbose=verbose)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
