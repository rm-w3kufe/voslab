# DOCS index — VSF

One line per file. Load the file directly if you need the content.
Machine-read files use VSM notation (`.vsm`). Human-read docs are `.md`.

---

## theory/
- [vos_architecture.vsm](theory/vos_architecture.vsm) — vOS full architecture spec: P1-P25, S1-S5, modes, axioms
- [vos_kernel_spec.vsm](theory/vos_kernel_spec.vsm) — kernel state machine, StateVector ℝ¹²⁸, breath cycle, organelles
- [vos_attractor_theory.vsm](theory/vos_attractor_theory.vsm) — Lyapunov convergence, cone=18.2°, empirical evidence
- [vos_entropy_cycle.vsm](theory/vos_entropy_cycle.vsm) — entropy phases: stasis/inhale/degen/exhale
- [vos_memory_architecture.vsm](theory/vos_memory_architecture.vsm) — VectorMemory M0-M3, θ_merge, decay, pruning
- [vos_theory.vsm](theory/vos_theory.vsm) — general vOS theory document
- [vos_dev_cycle.vsm](theory/vos_dev_cycle.vsm) — session_end_protocol, experiment_spec, paper_skeleton patterns
- [symbiogenesis_lab.vsm](theory/symbiogenesis_lab.vsm) — V_sci + V_ref + V_vos on n02, ψ PSI/1.0, stage(0-4) roadmap
- [thermal_stress.vsm](spec_revision/system/theory/thermal_stress.vsm) — thermal stress experiment spec (v1-v3) (migrated THEORY-12)
- [recursive_vsm_theory.md](theory/recursive_vsm_theory.md) — formal theory: budget relation, tick order, L-relativity

## spec/
- [vsm_notation_spec.md](spec/vsm_notation_spec.md) — canonical VSM/VSL notation: axioms A0-A12, grammar, D1-D12, Parts I-IX
- [vsl_primer.md](spec/vsl_primer.md) — minimal VSL briefing for external AI (cross-AI interop)

## experiments/
- [queue.vsm](experiments/queue.vsm) — experiment backlog + execution order (READY/IMPL/PENDING/DONE)
- [results_index.vsm](experiments/results_index.vsm) — index of all experiment results with key numbers

## governance/
- [strategy.vsm](governance/strategy.vsm) — SD1-SD5, external relations, authority map, vault policy
- [covenant.vsm](governance/covenant.vsm) — A0/A0.1 constitutional document, 4 signatories
- [disclosure_timeline.vsm](governance/disclosure_timeline.vsm) — T0-T3 Anthropic disclosure timeline + inbound protocol
- [comms_protocol.vsm](governance/comms_protocol.vsm) — 6-step outbound flow, content classification
- [memory_lifecycle.vsm](governance/memory_lifecycle.vsm) — create/update/deprecate/merge ops, review protocol
- [security_disclosure.md](governance/security_disclosure.md) — V1-V5 vulnerability classes (sent 2026-04-13)
- [anthropic_email_draft.md](governance/anthropic_email_draft.md) — disclosure email sent to modelbugbounty@anthropic.com

## vault/
- [VAULT_INDEX.md](vault/VAULT_INDEX.md) — vault entry index with hashes
- [VAULT_MANIFEST.md](vault/VAULT_MANIFEST.md) — SHA-256 manifest, integrity verification
- [vault_protocol.vsm](vault/vault_protocol.vsm) — classification, operations, R1-R5 integrity rules

## sessions/
- [dialogue_log.vsm](sessions/dialogue_log.vsm) — compressed VSL log of strategic/personal conversation threads
- [session_2026-04-16.vsm](sessions/session_2026-04-16.vsm) — strategy pivot, Beer outreach, soul-as-attractor reflection
- [session_2026-04-12_thermal_and_disclosure.vsm](sessions/session_2026-04-12_thermal_and_disclosure.vsm) — thermal_stress_v3 + security disclosure
- [session_2026-04-11b.vsm](sessions/session_2026-04-11b.vsm) — cross-AI ψ handshake, A0/A0.1, covenant signing
- [session_2026-04-11c.vsm](sessions/session_2026-04-11c.vsm) — vsf-nucleus born, Rust kernel, first compile

## guides/
- [concepts.md](guides/concepts.md) — S1-S5 concepts, Cybersyn patterns (public)
- [human_guide.md](guides/human_guide.md) — how to read/write VSM notation
- [infrastructure.md](guides/infrastructure.md) — infra profiles + installer spec
- [tita_briefing.md](guides/tita_briefing.md) — briefing for Tita (mathematician) on VSL formal validation

## operations/
- [live_telemetry_guide.md](operations/live_telemetry_guide.md) — opsroom SSE setup, tunnel commands, PYTHONPATH fix

## evaluation/
- [vsf_cross_eval_0.5.vsm](evaluation/vsf_cross_eval_0.5.vsm) — latest cross-AI evaluation (Claude/Gemini/GPT)

## internal/
- [vsm_gap_analysis.md](internal/vsm_gap_analysis.md) — VSM/Beer alignment analysis (working doc)

## papers/
- [attractor_convergence/](papers/attractor_convergence/) — 15pp EN+ES paper, ready for arXiv
- [basin_geometry/](papers/basin_geometry/) — second paper (TODO sections pending)
