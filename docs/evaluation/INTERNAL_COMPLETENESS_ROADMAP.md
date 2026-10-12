> ⚠️ DEPRECATED 2026-05-25 — Canonical source is now **docs/spec_revision/system/plan/strategy_plan.vsm (Tier α detail kept here)**.
> This file is kept for historical traceability. Do not use as live reference.

# VSF Internal Completeness — Roadmap before S1 integration

**Date:** 2026-05-25
**Owner:** VSF Validation Team
**Policy:** Per user principle, NO S1 integration (BBH publisher → events.jsonl
load) until VSF is internally functional + trustworthy.
**Predecessor:** `docs/VSF_VSM_SCORING.md` (baseline 6.3/10)
**Status:** Strategic — supersedes the "race to W2" trajectory

---

## Why this document exists

Up through 2026-05-25 evening, work pushed toward BBH-as-S1 integration as
the next step. After γ.9 + P.4 + BBH publisher contract were delivered,
rmw3 (S5) reframed:

> "Solo cuando logremos 'cierto nivel de confianza' en el sistema, creo
> que sería apropiado integrar módulos S1. Antes de eso, el VSF debería
> ser completamente funcional de manera interna al menos."

This is the correct Beer-faithful order. S1 inherits whatever dysfunctions
S3/S3\*/S5 carry. If S3* doesn't exist, an S1 cannot be audited. If
algedonic was never exercised, the first real incident lands in untested
code. Adding S1 first compounds problems instead of resolving them.

This document enumerates the gaps, orders them by dependency, and proposes
internal completeness milestones.

---

## Gap inventory (taxonomy per subsystem)

### S1 — Operations  (current 5/10, defer)

**Gaps:**
- ✗ No real S1 (BBH not publishing)
- ✗ No multiple-instance support
- ✗ No bounded_self_correction events emitted

**Decision:** Hold. γ.9 subscriber is ready; contract delivered to BBH.
We do NOT prioritize S1 work until S3*/S5 reach acceptable scores.

### S2 — Coordination  (6/10)

**Gaps:**
- ◐ No dedicated `s2.rs` module; coordination is via ALG-1 inside invariant_checker
- ✗ No cross-instance lock manager (academic until S1 multi-instance)
- ◐ Hysteresis defined but rarely exercised

**Decision:** Hold until S1 multi-instance is needed. The S2 function is
adequately served by γ.4 algedonic gate today.

### S3 — Control  (7/10)

**Gaps:**
- ◐ **P.3.1**: Arc<RwLock<NucleusConfig>> not threaded to S4Orchestrator
  → param_change events emit BUT actual config behavior on next cycle is
  isolated. The MEASUREMENT loop works, the CONTROL loop is half-open.
- ◐ Supervisor restart events have no rate limit on restart frequency
- ◐ No "deny" decision exercised by S3 (always approves Qwen output)

**Decision:** **Priority A1** — close P.3.1 immediately. Without it, S3
is a sensor not an actuator.

### S3* — Audit  (2/10)  ← **BIGGEST GAP**

**Gaps:**
- ✗ Zero code references — `s3_star.rs` doesn't exist
- ◐ Spec exists: `docs/theory/systems/S3_star_audit.md`, agent prompt in DESIGN
- ✗ No separate model / process for independent observation
- ✗ No covenant drift detection in production
- ✗ No `audit_sample_rate_per_24h` enforcement (the policy is in
  s5_policy.default.json but no code reads it)

**Decision:** **Priority A0** — this is the load-bearing gap. Beer was
explicit: "an organization without S3* gets captured by its S3."

Implementation sketch:
- New module `s3_star.rs`
- Tokio task wakes at random intervals (Poisson with mean = inverse of
  audit_sample_rate)
- At each wake:
  - Read covenant.vsm canonical hash, compare against S5 policy
  - Sample N recent events.jsonl entries, verify Merkle chain locally
  - Sample S4 decisions, check against covenant constraints
- Emit `s3_star_sample` canonical event with finding
- If finding severity ≥ threshold → emit algedonic

This is the next ~2-4h coding milestone.

### S4 — Intelligence  (6/10)

**Gaps:**
- ◐ "Environment" is just /proc + BBS — not real outside
- ◐ Qwen decisions are short-horizon (per-cycle), no plan persistence
- ✗ No CHECO-equivalent (system simulation / what-if)
- ◐ Trust score for Qwen model not enforced (s5_policy has `tau_llm_model`=0.8 but no check)
- ✗ Multi-step reasoning not exercised

**Decision:** **Priority B2** — design phase first. The "real env feed"
question depends on what VSF is FOR. We deferred this in the past for
good reason: there is no concrete domain (yet) requiring external scan.

### S5 — Policy  (5/10)

**Gaps:**
- ✗ No live S5 policy engine — config is static JSON
- ✗ No S5 agent (intentional — high risk, requires human gate)
- ◐ `signature` field in s5_policy.schema.json is optional, never populated
- ✗ No multi-witness verification (`witnesses[]` array is empty)
- ◐ A5 human approval gate spec'd, never exercised

**Decision:** **Priority A2** — design + skeleton. Even before an LLM
S5 agent, we should:
  - Wire boot-time covenant signature verification (currently optional)
  - Add a `verify_at_boot` enforcement that fails-closed if covenant mismatch
  - Skeleton `s5.rs` that loads + validates s5_policy.json each boot

### Algedonic channel  (8/10)

**Gaps:**
- ◐ Deployed, never exercised by real incident
- ◐ Cross-system flow (BBH algedonic → VSF S5) untested
- ✗ No automatic resolution-confirmation handshake

**Decision:** **Priority A3** — synthetic exercise. Build a test harness
that:
  - Injects a synthetic distress signal
  - Measures local resolution time vs cascade trigger
  - Verifies the algedonic_seq counter monotonicity
  - Verifies rate-limit enforcement (2/sec)

This is a 1-2h test-only task.

### Recursion  (4/10)

**Gaps:**
- ✗ No code refs (only theory)
- ✗ V(vsf-nucleus, L=1) is the only instance; no L=2 inside

**Decision:** Hold. Recursion is exercised by S1 multi-instance; deferred
with S1 itself.

### Variety / Ashby  (7/10)

**Gaps:**
- ◐ VAR-1 tracked but rarely violated in production (no real load)
- ◐ K_φ↑/K_φ↓ measurement instrumented (GATE_3) but no W2 data
- ◐ Internal-only K measurement possible: vary the load synthetically

**Decision:** **Priority B1** — synthetic load test. Generate intra-VSF
variety (synthetic events) to drive K_φ↑ away from baseline 1.0 and
measure with the existing Markov pipeline.

### Trust + Covenant  (7/10)

**Gaps:**
- ◐ Covenant hash verified at boot per s5_policy.verify_at_boot=true, but
  no enforcement (what does failure do? — not coded)
- ✗ Witness signatures: schema defined, no implementation
- ◐ Trust scores per-system stored statically; no live update path

**Decision:** **Priority A4** — fail-closed on covenant mismatch. Today
the boot proceeds even if covenant drifts. This contradicts S5's role.

---

## Ordered priorities (dependency-respecting)

### Tier α — Internal hardening (REQUIRED before any S1)

| # | Item | Effort | Lifts score to |
|---|---|---|---|
| **A0** | **`s3_star.rs` (anti-capture audit)** | 2-4h Rust | S3* 2→5 |
| A1 | P.3.1 Arc<RwLock<NucleusConfig>> threaded to S4 | 1-2h Rust | S3 7→8 |
| A2 | S5 skeleton: boot-time covenant verify with fail-closed | 1-2h Rust + tests | S5 5→6, Trust 7→8 |
| A3 | Algedonic synthetic exercise (test harness) | 1-2h Rust tests | Algedonic 8→8 (validation) |
| A4 | Witness signature scaffolding (verify, not yet sign) | 2-3h | Trust 8→8.5 |

**Tier α cumulative target: 7.5 / 10** — meets "internal completeness" threshold

### Tier β — Internal validation (BEFORE S1, after Tier α)

| # | Item | Effort | Outcome |
|---|---|---|---|
| B0 | β.6 — 24h panic injection in LXC 107 | 1d wallclock, 2h setup | confidence in supervision |
| B1 | Synthetic load test → internal K measurement | 0.5d | GATE_3 partial close (without BBH) |
| B2 | S4 external env feed design (NOT implementation) | 1h | scope clarity |
| B3 | β.5 cgroup v2 budgets per subsystem | 2-3h | resource discipline |

**Tier β cumulative target: 8.0 / 10**

### Tier γ — Then and only then, S1 integration

| # | Item | Status |
|---|---|---|
| γ.9 (DONE) | bbh_subscriber operational | ✅ awaits BBH |
| BBH publisher | BBH side | external |
| Recursion exercise | depends BBH | external |
| GATE_3 close with real data | depends BBH | external |

---

## Confidence threshold (informal, to be calibrated by rmw3)

VSF achieves "certain level of confidence" when:

1. VSM conformance score ≥ 7.5/10 per `VSF_VSM_SCORING.md`
2. S3* operational ≥ 7 days with audit log
3. Covenant verified at boot fail-closed for ≥ 30 days
4. At least one synthetic algedonic fire successfully resolved
5. Supervisor restart events within expected envelope ≥ 14 days
6. No critical debt items open

These are working thresholds; rmw3 to confirm or refine.

---

## What this means for the immediate next session

**Do:**
- Start `s3_star.rs` (Tier α, item A0) — biggest gap, atackable now
- Continue passive W1 monitoring (collector keeps running)
- Keep BBH publisher contract on file (it's ready when we are)

**Don't:**
- Push BBH for publisher implementation timeline
- Add new S1 module variants
- Race toward W2 measurement window

**Communicate to BBH:**
- "VSF appreciates the math foundations work — GATE_5 closed."
- "VSF will achieve internal completeness before requesting W2 plumbing."
- "Contract `bbh_publisher_contract.md` remains valid; please review at your pace."
- "No timeline pressure from VSF side."

---

## References

- `docs/VSF_VSM_SCORING.md` (baseline 6.3/10 self-assessment)
- `docs/operational/gate3_experimental_plan.md` (Markov plan, awaiting data)
- `docs/operational/bbh_publisher_contract.md` (ready, no pressure)
- `docs/theory/systems/S3_star_audit.md` (spec for s3_star.rs)
- `core/s5_policy.default.json` (witnesses[] empty, signature optional)
- memory: [[vsf-internal-completeness-before-s1]] (strategic principle)
