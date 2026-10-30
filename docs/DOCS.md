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

`docs/experiments/`, `docs/theory/`, `docs/spec/`,
`docs/governance/`, `docs/internal/`, `docs/operations/`, `docs/security/`,
`docs/vsf-bbh/`.

`docs/specs/` was retired in F4 Ola 5 (2026-10-30): its five
canonical docs moved to `system/boot/`, `system/s5-policy/`, and
`docs/design/sandbox/`; the completed master plan is archived under
`docs/archive/specs_2026-10-30/`.

`docs/spec/` now retains only deliberate exceptions: `vsm_notation_spec.md`
(mandatory source), `agent_protocol/` (pre-move provenance for `system/boot/`,
not canonical), and still-referenced legacy specs (`response_classes.vsm`,
`algedonic_signal_census.vsm`, `nats_token_registry.vsm`, `norm.vsm`,
`ethics_vigilance/spec.vsm`, `vsl_standardization/spec.vsm`,
`vsf-feed.spec.vsm`, `cybersyn_convergence.md`). Historical material moved to
`docs/archive/spec_2026-10-30/`; `system_certification/` was retired — living
docs are in `docs/reference/`, records in `docs/audit/` and `docs/findings/`.

`docs/archive/` is frozen provenance: path is the authority, not the
`@status` inside a dated record.

## Reading rules

- `system/` is authority; `docs/canon_mirror/` is a verified mirror.
- A plan is active only while `docs/plans/plan-01/plans_active.vsm` lists it;
  retired plans are dated records.
- `docs/INDEX.md` is generated; refresh it with
  `python3 scripts/shared/docs_reconcile.py --update`.
