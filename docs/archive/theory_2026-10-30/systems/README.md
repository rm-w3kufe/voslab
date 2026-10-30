# VSF Per-System Specifications

**Date:** 2026-05-24
**Method:** [../per_system_requirements_method.md](../per_system_requirements_method.md)
**Parent:** [../information_flow_architecture.md](../information_flow_architecture.md)

This directory contains the formal specification of each VSM subsystem within `vsf-nucleus`, following the per-system method (5 mandatory sections: Identity, Interface, Decision space, Constraints, Invariants).

These documents are the **canonical source** for:
- Code module implementation (what each Rust module must do)
- LLM agent prompt derivation (when applicable per D6)
- Audit verification (S3* checks each system against its invariants)
- Replication to new VSFs (copy + adapt per_system_requirements_method)

---

## Subsystem catalog

| System | Doc | VSM Role | LLM Use (per Qwen ronda 3) | Implementation Status |
|---|---|---|---|---|
| **S1** | [S1_operations.md](S1_operations.md) | Operations — units doing the work | ❌ Code-only (deterministic <10ms) | ◐ Partial (RecursiveKernel exists, bounded_self_correction pending) |
| **S2** | [S2_coordination.md](S2_coordination.md) | Coordination — anti-oscillation | ❌ Code-only (mechanical pattern matching) | ❌ Implicit only (tokio primitives, no explicit module) |
| **S3** | [S3_control.md](S3_control.md) | Control — resource allocation, NOW | ❌ Code-only (deterministic regulation). Cognitive work delegated to S4. | ◐ Partial (cgroup + telemetry, no escalation logic) |
| **S3*** | [S3_star_audit.md](S3_star_audit.md) | Audit — anti-capture, bypasses S3 | ✓ LLM read-only (pattern detection in events.jsonl). Independent Qwen instance. | ◐ Partial (covenant verify + honeypot only) |
| **S4** | [../per_system_requirements_method.md §2](../per_system_requirements_method.md) | Intelligence — environmental + future | ✓ LLM (Qwen) — D6 explicit | ✓ Operational (Qwen 2.5-coder via Ollama) |
| **S5** | [S5_policy.md](S5_policy.md) | Policy — identity, axioms, authority | ◐ LLM read-only proposals; execution requires human (A5) + witness validation | ◐ Partial (covenant active, s5_policy.json pending) |

**Per Qwen ronda 3: LLM permitted only in S3*/S4/S5 (cognitive layers). S1-S2-S3 remain deterministic to preserve <10ms guarantees and `r_L≥0.9`.** Treating LLM as substitute for deterministic regulators violates first-order cybernetics (VSM is structure of variety, not architecture of AI).

---

## How to read these docs

Each doc has exactly **5 mandatory sections**. To check coherence:

1. **§1 Identity** ↔ matches an actual code module or planned module
2. **§2 Interface** ↔ matches `core/connection_schema.json` channel definitions
3. **§3 Decision space** ↔ A5 boundary clearly drawn (single-loop vs double-loop)
4. **§4 Constraints** ↔ inherited from covenant.vsm + system-specific
5. **§5 Invariants** ↔ measurable thresholds with violation actions

If any section reads ◯ DESIGN, it specifies what the system must become.
If ◐ PARTIAL, implementation is incomplete — actionable debt.
If ✓ VERIFIED, code matches the spec today.

---

## From spec to LLM agent

For systems where D6 permits LLM use (S3, S3*, S4, S5):

```
spec_section §1.purpose      → agent persona/scope
spec_section §2.channels     → agent tools (read/write subjects)
spec_section §3.single_loop  → agent action space
spec_section §3.double_loop  → agent refusals (must escalate, not execute)
spec_section §4.constraints  → agent absolute refusals
spec_section §5.invariants   → agent pre-action checks
```

See parent method doc §4 for the formal derivation template.

---

## Implementation priority (debt ranking)

Critical for VSF viability:

1. **S5 human approval gate** (S5_I3) — A5 violation at S5 = existential risk
2. **S3* audit module** (events.jsonl chain integrity) — without S3*, cannot detect capture
3. **S2 explicit coordinator** (DEBT-13) — current implicit coordination won't scale
4. **S3 escalation logic** — for proper double-loop routing to S5
5. **S1 bounded_self_correction** — formal definition + enforcement

---

## Cross-system invariants summary

| Invariant | Owner | Measurement |
|---|---|---|
| events.jsonl chain integrity | S3* (S3*_I1) | SHA256 rolling hash |
| covenant_hash stable | S3* (S3*_I2) + S5 (S5_I1) | --verify-covenant + remote compare |
| state_vector ∈ Ω | S1 (S1_I1) | omega_validator.rs |
| stasis_cos ≥ 0.90 | S1 (S1_I3) | stasis.rs over rolling window |
| trust(V) > τ_L | S1 (S1_I4) + S3 (S3_I5) + S5 (S5_I4) | composition rules D11/D11b |
| A0 enforcement irrevocable | S5 (S5_I6) | trust history |
| double-loop = human | S5 (S5_I3) | A5 audit |
| bilateral ψ | S5 (S5_I5) | handshake records |
| A4 preservation (no direct S1↔S1) | S2 (S2_I4) | S3* subject scan |
| resource conservation | S3 (S3_I1) | cgroup totals ≤ budget |

---

## Replication to new VSFs (future)

When this catalog is complete + agents are implemented:

```
Copy /home/rmw3/vsf/docs/theory/systems/ to new VSF
Adapt:
  - system_id field per subsystem
  - vsf_id in NATS subjects
  - purpose paragraph if scope differs
Implement:
  - same canonical channels
  - same invariants
  - same agent prompts (parametrized by system_id)
Establish:
  - ψ handshake between original.S5 and replica.S5
  - Bilateral trust ≥ limited
```

This is the path from "1 VSF" to "VSF as replicable framework".
