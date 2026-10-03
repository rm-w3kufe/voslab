# RULES — hard, non-negotiable (pointer file)

Canon: `docs/spec_revision/system/boot/hard_rules.vsm` (PROTOCOL_VERSION 3).
This file is a POINTER FILE — it does NOT restate rule bodies (R5: canon
over recall). Each rule maps to its canonical block and to its incident
rationale. Rule > memory > inference, always.

Compressed 2026-08-12 (boot token reduction, Nivel 1, rmw3 go): 4,219 tok →
pointer table. Bodies → canonical blocks; rationale → `docs/incidents/`;
instance data → `instance/instance.vsm`. Alphabet: `docs/spec/vsm_notation_spec.md`
Part I (∀ ∘ ⟹ ≡ ⊥ ⊕ ⟸).

| # | Rule | Canon block | Rationale / incidents |
|---|---|---|---|
| R1 | Locality | `hard_rules.R1_locality` | WSL libc ≠ LXC libc; R1a/R1b/R1c merged 2026-08-03 |
| R2 | → R1 | merged | 2026-08-03 compression |
| R3 | → R1 | merged | 2026-08-03 compression |
| R4 | Verification | `hard_rules.R4_verification` | `docs/incidents/2026-08-02_clima_nats_observability_incident.vsm` (3 confirmed cases); `2026-08-02_recovery_plan.vsm` phase D |
| R5 | Canon over recall | `hard_rules.R5_canon_over_recall` | 2026-06-22 post-compact run on recall alone |
| R6 | Internal first | `hard_rules.R6_internal_first` | scope ∀ S1 ∈ external_domain; gate status ∈ TASKS.vsm only |
| R7 | state.db wins | `hard_rules.R7_state_db_wins` | 2026-08-11 unscoped-inversion fix; `rules` domain RETRACTED 2026-08-12 — `state_query("rules")`/`vsf-q rules` fail loud |
| R8 | SPOF | `regulation_layer.spof_pattern` | n01/n02 instance → `instance/instance.vsm` §operations.n01_access |
| R9 | No silent concession | `hard_rules.R9_no_silent_concession` | opsroom view-contract v0.1, 2026-06-05 |
| R10 | LLM boundary | `hard_rules.R10_llm_boundary` | Qwen in algedonic path, 2026-06-10 |
| R10.1 | LLM tactics, ¬enforcement | `hard_rules.R10_1_llm_tactics_not_enforcement` | `docs/spec/strategic_tactical_authority.vsm`, 2026-06-21 |
| R11 | Naming | `hard_rules.R11_naming` | CRAG / SCADA / BBS renames |
| R12 | → R4 | merged | 2026-08-03 compression |
| R13 | Visibility | `core_boot_primer.channels` | `Ax_InterfaceOnly`; bbh asymmetry is design |
| R14 | → R4 | merged | 2026-08-03 compression |
| R15 | VSL exchange | `core_boot_primer.comms` | Meta 2026-04-09 → Qwen 2026-05-09 → DS 2026-08-03; CROSS-AGENT-VSL-ONBOARDING-ARTIFACT |
| R16 | Impl with design | `hard_rules.R16_impl_with_design` | IMPL-WITH-DESIGN-POLICY-2026-08-14; detector-first — check `impl-with-design-valid` built 2026-08-15 before rule declared |
| R17 | Destructive explicit consent | `hard_rules.R17_destructive_explicit_consent` | DESTRUCTIVE-ACTION-EXPLICIT-OK (lección 2026-08-11); ratified rmw3 S5 2026-08-15 (R17-DESTRUCTIVE-EXPLICIT-CONSENT) |
| R18 | Write-time conformance | `hard_rules.R18_write_time_conformance` | AUTONOMÍA OPERACIONAL (rmw3 S5 2026-08-17): todo doc editado → versión canónica del protocolo; el demonio `vsl-check-on-write` lo enforcea al escribir (BLOCKING), no en el commit; task R18-WRITE-TIME-CONFORMANCE |
| doc_sync | Status ∈ TASKS.vsm only | `hard_rules.doc_sync_practice` | MASTER_PLAN retirement 2026-07-31; flipped same commit |

## Operational data — lives in instance, not here

- R8 n01/n02 ssh access: `docs/spec_revision/system/instance/vsf-instance-v1/instance.vsm` → `operations.n01_access`
- S5 CA renewal (ITEM_6.4, root exp 2027-06-08, renew ≤ 2027-05-01): `operations.s5_ca_renewal` — human backstop

These were in `RULES.md` R8 + annex until 2026-08-12; moved per
R_param_resolution (substrate artifacts → instance). Do not re-add.