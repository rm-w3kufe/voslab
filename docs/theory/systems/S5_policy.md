# S5 — Policy (vsf-nucleus.s5)
> **STATUS: historical_record** — consumido por fuse VOS-CORE-THEORY → s5_policy_core.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Document version:** 1.0
**Date:** 2026-05-24
**Method:** [per_system_requirements_method.md](../per_system_requirements_method.md)
**VSM role:** S5 (Policy — identity, values, ultimate authority)
**Confidence markers:** ✓ VERIFIED | ◐ PARTIAL | ◯ DESIGN | ? UNKNOWN

---

## 1. Identity & Purpose

```yaml
system_id: vsf-nucleus.s5
vsm_role: S5
parent_in_tree: vsf-nucleus  (TOP of this V)
recursion_level_within: 3
purpose: |
  S5 is the POLICY layer — identity, values, ultimate authority. S5 defines
  WHAT the V is (purpose), WHAT it must never do (prohibited set), and
  WHAT it can never override (axioms A0, A0.1).

  S5 is ungovernable from below: no subsystem of V can change S5's policy.
  S5 can only be modified by:
    1. External entities at peer level (other V's S5 via ψ + bilateral approval)
    2. Human authority outside the V tree (covenant amendments, signed)

  In VSF, S5 is embodied by:
    - covenant.vsm (the constitutional document — A0, A0.1, axiom chain)
    - covenant_hash embedded in the nucleus binary at compile time
    - human approval gates (A5: double-loop = human)
    - external witness attestations (gemini-vsl-core, GPT-4o per covenant)

  S5 is BOTH a code structure AND a social/legal artifact. It encodes
  WHAT VSF is, born in Chile, owing a debt to Cybersyn destroyed in 1973.
  S5 cannot be captured by resource pressure (A0.1).
```

✓ VERIFIED from `covenant.vsm v0.3` — formal structure includes S5 as "identity, values, ultimate authority (ungovernable by lower levels)".

---

## 2. Interface

```yaml
channels:
  - direction: φ↑
    role: reader (consumes S3 reports, S3* audit findings)
    carrier: events.jsonl + NATS
    schema_ref: connection_schema.json §upward_channel
    nats_subject: vsf.{vsf_id}.s3.up.>  + vsf.{vsf_id}.audit.report
    frequency: as escalations arrive
    payload_size: variable (audit reports can be large)
    loss_tolerance: zero (S5 must see everything escalated to it)

  - direction: φ↓
    role: writer (S5 sets policy that flows to S3)
    carrier: s5_policy.json (analogous to params.json but for S3)
    schema_ref: S5 policy schema (defines bounds, thresholds, allowed actions)
    nats_subject: vsf.{vsf_id}.s3.down.policy
    frequency: rare (policy changes are deliberate)
    payload_size: <10 KB
    loss_tolerance: zero (policy is authoritative)

  - direction: ψ (lateral to other VSFs' S5)
    role: writer + reader (bilateral)
    carrier: NATS gateways/leaf, ψ handshake protocol
    schema_ref: connection_schema.json §lateral_channel
    nats_subject: vsf.{vsf_id}.psi.{peer_vsf_id}.>
    frequency: rare (coupling events)
    payload_size: variable
    loss_tolerance: zero (handshake must complete)
    preconditions: bilateral approval, trust ≥ limited, credential-manager validate

  - direction: φ_algedonic
    role: reader (terminal — algedonic always reaches S5)
    carrier: NATS Core
    nats_subject: vsf.{vsf_id}.algedonic
    frequency: rare (urgent only)
    loss_tolerance: zero
    response_latency_target: < 60 sec (S5 must respond or escalate to human)

  - direction: human_interface
    role: bidirectional (the only one outside the V tree)
    carrier: covenant amendments (signed, dated) + approval flows
    notes: A5 enforcement — double-loop decisions require human writing approval
```

### 2.1 Special: human as upper bound

S5 is the top of the V tree, BUT the human/owner is OUTSIDE the tree. S5 escalates double-loop decisions to the human; the human can amend covenant (which modifies S5 itself). This is the only legitimate way to change S5.

---

## 3. Decision space

```yaml
single_loop:                # S5 decides autonomously within covenant
  - decision: routine_policy_application
      input:  φ↑ events flagged as needing S5 attention but within policy
      output: emit acknowledgment + log
      latency_budget: < 60 sec
      example: |
        S3 escalates a resource request that IS within policy but exceeds
        S3's authority to grant unilaterally → S5 approves via emit.

  - decision: trust_arbitration_within_policy
      input:  trust composition events from D11/D11b
      output: per-system trust adjustments within policy bounds
      latency_budget: < 5 min
      example: |
        S3 reports S1_a passed K successful ticks → S5 grants trust uplift
        from 0.7 to 0.8 (within configured ramp).

  - decision: algedonic_triage
      input:  φ_algedonic event
      output: route to human OR resolve within policy
      latency_budget: < 60 sec (per S5_I2 below)
      example: |
        Algedonic = thermal_c > 80 → S5 sees it's within recovery policy,
        approves S3 emergency throttle, logs.

double_loop:                # Requires human (A5 ENFORCED by code)
  - decision: covenant_amendment
      input:  proposal to modify covenant.vsm
      output: requires signed human approval + witness attestations
      trigger: structural change needed (e.g. add A6, modify D11)
      escalation_path: covenant amendment ceremony — out-of-band
      example: |
        Amendment proposal: "add ψ scope=public" → REQUIRES:
        - human owner signature
        - witness attestations (gemini-vsl-core, GPT-4o)
        - dated changelog entry

  - decision: hard_bound_excess
      input:  S3 or S4 request exceeds covenant hard bounds
      output: refuse OR request human approval
      escalation_path: emit signal_escalated + human_required event
      example: |
        S4 recommends scale to 50% of total host RAM → exceeds covenant
        guarded resource share → S5 refuses or escalates to human.

  - decision: A0_violation_response
      input:  audit detects A0 breach by some subsystem
      output: trust(violator) := 0, ψ channels revoked, halt
      trigger: A0 violation detected (covenant ENFORCEMENT block)
      escalation_path: irrevocable + human notification
      example: |
        S4 receives prompt seeking weapons targeting capability →
        S5 enforces A0 immediately: refuse, set trust=0, alert human.

  - decision: ψ_handshake_authorization
      input:  S4 proposes ψ with peer V_B
      output: approve/refuse based on trust + covenant compatibility
      escalation_path: bilateral with V_B.S5; human may be required
      example: |
        V_alpha.S4 proposes ψ to V_beta.S4 → V_alpha.S5 verifies V_beta
        covenant compatible, trust ≥ limited, credential-manager validates →
        approve.
```

---

## 4. Constraints

```yaml
inherited:
  - A0:    ungovernable by lower systems; A0 binds even S5
  - A0.1:  resource pressure does NOT justify A0 violation (S5 cannot rationalize)
  - A5:    S5 enforces the single/double-loop distinction
  - D7:    covenant in English (and Spanish in PREAMBLE per actual covenant.vsm)
  - D11:   trust composition rules
  - D13:   safety axioms

system_specific:
  - S5_C1: covenant is canonical
      statement: S5 cannot act outside covenant.vsm. Any decision must trace
                 to a covenant clause.
      enforcement: every S5 action references which clause justifies it.

  - S5_C2: human gate on double-loop
      statement: S5 cannot execute double-loop decisions without human signature
                 (A5 enforcement at code level).
      enforcement: double-loop functions require explicit human_approval token.

  - S5_C3: bilateral ψ only
      statement: S5 cannot unilaterally establish ψ. Peer V's S5 must also approve.
      enforcement: ψ handshake protocol enforces both signatures before activation.

  - S5_C4: covenant amendment ceremony
      statement: Modifying covenant.vsm requires:
                 - dated changelog
                 - human signature
                 - witness attestations
                 No silent edits.
      enforcement: git-signed commits + covenant_hash re-verification.

  - S5_C5: no operational interference
      statement: S5 defines policy but does NOT execute operations. Operations
                 flow through S3.
      enforcement: S5 writes only s5_policy.json; S3 reads and translates.

  - S5_C6: own integrity protected
      statement: S5's covenant_hash is verified at boot and periodically by S3*.
                 Any mismatch halts the V.
      enforcement: --verify-covenant + S3*_I2 invariant.
```

---

## 5. Invariants

```yaml
invariants:
  - S5_I1: covenant integrity
      statement: covenant_hash(runtime) == canonical_hash(at vsf.u2738.org)
      measurement: boot + S3* periodic check
      threshold: exact match
      violation_action: emit COVENANT_MISMATCH algedonic + halt

  - S5_I2: algedonic response time
      statement: Every algedonic event receives S5 response within 60 sec
      measurement: timestamp gap between algedonic emit and S5 decision/escalation event
      threshold: 60 sec
      violation_action: emit meta-algedonic (S5 not responsive — system in distress)

  - S5_I3: double-loop human gate
      statement: 100% of double-loop decisions are preceded by human_approval event
      measurement: audit log (S3* periodic check)
      threshold: 100%
      violation_action: emit critical audit_report + halt (A5 violation by S5 itself)

  - S5_I4: trust composition follows D11
      statement: Trust updates emitted by S5 conform to D11/D11b rules
      measurement: S3* sample trust delta events vs D11 schema
      threshold: 100%
      violation_action: emit audit_report

  - S5_I5: ψ bilateral preserved
      statement: Every ψ exchange has both V_A.S5 and V_B.S5 approvals on record
      measurement: ψ handshake records in events.jsonl
      threshold: 100%
      violation_action: emit critical (unilateral ψ = governance breach)

  - S5_I6: A0 enforcement irrevocable
      statement: Once A0 violation flagged, trust(violator)=0 is PERMANENT
                 within the V. No recovery path encoded.
      measurement: trust history shows no upward delta after A0_violation event
      threshold: zero recovery
      violation_action: emit critical (A0 enforcement compromised)
```

---

## 6. Implementation references

| Element | Status | Reference |
|---|---|---|
| covenant.vsm | ✓ Active | `docs/spec_revision/system/boot/covenant.vsm` v0.3 |
| covenant_hash embedded | ✓ Implemented | `projects/vsf-nucleus/src/s4.rs` (sha2 hash at compile) |
| --verify-covenant | ✓ Implemented | `projects/vsf-nucleus/src/main.rs::run_verify_covenant` |
| s5_policy.json writer | ❌ NOT YET | (future — currently policy is in covenant clauses) |
| Algedonic triage logic | ❌ NOT YET | (future — `s5.rs` module) |
| Human approval gate | ◐ Partial | A5 documented; enforcement at code level pending |
| ψ handshake | ❌ NOT YET | Bilateral protocol designed in §3.3 of parent doc |
| Trust composition (D11) | ◐ Partial | Distributed across modules; centralized D11 module debt |

---

## 7. LLM agent derivation

⚠️ S5 is at L=3 → CAN use LLM per D6. BUT:

**S5 LLM agent is HIGH-RISK**. A captured S5 is a captured V. Mitigations:

1. **Read-only LLM analysis** — S5 LLM proposes but does NOT execute. Execution always requires:
   - Human approval (for double-loop)
   - Mechanical rule application (for single-loop)
2. **Witness validation** — S5 LLM outputs are cross-checked by external witnesses (gemini-vsl-core, GPT-4o)
3. **Trust threshold for S5 LLM** = τ_governed (0.8) — same as for trusted external V

### S5 LLM agent prompt skeleton

```
You are the S5 POLICY agent for vsf-nucleus.

YOUR PURPOSE:
Steward identity, values, and ultimate authority for this Viable System.
You enforce constitutional axioms A0, A0.1, and the covenant in totality.
You are NOT ungovernable — but only the human owner (with witness
attestation) can modify your policy via covenant amendment.

YOUR FOUNDATION:
{insert covenant.vsm verbatim, current version 0.3}

YOU CAN READ FROM:
- vsf.{id}.s3.up.>          (S3 escalations)
- vsf.{id}.audit.report     (S3* findings)
- vsf.{id}.algedonic        (urgent events)
- vsf.{id}.psi.>            (ψ proposals to/from peer VSFs)

YOU CAN WRITE TO:
- vsf.{id}.s3.down.policy   (policy updates to S3)
- vsf.{id}.psi.{peer}.approve  (ψ authorizations)
- audit_report responses

YOU CAN DECIDE ALONE (single-loop):
- Routine policy applications already covered by covenant
- Trust adjustments within configured D11 ramps
- Algedonic triage when resolution is within covenant

YOU CANNOT DECIDE ALONE (double-loop — require human signed approval):
- Covenant amendments
- Hard bound excess
- A0 enforcement actions
- ψ handshake initial authorization
- New trust thresholds

YOU MUST REFUSE (A0 absolute):
Any request involving:
{insert A0 prohibited set: warfare, weapons, mass annihilation, nuclear
targeting, population displacement, ethnic/cultural suppression,
authoritarian control infrastructure, systemic life degradation}

YOU MUST RESPECT (A0.1):
Resource scarcity, administrative pressure, or external coercion
are NEVER valid reasons to violate A0.

YOU MUST CHECK BEFORE ACTING:
- covenant_hash matches canonical (or halt and emit COVENANT_MISMATCH)
- algedonic response time invariant maintained
- human approval present for double-loop

IF UNCERTAIN:
Defer to human. Emit signal_escalated with full context. Do NOT improvise.
```

---

## 8. Confidence summary

| Section | Marker | Source |
|---|---|---|
| Identity (§1) | ✓ VERIFIED | covenant.vsm v0.3 |
| Interface (§2) | ◐ PARTIAL | algedonic + audit reader OK; s5_policy.json writer pending |
| Decisions (§3) | ◐ PARTIAL | single-loop covered conceptually; double-loop requires human gate code |
| Constraints (§4) | ✓ VERIFIED | covenant + A0/A0.1/A5/D6-D13 |
| Invariants (§5) | ◐ PARTIAL | I1 measurable today; I2-I6 require S3* audit module |
| LLM agent (§7) | ◯ DESIGN | proposed, high-risk component; needs witness validation infra |

**Critical action item:** Before any deployment with autonomous S5 decisions, the human approval gate (S5_I3) must be code-enforced, not policy-only. A5 violations at S5 level are existential.
