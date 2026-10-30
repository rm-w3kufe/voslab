# Cybersyn Convergence — Divergence Register & Convergence Paths

> Canonical reference for R11 Case A. Each Cybersyn-heritage component is
> assessed against Beer's original design. The name is the target; this
> document records the gap and the path to close it.
>
> Scoring: **conformity %** = fraction of Beer's canonical function currently
> implemented. Updated at each session that advances a component.
>
> Last updated: 2026-06-10

---

## Assessment Table

| Component | VSM Role | LXC | Current impl | Conformity | Gap summary |
|-----------|----------|-----|-------------|-----------|-------------|
| Cybernet | S2 coordination | 106 | NATS + bbs-api + topic schema + live φ↑ replication + φ↓ enforcement + delivery tiers + A4 network firewall | **100%** | C2.a-e ✓ COMPLETE (e: 2026-06-12 — 106.fw allow-list live, S1→S1 blocked, NAT source-attribution bug fixed, coupling_registry row) |
| Cyberfilter | S3 control | 101 | vsf-nucleus + norm.vsm + variety accounting + RC-3/RC-4 action channel + EWMA/CUSUM SPC | **100%** | F3.a ✓; F3.b ✓; F3.c ✓ 2026-06-12; F3.d ✓ 2026-06-20 (cyberfilter_variety.py: events_in/alerts_out → state.db:cyberfilter_health, daily timer) |
| Cyberstride | S3* audit | 107 | reconciler + KPI poller + SA exception feed + spot-checks + exp-progress tracking | **100%** | S3*.a-e ✓ (2026-06-12); all capabilities closed |
| CHECO | S4 intelligence | 101 | EP+AC+SD+SA + what-if engine + NL narrator + env model | **100%** | CH.a-e ✓ COMPLETE 2026-06-20 (CH.c KernelStepper what-if; CH.d Qwen NL narrator E2E; CH.e PSI+thermal+telemetry env model) |
| Opsroom | S5 policy | 109 | formaid diagram studio | **15%** | excluded from convergence plan by operator decision (2026-06-11) |

> Scores updated 2026-06-20: Cybernet 100 / Cyberfilter 100 / Cyberstride 100 / CHECO 100 / Opsroom 15 — mean 83% (100% excl. Opsroom).
> Previous 2026-06-19: Cybernet 100 / Cyberfilter 95 / Cyberstride 100 / CHECO 55 / Opsroom 15 — mean 73%.
> Previous 2026-06-12: Cybernet 100 / Cyberfilter 95 / Cyberstride 100 / CHECO 35 / Opsroom 15 — mean 69%.
> Previous 2026-06-12k: 95/95/100/35/15. Baseline 2026-06-10: 60/50/30/25/15.
> C2.e note: per-LXC pve firewall live on 106/107/108/109 (sources: scripts/state/firewall/).
> Pre-existing NAT bug fixed en route: bridge-nf + `-o vmbr0` MASQUERADE rewrote ALL inter-LXC
> traffic to the host LAN IP — broker could not attribute sources. vsf-nat-vlans.service now
> inserts an intra-10.10.0.0/16 RETURN exemption. Residual: 101/104 NIC firewall flag deferred
> to ~2026-06-18 (EXP-TRUST-01 phase A: prod 101 untouched).

---

## 1. Cybernet → S2 (LXC 106: nats-server + bbs-api)

**Beer's definition:** A telex/communications network connecting operational
units (factories) to the Santiago centre and back. Real-time, reliable,
redundant message relay — the *channel*, not the intelligence. Carried φ↑
(operational data up) and φ↓ (management instructions down).

**Current implementation:** NATS pub/sub broker on LXC 106 (`s2-broker`),
plus `bbs-api` for structured messages. The S2 function (prevent S1 units from
colliding) is structurally present.

**Conformity: 60%**

**What is missing:**
- φ↑/φ↓ channels not fully wired — most nucleus telemetry goes directly to
  `events.jsonl` without routing through NATS
- No formal channel protocol (VSI/1.0 task O is the enabler)
- Management instructions (φ↓) from S3→S1 path is implicit, not enforced
  through the broker

**Convergence path:**
1. Wire nucleus φ↑ to NATS topics (DSN-COUPLE-01 phases 3b/4 — task F5.x.1+4)
2. Define formal φ↑/φ↓ topic schema in NATS (extends VSI/1.0 L3 channel)
3. Route all S1→S3 and S3→S1 flows through the broker (not direct SSH/file)

---

## 2. Cyberfilter → S3 (LXC 101: vsf-nucleus-operational)

**Beer's definition:** A statistical filter that attenuates the variety of
operational data from S1, presenting only significant deviations from agreed
norms to S3 management. Statistical, not conversational. Operates on time-
series production variables compared against a model (plan vs. actuality).
In Cybersyn: Cyberfilter was statistical process control at the S3 interface.

**Current implementation:** vsf-nucleus Rust kernel computes Lyapunov
exponents, stasis_cos (cosine similarity to attractor), trust tracking,
invariant checks, and homeostatic monitoring. AC classifier (ac_classifier.py)
provides deterministic anomaly classification over φ↑ events.

**Conformity: 50%**

**What is conformant:**
- Variety reduction: only significant deviations (class A/B) surface as alerts
- Statistical character: Lyapunov analysis, stasis_cos — no LLM in the path
  (R10 / D6')
- Real-time: sub-second kernel ticks

**What is missing:**
- Plan vs. actuality comparison: nucleus monitors convergence to an attractor,
  not deviation from an operator-set production norm
- S3 interface: filtered output (AC alerts) is not yet formally handed to S3
  control — it goes to s5-alerts.db and is read by SD/human, but S3 does not
  act on it automatically
- Multi-variable statistical process control (SPC): nucleus tracks the single
  aggregate state vector ℝ¹²⁸, not per-variable operational KPIs

**Convergence path:**
1. Define "norm" as the attractor region (R ⊂ Ω) — deviation from R = alert
   (already implicit in Lyapunov regime tracking; needs explicit norm concept)
2. Wire AC class-A alerts to an S3 action channel (not only to SD/human)
3. Per-variable SPC for key S1 operational indicators (future — depends on S1
   units declaring their KPIs in coupling manifests)

---

## 3. Cyberstride → S3* (LXC 107: vsf-s3-star)

**Beer's definition:** The STAFFORD BEER Operations Management Information
System — a statistical software package for tracking factory performance
indicators, production planning, and management by exception. In VSM terms
it supports the *sporadic direct channel* from S3 to S1 that bypasses S2,
allowing S3 to see S1 directly when needed. Statistical process control,
PERT-style progress tracking.

**Current implementation:** `vsf-s3-star` runs the anti-orphan topology
reconciler: census of declared vs. live components, detects orphans/flap,
emits algedonic signals. SA auditor (`sa_auditor.py`) is invoked from this
layer.

**Conformity: 30%**

**What is conformant:**
- Correct architectural position: S3* is the sporadic direct audit channel —
  topology reconciliation IS a form of direct S3→S1 inspection
- SA auditor gives management-by-exception output (audit flags)

**What is missing:**
- No statistical tracking of S1 operational KPIs against a plan
- No PERT/progress tracking of experiment or task execution
- The "sporadic direct" character is present for topology but not for
  operational performance data

**Convergence path:**
1. Extend S3* to poll S1 operational metrics (nucleus kernel_tick stats:
   stasis_cos trend, trust history, regime transitions) on a scheduled basis
2. Compare against baseline (a "plan" expressed in experiment specs)
3. SA auditor integration: LXC 107 invokes `sa_auditor.py` on a schedule
   (pending task in project_pending_arcs)

---

## 4. CHECO → S4 (S4 Intelligence Layer, LXC 101)

**Beer's definition:** CHilean ECOnomy — a large-scale system dynamics
simulation model (Forrester style) for forward projection and scenario
analysis of the national economy. S4 function: look *outward* (environment
sensing) and *forward* (future state projection). What-if analysis, scenario
modeling, consequence simulation.

**Current implementation:** S4 Intelligence Layer — EP (RAG retrieval from
experiment corpus), AC (deterministic algedonic classifier), SD (S5 synthesis
digest), SA (semantic auditor of coupling registry + experiments). Backward-
looking analyst + pattern recognizer + synthesis engine.

**Conformity: 25%**

**What is conformant:**
- Correct S4 function: environmental intelligence, pattern recognition,
  synthesis for management — these are S4 activities
- SD and SA produce intelligence *for* S5 decision-making (the Opsroom feed)
- AC provides the filtering Beer assigned to the environmental monitoring layer

**What is missing:**
- No forward simulation / scenario modeling (the core of CHECO)
- Intelligence is retrospective (what happened) not prospective (what will
  happen given X)
- No model of the "environment" (external variety) — only internal state

**Convergence path:**
1. `vsl_run.py propose` is the first step: Qwen proposes next experiments =
   a primitive forward projection from past patterns
2. Future: scenario simulation over ℝ¹²⁸ state space using the attractor
   geometry (basin volume, Lyapunov stability margins → what-if perturbations)
3. EXP-TRUST-01 and EXP-LYAP-CERT would produce the empirical basis for a
   simple forward model ("if trust degrades at this rate, viability breach
   in N ticks")

---

## 5. Opsroom → S5 (LXC 109: formaid studio, vsf-view-host :8088)

**Beer's definition:** The Operations Room — a purpose-built decision support
environment for S5 operators. Hexagonal room, 7 Aeron chairs, 4 large
projection screens showing variety-reduced operational data (filtered by
Cyberfilter), an algedonic panel with direct alert-to-operator signaling.
Designed for real-time collaborative decision-making with minimal extraneous
variety. Decisions recorded. Every data display was pre-filtered — operators
saw only what required a decision.

**Current implementation:** Formaid diagram studio on LXC 109 — a Mermaid
diagram editor with live view modules (`cybernetic-rag` showing φ↑ events,
`system-topology` showing state.db). A visualization and diagramming tool.

**Conformity: 15%**

**What is conformant:**
- Correct layer: deployed as the S5 surface
- System topology visible: `system-topology` module shows the VSM structure
- Some φ↑ signal visibility: `cybernetic-rag` module shows nucleus events

**What is missing (the most significant gap):**
- No variety reduction: raw events are shown, not pre-filtered to decision-
  relevant signals
- No integrated algedonic panel: AC alerts (s5-alerts.db) are not wired into
  the display
- No SD digest integration: the synthesis output of SD is not surfaced
- No decision recording: S5 decisions are not logged in the Opsroom
- No multi-seat / collaborative interface
- No action triggers from the Opsroom surface

**Convergence path (prioritized):**
1. **Near-term**: Wire AC alerts → Opsroom view module (show class A/B alerts
   with timestamp and label in a dedicated algedonic panel widget)
2. **Near-term**: Surface SD digest output in the Opsroom — when a digest.vsm
   is written, it should appear in the S5 view
3. **Medium-term**: Variety reduction in the topology view — only show
   degraded/warning/critical states, not the full topology by default
4. **Longer-term**: Decision recording — when an operator acknowledges an
   alert or accepts/rejects an SA audit flag, record it in state.db
5. **Vision**: Replace the generic diagram studio with a purpose-built S5
   decision surface (Beer's intent) — this is a significant UX arc

---

## Conformity Summary

```
Cybernet  (S2):  95% ███████████████████░  next: C2.e A4 firewall (R3/Fable — final gap)
Cyberfilter(S3): 70% ██████████████░░░░░░  next: F3.b S3 action channel (gate: C2.c + S5 ratify)
Cyberstride(S3*):100% ████████████████████  COMPLETE (S3*.a-e, 2026-06-12)
CHECO      (S4): 55% ███████████░░░░░░░░░  next: CH.c what-if (gate: Theme E lyapunov/vr wiring)
Opsroom    (S5): 15% ███░░░░░░░░░░░░░░░░░  EXCLUDED from plan (operator decision 2026-06-11)
```

**Mean conformity: 73%** (... → 63% 2026-06-12 → 73% 2026-06-19: CHECO 35→55% via CH.b calibrated) — 83% excluding Opsroom.
CRITICAL-PATH CORRECTION (2026-06-11 evening): C2.b verified ALREADY LIVE —
nats_publisher tails events.jsonl and republishes (kernel_tick observed on the
broker). COUPLE-01 3b is no longer the Cybernet gate; it remains wanted only
for F3.c (KPI manifests) and sensor-registry generality. New critical path:
C2.c (φ↓ enforcement) → F3.b (S3 action channel) — both Sonnet-executable.
Wave 1 + Wave 2 executed 2026-06-11: topic schema, norm.vsm, KPI poller,
EXP-TRUST-01 phase A, variety accounting (+ AC heartbeat fix), operator
shadow wiring (F5.x.1) + omega wiring reconciled (F5.x.4). Single biggest
remaining gate: COUPLE-01 3b (manifest-driven sensor registry) → opens
C2.b/c → opens F3.b.

---

# Convergence Plan to 100% (2026-06-11)

> Scope: Cybernet, Cyberfilter, Cyberstride, CHECO. **Opsroom excluded by
> operator decision (rmw3, 2026-06-11)** — its convergence path above remains
> the reference but is not scheduled here.
>
> Planning style: logical gates (IF/THEN), not time estimates
> (per feedback_temporal_estimation_antipattern). A phase is *ready* when its
> gate condition holds, *done* when its acceptance criterion is verifiable.

## Scoring rubric

Each component's canonical function is decomposed into equally-weighted
capabilities. Conformity % = capabilities verified / total. "Verified" means
an acceptance criterion that a fresh auditor can check from artifacts
(state.db rows, running crons, committed specs, passing tests) — not from
session memory.

---

## Cybernet (S2): 60% → 100%

Beer's canon decomposed (5 capabilities, 20% each):
1. ✅ Broker exists, S1-adjacent services connected (NATS LXC 106)
2. ✅ Structured message relay (bbs-api)
3. ◐ φ↑ carried on the channel (algedonic only; bulk telemetry bypasses broker)
4. ◯ φ↓ enforced through the channel (phi_down_subscriber exists; S3→S1 still direct SSH/file)
5. ◯ Formal channel protocol + A4 network enforcement

**C2.a — Formal topic schema** [gate: none — ready now]
- Define `vsf.{id}.phi.up.{unit}` / `vsf.{id}.phi.down.{unit}` topic grammar
  as a VSI/1.0 L3 extension; document in `docs/spec/` + register each topic
  family as coupling_registry rows
- Accept: schema doc committed + registry rows active + sa_auditor sees them

**C2.b — φ↑ through the broker** [gate: DSN-COUPLE-01 phase 3b (Theme E)]
- Nucleus dual-writes: events.jsonl stays the local journal (source of truth,
  Merkle-chained); NATS gets the live stream on `phi.up.nucleus`
- Accept: subscriber on LXC 104 receives ≥99% of journal events; opsroom
  cybernetic-rag module can switch source file→topic with no visual diff

**C2.c — φ↓ through the broker only** [gate: C2.b]
- All S3→S1 parameter changes published to `phi.down.{unit}`; direct-file
  params.json path deprecated; phi_down_subscriber becomes the only intake
- Accept: a params change issued via NATS lands in nucleus config; a
  direct-file change raises an integrity alert (M6-style)

**C2.d — Reliability + anti-oscillation** [gate: C2.b]
- Delivery guarantee tier decision (JetStream vs at-most-once + journal
  replay); reconnect/backoff tested; S2 damping: dedup + rate-limit on
  algedonic storms (cooldown already exists in AC — generalize to broker level)
- Accept: broker restart under load loses 0 journaled events after replay;
  storm test (100 alerts/min) emits ≤ rate-limited stream

**C2.e — A4 at the network layer** [gate: C2.c]
- Firewall rules: S1 LXCs can reach only the broker (no sibling routes);
  access_model column enforced per topic
- Accept: pct exec ping/connect test S1→S1 fails; S1→broker succeeds;
  documented in coupling_registry

IF C2.a..e verified THEN Cybernet = 100%.
Score trajectory: a→70%, b→80%, c→90%, d+e→100%.

---

## Cyberfilter (S3): 50% → 100%

Beer's canon decomposed (5 capabilities, 20% each):
1. ✅ Variety attenuation (class A/B alerts only surface)
2. ✅ Statistical, non-conversational filter in the signal path (R10/D6')
3. ◐ Plan-vs-actuality: attractor convergence tracked, but no operator-set norm
4. ◯ Filtered exceptions handed to S3 *action*, not just to humans
5. ◯ Per-variable SPC on declared S1 KPIs

**F3.a — Explicit norm spec** [gate: none — ready now]
- Write `norm.vsm`: the agreed operating region R ⊂ Ω as explicit bounds
  (stasis_cos ≥ θ, trust ≥ τ, Lyapunov ceiling, viable_full) — S5-ratified
  (double-loop ONCE, then the norm is the standing plan)
- Accept: norm.vsm committed + ratified marker in state.db s5_policy;
  AC classifier reads thresholds from it instead of hardcoded values

**F3.b — S3 action channel (D4-L2 classes)** [gate: C2.c + F3.a + HUMAN]
- Define pre-authorized response classes in VSL (e.g. `class survival_mode:
  IF trust < 0.8 THEN throttle + alert`); S5 ratifies each class explicitly
  (A5: ratification is double-loop; execution thereafter is single-loop)
- AC class-A alerts publish to `phi.down.nucleus` action topic; nucleus
  executes only ratified classes; everything else still routes to humans
- Accept: injected synthetic class-A alert triggers the ratified response
  end-to-end with zero human intervention, and the action is logged with the
  class id + ratification ref

**F3.c — Per-variable SPC** [gate: DSN-COUPLE-01 manifests declare KPIs]
- Each S1 unit's coupling manifest declares its KPIs + expected ranges;
  filter computes EWMA/CUSUM control limits per variable from a baseline
  window; exceptions only (management by exception)
- Accept: ≥2 S1 units with declared KPIs under SPC; a simulated drift in one
  KPI raises exactly one exception (no storm)

**F3.d — Variety accounting** [gate: F3.a]
- Measure attenuation ratio events_in/alerts_out per day; publish as a
  Cyberfilter health metric (Ashby compliance made measurable)
- Accept: metric visible in SD digest input + queryable in state.db

IF F3.a..d verified THEN Cyberfilter = 100%.
Score trajectory: a→65%, d→75%, b→90%, c→100%.

---

## Cyberstride (S3*): 30% → 100%

Beer's canon decomposed (5 capabilities, 20% each):
1. ✅ Sporadic direct channel exists (topology census bypasses S2)
2. ◐ Management by exception (audit flags exist; scope = topology+semantic only)
3. ◯ Statistical tracking of S1 performance vs plan
4. ◯ Progress tracking of planned work (experiments/tasks)
5. ◯ True sporadic character for operational data (scheduled + randomized)

**S3*.a — Operational KPI polling** [gate: none — ready now]
- Extend the LXC 107 cycle: sample nucleus operational stats directly
  (stasis_cos trend, trust history, regime transitions) into an s3star
  time-series store; this is the direct S3→S1 inspection applied to
  performance, not just topology
- Accept: time series accumulating on LXC 107; gap in polling raises a flag

**S3*.b — Plan comparison** [gate: S3*.a]
- "Plan" = declared expectations: experiment spec close_criteria + norm.vsm
  bounds + TASKS.vsm open tasks; compare actuals each cycle → exception list
- Accept: a stalled experiment (no state change across N polls) and an
  out-of-norm KPI both produce exceptions; nominal state produces none

**S3*.c — Exception feed into SA** [gate: S3*.b]
- SA auditor (already cron 6h on 107) receives the exception list as prompt
  context — Qwen audits exceptions, not raw dumps (variety reduction before
  the LLM boundary, R10-consistent)
- Accept: SA prompt contains the exception block; audit flags reference
  exception ids

**S3*.d — Randomized spot-checks** [gate: S3*.a]
- Each cycle picks one random declared component: verify binary hash (M6
  machinery), service active, and one KPI sample direct from source —
  the genuinely *sporadic* audit Beer intended
- Accept: spot-check log shows uniform coverage over components across
  cycles; a deliberately stopped service on the sandbox (108) is caught by
  the next spot-check

IF S3*.a..d verified THEN Cyberstride = 100%.
Score trajectory: a→50%, b→70%, c→85%, d→100%.

---

## CHECO (S4): 25% → 100%

Beer's canon decomposed (5 capabilities, 20% each):
1. ✅ S4 intelligence products for S5 (EP/AC/SD/SA operational)
2. ◐ Pattern-based proposal (vsl_run propose = primitive forward projection)
3. ◯ Calibrated forward model (time-to-breach projection)
4. ◯ What-if scenario simulation (perturbation → basin analysis)
5. ◯ Environment model (external variety sensing)

**CH.a — Empirical calibration data** [gate: none — ready now; long-running]
- Launch EXP-TRUST-01 (7-day trust dynamics) + EXP-LYAP-CERT; these produce
  the decay/stability parameters a forward model needs
- Accept: both experiments report.vsm with verdict + parameter estimates
  indexed in rag-nucleus.db

**CH.b — Deterministic projection engine** [gate: CH.a]
- `checo_project.py` (or Rust module): given current ℝ¹²⁸ state + Lyapunov
  exponents + calibrated trust slope → project N ticks, output time-to-breach
  margins per norm.vsm bound. Forrester-lite system dynamics; NO LLM in the
  engine (D6/R10) — pure numerics
- Accept: backtest — engine run on historical journal segments predicts the
  known outcome (viability breach or stasis) within stated error bounds

**CH.c — What-if perturbation analysis** [gate: Theme E (lyapunov.rs +
  vr_complex.rs wired) + CH.b]
- Apply synthetic perturbation δ to state vector → basin membership test
  (inside R: recovers; outside: projected divergence) using the attractor
  geometry results (basin radius, cone angle from the papers)
- Accept: perturbation sweep reproduces the empirical critical angle
  (θ_PSI ≈ 0.9377) found in EXP era — the model agrees with measured reality

**CH.d — Scenario interface (LLM at the boundary)** [gate: CH.c]
- Operator asks "what if X" in natural language → Qwen translates to a
  perturbation spec (VSL) → deterministic engine simulates → Qwen narrates
  the result. LLM is translator/narrator only, never simulator (R10)
- Accept: end-to-end scenario run from natural-language question to narrated
  projection, with the .vsm intermediate artifacts persisted

**CH.e — Environment model** [gate: CH.b; scope-limited by R6 internal-first]
- External variety sources available *now*: host thermal state, resource
  pressure (RAM/disk/load), broker health. Model their dynamics as the S4
  "environment" vector; (BBH program metrics join later WHEN R6 gate opens)
- Accept: S4 digest includes environment trend section; a synthetic thermal
  ramp on the sandbox produces a prospective (not retrospective) warning

IF CH.a..e verified THEN CHECO = 100%.
Score trajectory: a→35%, b→55%, c→75%, d→90%, e→100%.

---

## Cross-component dependency graph

```
Theme E (F5.x.1, F5.x.4, module wiring, COUPLE-01 3b/4)
  ├─→ C2.b (φ↑ via NATS) ─→ C2.c (φ↓ enforced) ─→ C2.d, C2.e
  │                              └─→ F3.b (S3 action channel; +HUMAN ratification)
  └─→ CH.c (what-if; needs lyapunov.rs + vr_complex.rs live)

No gate (start anytime, in parallel):
  C2.a (topic schema) · F3.a (norm.vsm; +HUMAN ratification once)
  S3*.a (KPI polling) ─→ S3*.b ─→ S3*.c
                     └─→ S3*.d
  CH.a (launch EXP-TRUST-01 + EXP-LYAP-CERT; long-running background)
  F3.d (variety accounting; after F3.a)

Experiment-gated:
  CH.a ─→ CH.b ─→ CH.d, CH.e

Manifest-gated (COUPLE-01 manifests with KPI declarations):
  F3.c (per-variable SPC)
```

## Execution waves

| Wave | Items | Gate | Mean conformity after |
|------|-------|------|----------------------|
| 1 | C2.a, F3.a (+human ratify), S3*.a→b, CH.a launch, F3.d | none | ~36% → ~51% (excl. Opsroom) |
| 2 | Theme E: F5.x.1 + F5.x.4 + COUPLE-01 3b/4 (Opus session) | none — it IS the gate-opener | unlocks wave 3 |
| 3 | C2.b→c, S3*.c→d, CH.b (when CH.a data lands) | wave 2 | ~70% |
| 4 | F3.b (+human ratify classes), C2.d→e, CH.c | wave 3 | ~85% |
| 5 | F3.c (manifests), CH.d→e | wave 3/4 | 100% (4 systems) |

**Human (S5) decision points embedded in the plan:**
1. F3.a — ratify norm.vsm (once)
2. F3.b — ratify each pre-authorized response class (once per class)
3. C2.d — choose delivery-guarantee tier (JetStream vs journal replay)
4. R6 — opening the BBH gate for CH.e external scope (separate, unforced)
