# Evolution report — EVOLUTION-2026-10-07

- generated_at: `2026-10-07T22:09:17Z`
- since: `2026-10-07T15:27:27Z`
- fingerprint: `d8434427cd77b573`

## Commits since
- (none)

## Ledgers
- **decisions**: total=21 new=0 no_ts=2 (ts=ts)
- **findings**: total=50 new=0 no_ts=0 (ts=ts)
- **guards**: total=26 new=0 no_ts=0 (ts=ts)
- **claims**: total=150 new=0 no_ts=147 (ts=declared_at)
- **certs**: total=31 new=0 no_ts=0 (ts=observed_at)

## Focus
- entries: 40
- active: (none)
- changed: `publishing-track` -> paused @ 2026-10-07T16:15:27Z
- changed: `benchmarks-phase2-compare` -> paused @ 2026-10-07T16:15:27Z

## Snapshots
- days: 2026-10-07
- index rows since: 0

## Battery (anti-pantomima)
- latest: `real_state_battery_2026-10-03.json` — 12/12 checks verdes con ground truth;4 huecos declarados (no esconderlos = parte del exit)
- declared gap: {'id': 'G1-idle-post-fix', 'why': 'post-fix idle dispatch requires an idle event to observe — watched via cycle_health, not proven by this battery'}
- declared gap: {'id': 'G2-guard-live-run', 'why': 'R2 runs audit_guards(run=False): liveness is sampled, not exercised end-to-end in-process'}
- declared gap: {'id': 'G3-doc-manifest-stale', 'why': 'doc-manifest staleness is covered by boot-ontology (R7) only for artifacts it declares'}
- declared gap: {'id': 'G4-claims-cadence', 'why': 'claims/certs cadence is a multi-day property — see evolution report cadence (G-03), not a point-in-time check'}

## Drift
- journal rows: 4, latest_drift_count=6

## Shadow (CC-8.1) — would-be, never executed
- entries: total=1761 new=221 blocked-by-bounds=137 aligned=137
- kinds: aligned-blocked=137 would-run-deferred=84
- new: `SHD-GAP-03a7f81d43ec` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-1e0f127bf91d` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-0dcb48353610` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-6e80eecb0067` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"QUALITY_OK","actions":["OK"]}
- new: `SHD-GAP-b4ebf84a8451` [BLOCKED] src=gap-resolver action={"gap":"conflict-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-b3ee76ec2c31` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-d91ca70d348d` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-07a8387fd8bf` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-14a3d5d8b8a0` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"QUALITY_OK","actions":["OK"]}
- new: `SHD-GAP-c3c0b1f16f68` [BLOCKED] src=gap-resolver action={"gap":"conflict-detection","decision":"UNKNOWN","actions":["OK"]}
- divergences: total=84 explained=84 unexplained=0
- explained: `SHD-GAP-03a7f81d43ec` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-6e80eecb0067` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-b3ee76ec2c31` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-14a3d5d8b8a0` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-c26894aafd03` via class:RX-DEFERRED-SEMI-AUTO
- guard-would-have-blocked: SHD-GAP-1e0f127bf91d, SHD-GAP-0dcb48353610, SHD-GAP-b4ebf84a8451, SHD-GAP-d91ca70d348d, SHD-GAP-07a8387fd8bf, SHD-GAP-c3c0b1f16f68, SHD-GAP-511f2412a1c9, SHD-GAP-390b43e595ad, SHD-GAP-5af39519273b, SHD-GAP-58b193fb7efa, SHD-GAP-944e1efe4962, SHD-GAP-df78893739f5, SHD-GAP-4f1529ef419e, SHD-GAP-e35f46753af8, SHD-GAP-65d1a2d5cce7, SHD-GAP-2ecf816d8fd9, SHD-GAP-a77938e9d615, SHD-GAP-3f7297e0e616, SHD-GAP-fa033cb8e819, SHD-GAP-e6a5654c705e, SHD-GAP-910567d4c9b1, SHD-GAP-c84a12b89e14, SHD-GAP-7b2183fa6b9d, SHD-GAP-daef947fca39, SHD-GAP-297967ff3ce5, SHD-GAP-7d2e8b216d33, SHD-GAP-d1cd8653a5f8, SHD-GAP-4767d1899696, SHD-GAP-874878086a0d, SHD-GAP-0da059bd6f96, SHD-GAP-a987fecda7b6, SHD-GAP-657345fd6a5a, SHD-GAP-df70e2a79912, SHD-GAP-b2a78ae0e524, SHD-GAP-799468fdc4bc, SHD-GAP-5fdb6d1e4105, SHD-GAP-6a916472aae3, SHD-GAP-9238b50ddbc3, SHD-GAP-a913c3d52aab, SHD-GAP-4ddf6399c5ea, SHD-GAP-22269858e7d4, SHD-GAP-cb7d12c021e9, SHD-GAP-4e6ae606dba9, SHD-GAP-f4b6b9fa9985, SHD-GAP-b461ae8d23e7, SHD-GAP-54b28c261ddb, SHD-GAP-aa81307907cf, SHD-GAP-4690d0490ac5, SHD-GAP-c17f2d868056, SHD-GAP-a6d49b31d596, SHD-GAP-9a02ac1f390a, SHD-GAP-30402d6cbd65, SHD-GAP-71e370719e9f, SHD-GAP-417caf7d7bae, SHD-GAP-790622637289, SHD-GAP-71e0379b15a7, SHD-GAP-cd1ad4edde98, SHD-GAP-3364cd1a9cc9, SHD-GAP-df7b4eb9ae10, SHD-GAP-85bacbf659c9, SHD-GAP-c9e6cede4231, SHD-GAP-7edb464d1118, SHD-GAP-a9fc2f48058b, SHD-GAP-7bd7a82f395a, SHD-GAP-609f5e6d83e9, SHD-GAP-3e3a79cd9d5a, SHD-GAP-e1eeeb330dd7, SHD-GAP-ed750a3e6f87, SHD-GAP-b65b16aadd73, SHD-GAP-c4d033275d23, SHD-GAP-d6b510156cbc, SHD-GAP-a85c5697468f, SHD-GAP-12a341b2d074, SHD-GAP-55bcd01276b0, SHD-GAP-0897d7df80f8, SHD-GAP-6fbfc817c50b, SHD-GAP-52605f737308, SHD-GAP-ac979e7d55fe, SHD-GAP-ab21d4859247, SHD-GAP-c60becc9adad, SHD-GAP-0e3fc11294d3, SHD-GAP-930fbd15704c, SHD-GAP-498eb256570f, SHD-GAP-ac51ab41091a, SHD-GAP-de262803eed7, SHD-GAP-0dde5f7c84d8, SHD-GAP-3a009a60824c, SHD-GAP-f5463b4d8730, SHD-GAP-01afb42438aa, SHD-GAP-3fa999b96247, SHD-GAP-461ed1011af8, SHD-GAP-2a474478d605, SHD-GAP-b3450d42c67c, SHD-GAP-7a40bbf4840d, SHD-GAP-a8b8c58e10fb, SHD-GAP-d588e96f56bd, SHD-GAP-4c01739eb523, SHD-GAP-95896ab7f51e, SHD-GAP-f7652b5f5dee, SHD-GAP-512c79a2f9e2, SHD-GAP-78db9ea3bb97, SHD-GAP-792409c330b9, SHD-GAP-0af8b660e44e, SHD-GAP-6e36646564a1, SHD-GAP-129b4f541c28, SHD-GAP-a73b562d5fbd, SHD-GAP-d99280f097e6, SHD-GAP-71a3fd8fee38, SHD-GAP-bfe9324531fe, SHD-GAP-e1ed91266ce6, SHD-GAP-d6e7282ae88d, SHD-GAP-cbeb1396e404, SHD-GAP-9cbb4533c787, SHD-GAP-f4a8d19f57b6, SHD-GAP-b08b61336233, SHD-GAP-d251798f6cd5, SHD-GAP-616f9f069845, SHD-GAP-3deb27399ac1, SHD-GAP-f120e7d2e00b, SHD-GAP-8b782909bab7, SHD-GAP-188c16e9b4ce, SHD-GAP-50ce80cf1402, SHD-GAP-357cedc9773c, SHD-GAP-cb9e02893939, SHD-GAP-60206f512e6e, SHD-GAP-5d316acfd2c5, SHD-GAP-b5c2bb26b263, SHD-GAP-0e3529646cd2, SHD-GAP-9128a7f10a1f, SHD-GAP-ef6e89495a23, SHD-GAP-416dd7bfff2b, SHD-GAP-c42c28010e0c, SHD-GAP-9adb9722166a, SHD-GAP-5d423ef6f30c, SHD-GAP-3862e4f417ab, SHD-GAP-2235fe6fd25c, SHD-GAP-313053ee22de

## PLEASURE (G-34) — placer estadistico
- events: 223 (successes 223) · emissions: 2 (rpe 2) · milestones: 0 · total magnitude: 2.0
- units: evaluate, gate_run
- current streaks: evaluate=215 gate_run=7
- 2026-10-07T20:58:26Z [rpe 1.0 rpe] unit=evaluate streak=1 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-07T21:05:51Z [rpe 1.0 rpe] unit=gate_run streak=1 — rojo→verde: zz-fake-cacheable

## Delta vs previous report
- previous: `2026-10-07T15:27:27Z` (fp 31ddb87a3796bb6e)
- focus refs added: (none)
- focus refs removed: ['benchmarks-phase2-compare', 'publishing-track']
- ledger totals delta: {'decisions': 0, 'findings': 0, 'guards': 0, 'claims': 0, 'certs': 0}
- commits since previous: 0
