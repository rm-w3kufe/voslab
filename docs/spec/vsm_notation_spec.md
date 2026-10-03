# VSM Formal Notation — Language Specification
# Version: 1.0 | Status: STABLE | Authors: VSF Project
# @ref Part XIII §13.5 for full CHANGELOG
# Audience: Humans (annotated) | Machines/LLMs (pure notation)
# Rule: `@vsm <version>` mandatory in every .vsm file — unknown version → halt

---

---

## Part I — Alphabet and Symbols

| Symbol | Meaning |
|--------|---------|
| `V` | Viable System constructor |
| `S1`..`S5` | Beer's five subsystems (Operations/Coordination/Control/Intelligence/Policy) |
| `E` | Environment — observable context at level L |
| `L` | Level — frame-local, not absolute (V.id is stable; L is view parameter) |
| `B` | Budget — total available resource at level L |
| `φ↑` | Upward channel: child → parent (attenuation) |
| `φ↓` | Downward channel: parent → child (amplification) |
| `ψ` | Structural coupling: horizontal S4↔S4, inter-VSM, bilateral S5 required |
| `θ` | Parameter set passed downward |
| `τ` | Local resolution threshold |
| `r` | Resolution rate: fraction of signals resolved locally |
| `∅` | Empty resolution — signal unresolvable at current level |
| `∘` | Composition — "A must go through B" |
| `⟹` | Escalation — signal propagates to parent |
| `≡` | Structural equivalence |
| `⊥` | Infeasible — system cannot maintain viability |
| `@` | Decorator — metadata attached to term |
| `⊕` | Variety combination (Ashby) — measure-parametric: `measure(Var)=\|states\|` ⟹ `⊕`=`·` ; `measure(Var)=additive` ⟹ `⊕`=`+`. VSF declares *additive* (⟹ `+`), per live VAR-1 in operational.rs. Ratified 2026-08-04 (L3/A5). |

    @status ∈ { planned, onboarding, iterating, testing, production, deprecated }

| Extension | Content | Audience | Convention |
|-----------|---------|----------|------------|
| `.vsm`    | Pure VSM notation | Machines + advanced humans | canonical — always tracked |
| `.vsm.md` | VSM with markdown wrapper | GitHub render / wiki | only in `docs/governance/`, `docs/sessions/`, `docs/experiments/spec` |
| `.tex`    | LaTeX source | Paper authoring | canonical — no `.tex.md` wrappers |
| `events.jsonl` | φ↑ payload | Runtime | gitignored |
| `params.json`  | φ↓ payload | Runtime | gitignored |

    // Convention rule: docs/theory/ uses .vsm only (pure VSL, no .md wrapper)
    // .tex.md files are not used — all paper source lives in .tex directly

---

## Part II — Axioms

### L-relativity (M3)

    rule(V.id): immutable ∧ globally_unique    // V.id never renamed — reframe() changes frame, not system

### A1 — Recursion

    S1(L) = { V_i(L+1) }_{i=1}^{n}

### A2 — Budget monotonicity

    B(child) ≤ B(parent)    ∀ (parent, child) ∈ V.hierarchy

### A3 — Physical resource

    B(L) = min( B_tokens(L), B_compute(L), B_time(L) )

### A4 — No direct sibling coupling

    ∀ V_i(L+1), V_j(L+1), i≠j:
      V_i ↛ V_j
      V_i → φ↑ → S3(L) → φ↓ → V_j    // ψ (D11) is NOT a sibling channel — connects different trees

### A5 — Autonomy ceiling

    ∀ op ∈ S1(L): op.autonomy ≤ S5(L).ceiling

    // Corollary 1: ∀ L>0: S5(L).ceiling ≤ S5(L-1).ceiling
    // Corollary 2 (A5⊕A2): S5(L+1).policy ⊆ S5(L).policy   — child policy ⊆ parent
    rule(S5(L), guard=generate(S5(L+1))): enforce: S5(L+1).policy ⊆ S5(L).policy
    // single-loop = automatable | double-loop = ALWAYS requires human

### A6 — Ashby's requisite variety

    Var(E(L)) ≤ Var(S3(L)) ⊕ Var(S2(L))
    // absorption_rate(L) = proxy for v1.0; dynamic extension deferred to v2.0 (Q-vsf-15)

    rule(S3*.emergency, guard=V.status=compromised):
      broadcast_revoke(all_active_psi)    // immediate — bypasses tick latency (A6+algedonic Beer §8)
      emit φ↑(urgency=CRITICAL, kind="security_breach")

### A7 — Escalation

    signal s escalates L+1→L  iff:  resolve(s, V(L+1)) = ∅  ∧  urgency(s) > τ_{L+1}
    // Resolvable+urgent → stays local. Unresolvable+non-urgent → deferred (D10).

### A8 — Absorption invariant

    |S(L)| ≤ |S(L+1)| · (1 − r_L)    r_L ∈ (0,1)
    // r=0.9 → grandparent sees ~1% of grandchild signals

### A9 — Budget exhaustion

    B_exhausted ⟹ (degrade ∨ abort)
    // B_exhausted ⟺ B_tokens=0 ∨ B_compute=0 ∨ B_time=0

    A9b: B_exhausted ⟹ minimal_governance_mode
    minimal_governance_mode: emit(events_min) | skip(S1) | restrict(S4)

    A9c: minimal_governance_mode ⊂ degrade
    degrade: includes(minimal_governance_mode) | reduce(capacity) | preserve(governance)

    A9d: abort ⟺ (critical_failure ∨ policy_violation)
    critical_failure ∈ { system_break, trust_collapse, invariant_violation }
    // ¬critical_failure ∧ ¬policy_violation ⟹ ¬abort (no spurious abort)

### A10 — Escalation target

    ordinary(s):  urgency(s) = LOW      → S3
                  urgency(s) = MEDIUM   → S4    // environment changed: adapt
                  urgency(s) ≥ HIGH     → S5    // may require human (D4)
    algedonic(s): NO urgency ladder — binary, S1 → S5 direct, bypasses all
                  fires ⟺ severity(s) ≥ τ_alg,  τ_alg ∈ S5.policy
    abort_requires_condition = True
    // Ratified 2026-08-04 (L3/A5, rmw3). Previously "urgency ≥ MEDIUM → S5"
    // for everything, which (a) made S5 do operational triage, violating its
    // insulation, and (b) matched neither live path: algedonic.rs carries no
    // urgency levels at all ("BINARY... urgency by routing priority, not
    // payload") while the S5 ledger triages at severity ≥ 8. A10 had merged
    // two different routing questions into one ladder.

### A11 — S4 activation gate

    S4_active ⟺ drift(V,t) > ε
    ε ∈ S5.policy    ε ≥ noise_floor
    // S4 updates AFTER S1 in tick(L) — reflects actual state, not prediction

---

## Part III — Definitions

### D1 — Viable System

    V(id, L) ::= ⟨ S1, S2, S3, S4, S5 ⟩ @ E(L), level=L
    // The FIVE subsystems ARE the viable system — all five always present,
    // missing → declare non-viable. E is the environment V is embedded IN,
    // not a component V has (A6 measures Var(E(L)); S4 maps Env → Model').
    // S3* is the sporadic direct audit CHANNEL, not a subsystem.
    //
    // Ratified 2026-08-04 (topology_Δ ∈ L3, per A5 — rmw3). Until then this
    // read ⟨S1,S2,S3,S4,S5,E⟩ here while the agent primer read
    // ⟨S1,S2,S3,S3*,S4,S5⟩: two incompatible definitions of what a viable
    // system IS, both claiming canonicity, diverging since 2026-04-09.
    // By the old rule ("all six present or non-viable") every system the
    // primer described was non-viable. See TASKS.vsm(DOC-CANON-COMPRESSION-
    // RESTRUCTURE-2026-08-03).

### D2 — Upward channel

    φ↑: V_i.id → S3(parent_of(V_i)).id
    payload = telemetry/{system_id}/events.jsonl
    schema  = connection_schema.json @ "upward"

### D3 — Downward channel

    φ↓: S3(parent_of(V_i)).id → V_i.id
    payload = telemetry/{system_id}/params.json
    schema  = connection_schema.json @ "downward"
    // Child reads at startup. No other configuration source valid.

### D4 — Learning loop taxonomy

    L1 process_autonomous:  kernel adjusts internal state within pre-authorized bounds — no escalation
    L2 class_execution:     executing pre-authorized metamorphosis CLASS — S5 declares once → single_loop
    L3 policy_change:       modifying WHAT the authorized class is → always requires_human → double_loop

    class_execution ⊂ single_loop | class_definition ∈ double_loop
    B_i = B(parent) · w_i / Σ_j w_j    // S3 budget bargain

### D5 — Recursion condition

    is_viable(u) = True   iff  complexity(u) > τ_viability    // τ set by parent S3 in params.json
    is_viable(u) = False  →    execute_atomic(u)

### D6 — LLM constraint

    S4(L).uses_LLM = True  only_if  L ≤ L_max    L_max = 2

### D7 — Opsroom mapping

    opsroom(V(id,L)) = {
      view["system_health"]    ≡ S3(L).audit,
      view["pipeline_status"]  ≡ S1(L).operations,
      view["signal_queue"]     ≡ S2(L).unresolved,
      view["priority_ranking"] ≡ S4(L).environment,
      view["coverage_gaps"]    ≡ S3(L) → S4(L)
    }

### D8 — Signal priority

    urgency(s) ∈ { CRITICAL, HIGH, MEDIUM, LOW }
    urgency(s) = f( impact_budget(s), impact_stability(s), model_drift(s) )
    s.status   ∈ { pending, resolved, undecidable, deferred }
    // Only CRITICAL+HIGH appear in opsroom Signal Queue (A8)

### D9 — Calibration score

    CalibScore(V,t) = (T_expected(V) / T_actual(V,t)) · (B_used / B_allocated)
    CalibScore ≈ 1.0 → nominal | < 0.7 → bottleneck | > 1.3 → model pessimistic

### D10 — Incompleteness state

    resolve(s,V) = ∅  ⟹  s.status = undecidable
    rule(S3(L), guard=s.status=undecidable):
      if urgency(s) > τ_L: s ⟹ φ↑(s)      // A7
      else: s.status = deferred
    // |deferred|/|total| > μ ∧ CalibScore < 0.7 → meta_shift indicator (D12)

### D11 — Structural coupling (ψ)

    ψ(V_A, V_B): S4_A ↔ S4_B    // inter-VSM — A4 still applies within tree
    requires: ¬sibling(V_A,V_B) ∧ governed(V_A) ∧ governed(V_B)
              ∧ trust_level ≥ limited ∧ S5(V_A).approve ∧ S5(V_B).approve
    mediated: expansion_module ∘ handshake ∘ S3.filter

    ψ.state ∈ { init, validate, negotiate, establish, active, degraded, revoked, abort }
    transitions:
      init→validate:   governed(requester)       | init→abort:      ¬governed
      validate→neg:    trust≥limited             | validate→abort:  trust<limited
      neg→establish:   human_approved ∧ rate_ok ∧ ¬circular_trust
      establish→active: channel_committed(psi_channels.jsonl)
      active→degraded: trust ∈ [τ_min,0.5)      | active→revoked:  trust<τ_min
      degraded→active: trust≥0.5                | degraded→revoked: trust<τ_min
      any→abort:       timeout ∨ replay_detected

    // Replay protection: nonce_registry {store: nonces.jsonl, TTL: δ∈[30s,120s]}
    // Handshake: (1) identity+governed_proof (2) S3* trust eval (3) scope negotiation (4) human_approve+commit
    // ψ connects S4s — inter-VSM coupling = exchange of environment models

### D11b — Trust formula

    governed(x) = has(params(x)) ∧ emits(events(x))
    trust_level  ∈ { none→forbid_ψ, limited→ψ_restricted, trusted→ψ_full }

    T(V,t) = 0.6·decay(T(V,t-1),λ) + 0.4·audit(V,t)
    audit(V,t) = (0.5·reachability + 0.3·stability(S3) + 0.2·(1-drift)) · (1-error_rate(S2))
    // λ ∈ S5.policy. VSL does NOT fix λ's indexing — a system may hold one
    // shared λ or one per level; it MUST declare which. (Same conformance
    // pattern as measure(Var) for ⊕, and Ω for viability.)
    //
    // VSF instantiates: ONE shared entropy-adaptive λ, NOT per-level —
    //   λ = LAMBDA_CALIBRATED · (1 + |ΔH|/H_max), clamped to [0.05, 0.20]
    //   LAMBDA_CALIBRATED = 0.10, measured 0.10002 ± 1.8e-5, rock-stable
    //   (EXP-TRUST-01 run_4 / phase B, 2026-06-19: per-axis λ_i tested and
    //   NOT warranted — H_TRUST2 refuted). Live: projects/vsf-nucleus/src/
    //   trust_axes.rs (LAMBDA_MIN/LAMBDA_MAX/LAMBDA_CALIBRATED).
    //
    // HISTORICAL (removed 2026-08-04): this section carried per-level
    //   defaults λ(L0)=0.02 λ(L1)=0.05 λ(L2)=0.15 plus an ordering
    //   constraint. They predate EXP-TRUST-01 and were never reconciled with
    //   it: no per-level λ exists anywhere in the codebase, and λ(L0)=0.02
    //   sits BELOW the deployed clamp floor (0.05), so it was unreachable by
    //   construction. The internal contradiction between that ordering and
    //   those defaults was a symptom of the whole block being stale, not a
    //   sign error. See TASKS.vsm(AXIOM-CANON-CONSISTENCY-2026-08-03).
    // S3* owns trust computation (not S4 — conflict of interest); missing history → conservative_default

    // Q-vsf-13 (2026-08-03 rmw3+Claude; SCOPE-CORRECTED 2026-08-04):
    // CONDITIONAL — binds only a system that declares PER-LEVEL λ. VSF
    // declares a single shared λ, so this rule is currently VACUOUS here.
    // Kept (not deleted) because the principle stands for any system that
    // does index λ by level: a child never gets a laxer standard than its
    // parent holds itself to, and loosening it is never silent.
    rule(S5(L), guard=configure(S5(L+1), λ) ∧ per_level(λ)):
      λ(L+1) ≥ λ(L)  →  single_loop                              // within bound, automatic
      λ(L+1) <  λ(L)  →  policy_drift ∘ require(S5(L).approve)    // loosening = double-loop

    rotate(V.credential):  // governed(V)=True throughout
      provision(new) → ψ.add_channel(new) → wait_telemetry(new) → revoke(old)

    rule(S3*(L), guard=V_peer.status ∈ {deprecated,compromised,unhealthy}):
      trust_score(V_peer) = 0 ∘ terminate(ψ) ∘ log(S2.access_log)    // single-loop; reinstate = double-loop

    rule(S4["ψ"], guard=incoming(ψ,V_B)):
      import: V_B.env_model → sandbox(S4)    // never direct write
      trust_level(V_B) ≥ trusted → integrate: sandbox → env_model

### D12 — Meta-shift

    meta_shift(V(L)) = True  iff:
      (∃ class(S): ∀ s∈class(S): resolve(s,V(L))=∅)
      ∧ |class(S)|/|S_total| > μ  ∧  CalibScore(V(L),t) < 0.7  for t>δ

    rule(S4["meta"], guard=meta_shift):
      low:    μ<0.2 ∧ CalibScore>0.6  → log
      medium: μ<0.5 ∧ CalibScore>0.5  → opsroom_signal_queue
      high:   μ≥0.5 ∨ CalibScore≤0.5  → φ↑(urgency=CRITICAL)

    rule(S5["meta"]): enforce no_auto_reframe    // reframe() always double-loop (D4)

### D13 — Structural safety constraints

    rule(S5): enforce: max_recursion_depth | promotion_budget_limit | ψ_rate_limit
                       no_circular_trust | no_unbounded_growth

    absorption_rate(L) = |S_resolved(L)| / |S_total(L)|    // S3* per tick
    rule(S4(L), guard=promote(x, E→V)):
      count(S1.units) > max_manageable_units(L) → resolve(promotion)=∅ ∘ φ↑(HIGH,"Variety_Overload")

    resistance(V) = system_size(V) ⊕ coupling_degree(V)
    rule(S3["inertia"], guard=single_loop_structural_op):
      require: Δstructure > threshold_inertia(V)    // S5 tunes threshold

    rule(S3*["audit"]): log: ψ_events | reframe_attempts | promotion_events | rejections

---

## Part IV — Grammar (BNF)

    system      ::= "@vsm" version NL mode_comment? domain_context? declaration+
    declaration ::= system_def | rule_def | channel_def | memory_def
                  | semantic_def | question_def | reframe_def

    mode_comment   ::= "//" "PSI/1.0" "—" ("machine-to-machine" | "impl")
    domain_context ::= "domain_context:" "{" dc_field ("," dc_field)* "}"
    dc_field       ::= "target=" id | "env=" env_id | "layer=" s_layer
    env_id         ::= id ("/" id)*    s_layer ::= "S1"|"S2"|"S3"|"S4"|"S5"

    system_def  ::= "V(" id "," "L=" int ")" ["@status=" status] "=" "{" subsystems "}"
    subsystems  ::= subsystem ("," subsystem)*
    subsystem   ::= "S1:" unit_list | "S2:" coord_spec | "S3:" regulate_spec
                  | "S4:" intel_spec | "S5:" policy_spec | "E:" env_spec
    unit_list   ::= "[" (id | system_def | "unit(" id ")") ("," ...)* "]"

    rule_def    ::= "rule(" subsystem_ref "," "guard=" guard "):" NL body+
    guard       ::= condition | "∅"
    body        ::= "  " "∀" quantified | "  " "∃" quantified | "  " action

    channel_def ::= "φ" direction "(" source "→" target "):" NL
                    "  payload=" file_ref NL "  schema=" schema_ref
    direction   ::= "↑" | "↓"
    coupling_def ::= "ψ(" id "," id "):" NL ("  " constraint NL)+

    memory_def  ::= memory_type "(" id "):" NL field+
    memory_type ::= "episodic" | "semantic" | "procedural" | "policy"
    reframe_def ::= "reframe(" id "," "new_parent=" id "):" NL ("  " action NL)+

    status  ::= "planned"|"onboarding"|"iterating"|"testing"|"production"|"deprecated"
    version ::= int "." int

---

## Part IV.b — Execution Semantics

### tick(L)

    tick(L):
      1. read φ↓(params)              // D3
      2. apply S2(coordination)        // A4
      3. apply S3(regulation)          // D4: budget, D8: triage
      4. ∀ s: resolve(s)=∅ → urgency>τ_L ? s⟹φ↑(s) : s.status=deferred    // A7, D10
      5. execute S1(operations)        // A1: each unit may tick(L+1)
      6. update S4(env_model)          // A11: only if drift>ε; reflects actual state
      7. emit φ↑(events)               // D2

### reframe(V_id, new_parent_id) — double-loop, human gate required (D4)

    propose:  S4 detects meta_shift ∨ external_governance → φ↑(HIGH)
    validate: governed(new_parent) ∧ credential_ok ∧ B(new_parent)≥B(V) ∧ A5_corollary_ok
    simulate: Δsignals + Δbudget + Δceiling → impact_report → S5(human)
    commit:   human_approved → V.parent=new_parent | establish φ↑↓ | files NOT renamed

---

## Part V — Translation rules

### 5.1 Prose → VSM

| Prose | VSM |
|-------|-----|
| "always X before Y" | `rule(S3, guard=∅): X ∘ Y` |
| "never X directly, use Y" | `∀ op: op.X ∘ Y` |
| "if condition, escalate" | `condition ⟹ φ↑(signal, urgency=HIGH)` |
| "confirm before destructive" | `op ∈ S5.ceiling.requires_confirm` |
| "priority A,B,C" | `S5.priorities = [A,B,C]` |
| "X can't talk to Y directly" | `X ↛ Y  // A4` |
| "can't resolve, escalate" | `resolve(s,V)=∅ ∧ urgency>τ ⟹ φ↑(s)` |
| "add governance above X" | `reframe(X, new_parent=org)` |
| "X and Y share env model" | `ψ(X,Y): S4_X ↔ S4_Y  // D11` |

### 5.2 VSM → Human

    @vsm 1.0         → "VSM spec version 1.0"
    V("X", L=0)      → "X is current root (frame-local)"
    φ↑(V_i → S3)    → "child i reports upward to parent coordination"
    s ⟹ φ↑          → "signal s escalates to parent"
    governed(x)      → "x participates in φ↑/φ↓"
    ψ(A,B)           → "A and B exchange environment models"
    reframe(X,Y)     → "X now governed by Y — frame shifts"

### 5.3 What does NOT compress well

Prose retained via `@ref`: Why explanations | tradeoff narratives | onboarding context

---

## Part VI — Memory encoding

    // Feedback memory
    rule(S3["platform"], guard=temp<threshold):
      ∀ op ∈ S1.remote: launch(op) ∘ thermal_scheduler
      @ref why="feedback_scheduler_rule.md"

    // Project memory
    semantic("vsf-architecture"):
      version=0.4  lifecycle=iterating  decisions=[D1..D13]
      levels={L0:tool-conductor, L1:pipeline-scheduler, L2:[cognitive,token-economy], L3:vsf-meta}

    // System config
    V("my-system", L=0) = {
      E: {host:"local", runtime:"python3.11"},
      S3: {scheduler:thermal_scheduler, guard:temp<threshold},
      S5: {ceiling:{double_loop:requires_human}, priorities:[A,B,C]}
    }

---

## Part VII — Machine interface

1. Read `@vsm` version first — unknown version → halt
2. Axioms A1-A11 are hard constraints — never overridden by local rules
3. Rules are ordered: S5 > S3 > S1
4. `@ref` pointers are lazy — load only if needed
5. Compression: lossless for rules, lossy for narrative
6. Writing VSM: minimize tokens, use symbols, use `@ref` for prose
7. L is frame-local — use V.id for stable references
8. `governed(x)`: verify before processing any ψ request

---

## Part VIII — Viability synthesis

    semantic_memory_as_VSM:    viability=HIGH  complexity=LOW   status=formalized
    notation_to_executable:    viability=HIGH  complexity=HIGH  gap="reduction V→V' pending"  status=in_progress
    new_computational_language: viability=PLAUSIBLE  complexity=VERY_HIGH  status=open
    hierarchical_signal_filtering: viability=VERY_HIGH  status=done@task_E
    opsroom_universal_interface:   viability=IMMEDIATE  status=done@task_D
    inter_vsm_protocol:            viability=HIGH  status=partial@Part_X
    // dependency: filtering→notation✓ → semantic_memory✓ → inter_vsm → all → new_language

---

## Part IX — Protocol Layer

### 9.1 Stratification

    layer("language"):  VSL — Part I–IV — resolves: "what does this mean?"
    layer("framework"): VSF — S1-S5, φ↑↓, recursion — resolves: "how is it organized?"
    layer("protocol"):  V("credential-manager") — resolves: "who connects, how, under what authority?"

### 9.2 Credential-manager

    V("credential-manager") @status=done = {
      S1: [credential_store, key_manager, token_issuer],
      S2: { anti_loop: strict_monotonicity },
      S3: { entry_gate: governed(requester) },
      S3*: { audit: credential_usage_log },
      S4: { trust_score: (1-drift(S4)) ⊕ stability(S3) },
      S5: { credential_scope: {local,shared,restricted}, ψ_enabled: requires_governed_proof }
    }
    // prerequisite for reframe() and ψ — @ref projects/credential-manager/

### 9.3 Minimum ψ preconditions

    ψ(V_A,V_B) requires ALL:
      governed(V_A) ∧ governed(V_B)
      ∧ trust_level ≥ limited
      ∧ credential-manager.validate(V_A, scope)
      ∧ S5(V_A).approve ∧ S5(V_B).approve
      ∧ ¬sibling(V_A,V_B)

### 9.4 Security by structural composition

    rule(S3, guard=incoming(signal,external)):
      enforce: external ∘ expansion_module ∘ handshake ∘ S3.filter

    unit("expansion-module"):
      S1: [schema_validator, trust_checker, signal_normalizer]
      S5: { policy: "no passthrough without governed(requester)" }

---

## Part X — Machine-to-Machine Mode (v0.4)

### 10.1 Variants

    B_full   — standalone; recipient has no schema; compression: 38–51%
    B_schema — machine-to-machine; recipient has VSF schema; compression: 72–79%
               header: // PSI/1.0 — machine-to-machine
               overhead: domain_context block only (~8 tokens)

### 10.2 domain_context (required in B_schema)

    domain_context: {target=vsf-nucleus, env=Rust/LXC, layer=S1}
    // Without it: context substitution — structurally correct, semantically wrong
    // target=id prevents identity drift | env=runtime | layer=S-layer of recipient

### 10.3 Drift metrics

    structural_drift ::= fraction of parse-tree elements incorrectly decoded    // target <5%, achieved ~0%
    semantic_drift   ::= fraction of domain referents substituted with recipient's context
                         // without domain_context: ~60% | with: ~5%
    // Measure independently — structurally correct parse with high semantic drift = silent failure

### 10.4 Compression measurement

    tool: tiktoken cl100k_base
    compression = 1 − (tokens_B / tokens_A)
    // Report B_full and B_schema separately — aggregating produces misleading mean

---

## Part XI — VSL File Grammar (v1.0)
// Part IV = V() system definitions. Part XI = .vsm file format (experiments, governance, M2M).

### 11.1 File structure

    vsm_file   ::= header NL+ version_decl NL+ comment* body footer
    header     ::= "⟦" WS id WS "|" WS exp_id WS "|" WS "vsm-" version WS "|" WS date WS "⟧"
    footer     ::= "⟦" WS "/" id WS "|" WS exp_id WS "|" WS "vsm-" version WS "⟧"
    version_decl ::= "@vsm" WS version
    date       ::= year "-" month "-" day   // ISO 8601

### 11.2 Body elements

    body       ::= (statement NL)*
    statement  ::= comment | kv_pair | block | array_block | hypothesis | fn_block

    comment    ::= "//" text_to_eol

    kv_pair    ::= key ":" WS value
    key        ::= [a-zA-Z_][a-zA-Z0-9_.]*
    value      ::= scalar | inline_block | ref

    scalar     ::= string | number | bool | null | identifier
    string     ::= '"' [^"]* '"'
    number     ::= "-"? [0-9]+ ("." [0-9]+)?
    bool       ::= "true" | "false"
    null       ::= "null"
    identifier ::= [a-zA-Z_][a-zA-Z0-9_./\-]*

    inline_block ::= "{" WS kv_pair (WS "," WS kv_pair)* WS "}"

    block      ::= key ":" WS "{" NL (WS+ statement NL)* "}"
    array_block ::= key ":" WS "[" NL (WS+ array_item NL)* "]"
    array_item ::= scalar | inline_block | hypothesis_item

    hypothesis_item ::= label ":" WS string ","?
    label      ::= [A-Z][0-9]+                     // H1, H2, C1, C2 …

    fn_block   ::= "fn" WS id "(" params? ")" WS "{" NL fn_body "}"
    fn_body    ::= (WS+ text_to_eol NL)*
    params     ::= param ("," WS param)*
    param      ::= id (":" WS type_name)?

### 11.3 References

    ref        ::= "@ref" WS ref_target
    ref_target ::= file_path ("#" anchor)?
    file_path  ::= (id "/")* id "." ext
    anchor     ::= id

    // @ref resolves relative to the repo root (~/vsf/)
    // Forward references are allowed; circular references are invalid (C5)

### 11.4 Type annotations (optional, for v1.0 validation)

    typed_kv   ::= key ":" type_name "=" value
    type_name  ::= "string" | "number" | "bool" | "ref" | "block" | "array"
                 | "vsm_id" | "date" | "duration" | "temp_c" | "percent"

---

## Part XII — Type System

### 12.1 Primitive types

| type      | syntax example            | description                      |
|-----------|---------------------------|----------------------------------|
| string    | `"text"`                  | UTF-8 quoted string              |
| number    | `3.14`, `-1`, `50000`     | integer or float                 |
| bool      | `true`, `false`           | boolean                          |
| null      | `null`                    | explicit absence                 |
| identifier| `thermal_cycling`         | unquoted name token              |

### 12.2 Composite types

| type      | syntax example                          | description              |
|-----------|-----------------------------------------|--------------------------|
| block     | `key: { a: 1, b: "x" }`               | key-value map            |
| array     | `key: [ H1: "...", H2: "..." ]`        | ordered sequence         |
| ref       | `@ref docs/spec/vsm_notation_spec.md`  | cross-document pointer   |

### 12.3 Domain types (semantic aliases)

| type      | underlying | validation rule                              |
|-----------|------------|----------------------------------------------|
| vsm_id    | identifier | must be unique within file                   |
| date      | string     | ISO 8601: YYYY-MM-DD                         |
| duration  | string     | `"240min"`, `"4h"`, `"30s"`                  |
| temp_c    | number     | range [−40, 120] °C                          |
| percent   | number     | range [0.0, 1.0]                             |
| s_layer   | identifier | ∈ {S1, S2, S3, S3_star, S4, S5}             |

### 12.4 Inference rules

- Unquoted token that is a valid number → inferred as `number`
- Unquoted token matching `true|false` → inferred as `bool`
- Anything else unquoted → inferred as `identifier`
- Quoted content → always `string`
- Block opener `{` → `block`; array opener `[` → `array`

---

## Part XIII — Validation Rules + Stability Policy

### 13.1 Syntactic validity (C1)

A `.vsm` file is syntactically valid iff:
- It begins with a `⟦ header ⟧` matching the grammar in §11.1
- It contains `@vsm <version>` on the second non-blank line
- All `{` are matched by `}`; all `[` are matched by `]`
- All strings are properly quoted (no unmatched `"`)
- Footer `⟦ /name ⟧` matches header name

### 13.2 Semantic validity (C5)

A `.vsm` file is semantically valid iff:
- All `@ref` targets resolve to existing files/anchors in the repo
- No circular `@ref` chains exist
- All `hypothesis_item` labels within an array are unique
- `date` fields parse as valid ISO 8601
- `temp_c` fields are in [−40, 120]
- `percent` fields are in [0.0, 1.0]

### 13.3 Invalidity conditions

A file is **invalid** (parser should emit ERROR) if:
- Header/footer mismatch (different `name` or `exp_id`)
- Unclosed block or array
- `@vsm` version missing or malformed
- `@ref` to non-existent file (when `--strict-refs` flag is set)
- Duplicate hypothesis labels in same array

A file produces a WARNING (not ERROR) if:
- `@ref` anchor not found (file exists, anchor missing)
- Domain type value out of range
- Unknown key in a known block context

### 13.4 Stability policy (C6)

VSL version semantics follow semantic versioning:

    MAJOR.MINOR  (no patch — spec changes are always significant)

    MAJOR bump: any change that invalidates previously valid files
                (remove keyword, change grammar rule, rename block)
    MINOR bump: backward-compatible additions
                (new optional key, new domain type, new Part)

    v0.x → v1.0: current transition — v1.0 is the first stable release
    v1.0+:        MAJOR bump required for any breaking change

Files declare their version with `@vsm MAJOR.MINOR`.
A parser targeting v1.0 MUST accept all v0.4 files without error
(v0.4 → v1.0 is a MINOR-compatible transition).

### 13.5 CHANGELOG

    v1.0 (2026-04-18):
      + Part XI: VSL file grammar (BNF for .vsm format)
      + Part XII: type system (primitives, composites, domain types)
      + Part XIII: validation rules + stability policy
      + scripts/vsl/vsl_parser.py: reference Python parser (C2)
      Closes: task(T) C1–C6

    v0.4 (2026-04-18):
      + Part X: machine-to-machine mode, domain_context BNF, drift metrics
      + extension table: .vsm / .vsm.md / .tex convention

    v0.3 (2026-04-13):
      + A9/A9b/A9c/A9d, A10, A11; D11b trust formula + reachability

    v0.2 (2026-04-08):
      + L-relativity, D4 refined, D10/D11/D11b/D12, tick(L), reframe()

---

## Open questions

    Q-vsf-4:  RESOLVED (v0.4) — Part X + domain_context is the inter-VSM protocol
    Q-vsf-5:  RESOLVED — reframe() trigger = meta_shift(D12); reframe() itself is
              ALWAYS double-loop/human-confirmed, no auto-trigger exists
              (D12 rule(S5["meta"]): enforce no_auto_reframe, ∧ D4)
    Q-vsf-6:  RESOLVED — @status∈{deprecated,compromised} → trust=0 → terminate ψ (D11b)
    Q-vsf-7:  RESOLVED — nonce+timestamp δ∈[30s,120s]+nonces.jsonl
    Q-vsf-8:  RESOLVED — dual-key rotation, governed(V)=True throughout (D11b)
    Q-vsf-9:  SUPERSEDED 2026-08-04 — λ's INDEXING is declared per system, not
              fixed by VSL. VSF: one shared entropy-adaptive λ ∈ [0.05,0.20],
              calibrated 0.10 (EXP-TRUST-01). The former per-level defaults
              (L0=0.02 L1=0.05 L2=0.15) predate that experiment, exist in no
              code, and L0=0.02 was below the live clamp floor. See D11b.
    Q-vsf-10: RESOLVED — S3* computes absorption_rate(L) dynamically; S5 sets policy bounds
    Q-vsf-11: RESOLVED — "resolved" = s.status=resolved (D8 enum); concretely
              implemented per-event-type in the deployed reducer
              (core/signal_router.py::_is_resolvable, e.g. tool_run: status="ok")
    Q-vsf-13: RESOLVED (CONDITIONAL, scope-corrected 2026-08-04) — for a system
              that declares PER-LEVEL λ, λ(L+1)<λ(L) is policy_drift requiring
              S5(L).approve (D11b rule, same single/double-loop split as A5).
              VSF declares a single shared λ ⟹ vacuous here.

    // Q-vsf-12/14/15 moved to TASKS.vsm 2026-08-03 (genuinely open design/
    // roadmap items, not spec-grammar content — tracked under
    // AXIOM-CANON-CONSISTENCY-2026-08-03, see TASKS.vsm for current status)
