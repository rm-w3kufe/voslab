# S1 — Operations (vsf-nucleus.s1)
> **STATUS: historical_record** — consumido por fuse VOS-CORE-THEORY → s1_spec.vsm + vos_core_theory.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Document version:** 1.0
**Date:** 2026-05-24
**Method:** [per_system_requirements_method.md](../per_system_requirements_method.md)
**VSM role:** S1 (Operations)
**Confidence markers:** ✓ VERIFIED | ◐ PARTIAL | ◯ DESIGN | ? UNKNOWN

---

## 1. Identity & Purpose

```yaml
system_id: vsf-nucleus.s1
vsm_role: S1
parent_in_tree: vsf-nucleus  (the containing V)
recursion_level_within: 0  (S1 may recurse — each work unit can be V')
purpose: |
  S1 is the layer of UNITS THAT DO THE WORK. In vsf-nucleus, S1 is the
  population of recursive kernels actually running experiments, tools,
  workflows, and bound operations. Without S1 the VSF has no operational
  output — no telemetry generated, no work delivered.

  Concretely in the Rust nucleus, S1 is instantiated by:
    - `RecursiveKernel` instances spawned by run_* functions in main.rs
    - tool-conductor work units (when operating)
    - external workers (BBH workers, experiment runners)
  Each S1 unit can itself be V' (Beer's Law of Recursion).
```

✓ VERIFIED from `projects/vsf-nucleus/src/main.rs` (run_pvsnp, run_metamorphosis, run_resilience, run_stress, run_fuzz, run_recursive — these all instantiate S1 work units).

---

## 2. Interface

```yaml
channels:
  - direction: φ↑
    role: writer
    carrier: events.jsonl (canonical) + NATS JetStream (mirror)
    schema_ref: connection_schema.json §upward_channel
    nats_subject: vsf.{vsf_id}.{system_id}.up.{event_type}
    frequency: high (1-10+ Hz per kernel, possibly hundreds of Hz aggregate)
    payload_size: 0.5-5 KB (kernel_tick events typical)
    loss_tolerance: bounded-100ms (per "núcleo primero" + tmpfs staging)
    notes: S1 is the PRIMARY producer of φ↑ events in the entire VSF

  - direction: φ↓
    role: reader
    carrier: params.json (canonical) + env vars (legacy)
    schema_ref: connection_schema.json §downward_channel
    nats_subject: vsf.{vsf_id}.{system_id}.down.params  (notification only)
    frequency: at tick boundaries (start of each cycle)
    payload_size: <2 KB
    loss_tolerance: full — defaults are used if params absent

  - direction: φ_algedonic
    role: writer (when violating own invariants)
    carrier: NATS Core
    schema_ref: ad-hoc, urgency-typed
    nats_subject: vsf.{vsf_id}.{system_id}.algedonic
    frequency: rare — only on existential threat
    payload_size: <1 KB
    loss_tolerance: zero

  - direction: S3*
    role: subject of audit (not writer; S3* reads S1's events.jsonl)
    notes: S1 cannot lie to S3* because events.jsonl is append-only canonical
```

### 2.1 What S1 does NOT have

- ❌ No direct sibling channel (A4) — S1↔S1 coordination only via S2 or parent S3
- ❌ No ψ — only S4 establishes ψ to other VSFs (S1 within a V cannot)
- ❌ No write access to its own params.json — only S3/S5 can write that

---

## 3. Decision space

```yaml
single_loop:                # Automatable by S1 itself
  - decision: tick_continuation
      input:  current state_vector + recent φ↓ params
      output: continue, pause, or signal_deferred event
      latency_budget: <100 ms per tick decision
      example: |
        State within Ω feasible region → continue tick.
        State near boundary → emit warning event, continue.

  - decision: emit_event
      input:  observed operation outcome
      output: append to events.jsonl + publish to NATS
      latency_budget: <1 ms (via tmpfs)
      example: |
        kernel_tick event after each tick completes successfully.

  - decision: bounded_self_correction
      input:  detected drift within tolerance
      output: adjust internal parameter within bounds declared in params.json
      latency_budget: <10 ms
      example: |
        If load > soft_threshold and params allow self-throttle: reduce rate by 10%.
      bound: must NOT cross hard limits from params.json (those require S3)

double_loop:                # Requires escalation
  - decision: kernel_halt_request
      input:  VSL invariant violated (own §5 invariants)
      output: emit kernel_halt event + cease operations
      trigger: integrity breach, trust collapse, A0 violation detected within own scope
      escalation_path: S3 + S5 + algedonic
      example: |
        thermal_c > 80 hard cap → halt + algedonic, S5 must approve resume.

  - decision: recursive_spawn
      input:  complexity(self) > variety_ceiling(self)
      output: request spawn of V' (recursive sub-system)
      trigger: variety overflow
      escalation_path: S3 approves spawn (resource allocation)
      example: |
        Single S1 kernel cannot regulate variety alone → spawn child V'(L+1).
```

---

## 4. Constraints

```yaml
inherited:
  - A0:    purpose(S1) ⊆ ethical set
  - A0.1:  cannot justify A0 violation under resource pressure
  - A4:    NO direct S1↔S1 coupling within same tree (must go via S2/S3)
  - A5:    double-loop corrections require human approval
  - D6:    S1 is L=0/L=1; NO LLM allowed at this level
  - D7:    code committed in English
  - D13:   safety invariants are blocking (halt on violation)

system_specific:
  - S1_C1: no LLM consultation
      statement: S1 MUST NOT invoke any LLM directly. All cognitive layer
                 work goes through S4 (D6 enforcement at code level).
      enforcement: Rust module boundary — no `ureq` to Ollama from S1 modules.

  - S1_C2: φ↓ read-only
      statement: S1 reads params.json but never writes to it.
      enforcement: filesystem permissions + code review.

  - S1_C3: bounded self-correction only
      statement: S1 adjustments must remain within explicit bounds in params.json.
                 Crossing bounds is a double-loop decision (requires S3).
      enforcement: pre-check in `bounded_self_correction` function.

  - S1_C4: tick atomicity
      statement: A tick either completes fully (emit kernel_tick) or aborts
                 (emit kernel_halt). No partial events.
      enforcement: tokio task with catch_unwind (per Qwen ronda 2 guidance).
```

---

## 5. Invariants

```yaml
invariants:
  - S1_I1: state in Ω feasible region
      statement: state_vector ∈ Ω at all times (no excursion outside feasible region)
      measurement: omega_validator.rs check at end of each tick
      threshold: membership ∈ {true}
      violation_action: emit_algedonic + kernel_halt

  - S1_I2: tick cadence stable
      statement: tick_duration ∈ [tick_target * 0.5, tick_target * 2.0]
      measurement: timestamp delta between successive kernel_tick events
      threshold: outside band → emit warning
      violation_action: emit signal_deferred (drift indicator), notify S3

  - S1_I3: stasis_cos preserved
      statement: stasis_cos ≥ 0.90 over rolling window of 10 ticks
      measurement: stasis.rs computation
      threshold: 0.90
      violation_action: emit signal_escalated + algedonic if drop > 0.05 in 1 tick

  - S1_I4: trust maintained
      statement: trust(self) > τ_L (typically 0.5 startup, 0.8 governed)
      measurement: trust scalar updated by S3/S5 observations
      threshold: τ_L
      violation_action: cease operations, emit kernel_halt

  - S1_I5: events.jsonl integrity (canonical ledger)
      statement: events.jsonl is append-only; previous lines never mutated
      measurement: SHA256 of all prior lines computed periodically by S3*
      threshold: hash must match expected
      violation_action: emit algedonic + halt (integrity breach)
```

---

## 6. Implementation references

| Element | Code location |
|---|---|
| RecursiveKernel | `projects/vsf-nucleus/src/kernel.rs` |
| state_vector | `projects/vsf-nucleus/src/state_vector.rs` (ℝ¹²⁸) |
| Ω validator | `projects/vsf-nucleus/src/omega_validator.rs` |
| stasis | `projects/vsf-nucleus/src/stasis.rs` |
| TelemetryWriter (φ↑) | `projects/vsf-nucleus/src/telemetry.rs` |
| Experimental modes | `projects/vsf-nucleus/src/main.rs::run_*` functions |

---

## 7. LLM agent derivation (when applicable)

⚠️ **D6 prohibits LLM at L=0/L=1**. S1 SHOULD NOT have an LLM agent.

However, **S1 can have a CONTROLLER LLM agent** that is structurally at L≥2 but oversees S1 operations. The controller would:
- Read events.jsonl from multiple S1 instances
- Identify patterns S1 alone cannot
- Propose double-loop decisions (e.g. recursive spawn, halt request)
- BUT itself runs in S4 layer, not S1

This means **S1 itself remains code-only**, while LLM oversight is via S4 looking at S1's events.

---

## 8. Confidence summary

| Section | Marker | Source |
|---|---|---|
| Identity (§1) | ✓ VERIFIED | run_* functions in main.rs |
| Interface (§2) | ✓ VERIFIED | connection_schema.json + telemetry.rs |
| Decisions (§3) | ◐ PARTIAL | bounded_self_correction not yet fully coded |
| Constraints (§4) | ✓ VERIFIED | A0-A5, D6, D13 from covenant.vsm |
| Invariants (§5) | ✓ VERIFIED | omega_validator.rs, stasis.rs implementations |
| LLM derivation (§7) | ◯ DESIGN | D6 + S4 oversight pattern |
