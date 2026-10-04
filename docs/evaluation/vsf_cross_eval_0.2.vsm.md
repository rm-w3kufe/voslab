# `vsf_cross_eval_0.2.vsm`

```
@vsm 0.2

// ============================================================
// VSF — CROSS-MODEL EVALUATION DOCUMENT
// Version: 0.2 (integrated)
// Purpose: cross-model validation — identify gaps, conflicts,
//          unconsidered aspects. Update model understanding.
// ============================================================

// ─── STRATIFICATION ─────────────────────────────────────────
// Three layers — distinct responsibilities:

layer("language"):
  name      = VSL
  resolves  = "mutual understanding — what does this message mean?"
  scope     = axioms, grammar, symbols, rules
  openness  = HIGH    // any system that parses VSL can participate
  risk      = promiscuity  // openness without protocol = any system connects

layer("framework"):
  name      = VSF
  resolves  = "structural organization — how is the system organized?"
  scope     = S1-S5, φ↑↓, recursion, regulation, intelligence, policy
  foundation = Beer(1972) + Ashby(1956)

layer("protocol"):
  name      = VSF-Protocol
  resolves  = "security + compartmentalization — who connects, with what, under what conditions?"
  implemented_as = V("credential-manager")
  status    = required_for_ψ    // not optional in open networks


// ─── AXIOMS A1–A8 ───────────────────────────────────────────

// A1 — Recursion
S1(L) = { V_i(L+1) }_{i=1}^{n}
// Every S1 unit is itself a complete viable system at L+1.
// Recursion depth is discovered at runtime, not fixed at design time.

// A2 — Budget monotonicity (parent-child, not index-dependent)
B(child) ≤ B(parent)    ∀ (parent, child) ∈ V.hierarchy
// L is frame-local — invariant holds regardless of how levels are numbered.

// A3 — Physical resource
B(L) = min( B_tokens(L), B_compute(L), B_time(L) )
// Budget is the most constrained physical dimension.

// A4 — No direct sibling coupling
∀ V_i(L+1), V_j(L+1) where i ≠ j:
  V_i ↛ V_j
  V_i → φ↑ → S3(L) → φ↓ → V_j    // all via parent S3
// ψ (D11) is NOT a sibling channel — it connects different VSM trees.

// A5 — Autonomy ceiling (with corollary)
∀ op ∈ S1(L): op.autonomy ≤ S5(L).ceiling
∀ L > 0:      S5(L).ceiling ≤ S5(L-1).ceiling    // ceiling propagates downward
// S5(L=0) = human-governed root. Sub-S5s may restrict, never exceed parent.

// A6 — Ashby's requisite variety
Var(E(L)) ≤ Var(S3(L)) ⊕ Var(S2(L))
// Persistent violation → meta_shift indicator (D12).

// A7 — Escalation (both conditions required)
s escalates  iff  resolve(s, V(L+1)) = ∅  ∧  urgency(s) > τ_{L+1}
// Resolvable but urgent → stays local.
// Unresolvable + not urgent → deferred (D10), not escalated.

// A8 — Absorption invariant
|S(L)| ≤ |S(L+1)| · (1 − r_L)    r_L ∈ (0,1)
// Signal volume decreases exponentially moving up levels.
// r ≈ 0.9 → root sees ~1% of grandchild signals.


// ─── KEY DEFINITIONS D1–D12 ─────────────────────────────────

// D1 — Viable System (formal tuple)
V(id, L) ::= ⟨ S1, S2, S3, S4, S5, E ⟩ @ level=L
// id = stable identifier (never changes)
// L  = frame-local position (changes on reframe)

// D2 — Upward channel
φ↑ : V_i.id → S3(parent_of(V_i)).id
φ↑.payload = telemetry/{system_id}/events.jsonl

// D3 — Downward channel
φ↓ : S3(parent_of(V_i)).id → V_i.id
φ↓.payload = telemetry/{system_id}/params.json

// D4 — Learning loop taxonomy
single-loop = corrections within pre-authorized rules   → automatable
double-loop = modifying the pre-authorization rules     → requires_human
// Pre-authorization: S5 defines a class of structural change once (human confirm).
// Execution within that class is autonomous (single-loop).
// Changing the authorization criteria = double-loop — always human.

// D5 — Recursion condition
is_viable(u) = True   iff complexity(u) > τ_viability    // recurse
is_viable(u) = False                                      // execute_atomic

// D6 — LLM constraint
S4(L).uses_LLM = True   only if L ≤ L_max    // default L_max = 2
// L0/L1 = pure deterministic — no LLM. Reason: LLMs have high variety → A6 risk.

// D7 — Opsroom (five views, domain-agnostic)
opsroom(V) = {
  view["system_health"]    ≡ S3.audit,
  view["pipeline_status"]  ≡ S1.operations,
  view["signal_queue"]     ≡ S2.unresolved,
  view["priority_ranking"] ≡ S4.environment,
  view["coverage_gaps"]    ≡ S3 → S4
}

// D8 — Signal priority and status
urgency(s) ∈ { CRITICAL, HIGH, MEDIUM, LOW }
s.status   ∈ { pending, resolved, undecidable, deferred }
urgency(s)  = f( impact_budget(s), impact_stability(s), model_drift(s) )
// urgency is derived from signal properties — A7 threshold τ_L operates on this.

// D9 — Calibration score
CalibScore(V, t) = (T_expected / T_actual) · (B_used / B_allocated)
CalibScore ≈ 1.0 → behaves as modeled
CalibScore < 0.7 → bottleneck
CalibScore > 1.3 → model pessimistic

// D10 — Incompleteness state
resolve(s, V) = ∅  ⟹  s.status = undecidable
rule(S3(L), guard=s.status=undecidable):
  if urgency(s) > τ_L: s ⟹ φ↑(s)        // A7
  else: s.status = deferred               // accumulate
// Deferred ≠ failure. Pool of deferred signals = level diagnostic (→ D12).

// D11 — Structural coupling ψ (inter-VSM, horizontal)
ψ(V_A, V_B) : S4_A ↔ S4_B
constraints:
  ¬sibling(V_A, V_B)                           // A4: no sibling bypass
  governed(V_A) ∧ governed(V_B)                // D11b: entry gate
  trust_level(V_A, V_B) ≥ limited              // D11b: trust
  S5(V_A).approve ∧ S5(V_B).approve            // A5: bilateral consent
mediated_by: expansion_module ∘ handshake ∘ S3.filter
// ψ connects S4s — inter-VSM coupling is an exchange of environment models.
// ψ between siblings is forbidden — use φ↑ → S3 → φ↓ instead.

// D11b — Participation predicate + trust
governed(x)           = has(params(x)) ∧ emits(events(x))
trust_score(V_A, V_B) = (1 - drift(S4(V_B))) ⊕ stability(S3(V_A))
trust_level           ∈ { none → forbid_ψ, limited → ψ_restricted, trusted → ψ_full }
rule(S4, guard=trust_score < τ_trust): restrict(ψ) ∘ notify(S5)
// governed(x) = minimum participation requirement. Ungoverned systems cannot connect.
// trust_score is dynamic — computed from observable system metrics.
// trust is maintained by S3* (sporadic audit channel).

// D12 — Meta-shift indicator
meta_shift(V(L)) = True  iff:
  (∃ class(S): ∀ s ∈ class(S): resolve(s, V(L)) = ∅)
  ∧ |class(S)| / |S_total| > μ
  ∧ CalibScore(V(L), t) < 0.7  for t > δ
// Meta_shift ≠ single escalation. It is a persistent structural failure.
// Candidate trigger for reframe() — always requires human approval (D4).


// ─── EXECUTION SEMANTICS ────────────────────────────────────

tick(L):
  1. read φ↓(params)             // D3: parent config first
  2. apply S2(coordination)       // A4: prevent sibling conflicts
  3. apply S3(regulation)         // D4: budget allocation + D8: signal triage
  4. for each s with resolve(s)=∅:
       if urgency(s) > τ_L: s ⟹ φ↑(s)    // A7
       else: s.status = deferred            // D10
  5. execute S1(operations)       // A1: each unit may tick(L+1)
  6. update S4(env_model)         // A6: after execution, not before
  7. emit φ↑(events)              // D2: report to parent
// S4 updates AFTER S1 — reflects what happened, not what was predicted.
// φ↓ is read BEFORE regulation — parent params inform the current cycle.


// ─── STRUCTURAL OPERATIONS ──────────────────────────────────

// reframe() — frame shift when super-structure is discovered
reframe(V_id, new_parent_id):
  precondition: governed(new_parent_id)
  precondition: credential-manager.validate(new_parent_id, scope=limited)
  action: V(V_id).parent = new_parent_id
  action: establish(φ↑(V_id → new_parent_id))
  action: establish(φ↓(new_parent_id → V_id))
  note: "system files are NOT renamed — L is a view parameter only"
// reframe() = double-loop structural change → requires human approval (D4).
// Trigger candidate: meta_shift(V(L0)) = True.

// promote() — boundary expansion E → V
// (pre-authorized class — see D4)
rule(S4(L), guard=detected(x) ∈ E(L) ∧ policy(S5).allows_promotion):
  if controllable(x) ∧ needs_regulation(x):
    promote(x, E → V)
    establish(φ↓, φ↑) ∘ x        // no telemetry → no inclusion
rule(S3(L), guard=is_promoted(x)):
  S1.append(unit(x))
  B(x) = allocate_budget(B(parent))    // A2 + A3


// ─── HYBRID GOVERNANCE ──────────────────────────────────────

S5(L=0).mode = human_governed         // root always human
S4(L).mode   = semi_autonomous
S3(L).mode   = automated              // single-loop regulation
S2(L).mode   = automated
S1(L).mode   = automated

rule(S5(L=0), guard=∅):
  ∀ L > 0 : ∃ S5(L) ∧ is_generated(S5(L))
  enforce(A5.ceiling) ∘ requires_human_confirm(modify_axioms)

rule(S5(L>0), guard=autopoiesis_enabled):
  can_modify(S1..S4) = True
  modify(S5)         = ∅    // sub-S5 cannot modify its own normative closure


// ─── PROTOCOL LAYER ─────────────────────────────────────────

V("credential-manager", L=?) @status=planned = {
  S1: [credential_store, key_manager, token_issuer],
  S2: { anti_loop: strict_monotonicity, coordination: access_log },
  S3: { regulation: auth_validation, entry_gate: governed(requester) },
  S3*: { audit: credential_usage_log },    // detects expired/revoked/missing
  S4: { intelligence: threat_detection,
        trust_score: (1 - drift(S4)) ⊕ stability(S3) },
  S5: { policy: {
          credential_scope: { local, shared, restricted },
          sharing_policy:   based_on(trust_level, identity, context),
          ψ_enabled:        requires_governed_proof,
          ceiling:          ≤ S5(parent).ceiling
        }}
}
// Prerequisite for: ψ channels, reframe(), any inter-VSM connection.

// ψ minimum preconditions (all required):
ψ(V_A, V_B) requires:
  governed(V_A) ∧ governed(V_B)                  // layer_1
  ∧ trust_level(V_A, V_B) ≥ limited              // layer_2
  ∧ credential-manager.validate(V_A, scope)       // layer_3
  ∧ S5(V_A).approve ∧ S5(V_B).approve            // A5
  ∧ ¬sibling(V_A, V_B)                            // A4

// Security by structural composition:
rule(S3, guard=incoming(signal, external)):
  enforce: external ∘ expansion_module ∘ handshake ∘ S3.filter

unit("expansion-module"):
  role = coupling_interface
  S1: [schema_validator, trust_checker, signal_normalizer]
  S5: { policy: "no passthrough without governed(requester)" }


// ─── AUTOPOIESIS ────────────────────────────────────────────

semantic("layered-autopoiesis"):
  S5(L=0) = human_governed                // normative closure at root
  S5(L>0) = generated_by(S3(L-1))
  ceiling(S5(L)) ≤ ceiling(S5(L-1))      // A5 corollary: monotonic


// ─── L-RELATIVITY ───────────────────────────────────────────

semantic("level-relativity"):
  L     = frame-local view parameter
  V.id  = stable system identifier (never changes)
  L=0   = current root of analysis — changes on reframe()
  // Channel schemas reference V.id, not L.
  // "tool-conductor at L=0" and "tool-conductor at L=1 under org-layer"
  // are the same system in different analysis frames.


// ─── CHANGE LOG (0.1 → 0.2) ─────────────────────────────────

semantic("changelog"):
  added   = [D10, D11, D11b, D12, tick(L), reframe(), promote()]
  refined = [A2(parent-child), A5(ceiling-corollary), D4(pre-authorization)]
  new     = [@status lifecycle, question() construct, Part-IX protocol layer]
  symbol  = [ψ added, σ added]


// ─── OPEN QUESTIONS ─────────────────────────────────────────

question("Q-vsf-4"):
  inter-VSM ψ protocol for different-owner systems ?
  // requires: schema federation standard + bilateral S5 consent mechanism
  // out of scope v0.2 — future work

question("Q-vsf-5"):
  reframe() trigger — automatic on meta_shift vs. always human-initiated ?
  // D12 defines indicator; D4 says structural changes require human
  // tension: at what threshold does meta_shift become urgent enough to alert?

question("Q-vsf-6"):
  should degraded @status propagate to trust_score in active ψ channels ?
  // e.g.: V @status=deprecated → trust_score drops → ψ restricted automatically?
  // connects D9(CalibScore) ↔ D11b(trust_score)

// ─── META CONSTRAINT ────────────────────────────────────────

rule(S5["meta"], guard=∅):
  enforce: A1..A8 immutable

rule(S5["meta"], guard=violation):
  system ⊥

```
