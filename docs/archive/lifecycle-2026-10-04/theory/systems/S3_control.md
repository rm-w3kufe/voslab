# S3 — Control (vsf-nucleus.s3)
> **STATUS: historical_record** — consumido por fuse VOS-CORE-THEORY → s3_allocation.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Document version:** 1.0
**Date:** 2026-05-24
**Method:** [per_system_requirements_method.md](../per_system_requirements_method.md)
**VSM role:** S3 (Control — resource allocation, "now")
**Confidence markers:** ✓ VERIFIED | ◐ PARTIAL | ◯ DESIGN | ? UNKNOWN

---

## 1. Identity & Purpose

```yaml
system_id: vsf-nucleus.s3
vsm_role: S3
parent_in_tree: vsf-nucleus
recursion_level_within: 2
purpose: |
  S3 is the "inside and now" regulator. Where S4 looks outside-and-future,
  S3 looks INSIDE the V (resource state of own S1s + S2 coordination
  effectiveness) and NOW (immediate regulation, not modeling). S3 is the
  hands-on operations manager.

  S3 responsibilities:
    1. Allocate resources (RAM, CPU, IO budget, network) across S1 units
    2. Monitor S1 performance against thresholds set by S5
    3. Receive S4 recommendations and translate them to operational params
    4. Write params.json (φ↓) for S1 consumption
    5. Authorize S2 coordination policy
    6. Enforce single-loop corrections (A5: single-loop = automatable)
    7. Escalate double-loop (A5: double-loop = human via S5)

  In vsf-nucleus today, S3 functionality is split across:
    - telemetry_publisher.rs (reads metrics, publishes state)
    - operational.rs (orchestrates worker threads, applies cycle policy)
    - cgroup.rs (resource isolation per kernel — Linux cgroup v2)
    - s4_operational.rs::publish_s4_analysis (S3 publishes S4 decisions)
```

✓ VERIFIED from current code: regulation + resource allocation logic is in `operational.rs::run_parallel` and `cgroup.rs`. Telemetry pipeline is in `telemetry_publisher.rs`.

---

## 2. Interface

```yaml
channels:
  - direction: φ↑
    role: reader (consumes S1 events.jsonl and S2 signals)
    carrier: events.jsonl (file) + NATS JetStream (subscribed)
    schema_ref: connection_schema.json §upward_channel
    nats_subject: vsf.{vsf_id}.{system_id}.up.>  (wildcard, all event types)
    frequency: high (consumes everything below)
    payload_size: variable
    loss_tolerance: bounded — JetStream guarantees with replay

  - direction: φ↑
    role: writer (S3 reports up to S5)
    carrier: events.jsonl + NATS
    schema_ref: event_type ∈ {phase_complete, param_change, resource_allocation}
    nats_subject: vsf.{vsf_id}.s3.up.{event_type}
    frequency: ~0.1-1 Hz (S3 publishes coarser-grained than S1)
    payload_size: 1-10 KB
    loss_tolerance: zero (must reach S5)

  - direction: φ↓
    role: writer (S3 writes params for S1)
    carrier: params.json (file) + NATS notify on change
    schema_ref: connection_schema.json §downward_channel
    nats_subject: vsf.{vsf_id}.{target_s1_id}.down.params
    frequency: as needed (after S4 decision or threshold trigger)
    payload_size: <5 KB
    loss_tolerance: zero (params are authoritative)

  - direction: φ↓
    role: reader (S5 sets S3's own policy)
    carrier: params.json (separate file: s3.params.json)
    schema_ref: S5-defined policy schema
    nats_subject: vsf.{vsf_id}.s3.down.policy
    frequency: rare (policy changes only)

  - direction: φ_algedonic
    role: writer (when resource exhaustion imminent)
    carrier: NATS Core
    nats_subject: vsf.{vsf_id}.algedonic
    frequency: rare
    payload_size: <1 KB
    loss_tolerance: zero

  - direction: φ_algedonic
    role: reader (S1 / S2 algedonic signals to S3 for triage before S5)
    notes: S3 is first-pass triage; routes critical to S5, handles others.
```

---

## 3. Decision space

```yaml
single_loop:                # S3 decides autonomously
  - decision: resource_reallocation
      input:  S1 telemetry showing resource pressure within S5-set bounds
      output: write new params.json for affected S1s + cgroup adjustments
      latency_budget: <5 sec
      example: |
        S1_a using 90% of allocated RAM, S1_b idle at 20% →
        S3 rebalances cgroup memory limits within S5-approved bounds.

  - decision: threshold_enforcement
      input:  S1 metric crosses warning threshold
      output: emit warning + adjust params (rate-limit, throttle)
      latency_budget: <1 sec
      example: |
        thermal_c crosses 65°C warn line → throttle S1 by 20% via params.

  - decision: S4_decision_application
      input:  s4-analysis event from φ↑
      output: translate S4 high-level decision to concrete params changes
      latency_budget: <10 sec
      example: |
        S4 says "AddContainers" → S3 evaluates if within budget,
        either applies (single-loop) or escalates (double-loop).

  - decision: S2_policy_authorship
      input:  observed S1 coordination patterns from S2 reports
      output: update S2's coordination policy params
      latency_budget: <5 min
      example: |
        S2 reports recurring oscillation → S3 sets longer cooldown in S2 policy.

double_loop:                # Escalate to S5 + human
  - decision: bound_violation_request
      input:  S4 recommendation OR S3 own analysis requires exceeding
              hard bounds set by S5
      output: emit signal_escalated → S5 → human approval
      trigger: A5 (double-loop = human)
      escalation_path: events.jsonl signal_escalated + algedonic if urgent
      example: |
        S4 says "scale out 4 containers" but S5 set max=2 →
        S3 cannot grant unilaterally; escalate to S5.

  - decision: reframe_invocation
      input:  cumulative_deferred > threshold, meta_shift_ratio high
      output: pause normal operations, request reframe from S5
      trigger: D12 indicator (capacity exhaustion)
      escalation_path: S5 + human
```

---

## 4. Constraints

```yaml
inherited:
  - A0, A0.1:  ethical primacy
  - A4:        S3 mediates S1↔S1; uses S2 for coordination
  - A5:        boundary between single-loop (S3 acts) and double-loop (escalate to S5+human)
  - D6:        S3 at L=2; CAN use LLM but typically delegates to S4 instead
  - D11/D11b:  trust composition — S3 updates per-S1 trust based on observations
  - D12:       meta_shift_ratio threshold triggers reframe escalation
  - D13:       safety axioms blocking

system_specific:
  - S3_C1: respect S5 hard bounds
      statement: S3 cannot grant resources beyond per-S1 caps set by S5 policy.
                 Any request crossing the cap is double-loop.
      enforcement: pre-check in resource_reallocation function.

  - S3_C2: no S4 substitution
      statement: S3 does not perform environmental scanning (that is S4).
                 S3 reasons about INSIDE/NOW, not OUTSIDE/FUTURE.
      enforcement: code structure — S3 modules do not call Ollama/Qwen.

  - S3_C3: params.json atomic write
      statement: params.json updates must be atomic (write to .tmp + rename).
                 No partial reads by S1 (which polls at tick boundary).
      enforcement: filesystem operation pattern in code.

  - S3_C4: trust updates monotonic in policy
      statement: Trust decreases on violations, increases only via successful
                 ticks or witness attestation. No arbitrary trust boost.
      enforcement: trust update function gated.

  - S3_C5: audit-readable
      statement: All S3 decisions must produce events in events.jsonl readable
                 by S3* (audit). No "silent" S3 actions.
      enforcement: every S3 function emits at least one event.
```

---

## 5. Invariants

```yaml
invariants:
  - S3_I1: resource conservation
      statement: Sum of S1 resource allocations ≤ total S5 budget at all times
      measurement: cgroup queries summed
      threshold: never exceed budget
      violation_action: refuse allocation request + emit algedonic

  - S3_I2: regulation responsiveness
      statement: When S1 threshold crossed, S3 acts within N=3 ticks
      measurement: time from S1 threshold event to S3 corrective params change
      threshold: 3 ticks
      violation_action: emit signal_deferred (S3 lagging)

  - S3_I3: S5 policy compliance
      statement: All S3 params.json writes satisfy S5 policy constraints
      measurement: S3* periodic audit checks params against S5 policy
      threshold: zero violations
      violation_action: emit algedonic (S3 acting outside policy)

  - S3_I4: escalation correctness
      statement: 100% of bound-violation requests escalate to S5 (none "absorbed" by S3)
      measurement: S3* cross-references events.jsonl S3 actions vs S5 policy
      threshold: 100%
      violation_action: emit algedonic (S3 absorbing what should escalate — corruption indicator)

  - S3_I5: trust composition integrity
      statement: trust(S1) updates follow D11/D11b rules (no out-of-band boosts)
      measurement: trust delta journal
      threshold: every delta has a justifying event
      violation_action: emit algedonic
```

---

## 6. Implementation references

| Element | Code location | Status |
|---|---|---|
| Resource regulation (cgroup) | `projects/vsf-nucleus/src/cgroup.rs` | ✓ Implemented |
| Telemetry consumer (S3 reads φ↑) | `projects/vsf-nucleus/src/telemetry_publisher.rs` | ◐ Indirect — publishes, doesn't yet consume |
| S4 decision application | `projects/vsf-nucleus/src/s4_operational.rs::publish_s4_analysis` | ✓ Implemented |
| params.json writer | not yet implemented | ❌ Future |
| Trust updates (D11) | distributed across modules | ◐ Partial |
| Escalation logic | not yet formalized | ❌ Future |

---

## 7. LLM agent derivation

⚠️ S3 is at L=2 → CAN use LLM per D6. BUT:

Per principle "núcleo primero", S3 should remain primarily Rust code:
- Resource allocation is deterministic math (no LLM needed)
- Threshold enforcement is rule-based
- LLM consultation would add latency + tokens cost

**Recommendation**: S3 delegates COGNITIVE work to S4 (LLM-based). S3 itself executes the application of S4 decisions deterministically.

If a per-system LLM agent for S3 is eventually built, its role would be limited to:
- Generating human-readable explanations of S3 decisions for audit
- Proposing policy revisions to S5 (rare, double-loop)

The agent's prompt template (per method §4.1) would emphasize:
- Read-only LLM analysis, deterministic execution
- Refusal to act on its own; always emit event for review

---

## 8. Confidence summary

| Section | Marker | Source |
|---|---|---|
| Identity (§1) | ✓ VERIFIED | code structure matches |
| Interface (§2) | ✓ VERIFIED | telemetry_publisher + cgroup |
| Decisions (§3) | ◐ PARTIAL | resource_reallocation works; reframe_invocation pending |
| Constraints (§4) | ✓ VERIFIED | derived from canon |
| Invariants (§5) | ◐ PARTIAL | I1-I3 measurable today; I4-I5 await S3* audit module |
