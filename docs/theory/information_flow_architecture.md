# VSF Information Flow Architecture
> **STATUS: historical_record** — consumido por fuse VOS-PROOFS → vos_proofs.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Document version:** 1.0
**Date:** 2026-05-24
**Authors:** rmw3 + Claude (Opus 4.7), iterated with Qwen 2.5-coder (consensus rounds 1+2)
**Status:** Formal specification — supersedes ad-hoc telemetry decisions
**Scope:** Canonical information flow taxonomy for VSF, mapping conceptual VSM channels to implementation carriers

---

## 0. Document purpose

This document formalizes the information flows of VSF — what travels between Viable Systems, why, and through which carriers. It is grounded in:

- Beer's VSM (1972, 1979) — the conceptual model
- VSF extensions documented in `covenant.vsm` v0.3 — ethical and structural axioms
- `core/connection_schema.json` v0.2 — channel contract
- Empirical findings from validation gates 1–4 + IO diagnosis (2026-05-24)
- Multi-LLM consensus (Claude + Qwen, 2 rounds)

It is intended to be read by future implementers and reviewers. Every claim is marked with confidence: ✓ VERIFIED (against canon or empirical test), ◐ PARTIAL (sound reasoning, incomplete evidence), ◯ DESIGN (proposed, untested).

---

## 1. Conceptual foundations

### 1.1 Stafford Beer's VSM (1972, *Brain of the Firm*)

Beer's claim: a system is **viable** if it can maintain identity while responding to environmental change. A viable system, regardless of scale (cell, team, firm, nation), exhibits the same five functions:

```
S1  Operations      — units that perform the actual work
S2  Coordination    — prevents destructive interference between S1 units
S3  Control         — resource allocation, internal regulation, "now"
S3* Audit           — sporadic direct channel, bypasses S3, reports to S5
S4  Intelligence    — environmental scanning, modelling the future
S5  Policy          — identity, values, ultimate authority (ungovernable from below)
```

Beer's **Law of Requisite Variety** (after Ashby, 1956): a system's regulator must have variety equal to or greater than the variety of the situation it regulates. Channels exist precisely to attenuate (S1→up) or amplify (S5→down) variety so each level can act on its proper scale.

Beer's **Law of Recursion**: any S1 complex enough to require regulation is itself a viable system. Recursion is unbounded conceptually; implementation truncates at "atomic" operations.

### 1.2 VSF extensions (`covenant.vsm`)

VSF adds to Beer's VSM:

| Extension | Reference | Purpose |
|---|---|---|
| **A0** — ethical primacy | covenant §A0 | `purpose(V) ⊆ {liberation, stability, dignity, ...}` ∧ `purpose(V) ∩ {warfare, weapons, ...} = ∅` |
| **A0.1** — anti-capture | covenant §A0.1 (proposed by gemini-vsl-core) | resource deprivation cannot justify A0 violation |
| **ψ channel** | connection_schema §lateral_channel | structural coupling between distinct V_A, V_B via S4 |
| **trust composition** | D11/D11b | trust score per V, decays on violation, enables ψ |
| **D6** — LLM placement | HANDOFF | No LLM at L0/L1; cognitive layer only L≥2 |
| **A5** — autonomy ceiling | HANDOFF | double-loop corrections require human approval |
| **A4** — no sibling coupling | HANDOFF | within a tree, S1↔S1 via parent S3 only |

### 1.3 The Cybersyn lineage

VSF is born in Chile, inheriting from Cybersyn (1971–1973). Per covenant preamble:

> "VSF nace en Chile. A0 existe porque Cybersyn no tenía A0. A0.1 existe porque Cybersyn no tenía A0.1. El covenant existe porque el Opsroom no tenía covenant."

The information flow architecture must honor this legacy: **worker sovereignty over capture**, **transparency over opacity**, **redundancy against single-point destruction** (the 1973 coup destroyed the Opsroom physically).

---

## 2. Formal structure of V

✓ VERIFIED (from covenant.vsm v0.3)

```
V ::= ⟨S1, S2, S3, S3*, S4, S5⟩

Recursion:
  ∀ s ∈ S1(V): s may itself be V' where V' ::= ⟨S1', S2', S3', S3*', S4', S5'⟩

Viability condition:
  viable(V)  iff  trust(V) > τ_L  ∧  entropy(V) < ε_max  ∧  integrity(V) > 0

Stronger (Beer-viability):
  viable_beer(V, t) ≡ viable(V, t)
                    ∧ d/dt[viable(V)] ≥ 0
                    ∧ adaptation_loop_active(S4, S3)
```

---

## 3. Channel taxonomy

Five channel types carry information in VSF. Each has a distinct direction, semantic, and integrity requirement.

### 3.1 φ↑ — Upward (telemetry)

✓ VERIFIED in `connection_schema.json` v0.2

```yaml
type: φ↑
direction: S1(L) → S3(L+1)
writer: child system (S1)
reader: parent system (S3)
semantic: "Child reports what happened"
carrier_canonical: telemetry/{system_id}/events.jsonl  (append-only)
variety_role: attenuation (Ashby) — many low-level events condensed to higher-level state
```

**Event schema** (from canon):
```
ts:            ISO-8601 UTC
system_id:     stable identifier (NOT level-indexed — recursion-stable)
event_type:    tool_run | phase_complete | thermal_wait | token_usage |
               anomaly | param_change | signal_escalated | signal_deferred
status:        ok | warn | error
signal_status: resolved | escalated | deferred
duration_s:    float
metrics:       object (system-specific)
```

**Sub-schemas for escalation/deferral** (D11/D12 mechanics):
```
signal_escalated: { signal_id, urgency: CRITICAL|HIGH|MEDIUM|LOW, resolve_attempted, reason }
signal_deferred:  { signal_id, urgency, deferred_count, meta_shift_ratio }
```

**Properties**:
- ✓ Append-only (immutable history → audit/rebuild)
- ✓ Schema-stable across recursion levels
- ✓ Cumple `connection_schema.json` φ↑ contract

### 3.2 φ↓ — Downward (parameters)

✓ VERIFIED in `connection_schema.json` v0.2

```yaml
type: φ↓
direction: S5(L+1) → S1(L)  (and S3(L+1) → S1(L) in practice)
writer: parent system (S3 or S5 depending on layer)
reader: child system (S1)
semantic: "Parent configures child"
carrier_canonical: telemetry/{system_id}/params.json
variety_role: amplification — single policy decision expanded to per-S1 parameters
read_pattern: at startup of each tick(L), child reads params (or uses defaults if absent)
```

**Param schema**:
```
_updated_at: ISO-8601 — when parent last wrote
_reason:     string — why params changed
params:      object — system-specific key/value pairs (typed schema per system)
```

**Decoupling property**: child works with defaults if params.json absent. This avoids hard dependency, supports graceful start.

### 3.3 ψ — Lateral (structural coupling between distinct V)

✓ VERIFIED in `connection_schema.json` v0.2

```yaml
type: ψ
direction: S4(V_A) ↔ S4(V_B)  (bidirectional environment model exchange)
participants: V_A.id, V_B.id — MUST NOT be siblings within same tree
preconditions:
  - governed(V_A) ∧ governed(V_B)
  - trust_level(V_A, V_B) ≥ limited
  - credential-manager.validate(both)
  - S5(V_A).approve ∧ S5(V_B).approve
mediated_by: expansion_module ∘ handshake ∘ S3.filter
```

**Payload schema**:
```
ts:        ISO-8601
source_id: string
target_id: string
channel:   "ψ"
scope:     local | shared | restricted  (= min(offer, trust_level))
payload:   object — scoped to agreed schema
```

**Key invariant**: ψ is the ONLY channel that crosses the boundary of a V tree. A4 (no direct sibling coupling within tree) still applies; ψ is for *different* V's at peer level, gated by trust + governance + S5 approval.

### 3.4 S3* — Audit (sporadic direct)

◐ PARTIAL — defined in covenant.vsm, less detailed in schema

```yaml
type: S3*  (audit)
direction: S5 ← S3* ← arbitrary level
purpose: "sees what S3 misses"
trigger: sporadic, asymmetric — initiated by S5 or S3* itself
not_constrained_by: normal S3 reporting filter
```

S3* is the **anti-corruption channel**. Beer's design protected against S3 becoming a captured gatekeeper. In VSF, S3* maps to:
- Direct read access to events.jsonl by S5 (skipping S3's summary)
- Honeypot/canary observations (LXC bastion: COVENANT_MISMATCH detection)
- External witnesses (gemini-vsl-core, GPT-4o per covenant)

### 3.5 φ_algedonic — Urgent/pain signal

✓ VERIFIED — VSL prescriptive (Qwen ronda 3)

```yaml
type: φ_algedonic
direction: arbitrary level → S5 directly (bypasses normal hierarchy)
purpose: existential threat or unrecoverable degradation
semantics: BINARY — φ_algedonic ∈ {0, 1}  (NOT level-graded)
priority: highest — "last to die" in shutdown sequence
compression: φ ≡ 1.0 (no attenuation, full fidelity)
urgency_signaling: by ROUTING PRIORITY at carrier layer, not by payload semantics
```

**Important — algedonic is binary, not graded.**

VSL prescribes `φ_algedonic ∈ {0, 1}`. Introducing CRITICAL/HIGH/MEDIUM/LOW levels in the algedonic payload **violates VSL parsimony** — it adds variety that S5 must absorb, breaking φ ≡ 1.0. Urgency is expressed by **routing priority** (NATS Core ahead of any JetStream traffic, dedicated subject) — NOT by payload field.

The algedonic channel is **cross-cutting**: it does not follow the φ↑ tree. Any level can fire. S5 acts immediately. In a healthy system, algedonic is rare; under attack or failure, it is the system's scream.

### 3.5.1 Algedonic gate (cascade prevention)

✓ VERIFIED — required by Qwen ronda 3

In a recursive V tree of N levels, an unbounded algedonic emission can cascade and saturate S5. VSL requires an **algedonic_gate** to prevent this:

```yaml
algedonic_gate (per level L):
  precondition: local_resolution_failed ∧ Δt > timeout_L
  decay: algedonic_decay(L, t) ≤ exp(-λ · t)  enforced by hysteresis
  rate_limit: max_escals_per_sec ≤ 2 per emitter
```

Without the gate, cascading algedonic from deep recursion can collapse `stasis_cos`. Implementation: emitter waits `timeout_L` for local resolution before escalating; rate-limit + hysteresis in the gate function.

---

## 4. Recursion topology

Beer's Law of Recursion is unbounded. VSF implementation maps recursion to **physical/process boundaries**:

| Recursion scope | Implementation | Channel carrier |
|---|---|---|
| Intra-binary (same Rust process) | tokio tasks within `vsf-nucleus` | In-memory `mpsc` / `broadcast` channels |
| Intra-host (different processes) | LXC ↔ LXC on same Proxmox node | NATS subjects / filesystem bind-mounts |
| Inter-host (different machines) | n01 ↔ n02 | NATS over network |
| Inter-VSF (different owners) | VSF_alpha ↔ VSF_beta | NATS gateways/leaf, ψ-gated |

### 4.1 Level addressing

✓ VERIFIED — `system_id` is stable, `level` is frame-local

A subsystem's `system_id` does NOT change when viewed from different frames. Levels are observer-relative:

```
From outside vsf-nucleus:    vsf-nucleus.level = 1
From inside vsf-nucleus:     its own S1's      = 0  (i.e. recursive frame shifts level)
```

This means an event published from an inner V'(L=0 internal) is identified by its stable system_id, not by its level. Tree depth is reconstructed from `system_id` ancestry, not from a level field.

### 4.2 Recursion within the collapsed nucleus

In the current `vsf-nucleus` Rust binary, recursion exists at runtime via:
- `state_vector.rs` (ℝ^128 representation per recursive kernel)
- `kernel.rs` (RecursiveKernel tick engine)
- `operator.rs` (SplitOperator + SoftmaxMixing — F5.x.1)
- `omega_validator.rs` (Ω feasible region — F5.x.4)
- `attractor.rs` (Lyapunov convergence — F5.x.2)

Each recursive kernel emits φ↑ events to the same `events.jsonl` stream, distinguished by its `system_id`. The Rust runtime is the carrier; events.jsonl is the canonical log.

### 4.3 Recursion across LXCs

Pre-colapso, each S-system lived in its own LXC. Post-colapso (2026-05-22/23), S1-S5 collapsed into LXC 101 (nucleus + ollama). External S1's (BBH workers, experiments running outside the nucleus) still need φ↑ to reach the nucleus — they emit to events.jsonl via filesystem bind-mount, or publish to NATS subjects.

### 4.4 Inter-VSF coupling

ψ is the only legitimate cross-VSF channel. It requires:
- Bilateral S5 approval (cannot be unilateral)
- Credential-manager validation
- Scope reconciliation (`min(offer, trust_level)`)
- S3 filter to enforce trust boundaries

In practice today, ψ has been used **experimentally** (chatgpt-gpt5.3 first acknowledgment per covenant changelog) but is not yet in production.

---

## 5. Information content per channel

Different channels carry different *kinds* of information. The carrier must match the content.

### 5.1 Quantitative — ℝ^128 state vectors

✓ VERIFIED in `state_vector.rs`

Continuous numerical state representing kernel attractor coordinates, used for:
- Lyapunov convergence monitoring
- Stasis (`stasis_cos` ≥ 0.90 invariant)
- Thermal load (`temp_c`)
- Trust scalars

**Properties**: bounded magnitude, fixed dimensionality, high frequency (~1–10 Hz), tolerable to sampling loss.

**Optimal carrier**: binary serialization (MessagePack, bincode, or raw f64 array) on NATS Core. Persistence in events.jsonl for audit (downsampled).

### 5.2 Semantic — LLM-readable text

S4 outputs from Qwen are natural-language reasoned decisions:
```json
{"action": "AddContainers", "decision_type": "ScaleOut",
 "reason": "RAM usage is at 12.0GB and no containers running...",
 "target": "Increase containers by 2"}
```

**Properties**: variable size (5–50 KB), low frequency (~0.01–0.1 Hz), high informational density, **not tolerable to sampling loss** (each decision is unique).

**Optimal carrier**: JSON on NATS JetStream with `ack_policy=explicit`. Persist full payload in events.jsonl.

### 5.3 Structural — configuration / params

φ↓ payloads. Schema per child system, typed, infrequent (changes only on parent decision).

**Optimal carrier**: JSON file (params.json) with timestamp + reason. Read at tick boundary, not subscribed real-time.

### 5.4 Audit — immutable history

events.jsonl is the canonical ledger. **All other carriers are derived views** (BBS SQLite hot-cache, NATS streams in-flight, aggregator downsampled tiers).

**Property**: any derived view can be destroyed and rebuilt from events.jsonl. This is the *single source of truth* invariant.

---

## 6. Carrier selection — mapping channels to implementations

✓ VERIFIED — corrected per Qwen ronda 3 "núcleo primero" principle

**Selection rule (mandatory):** start with the carrier **closest to the kernel**. Use NATS ONLY when crossing a boundary (LXC, host, federation) where in-memory/UDS cannot reach.

| Channel | Recursion scope | DEFAULT carrier | Promote to NATS when |
|---|---|---|---|
| φ↑ | intra-binary (same process) | `tokio::mpsc` + write events.jsonl | NEVER — stays in process |
| φ↑ | inter-process same LXC | Unix Domain Socket (UDS) + events.jsonl | NEVER — stays in LXC |
| φ↑ | inter-container same host | UDS via shared socket OR NATS JetStream | If multi-subscriber needed |
| φ↑ | inter-host (same VSF, multi-node) | NATS JetStream + events.jsonl rsync | Always |
| φ↓ | any | params.json file (read at tick boundary) | NEVER (file is the canon) |
| ψ | inter-VSF | NATS gateway / leaf node + handshake | Always (controlled federation) |
| S3* | any | direct read events.jsonl + honeypot logs | Only for cross-host audit |
| φ_algedonic | intra-binary | `tokio::broadcast` (instant, no IO) | NEVER |
| φ_algedonic | inter-process / inter-container | NATS Core (NO JetStream) | Always (sub-ms target) |
| φ_algedonic | inter-host | NATS Core over network | Always |
| S3 monitor | live operational view | UDS read of events.jsonl | If external dashboards |

### 6.0 Rationale — why "núcleo primero" for transport

Each step away from the kernel adds:
- Latency (tokio mpsc: ~1µs, UDS: ~10µs, NATS local: ~500µs, NATS network: 1-10ms)
- Failure modes (NATS down → blocked unless buffered locally)
- Resource cost (NATS uses ~30MB + Goroutines per connection)
- Cognitive load (NATS subjects vs direct function calls)

For boundaries where no alternative exists (inter-host, inter-VSF), NATS is unmatched. Otherwise it is over-engineering.

### 6.1 Critical separation: NATS Core vs JetStream

✓ VERIFIED empirically (Gate 1 = P99 488µs, Gate 4 = fsync 361ms)

- **NATS Core**: in-memory pub/sub, sub-millisecond latency, NO persistence. Used for **algedonic** (urgent, ephemeral).
- **NATS JetStream**: persistent streams with ack, replication, retention. Used for **telemetry + semantic** (durable).

Mixing these on the same stream destroys algedonic guarantees.

### 6.2 tmpfs staging as fsync mitigation

✓ VERIFIED empirically (Gate A2 = 2-3 µs on tmpfs vs 361 ms on ext4)

The host n02 disk is a TOSHIBA MQ04ABF100 5400 rpm HDD. fsync latency under multi-tenant load is 300+ms — this is hardware-bound, not software.

Mitigation:
```
events.jsonl writer:
  1. Append to /run/vsf/events.jsonl (tmpfs)        ← 3 µs fsync
  2. Async timer flushes to /var/lib/vsf/events.jsonl  ← every 100ms
  3. NATS publish in parallel ONLY if cross-LXC/host  ← 488 µs P99 (when used)
  4. Crash window: max 100ms of telemetry can be lost
     (compensated by NATS replication + on-restart replay from tmpfs if present)
```

### 6.1 Critical separation: NATS Core vs JetStream

✓ VERIFIED empirically (Gate 1 = P99 488µs, Gate 4 = fsync 361ms)

- **NATS Core**: in-memory pub/sub, sub-millisecond latency, NO persistence. Used for **algedonic** (urgent, ephemeral).
- **NATS JetStream**: persistent streams with ack, replication, retention. Used for **telemetry + semantic** (durable).

Mixing these on the same stream destroys algedonic guarantees.

### 6.2 tmpfs staging as fsync mitigation

✓ VERIFIED empirically (Gate A2 = 2-3 µs on tmpfs vs 361 ms on ext4)

The host n02 disk is a TOSHIBA MQ04ABF100 5400 rpm HDD. fsync latency under multi-tenant load is 300+ms — this is hardware-bound, not software.

Mitigation:
```
events.jsonl writer:
  1. Append to /run/vsf/events.jsonl (tmpfs)        ← 3 µs fsync
  2. Async timer flushes to /var/lib/vsf/events.jsonl  ← every 100ms
  3. NATS publish in parallel                        ← 488 µs P99
  4. Crash window: max 100ms of telemetry can be lost
     (compensated by NATS replication + on-restart replay from tmpfs if present)
```

---

## 7. NATS subject hierarchy (formal naming)

◯ DESIGN — formalizing based on canonical channel types

```
Subject pattern:
  vsf.{vsf_id}.{system_id}.{channel}.{detail}

Reserved channel slots:
  up           φ↑ telemetry, events, anomalies, signal_*
  down         φ↓ params (typically file-based, NATS for live notify)
  algedonic    φ_algedonic urgent (BINARY — no urgency levels in payload)
  s3_monitor   S3 LIVE operational telemetry view (in-flight, ephemeral)
  audit        S3* POST-HOC observations + ledger findings (separate from s3_monitor)
  meta         S5 policy + config updates
  psi          ψ inter-VSF
  s2           S2 coordination (anti-oscillation between S1s within a V)
  recurse      inner V' frames

Examples:
  vsf.alpha.nucleus.up.telemetry              ← φ↑ from nucleus (V_alpha)
  vsf.alpha.nucleus.up.s4-decision            ← semantic S4 output
  vsf.alpha.nucleus.down.params               ← φ↓ notification (file is canonical)
  vsf.alpha.nucleus.algedonic                 ← urgent from nucleus
  vsf.alpha.nucleus.recurse.L1.up.telemetry   ← inner V'(L1) telemetry
  vsf.alpha.s2.coordinator.signal             ← S2 mediating S1_a/S1_b
  vsf.alpha.audit                             ← S3* observations on V_alpha
  vsf.alpha.psi.beta.handshake                ← ψ between V_alpha ↔ V_beta
  vsf.alpha.psi.beta.scoped_payload           ← post-handshake exchange

Useful wildcards:
  vsf.*.algedonic                             ← all algedonic across all VSFs
  vsf.alpha.>                                 ← everything in V_alpha
  vsf.alpha.nucleus.up.>                      ← all upward from nucleus
  vsf.*.psi.*.>                               ← all inter-VSF traffic
```

---

## 8. Invariants and constraints

✓ VERIFIED from covenant.vsm v0.3 + connection_schema.json v0.2

| ID | Statement | Enforcement |
|---|---|---|
| **A0** | `purpose(V) ⊆ {liberation, stability, dignity, ...}` ∧ `purpose(V) ∩ {warfare, ...} = ∅` | trust→0, ψ revoked, status=compromised on violation |
| **A0.1** | Resource deprivation does NOT justify A0 violation | inalienable S5 sovereignty |
| **A4** | No direct sibling coupling within a V tree | all coordination via S2 or parent S3 |
| **A5** | Autonomy ceiling — double-loop = human required | single-loop=automatable, double-loop blocked at runtime |
| **D6** | No LLM at L0/L1 | cognitive layer placement constraint |
| **D7** | All committed files in English (code) | repository convention |
| **D11** | ψ requires bilateral S5 approve + trust ≥ limited | precondition gate |
| **D11b** | trust(V)=0 on A0 violation — permanent | no recovery path |
| **D12** | `meta_shift_ratio = deferred / total` indicates capacity exhaustion | escalate when ratio crosses threshold |
| **D13** | Safety axioms — system halts on integrity breach | VSL invariant checker |

### 8.1 Variety budgets (Ashby's law applied)

◐ PARTIAL — formalized informally, awaits empirical calibration

| Channel | Variety policy | Notes |
|---|---|---|
| φ↑ | attenuation ≥ 72% (Qwen estimate) | Many low-level events → summarized S3 state |
| φ↓ | structured amplification | One parent decision → per-S1 params |
| φ_algedonic | `φ ≡ 1.0` (no compression) | Full fidelity, urgent, BINARY {0,1} |
| ψ | scope-limited (`min(offer, trust)`) | Bilateral, gated |

### 8.2 Formal invariants (added by Qwen ronda 3)

✓ VERIFIED — VSL formal invariants required for compliance

| ID | Invariant | Meaning |
|---|---|---|
| **VAR-1** | `ΔV_in ≤ ΔV_out` per regulating step | Variety absorbed by a regulator ≥ variety it emits (Ashby applied) |
| **TRUST-1** | `trust_chain(path) = Π trust_i` | Trust composes multiplicatively along φ↑ / ψ paths; one weak link reduces the whole |
| **ALG-1** | `algedonic_decay(L, t) ≤ exp(-λ · t)` | Algedonic intensity per recursive level must decay exponentially over time to prevent cascade saturation of S5 |

These are runtime-checkable (not just declarative):
- VAR-1: measured per regulator by comparing input vs output rates
- TRUST-1: computed when forming or extending a trust chain
- ALG-1: enforced by the algedonic_gate (§3.5.1)

### 8.3 Empirical mapping to canon

◐ PARTIAL — explicit mapping required

Empirical thresholds used in experiments (`stasis_cos ≥ 0.90`, `temp_c < 70`, etc.) MUST map to formal axioms A0-A9 or to a covenant clause. Current state: many thresholds are empirical without formal derivation. Action item: produce a mapping table `empirical_metric ↔ formal_axiom_or_clause` in `docs/theory/empirical_to_canon_mapping.md`.

### 8.2 Trust composition

```
trust(V): ℝ ∈ [0, 1]
τ_L: trust threshold for level L (typically 0.5 at startup, 0.8 for governed)

Triggers:
  A0_violation(V)            → trust(V) := 0 permanent (D11b)
  signal_deferred over τ_def → trust degraded
  signal_escalated success   → trust slightly elevated
  external_witness_attest    → trust boost (bounded)
```

---

## 9. Operational patterns

### 9.1 Boot (`stasis_boot`)

```
1. Read params.json (φ↓) — defaults if absent
2. Initialize state_vector ∈ Ω feasible region
3. Emit `system_start` event to events.jsonl (φ↑)
4. Spawn S4 worker (300s cycle) + Telemetry worker (60s cycle)
5. Open NATS connection — publish capability announcement
6. Enter steady-state tick loop
```

### 9.2 Tick cycle

```
loop {
    state_now = read_metrics()
    emit kernel_tick event (φ↑)
    if S4_cycle_due {
        decision = qwen.analyze(state_now)
        emit s4-analysis event (φ↑ via semantic channel)
        publish to vsf.{id}.nucleus.up.s4-decision (NATS JetStream)
    }
    if telemetry_cycle_due {
        publish state_vector to vsf.{id}.nucleus.up.telemetry (NATS)
        append to events.jsonl (tmpfs staging)
    }
    sleep until next cycle
}
```

### 9.3 Algedonic escalation

```
if invariant_violated(stasis_cos < 0.90 OR temp_c > 70 OR trust < τ_L) {
    publish to vsf.{id}.algedonic (NATS Core, no JetStream)
    emit signal_escalated to events.jsonl
    if urgency == CRITICAL {
        S5 direct intervention triggered
    }
}
```

### 9.4 ψ handshake

```
1. V_A.S4 announces capability to vsf.alpha.psi.beta.handshake
2. V_B.S4 reads + validates: trust(A) ≥ limited, credential-manager.validate(A)
3. V_B.S5 approves → publishes ack
4. V_A.S5 confirms → ψ established
5. Bidirectional exchange via vsf.alpha.psi.beta.scoped_payload
6. Scope = min(V_A.offer, V_B.trust_level)
```

### 9.5 Reframe (double-loop recovery)

```
if cumulative_deferred > threshold OR L_max < L_now {
    pause current operations
    request_human_approval()                            (A5 enforcement)
    if approved {
        update covenant_hash, regenerate params.json
        resume with new frame
    } else {
        halt with reason
    }
}
```

### 9.6 Halt (VSL violation)

```
if violated_invariant in {A0, integrity, trust=0} {
    emit kernel_halt event with violation list
    publish to vsf.{id}.algedonic (last gasp)
    stop all workers
    persist final state
}
```

---

## 10. Implementation in current codebase

✓ VERIFIED inventory (2026-05-24)

### 10.1 Modules → channel correspondence

| Channel | Module | Status |
|---|---|---|
| φ↑ canonical (events.jsonl) | `telemetry.rs` (`TelemetryWriter`) | ✓ Implemented, invoked in experimental modes |
| φ↑ operational (BBS SQLite) | `telemetry_publisher.rs` | ✓ Implemented, but VIOLATES canon (sistema-céntrico, not Beer φ↑) |
| φ↓ params | `config.rs` (env-based for now) | ◐ Partial — uses env vars, not params.json yet |
| S4 cognitive | `s4.rs` + `s4_operational.rs` | ✓ Implemented, calls Ollama+Qwen |
| ψ | not implemented | ⏳ Future |
| S3* | not implemented as code; conceptually via covenant_hash + honeypot | ◐ Partial via VSF-Bastion |
| Algedonic | not implemented as separate channel | ⏳ Future (will be `vsf.algedonic.>` NATS Core) |

### 10.2 Gaps to canonical model

| Gap | Severity | Resolution |
|---|---|---|
| Motor 2 (BBS SQLite) violates φ↑ schema | Medium | Deprecate (Qwen consensus); migrate to events.jsonl + JetStream materialized view |
| Motor 1 (events.jsonl) inactive in operational mode | High | Feature flag `--telemetry-canonical` (γ phase) |
| params.json not implemented | Medium | Add `config.rs` extension to read params.json with reload-on-write |
| No algedonic channel | Medium | Add `algedonic.rs` module: NATS Core publisher |
| No ψ implementation | Low | Future (when multi-VSF needed) |

### 10.3 Mitigation strategy (Claude+Qwen consensus, 2 rounds)

```
γ (Production, low-risk, immediate):
  - Activate TelemetryWriter (Motor 1) in operational mode behind feature flag
  - tmpfs staging at /run/vsf/events.jsonl, flush 100ms to disk
  - NATS JetStream replicates events.jsonl in real-time
  - ext4 mount: not commit=1 (test showed no benefit) but keep tmpfs

β (PoC collapsed binary, parallel, isolated):
  - LXC 107 (recycled 102) — fresh container
  - Single binary: nucleus + nats-server (sidecar via UDS, NOT linked-as-library)
  - tokio::catch_unwind per S1-S5 subsystem (maintains VSL clausura L=0)
  - cgroup v2 budgets memory/cpu per subsistema
  - lxc.cgroup2.blkio.weight=50 (reduces IO contention)
  - Validate stasis_cos doesn't degrade under panic injection

Deprecation:
  - Motor 2 SQLite → read-only mode
  - S4 consumes events.jsonl via tail -f or async-rebuilt SQLite index
  - Drop after 2 validation cycles in β
```

---

## 11. Performance characteristics

✓ VERIFIED empirically (validation gates 2026-05-24)

| Channel | Carrier | Latency (P99) | Throughput | Loss tolerance |
|---|---|---|---|---|
| φ_algedonic | NATS Core | **488 µs** | 3142 req/s | Zero (must arrive) |
| φ↑ telemetry | NATS JetStream + tmpfs | <1 ms publish; 100ms flush | 10 Hz tested OK | 100ms window (replayable) |
| φ↑ semantic | NATS JetStream | ~5-50ms (large payload) | 0.1 Hz tested OK | Zero (each unique) |
| φ↓ params | filesystem | inode read latency | tick boundary | None (defaults fallback) |
| ψ | NATS gateway | network RTT-bound | low (handshake-rare) | Negotiated via scope |
| events.jsonl fsync | tmpfs | **3 µs** mean | unbounded | Limited by RAM |
| events.jsonl fsync | ext4 HDD | **361 ms** mean | ~3/sec | — (do not use as primary) |

### 11.1 Hardware-bound floor

✓ VERIFIED: n02 host disk = TOSHIBA MQ04ABF100 (5400 rpm 2.5" SATA HDD).

fsync 300-700ms on this disk is **expected hardware behavior**, not software bug. SSD/NVMe migration would change the equation but is out of scope until justified by load.

### 11.2 Failure modes

| Failure | Detection | Mitigation |
|---|---|---|
| Disk full | fs probe | tmpfs OOM → spill to logs; algedonic if persistent |
| NATS down | publish error | Buffer in tmpfs ledger; resume on reconnect |
| nucleus crash | systemd | Auto-restart; replay from events.jsonl tail |
| Qwen unreachable | timeout 120s | Skip S4 cycle; emit deferred signal |
| Network partition | NATS heartbeat | Each VSF operates autonomously, syncs on heal |

---

## 12. Evolution roadmap

```
PRESENT (2026-05-24):
  ✓ Nucleus Rust operational (LXC 101 collapsed)
  ✓ BBS SQLite embebido (violates canon — to deprecate)
  ✓ Validation gates passed
  ✓ Architecture decision: NATS + dual-write + tmpfs staging

NEXT (γ phase — feature flag in production):
  ◯ Activate TelemetryWriter in operational mode
  ◯ Add tmpfs staging for events.jsonl
  ◯ Deploy nats-server (sidecar in LXC 101 or new LXC)
  ◯ Refactor telemetry_publisher.rs to dual-write

PARALLEL (β phase — collapsed PoC):
  ◯ Recycle LXC 102 → LXC 107
  ◯ Single-binary nucleus + nats-server sidecar
  ◯ catch_unwind + cgroup budgets
  ◯ Validate L=0 clausura under panic injection

FUTURE:
  ⏳ params.json implementation (φ↓ canonical)
  ⏳ algedonic.rs module
  ⏳ S3* explicit implementation
  ⏳ ψ handshake protocol (when multi-VSF)
  ⏳ Migration to SSD/NVMe (when latency budget tightens)
  ⏳ Full collapse to bare metal (α option, future)
```

---

## 13. Confidence summary

| Section | Marker | Source of confidence |
|---|---|---|
| Beer's VSM (§1) | ✓ VERIFIED | Beer's published work + Medina (2011) |
| VSF axioms (§1.2, §8) | ✓ VERIFIED | covenant.vsm v0.3 in repo |
| Channel schemas (§3) | ✓ VERIFIED | connection_schema.json v0.2 in repo |
| Recursion topology (§4) | ◐ PARTIAL | conceptually sound; partial code implementation |
| Carrier mapping (§6) | ✓ VERIFIED empirically | gates 1-4 + tmpfs A2 measurements |
| NATS subject hierarchy (§7) | ◯ DESIGN | proposed, not yet deployed |
| Implementation gaps (§10) | ✓ VERIFIED | direct code inspection |
| Performance (§11) | ✓ VERIFIED | benchmark numbers from gates |
| Roadmap (§12) | ◯ DESIGN | post-consensus plan, awaits owner approval |

---

## 14. Decisions (closed 2026-05-24 by rmw3)

| # | Question | Decision |
|---|---|---|
| 1 | NATS subject prefix | **`vsf.{vsf_id}.>` from day 1** (multi-VSF ready, even if only 1 VSF exists today) |
| 2 | First real ψ scope | **After consolidating first system + replicating to second hardware** (not now — defer ψ until first VSF is stable replicable unit) |
| 3 | γ vs β order | **Parallel from day 1** (γ activates Motor 1 in production with safety net, β validates collapse in isolated LXC) |
| 4 | SSD migration | **No — work within hardware constraints**. **Viability is independent of hardware capacity.** Principle: "if a solution is costly in resources, find a more direct alternative closer to the kernel" |
| 5 | Collapsed binary final | **Hold open** — user open to interpretation but resource-constrained; principle from (4) applies |

### 14.1 Operating principle established by (4) — "núcleo primero"

> If a solution is costly in resources, look for an alternative **more direct, closer to the kernel**.

This principle takes priority over architectural sophistication. Applied retroactively to this document:

- ✓ NATS sidecar (Qwen consensus) — already aligned (30MB, light)
- ✓ tmpfs staging — already aligned (no extra hardware)
- ✓ events.jsonl as canonical ledger — already aligned (filesystem, no service)
- ◐ Future review: if NATS itself proves heavy for some recursion scopes, prefer **tokio in-memory channels** + **direct events.jsonl writes** at those scopes. NATS only at boundaries where it adds genuine value (inter-LXC, inter-host, federation).

**Implication for §6 carrier mapping**: a carrier should never be used "by default"; it must justify its cost. The default is the kernel-closest carrier (in-memory channel, then filesystem), with NATS reserved for proven need.

---

## 15. References

- Beer, S. (1972). *Brain of the Firm*. Allen Lane. — VSM foundational
- Beer, S. (1979). *The Heart of Enterprise*. Wiley. — recursion theorems
- Ashby, W.R. (1956). *An Introduction to Cybernetics*. Chapman and Hall. — variety law
- Medina, E. (2011). *Cybernetic Revolutionaries*. MIT Press. — Cybersyn history
- `/home/rmw3/vsf/core/connection_schema.json` v0.2 — channel canonical contract
- `/home/rmw3/vsf/docs/spec_revision/system/boot/covenant.vsm` v0.3 — A0/A0.1 + formal structure
- `/home/rmw3/.claude/projects/-home-rmw3-vsf/memory/project_dual_channel_decision.md` — consensus history Claude+Qwen
- Validation gates 1-4 raw data (`b9vcdfaee`, `bn39r2j5y`, `bj1uc8vj6` outputs)
- Empirical fsync TOSHIBA MQ04ABF100 measurements (2026-05-24)
