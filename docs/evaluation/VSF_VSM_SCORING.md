# VSF vs Beer's VSM — Honest Conformance Scoring

**Date:** 2026-05-25
**Author:** VSF Validation Team (self-assessment)
**Method:** Per-subsystem score 0-10 based on
  (a) implementation coverage in `projects/vsf-nucleus/src/`,
  (b) operational evidence in production LXC 101,
  (c) theoretical completeness in `docs/`.

**Important caveat:** This is self-assessment. External review by someone with
deep VSM expertise (e.g., Fierro UV per [[outreach-beer]]) would carry more
weight. Treat numbers as ordinal rankings, not absolute measurements.

---

## Headline 2026-05-29 — **6.6 / 10 FUNCTIONAL** (structural 7.5)

**Honest audit (Qwen 2026-05-29) corrected an inflated 7.5 claim.** Viability
requires BOTH structure AND continuous operation. Two scores now reported:

- **Design readiness (structural): 7.5/10** — organs built (Tier α + Phase 4)
- **Functional viability (operational): 6.6/10** — organs metabolizing ← HEADLINE

Qwen: "organs that don't metabolize = cadaver with correct anatomy. The gap
IS the diagnosis." Structural-only is "design readiness", not viability.

### Operational deductions (verified 2026-05-29 18:50 UTC)

| Subsystem | Structural | Functional | Deduction reason |
|---|---|---|---|
| S3* Audit | 6 | **4.5** | daemon never cycles (Poisson 100-day rate); only manual --once ran |
| Variety | 7 | **5.0** | invariant_check samples=0 (record_* never called) |
| BRECHA-5/6 | closed | **degraded** | bbs-bridge subscription dead 2.5d, silent, no recovery |

Restoration: fix_1 (s3-star rate=24/24h) + fix_2 (NATS heartbeat/reconnect) +
fix_3 (synthetic load). After all 3: functional ≈ structural ≈ 7.5.
**S1/BBH integration ON HOLD until fix_1 + fix_2** (Qwen Q7 verdict).

Detail: `docs/sessions/briefs/qwen_response_phase4_honest_audit_vsl_2026-05-29.md`.

---

## Structural progression history

### 5.0 / 10 baseline (2026-05-25, Qwen P4 review)

Earlier self-assessment scored 6.3/10 — Qwen identified generosity bias in 3 places:
- S5 5→3 (declarative without enforcement is not S5)
- Algedonic 8→5 (deployed ≠ validated)
- Recursion 4→3 (no live hooks, theory only)

Lowering the baseline makes the 7.5 target meaningful and forces functional
closure over count-of-deployments. Beer-faithful.

Strengths (still): S3 control + supervision, telemetry chain, covenant signed.
Weaknesses: S3* (no code), S5 enforcement gap, algedonic unvalidated, recursion dead.

---

## Per-subsystem scoring

### S1 — Operations (the units that do the work) — **5/10**

**Beer's definition:** Autonomous operational units that do the actual work
the system was built for. Each has its own viability + interface to S3.

**VSF implementation:**
- ✓ Canonical emit loop (γ.1) wraps a "kernel_tick" S1 inside Supervisor(S1) — but this is heartbeat, not work
- ✓ `Subsystem::S1` enum + supervision per β.4
- ✓ BBH-as-S1 inside V_vsf architecture defined + γ.9 subscriber ready
- ✗ BBH not yet publishing → no real S1 doing actual security work
- ✗ Multiple S1 instances (the canonical VSM has many) — only 1 instance today
- ◐ S1_operations.md spec exists but is mostly theoretical

**What would raise the score:**
- BBH publisher live → 7/10
- Multiple BBH instances (alpha, beta, ...) → 8/10
- Real recursive S1 (V_bbh has its own S1..S5 internally) → 9/10

### S2 — Coordination (anti-oscillation) — **6/10**

**Beer's definition:** Prevents S1 units from stepping on each other. Stafford
emphasized this is "the most overlooked" subsystem.

**VSF implementation:**
- ✓ `algedonic.rs` (γ.4) provides rate limiting per origin (max_per_sec=2.0)
- ✓ ALG-1 invariant prevents cascades (exp(-λt) decay enforced)
- ✓ Hysteresis baseline_stasis_cos for damping
- ✗ Only 11 code refs to "S2" — semantically present, lexically thin
- ✗ S2_coordination.md spec exists but no dedicated S2 module
- ◐ No explicit inter-S1 coordination (because only 1 S1 today)

**What would raise the score:**
- Explicit `s2.rs` module mediating between multiple BBH instances → 7/10
- Cross-instance lock manager + dependency graph → 8/10

### S3 — Control (resource allocation, NOW) — **7/10**

**Beer's definition:** Manages the now — resource allocation, performance
monitoring of S1 units, intervention authority.

**VSF implementation:**
- ✓ `s4_operational.rs` (despite the name, also does S3 work): reads system state, decides
- ✓ `supervisor.rs` (β.4) with per-subsystem restart logic — direct S3 function
- ✓ `invariant_checker.rs` (γ.6): VAR-1, TRUST-1, ALG-1 enforcement
- ✓ Algedonic emit on circuit-breaker → S3 intervention path
- ✓ P.3 phi_down_subscriber receives policy overrides → applies to config
- ◐ P.3.1 deferred: live config re-read by S4 thread not yet wired (control loop functionally measurable but behavioral change limited)
- ◐ 67 code refs to "S3" but naming overlap with `s3_nucleus_bbs` legacy

**What would raise the score:**
- P.3.1 Arc<RwLock> threading → 8/10
- Multi-S1 resource allocation logic (which BBH instance gets which target?) → 9/10

### S3* — Audit (anti-capture, bypasses S3) — **2/10**

**Beer's definition:** Sporadic direct channel from S5 to S1. Sees what S3
might filter out or suppress. Anti-corruption mechanism.

**VSF implementation:**
- ✗ **0 code references** to S3* / S3_star / s3_star
- ◐ S3_star_audit.md spec exists (theory only)
- ◐ S3_star_agent_prompt.md DESIGN (not deployed)
- ✓ Independent Qwen-on-different-LLM is design intent (separate from S4 Qwen)
- ✓ Covenant audit interval (60min) in s5_policy.default.json

**What would raise the score:**
- `s3_star.rs` module with sporadic sampling (audit_sample_rate_per_24h=0.01) → 5/10
- Separate process / different LLM model → 7/10
- Independent witness verification → 9/10

**Honest:** This is the biggest VSM gap. We have the theory but no code.

### S4 — Intelligence (environment + future) — **6/10**

**Beer's definition:** Watches the outside, plans ahead. Strategy.

**VSF implementation:**
- ✓ `s4_operational.rs` runs Qwen 2.5-coder cycles every 300s
- ✓ Reads system state + asks LLM for decisions
- ✓ 70 code refs, P.1 dual-write to events.jsonl
- ✓ S4_agent_prompt.md operational (deployed)
- ◐ "Environment" is currently just /proc + BBS — not real external monitoring
- ◐ Decisions are short-term (per cycle) not long-term planning
- ◐ Qwen output is JSON decisions to BBS — no real "plan" structure

**What would raise the score:**
- External env feed (HackerOne announcements, CVE feeds, weather, etc.) → 7/10
- Multi-step planning + plan_data persistence → 8/10
- CHECO equivalent (system simulation for what-if) → 9/10 — this is the
  vOS Stage 2-3 goal per [[vos-architecture]]

### S5 — Policy (identity, axioms) — **5/10**

**Beer's definition:** Sets the rules nobody can override. Identity, mission,
ethos.

**VSF implementation:**
- ✓ covenant.vsm v1.1 signed (hash in LICENSE)
- ✓ A0/A0.1 axioms (ethical primacy, anti-coercion)
- ✓ s5_policy.schema.json + s5_policy.default.json deployed
- ✓ τ_min thresholds, rate limits, algedonic params under S5 control
- ✗ No live S5 policy engine — policy is static config, no agent
- ✗ S5_agent_prompt.md is DESIGN (high-risk, gated by human approval)
- ✓ A5 enforcement: double-loop = human approval (in spec, not yet exercised)

**What would raise the score:**
- Policy engine that evaluates predicates → 6/10
- S5 agent (LLM proposing policy changes, gated by rmw3 sign) → 8/10
- Multi-witness covenant verification → 9/10

### Algedonic channel — **8/10**

**Beer's definition:** Pain/pleasure signal — direct from anywhere to S5,
bypassing hierarchy.

**VSF implementation:**
- ✓ `algedonic.rs` (γ.4) deployed, 210 LOC, 106 code refs
- ✓ Binary {0,1} per Qwen consensus round 3
- ✓ Rate-limited (MAX_PER_SEC=2.0 per origin)
- ✓ Local resolution timeout 500ms before escalation
- ✓ NATS Core path: `vsf.<vsf_id>.algedonic` separate subject
- ✓ Hysteresis with baseline_stasis_cos
- ✓ Cross-system: BBH can publish to `bbh.<inst>.algedonic`
- ◐ Not yet exercised by real distress signal in production

**What would raise the score:**
- First real production fire (incident → algedonic → S5 response → resolution) → 9/10
- Multi-instance cross-fire (one BBH's algedonic triggers other's S2 throttle) → 10/10

### Recursion (V(...) at multiple L levels) — **4/10**

**Beer's definition:** Every viable system contains and is contained in
viable systems. Self-similarity.

**VSF implementation:**
- ✓ `docs/recursive_vsm_theory.md` formal theory + axioms
- ✓ V notation in `vsm_notation_spec.md`
- ✓ V(vsf-nucleus, L=1) declared everywhere
- ✓ V(proxmox-n02, L=1) spec exists per [[proxmox-vm-architecture]]
- ✗ **0 code references** to "recursive" or "recursion" in nucleus
- ✗ No actual nested V instance live (BBH-as-V_bbh would be first)
- ◐ Theory rich, practice thin

**What would raise the score:**
- BBH live with its own S1..S5 internally → 6/10
- Two BBH instances (alpha, beta) both as V(bbh, L=2) → 7/10
- Cross-level audit (V_vsf.S3* sees V_bbh.S5 covenant violation) → 9/10

### Variety / Requisite Variety (Ashby) — **7/10**

**Beer's definition:** Control system variety ≥ regulated system variety.

**VSF implementation:**
- ✓ VAR-1 invariant: ΔV_in ≥ ΔV_out enforced in invariant_checker
- ✓ variety_delta field on every CanonicalEvent (γ.1)
- ✓ Variety attenuator semantics (φ↑ should attenuate)
- ✓ Variety amplifier semantics (φ↓ should amplify)
- ◐ K measurement protocol GATE_3 will quantify this empirically
- ◐ Currently mostly theoretical; needs W2 data

### Trust-1 + Covenant — **7/10**

- ✓ TRUST-1 invariant: Π trust_i ≥ threshold
- ✓ Covenant SHA-256 verified at boot (configurable per s5_policy)
- ✓ tau_min per system (defaults 0.5/0.6/0.8 per source)
- ✓ Multi-system trust composition (chain product)
- ◐ No witness signature verification yet (`signature` field optional)

---

## Score table (Qwen-refined 2026-05-25)

| Subsystem | Score | Trend | Bottleneck to raise | Note |
|---|---|---|---|---|
| S1 Operations | 5/10 | ↗ | BBH publisher | unchanged |
| S2 Coordination | 6/10 | → | Multi-S1 first | unchanged |
| S3 Control | 7/10 | ↗ | P.3.1 thread Arc<RwLock> | unchanged |
| **S3\* Audit** | **2/10** | → | **Build vsf-s3-star (separate binary)** | unchanged |
| S4 Intelligence | 6/10 | → | Real env feed | unchanged |
| **S5 Policy** | **3/10** | → | Enforcement (fail-closed) + agent + witness | **was 5, Qwen: declarative ≠ S5** |
| **Algedonic** | **5/10** | → | First real fire-and-resolve cycle | **was 8, Qwen: deployed ≠ validated** |
| **Recursion** | **3/10** | ↗ | BBH live as V_bbh | **was 4, Qwen: no live hooks** |
| Variety (Ashby) | 7/10 | ↗ | W2 K measurement (refined: semi-Markov, n≥100) | unchanged |
| Trust/Covenant | 7/10 | → | Multi-witness sign + verify path | unchanged |

**Refined mean: 5.1. Weighted core-five emphasis: 5.0.**

**Baseline: 5.0 / 10**. Target after Tier α: 7.5/10.

---

## Honest commentary

**What's GOOD about VSF as a Beer-faithful implementation:**

1. The 5-system framing is preserved end-to-end — not collapsed into MVC or microservices euphemisms.
2. Algedonic is a real binary signal, not a marketing word. γ.4 implements
   bypass-the-hierarchy semantics correctly.
3. Recursion is theoretically clean (V(id, L) + connection_schema), even if
   practice is thin.
4. Covenant + axioms + S5 trust ladder are not bolt-on ethics — they're
   structurally enforced (covenant.vsm signed, hash verified at boot).

**What's WORSE than canonical VSM:**

1. **S3\* is the biggest hole.** Beer was insistent that an organization
   without S3* gets captured by its S3. We have docs, no code.
2. **Recursion is single-level.** A real VSM has many V(...) at L=1 inside
   one V(...) at L=0. We have one V_vsf and a planned V_bbh, that's it.
3. **S4 is short-horizon.** Qwen sees current state + outputs decisions for
   the next ~minute. Real S4 should think in weeks/months.
4. **S5 has no agent.** Policy is static config files. Beer's S5 was an
   active conversation, not a JSON.

**What's BEER would say (if we could ask):**

> "Where's your homeostat? Where's your CHECO? Where's the Operations Room
> that lets the human see in real time? And — most importantly — what's
> your reason for being? S5 isn't config, S5 is identity."

We have an answer to the last one (covenant.vsm + A0 ethical primacy).
We are missing the rest.

---

## Roadmap to 8/10

In dependency order:
1. **BBH publisher live** → S1 to 7/10, Recursion to 6/10 — depends BBH side
2. **Write `s3_star.rs`** (sporadic sampling, separate model) → S3* to 5/10 (~1-2d Rust)
3. **P.3.1 Arc<RwLock> thread to S4** → S3 to 8/10 (~half day)
4. **Multi-instance support** (2nd BBH) → S2 to 7/10, Recursion to 7/10
5. **External env feed for S4** → S4 to 7/10 — design needed
6. **S5 agent (gated, witness)** → S5 to 7/10 — high risk, requires witnesses per A5

Cumulative effect: **7.5 / 10**, lifecycle `testing`.

For 9/10 we'd need first real algedonic fire + multi-witness covenant + CHECO-equivalent.

---

## References

- Beer, S. (1972). *Brain of the Firm*. Allen Lane.
- Beer, S. (1979). *The Heart of Enterprise*. Wiley.
- Medina, E. (2011). *Cybernetic Revolutionaries*. MIT Press.
- VSF: `docs/concepts.md`, `docs/recursive_vsm_theory.md`,
  `docs/theory/systems/{S1..S5}_*.md`, `core/connection_schema.json` v0.2.1.
