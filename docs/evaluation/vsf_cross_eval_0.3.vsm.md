# `vsf_cross_eval_0.3.vsm`

```
@vsm 0.2

// ============================================================
// VSF — CROSS-MODEL EVALUATION DOCUMENT
// Version: 0.3 (post-OB2+OB3+OB4 integration)
// Date: 2026-04-08
// Purpose: cross-model validation — find gaps, axiom violations,
//          unconsidered aspects. Propose refinements.
//
// Changes from 0.2 → 0.3:
//   D11b: trust formula updated — decay(λ), error_rate(S2), @status override
//   A5:   DNA integrity corollary added (Gemini OB2)
//   D13:  structural safety constraints formalized (Gemini OB4 + ChatGPT P18)
//   Q-vsf-6: RESOLVED
//   OPEN: handshake state machine (#10), revoke/rotate lifecycle (#11)
// ============================================================


// ─── STRATIFICATION ─────────────────────────────────────────

layer("language"):
  name      = VSL
  resolves  = "mutual understanding — what does this message mean?"
  scope     = axioms, grammar, symbols, rules
  openness  = HIGH

layer("framework"):
  name      = VSF
  resolves  = "structural organization — how is the system organized?"
  scope     = S1-S5, φ↑↓, recursion, regulation, intelligence, policy
  foundation = Beer(1972) + Ashby(1956)

layer("protocol"):
  name      = VSF-Protocol
  resolves  = "security + compartmentalization — who connects, with what, under what conditions?"
  implemented_as = V("credential-manager")
  status    = in_progress    // handshake + trust + scanner + provision implemented
                              // revoke/rotate + handshake state machine pending


// ─── AXIOMS A1–A8 ───────────────────────────────────────────

// A1 — Recursion
S1(L) = { V_i(L+1) }_{i=1}^{n}

// A2 — Budget monotonicity (parent-child relation — L is frame-local)
B(child) ≤ B(parent)    ∀ (parent, child) ∈ V.hierarchy

// A3 — Physical resource
B(L) = min( B_tokens(L), B_compute(L), B_time(L) )

// A4 — No direct sibling coupling
∀ V_i(L+1), V_j(L+1), i ≠ j: V_i ↛ V_j
// ψ (D11) is NOT a sibling channel — it connects different VSM trees.

// A5 — Autonomy ceiling (two corollaries)
∀ op ∈ S1(L): op.autonomy ≤ S5(L).ceiling
// Corollary 1 — Ceiling monotonicity:
∀ L > 0: S5(L).ceiling ≤ S5(L-1).ceiling    // ceilings never relax going down
// Corollary 2 — DNA integrity (Gemini OB2):
∀ L > 0: S5(L+1).policy ⊆ S5(L).policy      // child policy is strict subset of parent
rule(S5(L), guard=generate(S5(L+1))):
  enforce: S5(L+1).policy ⊆ S5(L).policy
// S5(L=0) = human-governed root. Sub-S5s may restrict further, never expand.
// DNA integrity ensures no sub-system can self-authorize capabilities above its parent.

// A6 — Ashby's requisite variety
Var(E(L)) ≤ Var(S3(L)) ⊕ Var(S2(L))

// A7 — Escalation (both conditions required)
s escalates  iff  resolve(s, V(L+1)) = ∅  ∧  urgency(s) > τ_{L+1}

// A8 — Absorption invariant
|S(L)| ≤ |S(L+1)| · (1 − r_L)    r_L ∈ (0,1)


// ─── KEY DEFINITIONS D1–D13 ─────────────────────────────────

// D1 — Viable System (formal tuple)
V(id, L) ::= ⟨ S1, S2, S3, S4, S5, E ⟩ @ level=L
// id = stable identifier; L = frame-local position

// D2 — Upward channel
φ↑ : V_i.id → S3(parent_of(V_i)).id
φ↑.payload = telemetry/{system_id}/events.jsonl

// D3 — Downward channel
φ↓ : S3(parent_of(V_i)).id → V_i.id
φ↓.payload = telemetry/{system_id}/params.json

// D4 — Learning loop taxonomy (pre-authorization pattern)
single-loop = corrections within pre-authorized class   → automatable
double-loop = modifying the pre-authorization class     → requires_human
// S5 defines the class of structural change once (human confirm).
// Execution within the class is autonomous.
// Changing the criteria = double-loop — always human.

// D5 — Recursion condition
is_viable(u) = True   iff complexity(u) > τ_viability    // recurse
is_viable(u) = False                                      // execute_atomic

// D6 — LLM constraint
S4(L).uses_LLM = True   only if L ≤ L_max    // default L_max = 2

// D7 — Opsroom (five views)
opsroom(V) = {
  view["system_health"]    ≡ S3.audit,
  view["pipeline_status"]  ≡ S1.operations,
  view["signal_queue"]     ≡ S2.unresolved,
  view["priority_ranking"] ≡ S4.environment,
  view["coverage_gaps"]    ≡ S3 → S4
}

// D8 — Signal status
urgency(s) ∈ { CRITICAL, HIGH, MEDIUM, LOW }
s.status   ∈ { pending, resolved, undecidable, deferred }

// D9 — Calibration score
CalibScore(V, t) = (T_expected / T_actual) · (B_used / B_allocated)
CalibScore ≈ 1.0 → behaves as modeled
CalibScore < 0.7 → bottleneck
CalibScore > 1.3 → model pessimistic

// D10 — Incompleteness state
resolve(s, V) = ∅  ⟹  s.status = undecidable
rule(S3(L), guard=s.status=undecidable):
  if urgency(s) > τ_L: s ⟹ φ↑(s)       // A7
  else: s.status = deferred              // pool — diagnostic for D12

// D11 — Structural coupling ψ (inter-VSM, horizontal)
ψ(V_A, V_B) : S4_A ↔ S4_B
constraints:
  ¬sibling(V_A, V_B)                           // A4
  governed(V_A) ∧ governed(V_B)                // D11b entry gate
  trust_level(V_A, V_B) ≥ limited              // D11b trust
  S5(V_A).approve ∧ S5(V_B).approve            // A5 bilateral
mediated_by: expansion_module ∘ handshake ∘ S3.filter

// ψ lifecycle states:
ψ.state ∈ { requested, validated, active, degraded, revoked }
// requested  → handshake initiated, identity not yet verified
// validated  → trust confirmed, awaiting S5 approval
// active     → channel operational
// degraded   → trust_score dropped to [τ_min, limited) — restricted mode
// revoked    → terminated (trust=0, @status degraded, or human decision)

// D11b — Trust score (v0.3 — decay + S2 component + @status override)
governed(x) = has(params(x)) ∧ emits(events(x))

// Full formula:
trust_score(V, t) = decay(trust_score(V, t-1), λ) ⊕ S3*.audit(V, t)
S3*.audit(V, t)   = stability(S3(V)) ⊕ (1 - error_rate(S2(V)))
decay(score, λ)   = score · (1 - λ)    // λ ∈ [0.0, 1.0], configurable

// trust_score(t) = 0.6 · decay(t-1, λ) + 0.4 · audit(t)
// audit(t)       = 0.5 · reachability + 0.3 · stability(S3) + 0.2 · drift_resistance
//                  · (1 - 0.3 · error_rate(S2))

// @status override (Gemini OB3 — closes Q-vsf-6):
rule(S3*(L), guard=V_peer.status ∈ {deprecated, compromised, unhealthy}):
  trust_score(V_peer) = 0
  terminate(ψ(V_local, V_peer)) ∘ log(S2.access_log)
// @status degraded → immediate trust=0 → ψ revoked, regardless of computed score.

// trust_level mapping:
trust_score ≥ 0.8 → trusted    (ψ_full)
trust_score ≥ 0.5 → limited    (ψ_restricted)
trust_score <  0.5 → none      (forbid_ψ)

// Configurable parameters (via params.json — S5 sets, S3* reads):
param(λ)          = decay_factor      // default 0.05
param(τ_min)      = min_trust_score   // below this → ψ termination signal
param(trust_window) = N events        // default 20

// D12 — Meta-shift indicator
meta_shift(V(L)) = True  iff:
  (∃ class(S): ∀ s ∈ class(S): resolve(s, V(L)) = ∅)
  ∧ |class(S)| / |S_total| > μ
  ∧ CalibScore(V(L), t) < 0.7  for t > δ
meta_shift.severity ∈ { low, medium, high }
// Candidate trigger for reframe() — always requires human approval (A5 + D4).
// rule(S5, guard=meta_shift): no_auto_reframe = True

// D13 — Structural safety constraints
rule(S5): max_recursion_depth ≤ N              // A1 depth bound
rule(S5): promotion_budget_limit = True        // E→V promotions bounded by B(L)
rule(S5): ψ_rate_limit ≤ K                    // max K concurrent ψ channels
rule(S5): no_circular_trust = True             // no A→B→A trust cycle
rule(S5): no_unbounded_growth = True           // |S1(L)| bounded
// Variety Overload guard (Ashby → structural constraint):
rule(S4(L), guard=promote(x, E → V)):
  if count(S1.units) > max_manageable_units:
    resolve(promotion) = ∅
    s ⟹ φ↑(urgency=HIGH, kind="Variety_Overload")
// Variety_Overload connects A6 to D13: variety excess is not just a signal,
// it prevents structural expansion until absorption capacity is restored.


// ─── EXECUTION SEMANTICS ────────────────────────────────────

tick(L):
  1. read φ↓(params)              // D3: parent config first — informs regulation
  2. apply S2(coordination)        // A4: prevent sibling conflicts
  3. apply S3(regulation)          // D4: budget + D8: signal triage
  4. for each s with resolve(s)=∅:
       if urgency(s) > τ_L: s ⟹ φ↑(s)   // A7 escalate
       else: s.status = deferred           // D10 pool
  5. execute S1(operations)        // A1: each unit may tick(L+1)
  6. update S4(env_model)          // A6: after execution — reflects reality
  7. emit φ↑(events)               // D2: report to parent
// CRITICAL: S4 updates AFTER S1. S4 models what happened, not what was predicted.
// CRITICAL: φ↓ is read before regulation — parent params constrain current cycle.


// ─── HANDSHAKE — 4 PHASES ───────────────────────────────────

handshake(V_A, V_B):
  phase_1["identity"]:
    exchange: { id, schema_version, governed_proof }
    gate: governed(requester) = True    // abort if False
    pre-trust — no credentials exchanged

  phase_2["trust"]:
    compute: trust_score(V_B) via S3*   // S3* owned — S4 cannot self-evaluate
    gate: trust_level ≥ limited
    outcome: psi_mode ∈ {ψ_full, ψ_restricted, forbid_ψ}

  phase_3["negotiate"]:
    scope = min(offered_scope(V_A), trust_ceiling(trust_level))
    trust_ceiling: trusted→shared, limited→local
    outcome: effective_scope ∈ {local, restricted, shared}

  phase_4["establish"]:
    check: D13.ψ_rate_limit not exceeded
    check: D13.no_circular_trust (DFS on active ψ graph)
    require: human_approved = True      // A5 bilateral S5 consent
    commit: ψ_channel record → psi_channels.jsonl

// Current implementation: src/handshake.py (phases 1-4 implemented)
// OPEN (#10): handshake needs state machine + replay protection + per-identity rate limit


// ─── STRUCTURAL OPERATIONS ──────────────────────────────────

reframe(V_id, new_parent_id):
  // Phase 1: propose — emit impact_report to S5
  // Phase 2: validate — governed(new_parent_id) + credential check
  // Phase 3: simulate — dry-run φ↑/φ↓ establishment
  // Phase 4: commit — V(V_id).parent = new_parent_id (human_approved required)
  note: "system files are NOT renamed — L is a view parameter only"
  type: double-loop    // D4 — always requires human approval

promote(x, E → V):
  precondition: controllable(x) ∧ needs_regulation(x)
  precondition: count(S1.units) ≤ max_manageable_units    // D13 Variety_Overload
  precondition: policy(S5).allows_promotion                // D4 pre-authorized class
  action: establish(φ↓, φ↑) ∘ x
  action: B(x) = allocate_budget(B(parent))                // A2 + A3


// ─── PROTOCOL LAYER (IMPLEMENTATION STATUS) ─────────────────

V("credential-manager") = {
  S1: [github_public, github_dark, parrot],       // SSH keypairs per service
  S2: { coordination: access_log, anti_loop: strict_monotonicity },
  S3: { entry_gate: governed(requester), source: handshake.py },
  S3*: { audit: health_check.py + trust.py, mode: emergency },
  S4: { scanner: scanner.py, scans: "~/vsf/projects/*/viability.yaml" },
  S5: { policy: credential_policy, ceiling: ≤ S5(parent).ceiling }
}

// Implemented (src/):
//   provision.py   — key generation + ~/.ssh/config entry (S1 operations)
//   health_check.py — SSH reachability + key age + algedonic escalation (S3*)
//   trust.py       — trust_score v0.3: decay(λ) + S2 error_rate + @status override (S3*)
//   scanner.py     — ecosystem scan + governed() predicate + proposals (S4)
//   handshake.py   — 4-phase ψ negotiation: identity→trust→negotiate→establish (S3)

// Pending (#10 — handshake upgrade):
//   state machine: { init, validate, negotiate, establish, active, revoked }
//   replay protection: nonce + timestamp window
//   per-identity rate limit (separate from D13 global ψ_rate_limit)

// Pending (#11 — credential lifecycle):
//   provision.py: revoke() — removes key + config entry + marks unit inactive
//   provision.py: rotate() — revoke + provision new key + update ψ channels
//   health_check.py: compromise_detect() — isolation signal to S3 on anomaly


// ─── AUTOPOIESIS ────────────────────────────────────────────

semantic("layered-autopoiesis"):
  S5(L=0) = human_governed
  S5(L>0) = generated_by(S3(L-1))
  ceiling(S5(L+1)) ≤ ceiling(S5(L))            // A5 Corollary 1
  policy(S5(L+1)) ⊆ policy(S5(L))              // A5 Corollary 2 — DNA integrity
  // Sub-S5 may be autonomous within its normative closure.
  // It cannot modify its own closure (Beer: autopoiesis ≠ autarchy).


// ─── L-RELATIVITY ───────────────────────────────────────────

semantic("level-relativity"):
  L     = frame-local view parameter — changes on reframe()
  V.id  = stable identifier — never changes
  A2 uses parent-child relation, not L-index
  channels reference V.id, not L
  // "tool-conductor at L=0" and "tool-conductor at L=1 under org-layer" = same system


// ─── RESOLVED QUESTIONS ─────────────────────────────────────

resolved("Q-vsf-6"):
  question: "should degraded @status reduce trust_score in active ψ channels?"
  answer: YES — @status ∈ {deprecated, compromised, unhealthy} → trust_score = 0
  mechanism: D11b @status override rule (see above)
  consequence: ψ channel transitions to state=revoked ∘ log(S2.access_log)
  CalibScore(D9) feeds S3*.audit(V,t) as stability proxy — linkage now explicit.


// ─── OPEN QUESTIONS ─────────────────────────────────────────

question("Q-vsf-4"):
  inter-VSM ψ protocol for different-owner systems?
  // requires: schema federation standard + bilateral S5 consent mechanism
  // out of scope v0.3 — future work (v2.0)

question("Q-vsf-5"):
  reframe() trigger — automatic detection vs. human-initiated?
  // D12 defines meta_shift as indicator; D4 says structural changes require human
  // tension: at what severity(meta_shift) should the system alert S5 vs. wait?

question("Q-vsf-7"):  // NEW
  handshake replay protection — is timestamp window sufficient?
  // nonce + timestamp(±δ) prevents replay attacks.
  // But: what is the correct δ for async VSF systems?
  // And: where is the nonce registry persisted? (telemetry? in-memory? external?)

question("Q-vsf-8"):  // NEW
  credential rotation and ψ continuity — how to rotate without breaking active channels?
  // rotate() = revoke + provision new key.
  // During rotation, the ψ channel is temporarily ungoverned.
  // Options: (a) pause ψ during rotation, (b) dual-key transition window,
  //           (c) revoke ψ → re-establish after rotation.
  // Which is correct per A5 + D11b?

question("Q-vsf-9"):  // NEW
  decay factor λ — how should it be calibrated across different VSM levels?
  // λ at L0 (infrastructure) may differ from λ at L2 (cognitive layer).
  // A slow-decaying trust at L0 may mask rapid environment shifts detected by L2 S4.
  // Should λ be level-local or global? Who sets it — S5(local) or S5(root)?

question("Q-vsf-10"):  // NEW
  Variety_Overload threshold — who owns max_manageable_units?
  // D13 defines the guard: count(S1.units) > max_manageable_units → Variety_Overload.
  // But max_manageable_units is currently a static config param (S5 policy).
  // Should S3* compute it dynamically based on observed absorption_rate (A8)?
  // Relates: A6 (Ashby) ↔ A8 (absorption) ↔ D13 (safety constraint).


// ─── EVALUATION REQUEST ─────────────────────────────────────

semantic("cross-model-request"):
  // To ChatGPT / Gemini: evaluate the following.

  request_1["axiom-consistency"]:
    // Do A1–A8 form a consistent, non-contradictory set?
    // Are there implicit dependencies between axioms not yet made explicit?
    // Specifically: does A5 Corollary 2 (DNA integrity) follow from A5 or require A2?

  request_2["trust-formula"]:
    // Evaluate the trust_score formula in D11b:
    //   trust_score(t) = 0.6 · decay(t-1, λ) + 0.4 · audit(t)
    //   audit(t) = (0.5·reachability + 0.3·stability + 0.2·drift_resistance) · (1 - 0.3·error_rate_S2)
    // Is the weighting scheme (0.5/0.3/0.2) theoretically justified?
    // Does the multiplicative S2 correction (1 - 0.3·error_rate) have a cybernetic basis?
    // Suggest: alternative formulation or normalization.

  request_3["open-questions"]:
    // Answer Q-vsf-7, Q-vsf-8, Q-vsf-9, Q-vsf-10 above.
    // Provide formal VSL rules where appropriate.

  request_4["handshake-state-machine"]:
    // We plan to upgrade handshake.py with ψ lifecycle states:
    //   { init, validate, negotiate, establish, active, degraded, revoked }
    // Propose: state transition rules + guard conditions per D11b + D13.
    // What events trigger each transition?
    // How does the state machine interact with trust_score decay?

  request_5["missing-concepts"]:
    // Is there any concept from Beer's VSM (1972) or Ashby (1956) not yet captured?
    // Any structural safety risk not covered by D13?
    // Any cybernetic principle violated by the current specification?


// ─── META CONSTRAINT ────────────────────────────────────────

rule(S5["meta"], guard=∅):
  enforce: A1..A8 immutable

rule(S5["meta"], guard=violation):
  system ⊥

```
