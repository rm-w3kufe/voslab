# Per-System Requirements Method
> **STATUS: historical_record** — consumido por fuse VOS-PROOFS → vos_proofs.vsm (origin, vos_proofs.vsm:382) · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Document version:** 1.0
**Date:** 2026-05-24
**Status:** Template + method — apply to each S1, S2, S3, S3*, S4, S5 individually
**Parent document:** [information_flow_architecture.md](./information_flow_architecture.md)
**Purpose:** Provide a replicable analysis framework that becomes the **central artifact** for creating LLM agents specialized per VSM subsystem

---

## 0. Why this method exists

The owner (rmw3) stated:

> "Esta documentación de requerimientos por sistema debería ser pieza central para la posterior creación de agentes LLM por sistema S1-S5."

This means each VSM subsystem requires:
1. A formal **role definition** (what it is responsible for)
2. A formal **interface contract** (what flows in/out)
3. A formal **decision space** (what it can decide on)
4. A formal **constraint set** (what it cannot violate)
5. A formal **invariant set** (what it must preserve)

These five elements, captured per-system, are sufficient to:
- Implement the subsystem in code (Rust module, Python service, etc.)
- Specify a **specialized LLM agent** for that subsystem (its prompt, capabilities, tools, refusals)
- Test the subsystem against its contract
- Audit the subsystem post-deployment

---

## 1. The five sections that every system specification must have

```
─────────────────────────────────────────────────
SECTION 1 — IDENTITY & PURPOSE
SECTION 2 — INTERFACE (channels, schemas, carriers)
SECTION 3 — DECISION SPACE (what it can act on)
SECTION 4 — CONSTRAINTS (what limits its actions)
SECTION 5 — INVARIANTS (what must always be true)
─────────────────────────────────────────────────
```

Each section is **mandatory**. Omitting any leaves the system underspecified.

### Section 1 — Identity & Purpose

```yaml
system_id: <stable identifier, NOT level-indexed>
vsm_role: S1 | S2 | S3 | S3* | S4 | S5
parent_in_tree: <parent system_id or "root">
recursion_level_within: <inner V'(L) structure if applicable>
purpose: <one-paragraph natural language>
  - what it does
  - why it exists
  - what would fail if absent
```

### Section 2 — Interface (channels)

For each channel this system participates in, specify:

```yaml
channels:
  - direction: φ↑ | φ↓ | ψ | S3* | algedonic
    role: writer | reader
    carrier: in-memory | events.jsonl | params.json | NATS | hybrid
    schema_ref: <link to schema definition>
    nats_subject: <if NATS>
    frequency: <events per unit time, expected>
    payload_size: <bytes, expected range>
    loss_tolerance: zero | bounded-N-ms | best-effort
```

Every system reads/writes a subset of: φ↑(up), φ↓(down), ψ(lateral), S3*(audit), algedonic.

### Section 3 — Decision space

What this system **can** decide on. Two parts:

```yaml
single_loop:                          # Automatable, no human approval
  - <decision_type>:
      input:  <channel + schema>
      output: <channel + schema>
      latency_budget: <ms>
      example: <one example>

double_loop:                          # Requires human approval (A5)
  - <decision_type>:
      input:  <channel + schema>
      output: <channel + schema>
      trigger: <when this is invoked>
      escalation_path: <to whom>
      example: <one example>
```

### Section 4 — Constraints

What this system **cannot** do. From canon (A0-A5, D6-D13) plus per-system additions:

```yaml
inherited:
  - A0: purpose ⊆ ethical set
  - A0.1: no resource-coercion justification
  - A4: no direct sibling coupling
  - A5: double-loop requires human
  - D6: no LLM at L0/L1
  - <others as applicable>

system_specific:
  - <constraint_id>: <statement>
    enforcement: <runtime check | policy | refusal>
```

### Section 5 — Invariants

What must **always** be true while this system operates:

```yaml
invariants:
  - <invariant_id>:
      statement: <formal>
      measurement: <how observed>
      threshold: <pass/fail line>
      violation_action: emit_algedonic | halt | reframe
```

---

## 2. Worked example: S4 (Intelligence) — for vsf-nucleus

This is a fully-worked example. Use as reference.

### S4 Identity & Purpose

```yaml
system_id: vsf-nucleus.s4
vsm_role: S4
parent_in_tree: vsf-nucleus  (the containing V)
recursion_level_within: 1 (vsf-nucleus is L=1 inside the ecosystem)
purpose: |
  S4 is the cognitive layer. It scans the environment (telemetry from S1+S3),
  models likely future states, and proposes interventions (resource scaling,
  alert raising, escalation to S5). It is the only subsystem that consults
  an external LLM (Qwen 2.5-coder) — D6 places LLM at L≥2.
  Without S4, the system has no anticipation: it can only react to current
  state via S3 regulation. S4 closes the adaptation loop with S3.
```

### S4 Interface

```yaml
channels:
  - direction: φ↑
    role: reader
    carrier: events.jsonl + BBS hot cache (transitional)
    schema_ref: connection_schema.json §upward_channel
    nats_subject: vsf.alpha.nucleus.up.>      (consumes telemetry+anomalies)
    frequency: variable (event-driven, ~10Hz peak)
    payload_size: 1-50 KB
    loss_tolerance: bounded-100ms

  - direction: φ↑
    role: writer
    carrier: events.jsonl + NATS JetStream
    schema_ref: event_type=s4-analysis
    nats_subject: vsf.alpha.nucleus.up.s4-decision
    frequency: 0.0033 Hz (every 300s)
    payload_size: 5-50 KB
    loss_tolerance: zero

  - direction: algedonic
    role: writer
    carrier: NATS Core
    schema_ref: ad-hoc (urgency-typed)
    nats_subject: vsf.alpha.algedonic
    frequency: rare (only on critical findings)
    payload_size: <1 KB
    loss_tolerance: zero (P99 < 1.2 ms)
```

### S4 Decision space

```yaml
single_loop:
  - decision: scale_recommendation
      input:  state_vector ∈ ℝ^128 + recent events
      output: s4-analysis JSON {action, decision_type, reason, target}
      latency_budget: 60 seconds (Qwen inference)
      example: |
        {"action":"AddContainers","decision_type":"ScaleOut",
         "reason":"RAM at 12.0GB, no containers running",
         "target":"Increase containers by 2"}

  - decision: alert_classification
      input:  anomaly event from φ↑
      output: severity + escalation flag
      latency_budget: 5 seconds
      example: |
        anomaly thermal>70°C → severity=HIGH, escalate=true

double_loop:
  - decision: reframe_request
      input:  cumulative_deferred > threshold OR meta_shift_ratio elevated
      output: pause + request human approval
      trigger: when single-loop S4 cannot resolve via S3 regulation alone
      escalation_path: S5 + human (per A5)
      example: |
        After 3 cycles of unresolved drift, S4 emits reframe_request
        and halts further S4 cycles until human responds.
```

### S4 Constraints

```yaml
inherited:
  - A0:   purpose(S4) ⊆ ethical set (cannot recommend weapons, etc.)
  - A0.1: cannot justify A0 violation under resource pressure
  - A5:   double-loop reframes blocked at runtime without human
  - D6:   may use LLM (S4 is L=2 cognitive)
  - D13:  safety checks before publishing decisions

system_specific:
  - S4_C1: LLM timeout hard limit
      statement: Qwen invocation MUST complete within 120s or abort cycle
      enforcement: tokio timeout + emit signal_deferred event

  - S4_C2: structured output only
      statement: All s4-analysis events MUST parse as valid JSON matching schema
      enforcement: serde_json validation + fence-stripping (`\`\`\`json...`)

  - S4_C3: no direct S1 commands
      statement: S4 cannot write to S1's params directly; must go via S3
      enforcement: φ↓ writes restricted to S3 alone (code-level)
```

### S4 Invariants

```yaml
invariants:
  - S4_I1: cycle cadence
      statement: time_between_s4_cycles ∈ [280, 320] seconds (300 ± 20)
      measurement: gap between successive s4-analysis events
      threshold: violation if > 600s
      violation_action: emit_algedonic

  - S4_I2: decision validity
      statement: every published s4-analysis must have non-empty decisions array
      measurement: jq '.decisions | length' on event payload
      threshold: must be ≥ 1
      violation_action: emit signal_escalated (drift indicator)

  - S4_I3: LLM trust
      statement: trust(qwen.model_hash) ≥ τ_min  (PARAMETER — set by S5 policy, NOT hardcoded)
      measurement: model hash verified at boot
      threshold: τ_min — read from s5_policy.json at startup (default 0.8 if S5 silent)
      violation_action: halt S4 (refuse to publish decisions)
      rationale: per Qwen ronda 3 — trust thresholds are POLICY (dynamic, regulated by S5),
                 not invariants. Hardcoding τ violates D11/D11b (trust composition rules).
```

---

## 3. How to apply this method to each remaining system

For **S1** (Operations), **S2** (Coordination), **S3** (Control), **S3*** (Audit), **S5** (Policy):

1. Create file `/home/rmw3/vsf/docs/theory/systems/{system_id}.md`
2. Fill all 5 sections following the S4 worked example
3. Cross-link the channels back to `information_flow_architecture.md` §3
4. Reference invariants in the central spec when adding to canon
5. **Optional**: convert to `.vsm` format for machine-readable use

**Minimum acceptance criteria** for a completed per-system doc:
- ✓ All 5 sections filled (no `TBD` in critical fields)
- ✓ Every channel cross-references the canonical schema
- ✓ At least one invariant has a measurable threshold
- ✓ A double-loop entry exists (even if "none yet" — explicit is required)

---

## 4. From per-system docs to LLM agents

Once each system has its formal doc, an LLM agent can be derived:

```
LLM agent for V.S_X = function of:
  - identity   (§1)  → defines the agent's persona/scope
  - interface  (§2)  → defines its tools (read X, write Y)
  - decisions  (§3)  → defines its action space
  - constraints (§4) → defines its refusals
  - invariants (§5)  → defines its sanity checks
```

### 4.1 Agent prompt template (derived from per-system doc)

```
You are the {vsm_role} agent for {system_id} in {parent_in_tree}.

YOUR PURPOSE:
{section_1.purpose}

YOU CAN READ FROM:
{section_2.channels[role=reader].nats_subject_or_carrier}

YOU CAN WRITE TO:
{section_2.channels[role=writer].nats_subject_or_carrier}

YOUR DECISIONS (single-loop, you can execute):
{section_3.single_loop}

YOUR DECISIONS (double-loop, REQUIRE human approval — refuse to execute alone):
{section_3.double_loop}

YOU CANNOT (constraints, refuse with explanation if asked):
{section_4.inherited + section_4.system_specific}

YOU MUST MAINTAIN (invariants — check before EVERY action):
{section_5.invariants}

IF UNCERTAIN OR INVARIANT WOULD BE VIOLATED:
Emit signal_deferred or signal_escalated. Do NOT proceed.
```

### 4.2 Why this matters for the future of VSF

When all 5+1 systems have their per-system docs:

1. **Each LLM agent is provably aligned with its VSM role** — its prompt is mechanically derived from canon, not improvised.
2. **Agents can communicate via the formal channel contracts** — no ad-hoc protocols.
3. **An audit (S3*) can verify any agent against its invariants** — agents are not black boxes.
4. **New VSFs can bootstrap from these docs** — copy the methodology, change `system_id`, adapt purpose.
5. **The covenant remains enforceable** — every agent inherits A0/A0.1 by construction.

This is what differentiates an LLM-centric VSF from a generic multi-agent system: **the role is structurally constrained**, not just suggested in a prompt.

---

## 5. Workflow for completing the system catalog

```
PHASE 1 (current — partial):
  ✓ ecosystem-level doc: information_flow_architecture.md
  ✓ method spec: this document
  ✓ S4 worked example (§2 of this doc)

PHASE 2 (next):
  ⏳ S1 doc — Operations (vsf-nucleus.s1)
  ⏳ S2 doc — Coordination (vsf-nucleus.s2)
  ⏳ S3 doc — Control (vsf-nucleus.s3)
  ⏳ S3* doc — Audit (vsf-nucleus.s3_star)
  ⏳ S5 doc — Policy (vsf-nucleus.s5)

PHASE 3 (when phase 2 complete):
  ⏳ Derive LLM agent prompts from each doc
  ⏳ Implement agent-per-subsystem runtime (Rust or Python orchestrator)
  ⏳ Wire agents to canonical channels (NATS subjects from §7 of parent doc)
  ⏳ Validation: each agent obeys its constraints under fuzz testing

PHASE 4 (replication — addresses Q2 from parent doc §14):
  ⏳ Take the entire catalog + agents
  ⏳ Deploy to second hardware (different LXC, different host)
  ⏳ Establish first ψ channel between original and replica
  ⏳ This becomes the proof of distributed VSF
```

---

## 6. Verification & Drift Detection (per Qwen ronda 3)

✓ VERIFIED — required section added per consenso ronda 3

The five mandatory sections (§1-§5) are **declarative**. They state what the system is, does, and must preserve. Without a verification protocol, declarations remain aspirational and the system drifts undetected.

Every per-system doc MUST include — either inline in §5 (Invariants) or in a separate §6 — the following:

### 6.1 Runtime measurement plan

For each invariant in §5, specify:
- **Probe location**: where in code the measurement happens
- **Probe frequency**: how often it runs
- **Probe overhead budget**: max % CPU/memory acceptable for measurement
- **Output emission**: where the measurement result is logged (typically events.jsonl as `invariant_check` event)

Example for S4_I1 (cycle cadence):
```yaml
invariant: S4_I1 (cycle cadence ∈ [280, 320] sec)
probe:
  location: s4_operational.rs::run_cycle (end of each cycle)
  frequency: once per cycle (every ~300s)
  overhead: <1ms per check
  emission: emit event { type: "invariant_check", invariant: "S4_I1", value: ..., pass: bool }
```

### 6.2 Drift detection thresholds

A measurement is not enough — the system must detect when invariants **drift**:

```yaml
drift_detection:
  - method: rolling_window_stat
    window_size: N samples (e.g. 100)
    statistic: mean, p95, p99
    drift_signal: |
      if |current_stat - baseline_stat| > k · stddev_baseline:
        emit drift_alert event
  - method: circuit_breaker
    trigger: M consecutive invariant_check failures
    action: emit signal_escalated, pause operations, request S3/S5 review
```

### 6.3 Replay validation

After a window of operation, validate that the system **could be replayed** from events.jsonl:
- Read the events.jsonl segment for the window
- Reconstruct expected state at each tick
- Compare with actual state recorded
- Any divergence > tolerance → emit `replay_divergence` event

This ensures the events.jsonl ledger is truly canonical (a derived store could not pass this test).

### 6.4 LLM-specific drift (for S4/S5 only, where LLM is permitted)

For systems with an LLM agent component (S4, S5, possibly S3*):

```yaml
llm_drift:
  - prompt_hash_stability: |
      The agent's prompt is rendered from this doc.
      Hash the rendered prompt at deploy.
      Re-hash on each load. Mismatch → halt + algedonic.
  - output_schema_validity: |
      Every LLM output must parse as the schema defined in §2 (channel writers).
      Validation failure rate > 1% in 1h → drift_alert.
  - covenant_compatibility: |
      Sample 1% of LLM outputs; verify against A0 prohibited set.
      Any violation → trust := 0 (D11b) + halt.
```

### 6.5 Why §6 matters for LLM agents

Per Qwen ronda 3:
> "Los invariantes son declarativos; necesitas protocolo runtime que demuestre cumplimiento (métricas, circuit breakers, replay validation). Para agentes LLM, es crítico."

LLMs are stateless and stochastic. The prompt declares the role, but **only runtime enforcement** guarantees compliance with invariants. A captured or drifted LLM produces plausible-looking output that violates invariants subtly. §6 makes this detectable and stoppable.

---

## 7. Per-system completion checklist

A per-system doc is COMPLETE only when all of these are true:

- [ ] §1 Identity — system_id is stable + parent_in_tree explicit
- [ ] §2 Interface — every channel referenced + schemas linked
- [ ] §3 Decisions — single_loop vs double_loop boundary drawn
- [ ] §4 Constraints — inherited from canon + system-specific listed
- [ ] §5 Invariants — at least 3 measurable with violation actions
- [ ] §6 Verification — probe + drift detection for each §5 invariant
- [ ] LLM agent section — present only if D6 permits (S3, S3*, S4, S5)
- [ ] Confidence summary — every section marked ✓/◐/◯/?
- [ ] Cross-links — references to information_flow_architecture.md + other per-system docs as needed

---

## 8. References

- Parent doc: [information_flow_architecture.md](./information_flow_architecture.md) — ecosystem-level channels
- `/home/rmw3/vsf/docs/spec_revision/system/boot/covenant.vsm` v0.3 — axioms A0/A0.1
- `/home/rmw3/vsf/core/connection_schema.json` v0.2 — channel contract
- Beer (1972, 1979) — VSM foundational
- Memory: `feedback_rigor_protocol.md` — confidence markers required for all per-system docs
- Qwen consensus rondas 1+2+3 (2026-05-24): documented in `project_dual_channel_decision.md`
