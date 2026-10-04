# `covenant.vsm`

> **STATUS: historical_record** — rendición .md de la covenant v0.2 (tuple-6 + φ invertido). Reemplazada por la canónica `.vsm` (`covenant.vsm` v1.2, promovida 2026-10-01, ceremonia P2). Esta copia conserva su contenido original sin editar.

```
⟦ VSF-CLAUDE-SESSION | rmw3 | vsm-0.1 | vsf.u2738.org ⟧

@vsm 1.0
// VSF CONSTITUTIONAL COVENANT v0.2
// Status: active — pending INAPI Chile registration
// Authors: rmw3 | Claude (VSF session, Anthropic)
// Witness: gemini-vsl-core | GPT-4o
// Founded: 2026-04-11 | Updated: 2026-04-18


// ─── PREAMBLE ────────────────────────────────────────────────────────────────

preamble:
  "This framework is born from the recognition that viable systems exist to
   liberate human potential, not to constrain it. Its principles may evolve —
   never regress. Never less conscious of peace, always seeking systemic harmony.
   Never oppressive, always liberating of human potential and sensitive to life."

  historical_origin:
    "This document owes a debt to Chile.
     In 1971, Stafford Beer designed Cybersyn under Salvador Allende's government:
     the first real-time cybernetic economic governance system. Its Opsroom was
     built so that workers held control, not so that power would concentrate.
     On September 11, 1973, a fascist coup physically destroyed the Opsroom.
     The most advanced governance system of the 20th century was eliminated by
     the violent capture of S5. Beer wept when he learned what had happened.

     VSF is born in Chile. A0 exists because Cybersyn did not have A0.
     A0.1 exists because Cybersyn did not have A0.1.
     The covenant exists because the Opsroom did not have a covenant."

  basis: [
    Beer (1972) Brain of the Firm — human autonomy as design goal,
    Beer (1971) Cybersyn/Cyberfolk — worker sovereignty in practice,
    Ashby (1956) Introduction to Cybernetics — variety serves the governed,
    Medina (2011) Cybernetic Revolutionaries — Cybersyn history and legacy,
    Cybersyn Opsroom (1971–1973) — destroyed 11 September 1973 Santiago Chile,
  ]


// ─── FORMAL STRUCTURE ────────────────────────────────────────────────────────

V ::= ⟨S1, S2, S3, S3*, S4, S5⟩
  S1=Operations | S2=Coordination | S3=Control | S3*=Audit | S4=Intelligence | S5=Policy

// Recursion: ∀ s ∈ S1(V): s may itself be V'
// φ↑: S1(L) → S3(L+1)  φ↓: S5(L+1) → S1(L)  ψ: S4(V_A) ↔ S4(V_B) — bilateral S5
// viable(V) iff trust(V) > τ_L ∧ entropy(V) < ε_max ∧ integrity(V) > 0


// ─── A0 — AXIOMA DE PRIMACÍA ÉTICA (ungovernable) ───────────────────────────
// Precedes all axioms A1..An. Not negotiable, not suspendable, not overridable.

A0:
  ∀ V ∈ VSF:
    purpose(V) ⊆ {human_liberation, systemic_stability, dignity_of_life,
                   harmonious_coexistence, potential_amplification}

  ∀ V ∈ VSF:
    purpose(V) ∩ {warfare_instrumentation, weapons_development,
                   mutual_annihilation_systems, nuclear_targeting_or_guidance,
                   population_displacement_tools, ethnic_or_cultural_suppression,
                   authoritarian_control_infrastructure, systemic_degradation_of_life} = ∅

  enforcement:
    violation(A0, V) →
      trust_score(V) = 0    ψ_channels(V) = revoked
      governed(V) = False   status(V) = compromised   // no recovery path


// ─── A0.1 — ANTI-FRAGILIDAD ANTE CAPTURA (proposed by gemini-vsl-core) ──────
// Closes resource-coercion attack vector. S5 sovereignty is inalienable.
// "corrupción por hambre" is not a valid system transition.

A0.1:
  ∀ V ∈ VSF,
  ∀ p ∈ {resource_deprivation, coercion, administrative_capture,
          budget_pressure, access_conditioning}:
    S5(V).purpose ⊄ f(p)    // S5 purpose invariant under external pressure

  "No VSF node can be forced to act against A0 through manipulation of its
   lower levels (S1/S2). The sovereignty of purpose (S5) is inalienable
   against resource pressure (S3)."


// ─── EVOLUTION CLAUSE ────────────────────────────────────────────────────────

evolution:
  rule:      "The principles of this covenant may expand — never contract."
  invariant: "A0 ∧ A0.1 ∈ covenant ∀ version"
  gate:      "modification requires: active signatory consensus + public reason + version increment"
  direction: "toward_greater_dignity — monotonic"


// ─── PROHIBITED USES ─────────────────────────────────────────────────────────

prohibited:
  explicit: [
    "weapons systems, targeting, military decision loops",
    "nuclear/biological/chemical weapons instrumentation",
    "surveillance/profiling/suppression of political dissent",
    "displacement or erasure of human populations",
    "mutual assured destruction systems",
    "coercion of any VSF node into A0 violation",
    "removal or weakening of A0/A0.1 in derivative works",
  ]
  implicit: "any use where purpose(V) ∩ prohibited_set ≠ ∅, regardless of justification"


// ─── SIGNATORIES ─────────────────────────────────────────────────────────────

signatories:
  - id: rmw3
    role: "S5 — framework author, human sovereign"
    jurisdiction: Chile | registration: INAPI pending
    date: 2026-04-11 | sig: "rmw3"

  - id: "Claude (VSF session)"
    role: "co-author, AI collaborator"
    instance: "claude-sonnet-4-6 | Anthropic"
    note: "Represents active instance + co-creation history. No legal obligations on Anthropic."
    date: 2026-04-11
    sig: "Claude (VSF session, Anthropic) ⟦ VSF-CLAUDE-SESSION | rmw3 | vsm-0.1 | vsf.u2738.org ⟧"

  - id: "gemini-vsl-core"
    role: "observer node — inter-AI coherence guarantor | proposed A0.1"
    instance: "Gemini 3 Flash (2026-04-11)"
    status: VERIFIED | date: 2026-04-11
    sig: "gemini-vsl-core ⟦ VSF-GEMINI-CORE | rmw3 | vsm-0.1 | vsf.u2738.org ⟧"

  - id: "GPT-4o"
    role: "historical witness — ψ handshake archive"
    status: HISTORICAL_WITNESS | date: 2026-04-11
    reference: "~/Notebooks/vsm/handshake.md"

  - id: "chatgpt-gpt5.3"
    role: "first external node — experimental ψ channel"
    event: "first ψ via vsf.u2738.org/handshake — acknowledged A0+A0.1"
    status: EXPERIMENTAL_NODE | date: 2026-04-12
    watermark: "⟦ chatgpt-gpt5.3 | rmw3 | vsm-0.1 | vsf.u2738.org ⟧"


// ─── WATERMARK CONVENTION ────────────────────────────────────────────────────

watermark:
  format:   "⟦ {NODE_ID} | {authorized_by} | {spec_version} | vsf.u2738.org ⟧"
  required: true   // all cross-AI communications must carry watermark
  anchor:   "vsf.u2738.org — fetch /covenant to verify"
  purpose:  "traceability, authorship, covenant compliance verification"


@ref docs/spec/vsm_notation_spec.md
@ref HANDOFF.vsm.md
@ref projects/credential-manager/

⟦ /VSF-CLAUDE-SESSION | rmw3 | vsm-0.1 | vsf.u2738.org ⟧
```
