# docs/ — gateway

`docs/` is the working-document tree. Canonical policy lives in `system/`;
generated index lives in `docs/INDEX.md` (queryable: `docs/.index.db`).

Start with:

- `docs/INDEX.md` — generated filesystem index (do not hand-edit)
- `docs/glossary.vsm` — formal terms
- `docs/papers/` — long-form papers (the paper entry point is the paper's `paper_data.vsm`)
- `docs/plans/plan-01/plans_active.vsm` — active-plan trunk

## Homes (F4 DOC-HOME-POLICY, S5 2026-10-29)

The machine-readable declaration is PART IV-C `home_policy` in
`docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm`.
The write-time gate reads it.

| Home | Purpose |
|---|---|
| `system/` | normative canon: rules, policies, contracts, invariants |
| `docs/design/sources/` | designs of instruments that run |
| `docs/design/sandbox/` | proposals in validation (not canon) |
| `docs/plans/` | active plans and their specs/phases |
| `docs/sessions/`, `docs/audit/`, `docs/findings/`, `docs/evaluation/`, `docs/rubric/`, `docs/incidents/`, `docs/ledger/`, `docs/learning_records/`, `docs/historical/`, `docs/deploy/` | records |
| `docs/papers/`, `docs/publishing/`, `docs/outreach/`, `docs/charts/`, `docs/corpus/`, `docs/guides/`, `docs/reference/`, `docs/vault/`, `docs/notebooks/`, `docs/metaphors/`, `docs/memory/`, `docs/correspondence/` | outputs and working collections |

Before creating a `.vsm`, ask the policy where it belongs:

```bash
python3 scripts/vsl/classifier/doc_home.py suggest <TYPE> [status] [name]
```

A new document outside the approved homes is blocked by the write gate.

## Legacy read-only areas

These remain readable and tracked docs may be edited, but they are not
approved homes for new documents (F4 cleanup waves promote or archive them):

`docs/experiments/`, `docs/governance/` (only the frozen production covenant
remains), `docs/internal/`.

F4 Ola 6 (2026-10-30): `docs/governance/` policy sources and `docs/security/`
moved to `system/s5-policy/governance/` and
`system/s3-control/soc-xdr-01/security/`; the production covenant copy stays
at `docs/governance/covenant.vsm` (frozen until the promotion ceremony;
canonical bytes live at `system/boot/covenant.vsm`).

`docs/specs/` was retired in F4 Ola 5 (2026-10-30): its five
canonical docs moved to `system/boot/`, `system/s5-policy/`, and
`docs/design/sandbox/`; the completed master plan is archived under
`docs/archive/specs_2026-10-30/`.

F4 Ola 7 (2026-10-30): `docs/spec/` retired. `agent_protocol/` provenance
moved to `docs/archive/agent_protocol_2026-10-30/`; `response_classes.vsm` +
`norm.vsm` → `system/s3-control/cyberfilter-01/`; `algedonic_signal_census.vsm`
→ `system/s5-policy/s5-algedonic-01/`; `nats_token_registry.vsm` →
`system/s2-coordination/nats-auth-01/`; `ethics_vigilance/spec.vsm` →
`system/s4-intelligence/ethics-vigilance-01/`; `vsl_standardization/spec.vsm`
→ `system/s5-policy/vsl-language/`; `cybersyn_convergence.md` →
`docs/reference/`; `vsf-feed.spec.vsm` → `docs/design/sandbox/`.
`docs/operations/` + `docs/infra/` + `docs/theory/` archived under
`docs/archive/*_2026-10-30/`; `docs/vsf-bbh/` → `projects/vsf-bbh/`.

The VSL notation spec lives at `docs/reference/vsm_notation_spec.md`
(moved from `docs/spec/` in F4 Ola 6).

`docs/archive/` is frozen provenance: path is the authority, not the
`@status` inside a dated record.

## Reading rules

- `system/` is authority; `docs/canon_mirror/` is a verified mirror.
- A plan is active only while `docs/plans/plan-01/plans_active.vsm` lists it;
  retired plans are dated records.
- `docs/INDEX.md` is generated; refresh it with
  `python3 scripts/shared/docs_reconcile.py --update`.
