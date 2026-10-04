# VSF — Recursive VSM: Theory and Formal Specification
> **STATUS: historical_record** — consumido por fuse VOS-PROOFS → vos_proofs.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).
# Session: 2026-04-07

---

## 1. Formal definition of the recursive viable system

A **Viable System** at level L is a tuple:

    V(L) = ⟨ S1(L), S2(L), S3(L), S4(L), S5(L), E(L) ⟩

where `E(L)` is the observable environment at that level.

**Recursion axiom (Beer):**

    S1(L) = { V_i(L+1) }   for i = 1..n

Every operational unit of S1 at level L **is** a complete viable system at level L+1.
This is not a design choice — it is the structural invariant that makes the system viable
at any scale.

---

## 2. Communication channels (inter-level contract)

**Upward channel** — variety attenuation (child → parent):

    φ_up : V_i(L+1) → S3(L)
    φ_up(V_i) = events.jsonl

**Downward channel** — policy amplification (parent → child):

    φ_down : S3(L) → V_i(L+1)
    φ_down(S3) = params.json

No direct coupling between levels — only named channels.
Defined in `core/connection_schema.json`.

---

## 3. Resources as physical quantities

The total budget at level L is the minimum across active constraints:

    B(L) = min( B_tokens(L), B_compute(L), B_time(L) )

where:
- `B_compute(L)` = f(temperature, CPU, RAM) — thermal scheduler signal
- `B_tokens(L)`  = available LLM context — same class of scarce resource

**Invariant (structural, not indexed):**

    B(child) ≤ B(parent)    ∀ (parent, child) ∈ V.hierarchy

L is frame-local (see §11). The invariant is expressed as a parent-child relation
so it holds regardless of how levels are numbered in the current analysis frame.
Within a fixed frame this is equivalent to `B(L+1) ≤ B(L)`.

Token budget and compute budget are treated as equivalent physical resources.
The most constrained one determines the effective budget at each level.

---

## 4. Recursive execution algorithm

```
ALGORITHM  VSM_Execute(project P, level L, budget B, parameters θ)
// Implements tick(L) — one full regulation cycle at level L
// @ref docs/spec/vsm_notation_spec.md#Part-IV.b

INPUT:
  P   — project identifier (stable; L is frame-local)
  L   — recursion depth in current analysis frame (L=0 is current root)
  B   — budget inherited from parent (A2: B_child ≤ B_parent)
  θ   — params.json received from parent (φ↓)

// tick step 1: read config from parent
1.  θ ← read_params(P)                    // φ↓: params.json — parent config

// tick step 2-3: coordination and regulation
2.  S2_output ← coordinate(S1_units)      // A4: prevent sibling conflicts
3.  S3_output ← regulate(S1_units, B)     // D4: budget allocation, D8: triage

// tick step 4: escalation of unresolvable signals
4.  FOR EACH signal s with resolve(s)=∅:
      IF urgency(s) > τ_L:
        escalate(s) → φ↑(s)               // A7: escalate to parent
      ELSE:
        s.status ← deferred               // D10: accumulate — not urgent

// tick step 5: execute operations
5.  S1_units ← discover_units(P)
    FOR EACH unit u ∈ S1_units:
      B_u ← B · w_u / Σ w_j              // S3 allocation — w = priority weight
      θ_u ← derive_params(u, θ)          // downward channel
      IF is_viable(u):                    // recursion condition (D5)
        events_u ← VSM_Execute(u, L+1, B_u, θ_u)
      ELSE:
        events_u ← execute_atomic(u, θ_u)  // L0/L1: pure Python, no LLM (D6)
      emit_upward(events_u)               // → parent's events.jsonl

// tick step 6: update environment model AFTER execution
6.  S4_output ← scan_environment(P, L)   // A6: LLM only if L ≤ L_max (D6)
                                          // S4 reflects what actually happened
// tick step 7: report to parent
7.  S5_output ← apply_policy(S3_output, S4_output)
    WRITE events.jsonl                    // φ↑: output contract to parent
    RETURN events.jsonl
```

**Recursion condition:**

    is_viable(u) = True   ⟺   complexity(u) > τ
                 = False        (atomic execution — tree leaf)

**Termination is guaranteed by:**
1. `B(L+1) ≤ B(L)` — budget strictly decreases
2. Project tree has finite depth
3. Leaf nodes call `execute_atomic` — no further recursion

---

## 5. Hierarchical signal filtering

This is the mathematically strongest property of the model,
and the one most directly implementable.

Let `s` be a signal generated at level `L+k` (descendant).
The escalation condition (A7):

    s escalates to L+k-1  ⟺  resolve(s, V(L+k)) = ∅  ∧  urgency(s) > τ_{L+k}

Signal status after resolution attempt (D10):

    resolve(s, V) = ∅  ∧  urgency > τ  →  s.status = undecidable → escalate
    resolve(s, V) = ∅  ∧  urgency ≤ τ  →  s.status = deferred    → accumulate

The deferred pool is a structural diagnostic:

    meta_shift(V(L)) = True  iff:
      (∃ class(S): ∀ s ∈ class(S): resolve(s, V(L)) = ∅)
      ∧ |class(S)| / |S_total| > μ
      ∧ CalibScore(V(L), t) < 0.7  for t > δ

When meta_shift is True, the current level may be structurally insufficient —
a candidate for adding a governing layer via reframe() (see §11).

**Absorption invariant:** in a calibrated VSM, signal volume decreases
exponentially as it moves up the hierarchy:

    |S(L)| ≤ |S(L+1)| · (1 - r_L)       r_L ∈ (0,1)

where `r_L` is the local resolution rate at level `L+1`.

With `r_L ≈ 0.9`, the grandparent (L=0) sees ~1% of the grandchild's (L=2) signals.
The intermediate level resolves, absorbs, or reformulates before escalating.

**Design consequence:** signals reaching the root-level opsroom are necessarily
critical or anomalous — this keeps the monitoring panel actionable at any scale.
This is not a design preference — it is a mathematical consequence of local resolution.

---

## 6. Ashby's Law (viability condition)

The system is regulable if and only if:

    Var(disturbance) ≤ Var(S3) ⊕ Var(S2)

where `⊕` is determined by the declared variety measure (one law, two
measures — not two laws):

    measure(Var) = |states|   ⟹  ⊕ = ·   (independent regulators multiply)
    measure(Var) = additive   ⟹  ⊕ = +   (Ashby's own logarithmic measure)

**VSF declares `measure(Var) = additive`, hence `⊕ = +`.** This is not a
convention chosen on paper: the deployed kernel computes incoming variety as
`dv_in = |Δcpu_pressure| + |Δmem_pressure| + |Δio_pressure|`
(`projects/vsf-nucleus/src/operational.rs`, invariant VAR-1) — three
independent variety axes combined by addition. Ratified 2026-08-04 (L3, per
A5). Until 2026-08-04 this section read `Var(S3) · Var(S2)`, which
contradicted that live code; see `TASKS.vsm(DOC-CANON-COMPRESSION-RESTRUCTURE-2026-08-03)`.

In our implementation:
- `S3` = scheduler / LLM (high variety by design)
- `S2` = inter-project coordination (anti-oscillation)

If disturbance variety exceeds the regulator's: the system must escalate to the
parent level or declare the situation outside its autonomy ceiling (see D3).

---

## 7. Opsroom as universal monitoring interface

The opsroom implements the five VSM views for any domain:

    System Health    → S3 audit      (physical resource state)
    Pipeline Status  → S1 operations (units running/stopped)
    Signal Queue     → S2 coord.     (unresolved signals — locally absorbed)
    Priority Ranking → S4 intel.     (environment model)
    Coverage Gaps    → S3→S4         (gap between model and reality)

The only variation between VSF instances is `E(L)` — the observable environment.
The opsroom design is domain-agnostic when correctly parameterized.

**Required pipeline alert (pattern):**
The opsroom must detect and display in Signal Queue when a phase completes
but the next phase is not queued within N seconds:

    "phase N completed but N+1 not queued after 60s"  →  priority: MEDIUM

This corresponds to a failure in the S3→S1 downward channel:
the scheduler (S3) completed a phase but did not emit the order to the next S1 unit.

---

## 8. Semantic memory as VSM

Claude's memory system has an implicit VSM structure:

    Episodic   (what happened)       → S1 upward — events.jsonl
    Semantic   (what things mean)    → S4 intelligence — knowledge graph
    Procedural (how to do things)    → S1 units — skills/, agents/
    Policy     (what to prioritize)  → S5 identity — CLAUDE.md
    Coordination (anti-loop)         → S2 — feedback memory

MEMORY.md is an attenuated S4: the index is the variety-reduced form of the
full memory state. This is not a metaphor — it is the formal mechanism.

**To fully formalize:** define an algebraic type for each memory entry
and a morphism between levels. Feasible with dependent types (Idris, Agda)
or Pydantic + JSON Schema as an engineering approximation.

---

## 9. VSM notation as an executable language

**Formal precedents:**

- **π-calculus (Milner, 1992):** named channels, concurrent processes.
  VSM is almost π-calculus with resource constraints:

      P | Q  →(VSM)→  V_i(L) ‖ V_j(L)   under B(L)

- **Actor model (Hewitt, 1973):** each actor receives messages, holds state,
  creates other actors. Each V(L) is an actor; φ_up/φ_down are the messages.

- **Curry-Howard for control:** if VSM is typed with dependent types,
  the types are viability specifications and programs are proofs of viability.

**Gap to close:**

    VSM_semantic  →(+ operational semantics)→  VSM_executable

Requires defining a reduction relation `V → V'` that describes how a viable
system advances over time. This turns the notation into a language with an
interpreter. This is not speculative research — it is language engineering
with solid theoretical foundations.

**Opportunity:** no mainstream computational language is based on VSM.
The combination of hierarchical signal filtering + physical resources as types
+ structural recursion is genuinely novel as a programming interface.

---

## 10. Calibration Run as a service

A known target (fixed surface, small scope, permitted tools) is a natural
pipeline benchmark. Formally:

    CalibScore(P, t) = T_expected(P) / T_actual(P, t)  ·  B_used / B_allocated

Score ≈ 1 → system behaves as modeled.
Deviation → identifies bottlenecks (thermal, I/O, tool variety).

This service should be an S1 unit of the VSF pipeline,
executable autonomously to validate system state before production runs.

---

## 11. Level relativity and reframe()

L is frame-local — not an intrinsic property of a system but a parameter of
the current analysis session. This has a concrete operational consequence:

**A system designed as L=0 today may become L=1 tomorrow** if a governing
organization is added above it. The system's files, channels, and identifiers
do not change — only the analysis frame shifts.

    // Stable identifier: V.id (never changes)
    // Frame-local:       V.L  (changes with context)
    // Channel contract:  keyed by system_id — stable across reframe()

The **reframe()** operation formalizes this shift:

    reframe(V_id, new_parent_id):
      precondition: governed(new_parent_id)                      // D11b
      precondition: credential-manager.validate(new_parent_id)   // Part IX
      action: V(V_id).parent = new_parent_id
      action: establish(φ↑(V_id → new_parent_id))
      action: establish(φ↓(new_parent_id → V_id))

**No files are renamed. No channels are destroyed.**
The system acquires a parent; its children are unaffected.

**Propagation:** reframe() is local to the node being reframed.
- Children: unaffected — their parent reference does not change
- Siblings of the new parent: unaffected — A4 governs via the parent S3
- New parent: gains a new S1 unit, must allocate budget (A2)

**Trigger:** meta_shift(V(L0)) is a candidate trigger — when the current root
cannot resolve a class of signals, a super-structure may be needed.
reframe() is a structural change and requires human approval (D4 double-loop).

---

## 12. Protocol layer

For any VSF system to open a ψ channel safely, three layers must be satisfied:

    layer_1 ("entry gate"):
      governed(V_A) = has(params(V_A)) ∧ emits(events(V_A))
      // A system not participating in φ↑/φ↓ is ungovernable — no ψ

    layer_2 ("trust"):
      trust_score(V_A, V_B) = (1 - drift(S4(V_B))) ⊕ stability(S3(V_A))
      trust_level ∈ { none → forbid_ψ, limited → ψ_restricted, trusted → ψ_full }
      // Dynamic trust: maintained by S3* audit, degrades on drift

    layer_3 ("credentials"):
      credential-manager.validate(V_A, scope)
      scope = min(credential_scope(V_A), allowed_by_trust_level)
      // Minimum credential sharing — least privilege

**The credential-manager is not an optional feature.** It is the minimum
infrastructure required for any open VSF network. Without it, ψ channels
are unsecured — VSL's openness becomes promiscuity.

This protocol is itself a VSF system (`V("credential-manager")` in Part IX
of the notation spec) — it is organized with S1-S5 and recurses like any other.

The distinction:
- **Language (VSL):** resolves communication — makes mutual understanding possible
- **Framework (VSF):** resolves organization — defines recursive structure
- **Protocol:** resolves security — determines who may participate and under what conditions

---

## Summary — Mathematical viability

| Idea                                | Viability    | Complexity  | Status                        |
|-------------------------------------|--------------|-------------|-------------------------------|
| Semantic memory → VSM               | High         | Low         | Formalized (§8)               |
| Notation → executable code          | High         | High        | In progress — tick(L) done    |
| New computational language          | Plausible    | Very high   | Open                          |
| Hierarchical signal filtering       | Very high    | Medium      | task_E — tick(L) enables it   |
| Opsroom as universal VSF interface  | Immediate    | Low         | Done (task_D)                 |
| Calibration run as a service        | Immediate    | Low         | D9 defined                    |
| Level relativity + reframe()        | High         | Medium      | Formalized (§11)              |
| Inter-VSM protocol (ψ)              | High         | Medium      | Partial — task_F needed       |

These ideas are not independent: hierarchical filtering requires executable notation (tick ✓);
executable notation requires formalized memory (✓); inter-VSM protocol requires
credential-manager (task_F); the opsroom is the visual projection of the complete system.
They are layers of the same mathematical object.

---

## Parallel project — Blog + Wiki

The VSF framework and its mathematical foundation (Beer + Ashby + recursion +
resources as types) deserves public documentation.

Proposal:
- **Format:** technical blog + reference wiki (GitHub Pages + mdBook)
- **Audience:** complex systems engineers, cybernetics researchers, AI architects
- **Core content:** this document + domain examples (BBH as anonymous case study)
- **Management:** as an independent VSF project in `projects/vsf-docs/`

The blog documents the *journey* (decisions, tradeoffs, failures).
The wiki documents the *specification* (types, algorithms, contracts).
