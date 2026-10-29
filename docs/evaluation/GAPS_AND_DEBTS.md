# VSF GAPS & DEBTS — Unified Register

**Status:** CANONICAL — replaces `DEBT_REGISTER_2026-05-23.md` + `DEBTS.vsm` + `vsm_gap_analysis.md`
**Last update:** 2026-05-25
**Companion:** `docs/plans/strategy_plan.vsm` (strategy), `docs/VSF_VSM_SCORING.md` (per-subsystem scores)

---

## Reading guide

Two registers in one doc:

- **§A — VSM Conformance Gaps** — distance from Beer's canonical VSM (Tier α targets these)
- **§B — Technical Debts** — operational fixes / housekeeping (independent of VSM gaps)

Severity scale: **CRITICAL** (blocks viability) | **MEDIUM** (breaks docs/UX) | **FUTURE** (architectural intent).

---

# §A — VSM CONFORMANCE GAPS

Per `VSF_VSM_SCORING.md` baseline 6.3/10. Tier α addresses A0-A4.

## GAP-S3STAR  ✗ CRITICAL  (current 2/10)

**The biggest gap. Beer-explicit: "Western management cybernetics omits S3*."**

- **Subsystem:** S3* Audit (anti-capture, bypasses S3)
- **Symptom:** Zero code references to `S3*` / `s3_star` in nucleus
- **Why it matters:** No sporadic independent audit ⇒ S3 capture undetectable
- **Spec exists at:** `docs/theory/systems/S3_star_audit.md`, `docs/theory/systems/agents/S3_star_agent_prompt.md`
- **Fix (Tier α Tα.0) — REFINED per Qwen P3b:** SEPARATE binary `vsf-s3-star`
  - New Cargo workspace member, NOT a tokio task in vsf-nucleus
  - Read-only access to `/var/lib/vsf/vsf_nucleus/events.jsonl`
  - Poisson sampling baseline (mean = inverse `audit_sample_rate_per_24h`), with hook for future suspicion-weighting
  - Each wake: covenant hash combo check (local sha256 + HTTPS GET canonical compare), Merkle spot-check, S4 decision audit
  - Emits `s3_star_sample` canonical event via separate NATS publish (system_id="s3_star")
  - Algedonic trigger: **policy-driven** via `s5_policy.s3_star.alert_predicate` (not fixed threshold)
- **Effort:** 4-6h Rust (was 2-4h before separation requirement)
- **Target score:** 2 → 5/10
- **Task:** #88
- **Rationale:** Same-binary tokio task shares crash domain with S3 → not anti-capture. Separate process is Beer-faithful minimum isolation.

## GAP-S3-CONTROL-LOOP  ◐ MEDIUM  (current 7/10)

- **Subsystem:** S3 Control
- **Symptom:** P.3 phi_down emits `param_change` events, but S4 thread doesn't re-read live config
- **Why it matters:** Sensor without actuator. K_φ↓ measurable, behavior change not closed
- **Fix (Tier α Tα.1):** Thread `Arc<RwLock<NucleusConfig>>` through OperationalNucleus → S4Orchestrator
- **Effort:** 1-2h Rust
- **Target score:** 7 → 8/10
- **Task:** #89

## GAP-S5-FAIL-CLOSED  ◐ MEDIUM  (current 5/10)

- **Subsystem:** S5 Policy
- **Symptom:** `s5_policy.verify_at_boot=true` is informational; mismatch does not abort
- **Why it matters:** S5 must own identity — drift without abort contradicts A0
- **Fix (Tier α Tα.2):** New `s5.rs` skeleton: load + validate policy, abort boot on covenant mismatch
- **Effort:** 1-2h Rust + tests
- **Target score:** S5 5→6, Trust 7→8
- **Task:** #90

## GAP-ALG-UNEXERCISED  ◐ MEDIUM  (current 8/10)

- **Subsystem:** Algedonic channel
- **Symptom:** γ.4 deployed, never fired by real distress in production
- **Why it matters:** Untested incident path; cross-system flow unverified
- **Fix (Tier α Tα.3):** Synthetic exercise harness — inject distress, measure resolution time, verify rate-limit + seq monotonicity
- **Effort:** 1-2h Rust tests
- **Target:** validation of existing score
- **Task:** #91

## GAP-WITNESS-EMPTY  ◐ MEDIUM  (current 7/10 Trust)

- **Subsystem:** Trust + Covenant
- **Symptom:** `s5_policy.witnesses[]` empty; `signature` field optional/never populated
- **Why it matters:** Single-point trust; no external attestation path
- **Fix (Tier α Tα.4):** Verify-path scaffolding (signing comes later). Boot reads witness pubkeys, verifies sig if present
- **Effort:** 2-3h Rust
- **Target score:** Trust 7→8.5
- **Task:** #92

## GAP-S2-NO-MODULE  ◯ MEDIUM  (current 6/10)

- **Subsystem:** S2 Coordination
- **Symptom:** 11 code refs, no dedicated `s2.rs` — coordination is implicit in γ.4 algedonic gate
- **Why it matters:** Academic until S1 multi-instance, but spec drift over time
- **Fix:** Hold — defer to Tier γ when first 2 S1 instances exist
- **Status:** DEFERRED

## GAP-S4-SHORT-HORIZON  ◯ MEDIUM  (current 6/10)

- **Subsystem:** S4 Intelligence
- **Symptom:** Qwen 300s cycles, env=/proc, no real outside; no multi-step plans
- **Fix (Tier β B2):** External env feed DESIGN (not implementation)
- **Status:** DESIGN phase before any implementation

## GAP-RECURSION-DEAD  ◯ FUTURE  (current 4/10)

- **Subsystem:** Recursion
- **Symptom:** 0 code refs to "recursive"/"recursion"; only one V instance live
- **Fix:** Exercise via BBH-as-V_bbh (Tier γ, depends external)
- **Status:** EXTERNAL DEPENDENCY

## GAP-S5-NO-AGENT  ◯ FUTURE  (current 5/10)

- **Subsystem:** S5 Policy
- **Symptom:** Policy is static JSON; no S5 LLM agent
- **Fix:** S5 agent gated by A5 human approval (high risk, requires witness)
- **Status:** DEFERRED — needs Tier α Tα.4 done first

---

# §B — TECHNICAL DEBTS

Operational fixes independent of VSM scoring. Mirrored from `DEBT_REGISTER_2026-05-23.md`
with live status updates.

## Post-colapso block (2026-05-23 origin)

| ID | Title | Severity | Status |
|---|---|---|---|
| DEBT-31 | LXC 102/104/106 fantasma post-colapso | Media | ✅ RESOLVED 2026-05-24 (102 destroyed; 104 renamed → telemetry; 106 → vsf-nats-test) |
| DEBT-32 | LXC 105 bbh-prod sin servicio | Media | ◐ open — BBH integration pending |
| DEBT-33 | sqlite3 CLI faltante en LXC 101 | Baja | ⏳ open (1 min fix, low priority) |
| DEBT-34 | Doc PHASE_1-4 RAM mismatch (564KB → 968KB → ~2.2MB now) | Baja | ◐ partial — vsf-arch.html updated, evaluation doc stale |
| DEBT-35 | Sin endpoint HTTP nucleus para query BBS externa | Media | ⏳ open (2-3h) |
| DEBT-36 | Logs S4 no inmediatos en journalctl | Baja | ⏳ open (30 min) |
| DEBT-37 | vsf-arch.html inconsistencia local/remoto | Resuelto | ✅ 2026-05-23 |
| DEBT-38 | Binary no stripped | Baja | ✅ RESOLVED — Cargo profile strip=true, lto=thin |
| DEBT-39 | Ollama API solo loopback (por diseño) | Spec | ✅ verified design intent |
| DEBT-40 | vsf-nucleus-control sin deployment plan | Baja | ⏳ open (deferred until paper retomar) |

## Session 2026-05-25 additions

| ID | Title | Severity | Status |
|---|---|---|---|
| DEBT-41 | systemd restart leaves zombie PID (incident this session) | Baja | ⏳ open — add `ExecStartPre=-/usr/bin/pkill -f vsf-nucleus` to unit |
| DEBT-42 | DEBT-34 evaluation doc PHASE_1-4 not updated for γ-aware binary | Baja | ⏳ open (5 min) |
| DEBT-43 | INDEX.md stale references (some pointed to soon-deprecated plans) | Baja | ✅ resolved by this consolidation |
| DEBT-44 | Plan/roadmap doc proliferation (7+ planning docs) | Media | ✅ RESOLVED 2026-05-25 — strategy_plan.vsm canonical, others deprecated |
| DEBT-45 | W1 collector lacks auto-restart on SSH drop | Baja | ⏳ open — wrap in systemd user unit or autossh |

## VSF-Sandbox debts (legacy, may be already resolved)

Originally in `vsf-infra/DEBTS.vsm`. Most CRITICAL items already resolved.
See that file for unresolved residue. Not migrated here line-by-line because
they pertain to vsf-sandbox public repo, not vsf-nucleus core.

| Pointer | Status |
|---|---|
| DEBT-01 covenant SHA placeholder | ✅ 2026-05-03 |
| DEBT-02 no covenant endpoint | ✅ 2026-05-03 |
| DEBT-03 kernel beacon verifier | ⏳ partial (nucleus Rust exists, beacon protocol not re-released) |
| DEBT-04 GitHub TODO stubs | ◐ partial |
| Other | see `vsf-infra/DEBTS.vsm` |

---

# §C — Cross-references

## Severity legend

- ✗ CRITICAL — blocks viability or VSM correctness
- ◐ MEDIUM — visible degradation, doesn't break
- ◯ FUTURE — architectural intent, scoped later

## Priority blocks (by Tier)

| Tier | Block | Items | Target |
|---|---|---|---|
| α | Internal hardening (current focus) | GAP-S3STAR, GAP-S3-CONTROL-LOOP, GAP-S5-FAIL-CLOSED, GAP-ALG-UNEXERCISED, GAP-WITNESS-EMPTY | VSF score 7.5/10 |
| β | Internal validation | DEBT-35, DEBT-36, GAP-S4-SHORT-HORIZON design | VSF score 8.0/10 |
| γ | S1 integration | DEBT-32, GAP-RECURSION-DEAD | depends BBH side |

## How to add an entry

When adding a new GAP or DEBT:
1. Pick the right section (§A vs §B)
2. Use unique ID (GAP-NAME or DEBT-NNN, sequential)
3. Provide: Subsystem, Symptom, Why, Fix, Effort, Task#
4. Cross-reference in `strategy_plan.vsm` if it changes strategy
5. Cross-reference in `VSF_VSM_SCORING.md` if it changes scores

## Closing an entry

- Mark ✅ RESOLVED with date + commit/evidence
- Move from "active" table to "resolved" subsection if needed
- Do NOT delete — historical traceability matters

## References

- `docs/plans/strategy_plan.vsm` — strategy
- `docs/VSF_VSM_SCORING.md` — scores
- `projects/vsf-nucleus/DEBT_REGISTER_2026-05-23.md` — original debt detail (kept for prose)
- `vsf-infra/DEBTS.vsm` — vsf-sandbox debts (separate repo)
- `docs/internal/vsm_gap_analysis.md` — original 2026-04-06 gap analysis (historical, superseded by VSF_VSM_SCORING)
