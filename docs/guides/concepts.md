@vsm 0.1
// CONCEPTS — VSF Core Concepts
// Audience: human (annotated notation + prose comments)
// @ref docs/spec/vsm_notation_spec.md — full formal spec (axioms, grammar, symbols)
// @ref docs/guides/human_guide.md — plain-language onboarding guide

// ─── THE FIVE SYSTEMS ────────────────────────────────────────────────────────

// S1 — Operations
// Units that produce value. Each is autonomous: own inputs, outputs, health_check.
// S1 units do not coordinate directly — that is S2's role.
∀ i≠j: V_i(L+1) ↛ V_j(L+1)                    // A4 — no direct sibling coupling
// Design smell: S1 units calling each other directly, or units with no verifiable output.
// Examples: data processing script, API microservice, specialized AI agent, engineering team.

// S2 — Coordination
// Prevents oscillation and conflict between S1 units. Has NO authority over S1.
rule(S2, guard=∅): ∀ conflict(S1_i, S1_j): arbitrate ∘ ¬command(S1)
// S2 answers "who goes first?" — never "what to do?"
// Design smell: S2 making business decisions, or S1 units blocking without arbitration.
// Examples: job scheduler with priority, distributed lock system, queue manager.

// S3 — Control
// Manages internal environment: allocates resources, enforces policies, monitors outputs.
// Acts THROUGH S2 — never bypasses it.
rule(S3, guard=∅): ∀ action ∈ S1: control(action) ∘ S2    // cannot bypass S2
// S3 conducts resource bargaining with S1: negotiates, does not impose.
// Accountability loop: S1 produces → S3 measures → S3 negotiates resources with S1.
// Design smell: S3 operating directly on S1, or S3 with no feedback loop from outputs.
// Examples: workflow orchestrator (Airflow, Prefect), resource allocator, task prioritizer.

// S3* — Audit (algedonic channel)
// Sporadic direct access to S1, bypassing S3. Sees what normal control misses.
φ(S3* → S1): bypass(S3)                          // normal sporadic audit
φ(S3* → S5): bypass(S3) ∧ bypass(S4)             // algedonic: crisis escalation
// mode ∈ {emergency, trajectory}
// emergency:  detects absolute anomalous states — no history required
// trajectory: detects baseline deviations — requires N≥10 complete cycles
// Design smell: nobody can observe S1 without going through S3.

// S4 — Intelligence
// Looks outward and toward the future. Does not act — prepares S5 to decide.
rule(S4, guard=∅): ∀ adaptation: propose(S5) ∘ ¬act_directly
// CHECO pattern: simulate scenarios before committing resources.
// CHECO is not viable until N≥5-10 complete cycles with classified data.
// Design smell: no environmental scanning, or S4 acting without S5 approval.
// Examples: external data feed (CVEs, API changes), market alert system.

// S5 — Identity
// Defines what the system IS and what it refuses to be.
// Sets the autonomy ceiling — no S1 unit can exceed it.
∀ op ∈ S1(L): op.autonomy ≤ S5(L).ceiling        // A5
// Balances S3 (internal stability) ↔ S4 (external adaptation).
// Does NOT manage operations — establishes the frame within which everything operates.
// Design smell: system with no explicit policy, or undeclared autonomy ceiling (= unlimited).

// ─── CYBERSYN PATTERNS ───────────────────────────────────────────────────────

// Patterns are solutions to universal coordination problems.
// They are not independent components — implemented WITHIN S2-S5.

// Cybernet   (CHANNEL)      → S2
// How data flows between levels. Bidirectional: φ↑ (upward) + φ↓ (downward).
// Gap: channel exists but nobody consumes it — data flows into a void.

// Cyberfilter (VARIETY)     → S3
// Ashby's Law: Var(E) ≤ Var(S3) ⊕ Var(S2)                  // A6
// Two flows: S1→S3 attenuated (Cyberfilter) | S3→S1 amplified (detailed instructions)
// Gap: systems that only attenuate — S3 loses effective control capacity.

// Cyberstride (ANOMALY)     → S3*
// Detects trajectories, not just states.
// "CPU at 90%" = state. "CPU rising 5%/h for 3h" = trajectory.
// Gap: reactive alerting (system already failed) vs. predictive (trajectory signals failure).

// CHECO       (PROSPECTION) → S4
// Simulate scenarios before committing resources.
// Training mode: deliver briefing while accumulating data for the model.
// Gap: activating CHECO before sufficient data — output is noise, not signal.

// Opsroom     (DECISION)    → S5
// Not a metrics dashboard — a decision space. Shows state, alerts, recommended action.
// Five views defined in D7 @ docs/spec/vsm_notation_spec.md:
opsroom(V(id, L)) = {
  view["system_health"]   ≡ S3(L).audit,         // do we have resources?
  view["pipeline_status"] ≡ S1(L).operations,    // are units working?
  view["signal_queue"]    ≡ S2(L).unresolved,    // what couldn't resolve locally?
  view["priority_ranking"]≡ S4(L).environment,   // what matters most now?
  view["coverage_gaps"]   ≡ S3(L) → S4(L)        // model vs. reality delta
}
// Gap: 200-metric dashboards where the operator must infer what to do.

// ─── RECURSION ───────────────────────────────────────────────────────────────

// Any S1 unit can itself be a complete viable system.
S1(L)[i] = V("name", L+1)   iff  S1[i].recursive=true ∧ S1[i].vsf_ref=path  // A1

// In viability.yaml:
//   s1_units:
//     - id: subsystem_a
//       recursive: true
//       vsf_ref: "subsystems/a/viability.yaml"

// ─── AUTONOMY CEILING ────────────────────────────────────────────────────────

// S5 declares maximum autonomy. No S1 unit can exceed it.
// ceiling ∈ {manual, supervised, semi-auto, auto}
// manual:     human approval for every action
// supervised: auto with operator notification
// semi-auto:  auto for reversible, manual for irreversible
// auto:       no human intervention

// ─── LEARNING LOOPS ──────────────────────────────────────────────────────────

// single-loop: corrects behavior WITHIN existing rules → automatable
// double-loop: modifies the rules themselves → requires_human (A5, always)
rule(S5, guard=∅): double_loop ∘ human_approval    // violation = rogue process

// ─── LIFECYCLE GATES ─────────────────────────────────────────────────────────

// Gates are verifiable — validator.py --gate={stage} returns bool.
gate(onboarding → iterating) = S1.defined ∧ S2.coordinator ∧ S5.policy
gate(iterating  → testing)   = S3.connected_to_S2 ∧ S3*.mode=emergency
gate(testing    → production) = S3*.mode=trajectory ∧ CHECO.viable ∧ double_loop.supervised

// ─── ADVANCED: BEER ALIGNMENT ────────────────────────────────────────────────

// Metasystem vs. operational system:
// metasystem       = {S3, S3*, S4, S5}   // supervises, adapts, defines identity
// operational_sys  = {S1, S2}            // produces value, coordinates execution
// Metasystem can act on operational system without consulting it. S1 has no veto.

// Two environments (Beer distinguishes explicitly):
// E_operational(S1): immediate — inputs, clients, resources of each unit
// E_external(S4):    future — macro changes, systemic threats, opportunities
// Design smell: S4 managing the immediate environment of S1 (that is S3's role).

// S3 ↔ S4 tension — central adaptation mechanism:
// S3: "optimize what we have — it works"
// S4: "the environment is changing — we need to adapt"
// S5: arbiter — decides when stability yields to adaptation
// S5 field: s3_s4_balance_policy

// Variety: bidirectional (not just attenuation):
// S1→S3: ATTENUATED (Cyberfilter) — S1 produces high variety, S3 cannot process all
// S3→S1: AMPLIFIED  (instructions) — S3 sends granular instructions to each S1 unit
// Var(E(L)) ≤ Var(S3(L)) ⊕ Var(S2(L))                      // A6

// Algedonic channel (S3* → S5 bypass):
// Normal:     S1 → S3* → S3 → S5
// Algedonic:  S1 → S3* --------→ S5   (total bypass when S3 may be the problem)
// Spec: s3_star.algedonic.bypass_s3=true + escalation_target=s5
