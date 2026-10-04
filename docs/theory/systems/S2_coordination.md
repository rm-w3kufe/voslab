# S2 — Coordination (vsf-nucleus.s2)
> **STATUS: historical_record** — consumido por fuse VOS-CORE-THEORY → s2_nats.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Document version:** 1.0
**Date:** 2026-05-24
**Method:** [per_system_requirements_method.md](../per_system_requirements_method.md)
**VSM role:** S2 (Coordination — anti-oscillation between S1 units)
**Confidence markers:** ✓ VERIFIED | ◐ PARTIAL | ◯ DESIGN | ? UNKNOWN

---

## 1. Identity & Purpose

```yaml
system_id: vsf-nucleus.s2
vsm_role: S2
parent_in_tree: vsf-nucleus
recursion_level_within: 1
purpose: |
  S2 PREVENTS DESTRUCTIVE INTERFERENCE between S1 units operating in
  parallel. In Beer's VSM, S2 is the "anti-oscillation regulator" — it
  detects when two S1 units are stepping on each other (resource contention,
  contradictory actions, timing collisions) and issues coordination signals.

  S2 is NOT a decision-maker (that's S3). S2 is a COORDINATOR — it ensures
  S1 units don't undo each other's work. Without S2, multiple S1s racing for
  the same resource can produce thrashing, oscillation, or worse (data
  corruption from concurrent unprotected writes).

  In VSF nucleus today, S2 is **largely implicit** — tokio mutexes and
  channels provide low-level coordination, but no explicit S2 module exists.
  This is acknowledged debt (DEBT-13 in vsf-arch.html).
```

⚠️ ◐ PARTIAL — S2 explicit module does not exist in code yet. Coordination is implemented at runtime level via tokio primitives. This doc specifies what S2 **must become**.

---

## 2. Interface

```yaml
channels:
  - direction: φ↑
    role: writer (coordination reports)
    carrier: events.jsonl
    schema_ref: connection_schema.json §upward_channel (event_type=coord_signal)
    nats_subject: vsf.{vsf_id}.s2.{coordinator_id}.signal
    frequency: low (~0.1-1 Hz when active, may be quiet for long periods)
    payload_size: <1 KB
    loss_tolerance: bounded — coordination is best-effort within window

  - direction: φ_lateral (S1 ↔ S1 MEDIATED)
      role: mediator (NOT direct S1↔S1, which violates A4)
      carrier: in-memory tokio channels (intra-process) OR NATS (inter-process)
      nats_subject: vsf.{vsf_id}.s2.coordinator.{s1_a}.{s1_b}
      frequency: event-driven (only when S1s need coordination)
      payload_size: <2 KB
      loss_tolerance: bounded — re-send if no ack

  - direction: φ↓ (reads from S3)
    role: reader
    carrier: params.json (S3 sets coordination policy)
    schema_ref: connection_schema.json §downward_channel
    nats_subject: vsf.{vsf_id}.s2.down.policy
    frequency: at policy update boundaries
    payload_size: <2 KB
```

### 2.1 Key invariant on channels

S2 communications **are NOT siblings violating A4** because:
- A4 prohibits **direct** sibling coupling
- S2 is the **mediator** explicitly authorized by VSM theory
- S1_a → S2 → S1_b is a valid 3-hop path

This is the structural reason S2 exists: it makes coordination legitimate.

---

## 3. Decision space

```yaml
single_loop:                # S2 acts autonomously within policy
  - decision: detect_oscillation
      input:  recent S1 events showing repeated cancel/redo, ping-pong, lock contention
      output: emit coord_signal to affected S1s
      latency_budget: <500 ms (must respond before oscillation amplifies)
      example: |
        S1_a writes config X, S1_b overwrites with Y, S1_a writes X again →
        S2 detects pattern, sends coord_signal to both with TTL-based lock proposal.

  - decision: resource_quanta_arbitration
      input:  S1 requests for shared resource that exceed quota
      output: queue order + per-request grant timing
      latency_budget: <100 ms
      example: |
        Two S1 kernels request thermal_budget when sum would exceed cap →
        S2 issues serialized grants honoring fairness policy from S3.

  - decision: heartbeat_propagation
      input:  S1 liveness signals
      output: aggregated status to S3, individual nudges to silent S1s
      latency_budget: configurable (default 5-30 sec)

double_loop:                # Coordination policy changes — escalate to S3
  - decision: policy_revision_request
      input:  observed oscillation patterns NOT covered by current policy
      output: emit signal_escalated to S3
      escalation_path: S3 deliberates, may consult S4, updates params.json
      example: |
        New oscillation pattern emerges (3-way deadlock between S1s) →
        S2 reports to S3; S3 amends policy; S2 reloads from new params.
```

---

## 4. Constraints

```yaml
inherited:
  - A0, A0.1:  ethical primacy
  - A4:        S2 is the LEGITIMATE mediator; without S2, A4 forbids S1↔S1
  - A5:        policy changes escalate to S3 (double-loop)
  - D6:        S2 at L=1 → NO LLM (coordination is mechanical, not cognitive)

system_specific:
  - S2_C1: no policy authorship
      statement: S2 enforces policy received from S3. S2 cannot create or
                 modify coordination policy autonomously.
      enforcement: code structure — S2 reads params, never writes to params.

  - S2_C2: bounded scope
      statement: S2 coordinates only within its parent V's S1 set. S2 does
                 NOT coordinate across recursive boundaries (V'(L+1) has its
                 own S2').
      enforcement: addressing — S2 only handles s1 within own tree.

  - S2_C3: idempotent signals
      statement: S2 coord signals must be safe to re-send (no destructive effect
                 if duplicated by NATS at-least-once delivery).
      enforcement: signal payload includes sequence number + intent verb.

  - S2_C4: no veto power on individual S1 work
      statement: S2 can order, queue, throttle, or pause S1s — but cannot
                 cancel a tick already in progress. Cancellation requires S3.
      enforcement: signal types limited to {grant, delay, throttle, pause}.
```

---

## 5. Invariants

```yaml
invariants:
  - S2_I1: oscillation detection latency
      statement: oscillation detected within N=3 cycles of pattern emergence
      measurement: time from first oscillation event to S2 coord_signal
      threshold: 3 * tick_target
      violation_action: emit signal_escalated (S2 ineffective)

  - S2_I2: coordination overhead bounded
      statement: S2 messages per second < 10% of S1 event rate
      measurement: rate counter over 60s window
      threshold: 10%
      violation_action: signal_deferred (S2 is becoming the bottleneck)

  - S2_I3: no spurious signals
      statement: every coord_signal must correspond to a real observed pattern
      measurement: S3* audit — sample 1% of signals, verify against events.jsonl
      threshold: false positive rate < 1%
      violation_action: emit warning + recalibrate detection thresholds

  - S2_I4: A4 preservation
      statement: All S1↔S1 traffic passes through S2 (no direct S1 coupling)
      measurement: S3* periodic scan for direct S1↔S1 NATS subjects
      threshold: zero direct S1↔S1 subjects
      violation_action: emit algedonic — A4 violation by some S1
```

---

## 6. Implementation references

⚠️ ◐ PARTIAL — current state of code:

| Element | Status | Path |
|---|---|---|
| Explicit S2 module | ❌ NOT YET | (to create: `projects/vsf-nucleus/src/s2.rs`) |
| tokio primitive coordination | ✓ implicit | Mutexes, channels in main.rs and operational.rs |
| NATS coord subjects | ❌ NOT YET | (proposed: `vsf.{id}.s2.*`) |
| Oscillation detector | ❌ NOT YET | (to design) |

This per-system doc is the **specification** for when S2 is implemented.

---

## 7. LLM agent derivation

⚠️ **D6 prohibits LLM at L=0/L=1**. S2 is at L=1 → **NO LLM agent for S2**.

S2 is mechanical pattern matching + signal routing. Implementation is pure Rust. If S2 detects patterns IT cannot resolve, it escalates to S3 (which may consult S4's LLM).

---

## 8. Confidence summary

| Section | Marker | Notes |
|---|---|---|
| Identity (§1) | ◐ PARTIAL | Conceptually defined, NOT implemented |
| Interface (§2) | ◯ DESIGN | Specifies what S2 SHOULD have |
| Decisions (§3) | ◯ DESIGN | Requires S2 module to be created |
| Constraints (§4) | ✓ VERIFIED | Derived from canon (A0-A5, D6) |
| Invariants (§5) | ◯ DESIGN | Thresholds are proposals, need empirical calibration |

**Action item:** S2 module is debt — should be implemented before multi-S1 production load increases. Until then, tokio primitives provide coordination at runtime level (acceptable for single-tenant nucleus).
