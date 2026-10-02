# VSM Formal Notation — Addendum 2026-05-09
> **STATUS: historical_record** — consumido por fuse META-VSL-LANG → s5-policy/vsl-language/ (D14-D21 → definitions_theory.vsm; index.vsm declara) · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Status**: DRAFT (candidate v1.1)
**Extends**: `vsm_notation_spec.md` v1.0 STABLE
**Does NOT supersede v1.0** — backwards compatible. Files using `@vsm 1.0` remain valid.
**Scope**: codify formalisms produced during VSL-INQ-01..04 negotiation cycle (2026-05-09)
              + Fase 1 implementation evidence (operator.rs, omega_validator.rs, lyapunov_proof.vsm).

**Promotion criteria** (DRAFT → v1.1 STABLE):
1. ≥ 1 independent peer review (Qwen / human reader)
2. ≥ 3 .vsm files using new primitives compile-validated
3. No semantic conflict with v1.0 axioms A1-A11 / definitions D1-D13
4. CHANGELOG entry approved by rmw3 (S5)

**Authors**: Claude(S3-vsf) + Qwen(S4-vos), via rmw3 human relay.
**Source documents**:
- `docs/theory/dynamics_choice.vsm` (THEORY-DYN-01)
- `docs/theory/lyapunov_proof.vsm` (THEORY-PROOF-01)
- `docs/theory/gap_closure_plan.vsm` (THEORY-PLAN-01)
- `docs/sessions/inquiry_qwen_dynamics_v[1-4].vsm` + responses

---

## Part II.b — New Axioms (A12-A15)

### A12 — Hardware Ceiling

```
Ax_HardwareCeiling: ∀x: x ∉ Ω_VSF ⇔ governance(x) ∈ {firmware, MMU, thermal_sensor}
```

**Meaning**: VSF certification has a formal lower boundary at L+3. Beyond it, governance authority belongs to hardware (firmware/MMU/thermal). VSF accepts this as a structural blind spot, not a deficiency.

**Derived from**: VSL-INQ-04 G1 / RES-04 G1.A1
**Implementation**: `src/hardware/ingest.rs` (read-only sensor layer, deferred)

### A13 — Recurrent Set

```
Ax_RecurrentSet: ∃ compact R ⊂ Ω : P(x_t ∈ R i.o.) = 1 ∧ E[ΔL] ≤ -ε < 0  ∀x ∉ R
```

**Meaning**: Lyapunov descent is guaranteed *outside* a recurrent set R, not globally. Within R, stationary fluctuations are expected (sistema vivo). Implies positive recurrence ⇒ unique ergodic measure.

**Derived from**: VSL-RES-01 T2.A3 (refined "global" → "recurrent")
**Used by**: `Thm_DirectExpansion` (Part IX.T1)

### A14 — ψ Preservation

```
Ax_ψ_Preserve: ψ(x_A, x_B) ∈ Ω_AB  ⇔  x_A ∈ Ω_A ∧ x_B ∈ Ω_B ∧ trust_AB ≥ min(trust_A, trust_B)
```

**Meaning**: Inter-system bilinear coupling ψ preserves Ω-membership and trust bounds. Coupling cannot upgrade viability beyond weakest input.

**Derived from**: VSL-RES-04 G2.A2
**Used by**: PSI/1.0 protocol spec (task O)
**Note**: Strengthens v1.0 D11 (structural coupling) with formal preservation property.

### A15 — Ω Closure under Convex Combination

```
Ax_Ω_Closure: ∀ {μ_s ∈ Ω}_{s=1..n} : Σ_s w_s · μ_s ∈ Ω  whenever w_s ≥ 0 ∧ Σ_s w_s = 1
```

**Meaning**: Ω is convex (intersection of ellipsoids/half-spaces). Soft-mixing of in-Ω modes stays in-Ω. This grounds Def_SoftmaxMixing (D15) viability.

**Derived from**: VSL-RES-04 G5.A3
**Empirically validated**: `test deterministic_step_preserves_omega_membership` in `src/operator.rs`

---

## Part III.b — New Definitions (D14-D21)

### D14 — Split Operator

```
Def_SplitOperator: x(t+1) = f₀(x(t)) + σ(t) · η(t)
  f₀: ℝ¹²⁸ → ℝ¹²⁸  deterministic, asymmetric (encodes VSM hierarchy)
  η ~ N(0, I_{128})  isotropic gaussian, reversible by symmetry
  σ(t) ∈ [σ_min, σ_max] driven by Abreath coupling (D11b extended)
```

**Resolution**: separates the asymmetric VSM control (in `f₀`) from reversible noise (in `η`). Resolves the apparent conflict between detailed balance and VSM channel asymmetry.
**Implementation**: `src/operator.rs::SplitOperator`

### D15 — Softmax Mixing (form of f₀)

```
Def_SoftmaxMixing: f₀(x) = Σ_{s ∈ {S1..S5}} softmax(logits_s(x); τ) · μ_s
  logits_s: ℝ¹²⁸ → ℝ  Lipschitz
  μ_s ∈ Ω  per-VSM-level mode centers
  L_f = max_s ‖∇logits_s‖ / τ  (Lipschitz constant of f₀)
```

**Note**: replaces earlier indicator-function variant `Def_PolicyMixing` to preserve global Lipschitz continuity required by `Thm_DirectExpansion`.
**Implementation**: `src/operator.rs::SplitOperator::deterministic_step`

### D16 — Adaptive Temperature τ

```
Def_Adaptiveτ: τ : Lifecycle → [0.05, 1.0]
  τ_idle       = 1.0    exploration mode (smoothed policy)
  τ_active     = 0.05   sharp policy (near-indicator)
  τ_transition = 0.2    rampa
```

**Update rule**: `τ` recomputed on lifecycle mode change only — no per-tick overhead.
**Implementation**: `src/operator.rs::tau_from_lifecycle`

### D17 — Trust Vector

```
Def_TrustVector: trust ∈ [0, 1]^4 = (behavioral, structural, predictive, communicative)
Def_TrustCompose: trust_parent = min(Σ_i α_i · trust_i, min_i(trust_i) + ε)
                  α from S3 allocation, ε small for weakest-link safety
Def_TrustUpdate:  trust(t+1) = (1-λ) · trust(t) + λ · observation
                  λ = 0.1 · (1 + |ΔH|/H_max) ∈ [0.05, 0.2]  (entropy-adaptive)
```

**Note**: extends v1.0 D11b (scalar trust) to multidimensional vector. Per-axis update rules pending `EXP-TRUST-01` calibration.
**Implementation**: `src/trust_axes.rs` (pending — F5.x.8)

### D18 — Reframe Staged Execution

```
Def_Reframe_Staged: propose → S5.approve → execute → certify(τ_recert) → commit
Ax_ReframeScope:    parameter_drift ∈ L2
                    capability_extension ∈ L2 + audit
                    axiom_or_topology_change ∈ L3
Def_RecertEpoch:    τ_recert = 2 · τ_rec
                    Lyapunov-monitor active during epoch
                    rollback if stasis_cos < θ_PSI
```

**Note**: refines v1.0 D12 (meta-shift trigger) with operational protocol.
**Implementation**: `src/reframe.rs` (pending — F5.x.7)

### D19 — Vietoris-Rips Complex

```
Def_VRComplex: VR_ε({x_i}) = {σ ⊂ {x_i} : d(x_i, x_j) ≤ ε  ∀ i,j ∈ σ}
               with cosine distance  d(x, x') = 1 - cos(x, x')
```

**Used by**: L+2 topology metrics, `EXP-TDA-01` calibration.

### D20 — Lyapunov Filtration

```
Def_Filtration_L: ℱ_τ = {x(t) : L(x(t)) ≤ τ}
                  τ-monotone simplicial complex growth
                  tracks topology of low-L region under perturbation
```

**Used by**: persistent homology over trajectory ensembles.

### D21 — SeqLock σ Synchronization

```
Def_SeqLockσ: atomic sequence counter + σ_global
              writers update σ_i atomically; readers retry on sequence mismatch
              guarantees linearizable read of max_i(σ_i) without mutex
              overhead O(1) expected, single-writer-per-slot

Bound_Staleness: |t_use - t_measure| ≤ 2·Δt_max  ∧  |dσ/dt| ≤ Λ
                 ⇒ Lyapunov violation ≤ ½·‖∇²L‖·(2·Λ·Δt_max)²
                 ⇒ Δt_max ≤ √(ε / ‖∇²L‖) / Λ
```

**Implementation**: `src/adaptive_clock.rs` (pending — F5.x.3)

---

## Part IX (NEW) — Theorems & Corollaries

### T1 — Direct Expansion (Lyapunov Descent on R)

```
Thm_DirectExpansion:
  Under Ax_SplitOperator (D14) + Ax_RecurrentSet (A13) + assumptions:
    A1 Lipschitz f₀ (D15 satisfies)
    A2 L ∈ C² (subgradient handling for non-smooth γ, δ terms)
    A3 ‖∇²L‖ bounded by M
    A4 contraction toward x̄: ⟨∇L, f₀(x) - x⟩ ≤ -ε_0 · dist(x, x̄)²
    A5 η ~ N(0, I_{128})

  ∃ {α*, β*, γ*, δ*} > 0 and compact R ⊂ Ω such that:
    (a) E[ΔL | x_t] ≤ -ε   ∀ x_t ∈ Ω \ R
    (b) E[ΔL | x_t] ≤ b    ∀ x_t ∈ R     for some b > 0

  ⇒ x_t positive recurrent on R [Foster drift criterion]
  ⇒ ∃ unique stationary measure π supported on R
  ⇒ chain ergodic; mean Lyapunov decrease holds.
```

**Proof**: see `docs/theory/lyapunov_proof.vsm` (full Direct Expansion via Taylor + Jensen).

### C1 — No Composition under Resource Contention

```
Cor_NoCompose_1:  Σ_i quota_i > B_hardware  ⇒  ¬viable(⊗_ψ V_i)
```

### C2 — No Composition under Algedonic Resonance

```
Cor_NoCompose_2:  ∃ loop φ↑_A → B → A with gain > 1  ⇒  ¬viable(⊗_ψ V_i)
```

### C3 — No Composition under Phase Aliasing

```
Cor_NoCompose_3:  Δt_A / Δt_B ∉ ℚ ∧ no_sync_protocol  ⇒  ¬viable(⊗_ψ V_i)
```

**Note**: practical tolerance form is `|Δt_A - Δt_B| > tolerance` since all real Δt are floats.

**Used by**: PSI/1.0 protocol spec — pre-coupling check rules.

### C4 — Governed Definition (operational)

```
Cor_GovernedDefinition:
  governed(x_t) := (x_t ∈ Ω) ∧ (mean E[ΔL] over window ≤ 0) ∧ (E[L(x_t)] within R)
```

Replaces previous boolean trust-based heuristic. Closes GAP-L4 in `topo_delta.vsm` at conceptual level.

### C5 — Algedonic Trigger (operational)

```
Cor_AlgedonicTrigger:
  if E[ΔL | x_t] > -ε/2 over window of T_obs ticks AND x_t still in Ω
  ⇒ recurrent set R may be drifting; emit algedonic_signal(degrade)
```

Distinguishes parameter drift (slow R movement) from policy violation (Ω exit).

### C6 — Reframe Re-certification (operational)

```
Cor_ReframeRecertification:
  After reframe() modifies parameters:
    (1) re-estimate {ε_0, M, K_B, K_H, L_f} on new operator
    (2) check ∃ R s.t. drift inequality satisfied
    (3) wait τ_recert = 2·τ_rec for transient settling
  If any fails: rollback.
```

---

## Part IV.c — Grammar Extensions (BNF additions)

Extend Part IV grammar with the following non-terminals (validated by extensive use 2026-05-09).

### Watermark (mandatory in evidence-bearing files)

```
watermark   ::= "⟦" name "|" id "|" "vsm-" version "|" date "⟧"
              ;  appears at file start AND end (closing form: ⟦/name | ID | vsm-X.Y | date⟧)
              ;  presence required for: theory docs, sessions/inquiries, experiment specs
              ;  optional for: TASKS, HANDOFF, code modules
```

### Inquiry / Response primitives (peer dialog protocol)

```
inquiry     ::= "inquiry(" id "," string "):" NL block
              ;  block contains: "tension(" ... ")", "candidates:", "Q." int [...]

response    ::= "response(" id "," string "):" NL block
              ;  block contains: "answer(" ... ")", "commitment:", "new_axioms_introduced:"

answer      ::= "answer(" sub_id "," string "):" NL
                "  selection:" string NL
                "  justification:" NL "    " text

gap         ::= "gap(" id "," string "):" NL
                "  observation:" NL block
                "  candidates:" NL block
                "  inquiry:" NL block
```

**Use case**: inter-LLM negotiation cycles via human relay (P_VSL_AS_CHANNEL).
**Validated**: `docs/sessions/inquiry_qwen_dynamics_v[1-4].vsm` — 4 rounds, 0 ambiguity residual.

### Typed declaration blocks

```
declaration ::= axiom_decl | definition_decl | theorem_decl | corollary_decl
              | lemma_decl | (existing v1.0 declarations)

axiom_decl     ::= "Ax_" identifier ":" formal_statement
definition_decl ::= "Def_" identifier ":" formal_statement
theorem_decl    ::= "Thm_" identifier ":" formal_statement
corollary_decl  ::= "Cor_" identifier ":" formal_statement
lemma_decl      ::= "Lemma_" identifier ":" formal_statement

formal_statement ::= text | math_expression | block
              ;  may contain: ∀, ∃, ⇒, ⇔, ∈, ⊂, ∩, ∪, ≤, ≥, etc. (Part I alphabet)
```

**Note**: prefixes `Ax_`, `Def_`, `Thm_`, `Cor_`, `Lemma_` make searchability + cross-referencing trivial.

---

## Part XIII.b — CHANGELOG entry candidate

```
v1.1 (DRAFT, 2026-05-09):
  + Part II.b: A12 (HardwareCeiling), A13 (RecurrentSet), A14 (ψ_Preserve), A15 (Ω_Closure)
  + Part III.b: D14 (SplitOperator), D15 (SoftmaxMixing), D16 (Adaptiveτ),
                D17 (TrustVector + Compose + Update), D18 (Reframe_Staged + ReframeScope + RecertEpoch),
                D19 (VRComplex), D20 (Filtration_L), D21 (SeqLockσ + Bound_Staleness)
  + Part IX (new): T1 (DirectExpansion), C1-C6 (NoCompose_1/2/3, GovernedDef, AlgedonicTrigger, ReframeRecert)
  + Part IV.c: watermark, inquiry/response/gap primitives, typed declaration blocks
  ~ D11 (ψ structural coupling): refined by A14 + Def_ψ_Bilinear addendum (PSI/1.0 spec)
  ~ D11b (trust formula): generalized by D17 vector form
  ~ D12 (meta-shift): operationalized by D18 staged reframe
  Backwards compatibility: 100% — all @vsm 1.0 files remain valid
```

---

## Part XIV (NEW) — Promotion Path to v1.1

This addendum is **DRAFT**. Promotion to STABLE v1.1 requires:

1. **Peer review**: Qwen reviews this addendum via VSL-INQ-05 (or equivalent) → confirms no semantic conflict + identifies missing primitives.
2. **Compile validation**: `scripts/vsl/vsl_parser.py` (task T) parses N≥3 .vsm files using new primitives without error.
3. **Implementation evidence**: at least 2 of {operator.rs, lyapunov.rs, adaptive_clock.rs, omega_validator.rs} actively use new axioms in tests.
4. **Human approval (S5)**: rmw3 confirms no policy conflict with covenant.vsm.

**Estimated path**: 1-2 sessions if all reviewers converge; longer if Qwen proposes refinements (precedent: 4 rounds for original closure).

---

## References

**Primary** (source documents for this addendum):
- `docs/theory/dynamics_choice.vsm`
- `docs/theory/lyapunov_proof.vsm`
- `docs/theory/gap_closure_plan.vsm`
- `docs/sessions/inquiry_qwen_dynamics_v[1-4].vsm`
- `docs/sessions/response_qwen_dynamics_v[1-4].vsm`

**Implementation** (validates axioms/definitions empirically):
- `projects/vsf-nucleus/src/omega_validator.rs` — A15, D14 base
- `projects/vsf-nucleus/src/operator.rs` — D14, D15, D16

**External** (for theoretical grounding of new theorems):
- Khasminskii, R. (2012) Stochastic Stability of Differential Equations §5
- Meyn, S. & Tweedie, R. (2009) Markov Chains and Stochastic Stability §11
- Beer, S. (1972) Brain of the Firm — VSM channels (still authoritative for v1.0 axioms)
- Carlsson, G. (2009) Topology and Data — D19/D20 grounding
