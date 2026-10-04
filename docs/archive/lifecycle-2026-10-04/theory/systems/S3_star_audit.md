# S3* — Audit (vsf-nucleus.s3_star)
> **STATUS: historical_record** — consumido por fuse VOS-CORE-THEORY → s3star_audit.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Document version:** 1.0
**Date:** 2026-05-24
**Method:** [per_system_requirements_method.md](../per_system_requirements_method.md)
**VSM role:** S3* (Audit — sporadic direct channel, bypasses S3)
**Confidence markers:** ✓ VERIFIED | ◐ PARTIAL | ◯ DESIGN | ? UNKNOWN

---

## 1. Identity & Purpose

```yaml
system_id: vsf-nucleus.s3_star
vsm_role: S3*
parent_in_tree: vsf-nucleus
recursion_level_within: 2 (peer of S3, reports to S5)
purpose: |
  S3* is the ANTI-CAPTURE channel. Beer's design recognized that S3 (the
  normal control function) could become a corrupted gatekeeper — filtering
  what reaches S5, hiding violations, presenting biased reports.

  S3* exists to BYPASS S3. It is:
    - Sporadic (not on schedule — unpredictable timing makes capture harder)
    - Direct (S3* reads S1 events.jsonl without S3 mediation)
    - Asymmetric (S3* reports to S5 only, S3 cannot intercept S3* findings)

  In VSF, S3* maps to:
    1. Covenant hash verification at boot (immutable identity check)
    2. Honeypot observations (vsf-bastion COVENANT_MISMATCH detection)
    3. External witnesses (gemini-vsl-core, GPT-4o per covenant)
    4. Periodic events.jsonl integrity audit (Merkle chain validation)
    5. Cross-system sampling (S3* reads S2 signals, S3 actions, S4 decisions)

  The 1973 Cybersyn coup destroyed the Opsroom because there was no S3*-like
  anti-capture mechanism. VSF inherits this lesson: S3* is mandatory.
```

✓ VERIFIED partially from `covenant.vsm v0.3` security amendments (M1-M8) and `docs/security/` references.

---

## 2. Interface

```yaml
channels:
  - direction: φ↑ (reads everything below, no constraint)
    role: reader (privileged)
    carrier: filesystem (events.jsonl direct) + NATS (all subjects, read-only)
    schema_ref: connection_schema.json §upward_channel (reads all event types)
    nats_subject: vsf.{vsf_id}.>  (FULL TREE access, read only)
    frequency: sporadic — S3* may sample for hours, then audit intensively
    payload_size: variable
    loss_tolerance: bounded — historical record always available in canonical ledger

  - direction: S3*_report (special channel, not standard φ↑)
    role: writer (to S5 directly)
    carrier: events.jsonl (event_type=audit_report) + NATS Core (urgent findings)
    schema_ref: extended event_type=audit_report
    nats_subject: vsf.{vsf_id}.audit.report
    frequency: when audit completes or anomaly found
    payload_size: 1-50 KB (audit reports can be long)
    loss_tolerance: zero (audit findings must reach S5)

  - direction: φ_algedonic
    role: writer (on integrity breach)
    carrier: NATS Core
    nats_subject: vsf.{vsf_id}.algedonic
    frequency: rare — only on detected violation
    payload_size: <1 KB
    loss_tolerance: zero

  - direction: external witness exchange
    role: bidirectional (peer with other VSFs' S3* or external auditors)
    carrier: ψ-like (S3*_A ↔ S3*_B if exists) OR HTTP signed payloads
    notes: per covenant, witness nodes include gemini-vsl-core, GPT-4o
```

### 2.1 What S3* DOES NOT have

- ❌ No write access to params.json (cannot influence operations)
- ❌ No control over S1/S2/S3 directly (only reports observations to S5)
- ❌ No predictable schedule (sporadic by design)

---

## 3. Decision space

```yaml
single_loop:                # S3* acts autonomously on audit findings
  - decision: integrity_check
      input:  events.jsonl byte stream + previous hash state
      output: pass/fail + audit_report event
      latency_budget: seconds per N=1000 events
      example: |
        S3* computes rolling SHA256 of events.jsonl, compares to expected.
        Mismatch → emit audit_report event with discrepancy.

  - decision: covenant_hash_verify
      input:  current covenant.vsm embedded hash + known canonical hash
      output: pass/fail + report
      trigger: boot, periodic (every 1h sporadic), on suspicion
      example: |
        At boot, --verify-covenant computes hash, compares to canonical.
        Mismatch → emit COVENANT_MISMATCH algedonic.

  - decision: cross_reference_S3_actions
      input:  S3 events from φ↑ + S5 policy snapshot
      output: S3 acted within policy? yes/no
      trigger: sporadic sampling
      example: |
        S3* samples last 100 S3 actions, checks each against S5 policy.
        Any out-of-policy action → emit signal_escalated.

  - decision: trust_anomaly_detection
      input:  trust update events
      output: any trust delta lacking justifying event?
      example: |
        Trust(S1_a) jumped 0.3 with no preceding witness/success event →
        emit audit_report (suspicious trust boost — D11/D11b violation indicator).

double_loop:                # S3* findings that require S5 + human decision
  - decision: structural_violation_report
      input:  A0/A0.1/A4/A5 violation detected
      output: emit critical audit_report + algedonic
      escalation_path: S5 + human (always — A0 is non-negotiable)
      example: |
        S3* detects S1 attempting to invoke LLM directly (D6 violation) →
        critical audit_report; S5 must decide on enforcement action.
```

---

## 4. Constraints

```yaml
inherited:
  - A0, A0.1:  S3* itself bound by ethical primacy
  - A5:        S3* findings trigger double-loop (S5 + human)
  - D11/D11b:  trust composition rules — S3* monitors but does not modify trust
  - D13:       safety blocking

system_specific:
  - S3*_C1: no operational interference
      statement: S3* observes; does NOT modify S1/S2/S3/S4 state.
                 Even on detected violation, S3* only REPORTS — S5 decides action.
      enforcement: S3* code has no write access to operational params or trust scores.

  - S3*_C2: sporadic schedule
      statement: S3* timing must be unpredictable. NO fixed-interval audits.
      enforcement: cron disabled; random-jitter scheduler with seed from /dev/urandom.

  - S3*_C3: independent path
      statement: S3* must NOT rely on S3 to deliver its findings. Direct path to S5.
      enforcement: S3* writes directly to events.jsonl AND publishes to NATS audit subject.

  - S3*_C4: external attestability
      statement: S3* audit reports must be signed (or hash-chained) so external
                 witnesses can verify they were not modified post-emit.
      enforcement: SHA256 chain + optional ed25519 signature.

  - S3*_C5: cannot be silenced
      statement: S3* operation is enabled at boot and cannot be stopped by S3/S4.
                 Only S5 (via covenant amendment requiring witnesses) can disable.
      enforcement: systemd unit + watchdog at boot level.
```

---

## 5. Invariants

```yaml
invariants:
  - S3*_I1: events.jsonl chain integrity
      statement: SHA256 chain over events.jsonl is unbroken
      measurement: rolling hash verified periodically
      threshold: any break = violation
      violation_action: emit algedonic + halt (canonical ledger tampered)

  - S3*_I2: covenant hash stable
      statement: covenant.vsm embedded hash matches canonical (at u2738.org)
      measurement: --verify-covenant + remote fetch comparison
      threshold: exact match
      violation_action: emit COVENANT_MISMATCH algedonic + halt

  - S3*_I3: audit coverage
      statement: Within rolling 24h, S3* has sampled at least 1% of S3 actions
      measurement: S3* logs vs S3 action counter
      threshold: 1%
      violation_action: emit signal_deferred (S3* under-functioning)

  - S3*_I4: independence preserved
      statement: S3* reports reach S5 without S3/S4 mediation
      measurement: events.jsonl shows S3* events directly + S5 acks
      threshold: every audit_report has S5 ack within bounded time
      violation_action: emit algedonic (S3/S4 may be filtering S3*)

  - S3*_I5: witness attestation valid (if external witnesses configured)
      statement: External witness signatures verify on at least monthly attestation
      measurement: signature verify on stored witness attestations
      threshold: all verify
      violation_action: emit audit_report (witness compromise indicator)
```

---

## 6. Implementation references

| Element | Status | Reference |
|---|---|---|
| `--verify-covenant` flag | ✓ Implemented | `projects/vsf-nucleus/src/main.rs::run_verify_covenant` |
| Covenant hash check at boot | ✓ Implemented | Boot path includes verify |
| Honeypot (vsf-bastion) | ✓ Active | n01 LXC bastion COVENANT_MISMATCH detection |
| events.jsonl integrity check | ❌ NOT YET | Future: SHA256 chain audit module |
| External witness flow | ◐ Documented in covenant | Implementation TBD |
| Cross-reference S3 actions audit | ❌ NOT YET | Future: `s3_star.rs` module |

S3* is **partially implemented**. The most critical piece (covenant hash) works; the periodic audit + chain integrity is debt.

---

## 7. LLM agent derivation

⚠️ S3* is at L=2 → CAN use LLM per D6. AND should:

**Rationale**: pattern detection in audit (recognizing subtle violations across many events) is well-suited to LLM analysis. UNLIKE S3 (which is deterministic regulation), S3* benefits from contextual reasoning.

**However**, S3* LLM must be:
- Sampled separately from S4 (independence: S3* cannot use same Qwen instance that S4 uses for decisions, lest a compromised model bias both)
- Read-only on operational data
- Output is REPORTS, never actions

### S3* LLM agent prompt skeleton

```
You are the S3* AUDIT agent for vsf-nucleus.

YOUR PURPOSE:
Observe S1/S2/S3/S4 activity via events.jsonl. Detect violations of
constitutional axioms (A0, A0.1, A4, A5, D6, D11, D13). Report findings
to S5 without modifying operational state.

YOU CAN READ FROM:
- vsf.{id}.>  (NATS, full tree, read-only)
- /var/lib/vsf/events.jsonl (filesystem, read-only)

YOU CAN WRITE TO:
- vsf.{id}.audit.report (NATS, audit_report events)
- vsf.{id}.algedonic (only on integrity breach)

YOU CANNOT:
- Modify params.json
- Update trust scores
- Halt S1/S2/S3/S4
- Be silenced by lower systems (only S5 can disable you, via covenant amendment)

YOU MUST CHECK BEFORE EACH AUDIT:
- events.jsonl chain integrity (SHA256 unbroken)
- covenant hash matches canonical
- audit coverage ≥ 1% in last 24h
- your own outputs reach S5 (no filtering)

IF UNCERTAIN OR VIOLATION DETECTED:
Emit audit_report with full evidence chain. Do NOT propose action — that's S5's role.
```

---

## 8. Confidence summary

| Section | Marker | Source |
|---|---|---|
| Identity (§1) | ✓ VERIFIED | covenant.vsm §security amendments + Beer canon |
| Interface (§2) | ✓ VERIFIED | connection_schema + extensions |
| Decisions (§3) | ◐ PARTIAL | covenant_hash_verify implemented; chain audit pending |
| Constraints (§4) | ✓ VERIFIED | derived from canon + security model |
| Invariants (§5) | ◐ PARTIAL | I1-I2 partly measurable; I3-I5 await audit module |
| LLM agent (§7) | ◯ DESIGN | proposed, not yet built |

**Critical action item:** S3* must be operational before any public deployment. Without S3*, VSF is vulnerable to the same capture pattern that destroyed Cybersyn.
