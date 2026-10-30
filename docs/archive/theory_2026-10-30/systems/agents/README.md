# LLM Agents — two planes

**Date:** 2026-05-25 (runtime), 2026-05-31 (opsroom layer added)
**Status:** Phase 3+ (post no-external ceiling, cycle 3)
**Method:** Derived mechanically from per-system docs per `per_system_requirements_method.md §4`

This directory organizes **two independent agent planes**:

| Plane | Where | When | LLM | Files |
|-------|-------|------|-----|-------|
| **[`runtime/`](runtime/)** | n02 LXCs | 24/7 autonomous | Qwen (Ollama) | S3*, S4, S5 prompts |
| **[`opsroom/`](opsroom/)** | WSL (operator laptop) | Operator-present only | Claude | All 6 S + Research + Orchestrator + Guest pattern |

The two planes do not communicate in real time. The bridge is
git + `state.db`. See `opsroom/README.md §"Runtime separation"`.

The section below covers the **runtime plane** — the canonical
constraint that LLM is permitted *inside the kernel* only at
S3*/S4/S5. The opsroom plane is **D6-exempt** because it does not
participate in the runtime loop.

## Which kernel subsystems get an LLM agent?

Per **Qwen consensus ronda 3** + **D6 axiom** + **per_system_requirements_method.md**:

| Subsystem | LLM Agent? | Reason |
|---|---|---|
| S1 Operations | ❌ NO | D6: L=0/1, deterministic Rust required (<10ms) |
| S2 Coordination | ❌ NO | Mechanical pattern matching, no cognitive work |
| S3 Control | ❌ NO | Deterministic regulation; delegates cognitive to S4 |
| **S3* Audit** | ✅ YES (read-only) | Pattern detection in events.jsonl benefits from contextual reasoning |
| **S4 Intelligence** | ✅ YES (Qwen active) | D6 explicit; environmental scanning + future modelling |
| **S5 Policy** | ◐ HIGH-RISK proposal-only | Read-only proposals; execution always requires human (A5) |

**Principle**: LLMs are tools INSIDE S4/S5/S3*, NOT substitutes for deterministic regulators (Qwen ronda 3 corrected bias).

## How each agent prompt is derived

From per-system doc §1 (Identity) + §2 (Interface) + §3 (Decisions) + §4 (Constraints) + §5 (Invariants):

```
identity §1   → agent persona/scope
interface §2  → agent's tools (NATS subjects to read/write)
decisions §3  → agent action space (single-loop) + refusals (double-loop)
constraints §4 → agent absolute refusals (A0/A0.1/A4/A5/D6/D11/D13)
invariants §5 → agent pre-action checks
```

Each agent is a SYSTEM PROMPT + a thin orchestrator (Rust nucleus calls into Qwen via Ollama with the prompt).

## Runtime agent files

Now under `runtime/`:

| File | Status |
|---|---|
| [runtime/S4_agent_prompt.md](runtime/S4_agent_prompt.md) | ✓ ACTIVE (currently running in nucleus s4_operational.rs) |
| [runtime/S3_star_agent_prompt.md](runtime/S3_star_agent_prompt.md) | ◯ Designed, not yet implemented |
| [runtime/S5_agent_prompt.md](runtime/S5_agent_prompt.md) | ◯ Designed, not yet implemented |

## Opsroom agent files

Under `opsroom/` (added 2026-05-31, post-cycle-3 ceiling):

| File | Role |
|---|---|
| [opsroom/README.md](opsroom/README.md) | Runtime separation, Cybersyn 7-chair adaptation, policy alignment |
| [opsroom/Orchestrator.md](opsroom/Orchestrator.md) | Main Claude session (the seat you're in right now) |
| [opsroom/S1_specialist.md](opsroom/S1_specialist.md) | Operations module R&D |
| [opsroom/S2_specialist.md](opsroom/S2_specialist.md) | Coordination R&D |
| [opsroom/S3_specialist.md](opsroom/S3_specialist.md) | Control / regulator R&D |
| [opsroom/S3_star_specialist.md](opsroom/S3_star_specialist.md) | Audit logic R&D + meta-auditor |
| [opsroom/S4_specialist.md](opsroom/S4_specialist.md) | Cognitive prompt engineering + K_φ↓ measurement |
| [opsroom/S5_specialist.md](opsroom/S5_specialist.md) | Policy + covenant drafting (HIGH-RISK proposal-only) |
| [opsroom/Research_specialist.md](opsroom/Research_specialist.md) | Papers + experiments + theory + glossary |
| [opsroom/Guest_pattern.md](opsroom/Guest_pattern.md) | How to invite ad-hoc specialists (dashboards, audits, security reviews) |

## Runtime integration plan

1. **S4 agent** — already implemented in `s4_operational.rs::run_cycle`. This doc captures the **canonical prompt** (currently hard-coded in Rust) for review + refinement.

2. **S3* agent** — to be implemented when `s3_star.rs` module exists. Will run as separate Tokio task under Supervisor(S3Star) with read-only events.jsonl access + independent Qwen instance (per Qwen ronda 3 — separate from S4 to avoid model bias propagation).

3. **S5 agent** — last to implement. Strictly read-only LLM proposals. Every output must be verified by external witnesses (gemini-vsl-core, GPT-4o) before any execution. Human gate (A5) enforced at code level.

## Runtime validator (required per Qwen ronda 3 §3)

For all LLM agents:
```
LLM agent output → schema validator → covenant check → invariant check → emit
                   ^ runtime code, not LLM logic
```

The prompt declares the role; **runtime enforcement** guarantees compliance. A captured/drifted LLM produces plausible-looking output that violates invariants subtly. The validator catches this.
