# Evolution report — EVOLUTION-2026-10-10

- generated_at: `2026-10-10T17:44:13Z`
- since: `2026-10-09T15:48:35Z`
- fingerprint: `83df1a94ce39b001`

## Commits since
- `60e1857` 2026-10-10T03:24:07-03:00 — feat(analysis): NB06 L3 verificacion simbolica — 8 checks sympy (6 PASS + 1 COND + 1 GRID)
- `30d8042` 2026-10-10T01:26:24-03:00 — feat(analysis): NB05 grafos-capas (micro/meso/macro) + NB04 L2-full + main.claims 375/375 routes
- `12beae5` 2026-10-10T00:16:38-03:00 — docs(plans): graph_epistemic_proposal — grafo epistemico unificado (proposed)
- `0212ac2` 2026-10-09T23:39:52-03:00 — feat(analytic_engine): DEPTH-v1 sidecar por documento — persist_depth() idempotente
- `587cc46` 2026-10-09T23:18:43-03:00 — feat(analytic_engine): depth_estimator — auto L1-L5 level + tool estimation (R10)
- `57ad00b` 2026-10-09T17:01:38-03:00 — chore(focus): QUEUE-EXEC note — F2 analisis conjunto entregado (NB00-02, B1/B2/C cerrados, Q1-Q3 DISCHARGED)
- `87956b5` 2026-10-09T16:42:31-03:00 — feat(analysis): B2+C — inventario A0/A0.1 + correlacion Q1-Q3 DISCHARGED (10 tests)
- `b73eacc` 2026-10-09T16:30:24-03:00 — feat(analysis): B1 coherencia interna — l2_parser + NB01 (7 tests)
- `ce3288d` 2026-10-09T16:15:07-03:00 — feat(analysis): F2/L2 NB00 situacion del conjunto + sync LXC114

## Ledgers
- **decisions**: total=21 new=0 no_ts=2 (ts=ts)
- **findings**: total=50 new=0 no_ts=0 (ts=ts)
- **guards**: total=26 new=0 no_ts=0 (ts=ts)
- **claims**: total=150 new=0 no_ts=147 (ts=declared_at)
- **certs**: total=31 new=0 no_ts=0 (ts=observed_at)

## Focus
- entries: 48
- active: QUEUE-EXEC-2026-10-08
- changed: `QUEUE-EXEC-2026-10-08` -> active @ 2026-10-10T17:37:58Z

## Snapshots
- days: 2026-10-09, 2026-10-10
- index rows since: 1

## Battery (anti-pantomima)
- latest: `real_state_battery_2026-10-03.json` — 12/12 checks verdes con ground truth;4 huecos declarados (no esconderlos = parte del exit)
- declared gap: {'id': 'G1-idle-post-fix', 'why': 'post-fix idle dispatch requires an idle event to observe — watched via cycle_health, not proven by this battery'}
- declared gap: {'id': 'G2-guard-live-run', 'why': 'R2 runs audit_guards(run=False): liveness is sampled, not exercised end-to-end in-process'}
- declared gap: {'id': 'G3-doc-manifest-stale', 'why': 'doc-manifest staleness is covered by boot-ontology (R7) only for artifacts it declares'}
- declared gap: {'id': 'G4-claims-cadence', 'why': 'claims/certs cadence is a multi-day property — see evolution report cadence (G-03), not a point-in-time check'}

## Drift
- journal rows: 4, latest_drift_count=6

## Shadow (CC-8.1) — would-be, never executed
- entries: total=2650 new=459 blocked-by-bounds=241 aligned=241
- kinds: aligned-blocked=241 would-run-deferred=218
- new: `SHD-GAP-f7c2e4bd771a` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-788b4c57be76` [would-run] src=gap-resolver action={"gap":"patch-detection","decision":"STALE_PATCH","actions":["ALERT: Patch is st
- new: `SHD-GAP-94a1ce41c526` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-e35abab4c2a1` [would-run] src=gap-resolver action={"gap":"patch-detection","decision":"STALE_PATCH","actions":["ALERT: Patch is st
- new: `SHD-GAP-c436bf4b1409` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-eb78dd61867a` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"QUALITY_OK","actions":["OK"]}
- new: `SHD-GAP-fca45f85d824` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-f7618cb458fe` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"QUALITY_OK","actions":["OK"]}
- new: `SHD-GAP-d1743dae65c8` [BLOCKED] src=gap-resolver action={"gap":"conflict-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-cfdcbe6d36fa` [BLOCKED] src=gap-resolver action={"gap":"conflict-detection","decision":"UNKNOWN","actions":["OK"]}
- divergences: total=218 explained=218 unexplained=0
- explained: `SHD-GAP-f7c2e4bd771a` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-788b4c57be76` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-94a1ce41c526` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-e35abab4c2a1` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-eb78dd61867a` via class:RX-DEFERRED-SEMI-AUTO
- guard-would-have-blocked: SHD-GAP-c436bf4b1409, SHD-GAP-fca45f85d824, SHD-GAP-d1743dae65c8, SHD-GAP-cfdcbe6d36fa, SHD-GAP-58350dc3d789, SHD-GAP-c3d6050dad94, SHD-GAP-15a6d08898c9, SHD-GAP-9d6f8cfcea45, SHD-GAP-004fa1f38460, SHD-GAP-6bee4251a00c, SHD-GAP-4cdae92e01ca, SHD-GAP-7aee6a66bb9c, SHD-GAP-f4248372f642, SHD-GAP-617e94ebc549, SHD-GAP-35e38801be0e, SHD-GAP-c1bb125c8b62, SHD-GAP-ac79d4c35cab, SHD-GAP-ded20478896c, SHD-GAP-2f41bc860ca5, SHD-GAP-bfa31bc63402, SHD-GAP-ff5526c24a0a, SHD-GAP-d98d1e5b3960, SHD-GAP-ed137c7c0e59, SHD-GAP-958a8a78c733, SHD-GAP-f894f535c0ab, SHD-GAP-0cf896e751cc, SHD-GAP-4d12e82d090a, SHD-GAP-8157f9ce6b45, SHD-GAP-c32d64ac8e9e, SHD-GAP-24f0d1e14788, SHD-GAP-419dab8450a5, SHD-GAP-860b13559611, SHD-GAP-fdb2cf082dcf, SHD-GAP-dd54b7cdfab2, SHD-GAP-f388c20d174f, SHD-GAP-129eb9ddd1f1, SHD-GAP-c4560fc85c74, SHD-GAP-f136858441df, SHD-GAP-24168a5f3802, SHD-GAP-9fe3b342f71c, SHD-GAP-605a0933251f, SHD-GAP-231cd468fa33, SHD-GAP-3416ca643cfa, SHD-GAP-5f6862e3f9a6, SHD-GAP-71579ee8dcf7, SHD-GAP-24783ef555bd, SHD-GAP-144ae08b07c8, SHD-GAP-6f3270ace0d5, SHD-GAP-7203d3816f6c, SHD-GAP-03203833189a, SHD-GAP-4dc87dd79ba3, SHD-GAP-33fc16602fd2, SHD-GAP-b37941696192, SHD-GAP-0003c2539352, SHD-GAP-15b735633abb, SHD-GAP-e7e6bcee4459, SHD-GAP-96959eeba2f9, SHD-GAP-fc1e27a21d13, SHD-GAP-01e9113e59d4, SHD-GAP-bc1fd425aaa1, SHD-GAP-3579e4ab3776, SHD-GAP-92174104ab33, SHD-GAP-5b44312ca208, SHD-GAP-126c926d48a5, SHD-GAP-bf81b6aa8b4f, SHD-GAP-b2e9b6f6f9f1, SHD-GAP-d228f743b37b, SHD-GAP-45f47b3d4a25, SHD-GAP-60e425bb760a, SHD-GAP-aaf6d901e6c2, SHD-GAP-36b3b980e0f1, SHD-GAP-7bf571e27b65, SHD-GAP-ccec528e2180, SHD-GAP-7af5de3581f3, SHD-GAP-2204f21da15a, SHD-GAP-b6e4f1215916, SHD-GAP-7f1db7c3bf11, SHD-GAP-414bceac354f, SHD-GAP-65cc39e66479, SHD-GAP-d466b2c983c4, SHD-GAP-a43b00257377, SHD-GAP-29cabea84aa8, SHD-GAP-b6ff25c7639a, SHD-GAP-2e6cd4714d4e, SHD-GAP-c714d4db0cc3, SHD-GAP-460313e7f038, SHD-GAP-a8eeed50aa5a, SHD-GAP-8cfed4453182, SHD-GAP-05eed7ae632d, SHD-GAP-79e77dc83655, SHD-GAP-8b5bb7b98952, SHD-GAP-6e4a20ca3511, SHD-GAP-276bd4b673ad, SHD-GAP-304fb536cde1, SHD-GAP-949cc0de5d3e, SHD-GAP-8b7451564048, SHD-GAP-cd16253e5519, SHD-GAP-23c70c3cbaf6, SHD-GAP-b6bd02c2a0bf, SHD-GAP-36357e4670d8, SHD-GAP-21f8fc6d3da2, SHD-GAP-2d4ca0d83de6, SHD-GAP-a60ac1dc260c, SHD-GAP-21ea5251694b, SHD-GAP-633ad7e8e3ad, SHD-GAP-905695e3547a, SHD-GAP-6738275046ab, SHD-GAP-b5c60d976248, SHD-GAP-a0d38fc0bfe0, SHD-GAP-769755b9191d, SHD-GAP-4d4a436493f4, SHD-GAP-f90c812892f0, SHD-GAP-4857bf02b3b8, SHD-GAP-103712d0e41e, SHD-GAP-24d50b21847b, SHD-GAP-decfce96ad1f, SHD-GAP-5f3c98157787, SHD-GAP-0c6660bdf1ce, SHD-GAP-eeab0eb8d2cf, SHD-GAP-3434557bfdc7, SHD-GAP-22ce24589ede, SHD-GAP-729d4f89e611, SHD-GAP-cf9bece9276b, SHD-GAP-241e1e83883b, SHD-GAP-cb12eb6e5647, SHD-GAP-8bada0f267b3, SHD-GAP-4c4aa0bc1cc2, SHD-GAP-75a460515437, SHD-GAP-c2d27c3d02eb, SHD-GAP-6ed20f94d4f0, SHD-GAP-bf969507f6f9, SHD-GAP-fc385854e446, SHD-GAP-6c68afc2dcef, SHD-GAP-62c8af6b9bf8, SHD-GAP-dc7b07e42eea, SHD-GAP-83fccda23a37, SHD-GAP-d978412197c1, SHD-GAP-592ddc9d5d7c, SHD-GAP-164fc8714992, SHD-GAP-be482afc8008, SHD-GAP-c043925c7580, SHD-GAP-25ff82f40a7d, SHD-GAP-182af19edb92, SHD-GAP-ea426fa35af1, SHD-GAP-59ed7ddc371a, SHD-GAP-b9db26e7ffe0, SHD-GAP-9a9ee3d58aeb, SHD-GAP-a6c32a9e84de, SHD-GAP-5af256a67581, SHD-GAP-e18d778fb2cd, SHD-GAP-b10fe42ce05b, SHD-GAP-f0df0940c6bb, SHD-GAP-676e4356a8d5, SHD-GAP-8be98164b9e7, SHD-GAP-99ab31effec7, SHD-GAP-fab4f1cd5b8b, SHD-GAP-fe51dda6620f, SHD-GAP-90955760e950, SHD-GAP-3a05d724f49f, SHD-GAP-a603d5d4b94c, SHD-GAP-fdbacb4b7c55, SHD-GAP-d434790646d5, SHD-GAP-6a2a0860debf, SHD-GAP-826e27162e2f, SHD-GAP-97c3bbf27cdb, SHD-GAP-2f3d9c41d6f3, SHD-GAP-55b60a4d0f93, SHD-GAP-4ee6c2291074, SHD-GAP-f210911c4524, SHD-GAP-22a1dbfc5900, SHD-GAP-5849353c759e, SHD-GAP-b166745b17b3, SHD-GAP-b048af93a8e4, SHD-GAP-11e26ddfde2d, SHD-GAP-1319c04dc2bc, SHD-GAP-5e4bca591be9, SHD-GAP-2789a7973a75, SHD-GAP-5936cc27a4da, SHD-GAP-335292086fe4, SHD-GAP-31485ad2fa9b, SHD-GAP-4b095ef15393, SHD-GAP-cc20354e995a, SHD-GAP-3842a9f0f58b, SHD-GAP-e391094b8b8f, SHD-GAP-00d733061b09, SHD-GAP-261f9506fced, SHD-GAP-7aef7ced075f, SHD-GAP-d808174a8aee, SHD-GAP-3c11f6031d95, SHD-GAP-09c7b640fb5a, SHD-GAP-1e4d324f32dd, SHD-GAP-437bcd0c34a7, SHD-GAP-b98567af8b92, SHD-GAP-2e60fe1b8b2b, SHD-GAP-f811cd92ba9c, SHD-GAP-faa6d9edf355, SHD-GAP-778d1a113161, SHD-GAP-eca5359ebce9, SHD-GAP-714d42c64249, SHD-GAP-8117fe58189e, SHD-GAP-59fb7b9bed56, SHD-GAP-da177dbbf51d, SHD-GAP-900e4bc2b2fa, SHD-GAP-5bd66d8ced2c, SHD-GAP-630995d9699e, SHD-GAP-bcf8d57a71e8, SHD-GAP-d7ac7fe21dba, SHD-GAP-99095a829895, SHD-GAP-bd14c07b48ca, SHD-GAP-c5c974364fee, SHD-GAP-d88f5d80307d, SHD-GAP-9fba1801f432, SHD-GAP-42fe8642ce8b, SHD-GAP-409a88923fdd, SHD-GAP-902bd0cd7faa, SHD-GAP-6978f041f4a4, SHD-GAP-6e84036554f6, SHD-GAP-9cd514a98721, SHD-GAP-80dffe79a141, SHD-GAP-5110c3c55144, SHD-GAP-75247c076f18, SHD-GAP-f8701a6ce9f2, SHD-GAP-ed5ff9e53ac0, SHD-GAP-1b3760844fbd, SHD-GAP-e17975b09946, SHD-GAP-0014e0faf931, SHD-GAP-e411dcdedfeb, SHD-GAP-b1076ed2ceb1, SHD-GAP-8ee192a5a1d3, SHD-GAP-f41b91fa0252, SHD-GAP-3534ca2822aa, SHD-GAP-1d317cc50e77, SHD-GAP-1c3f32abf6ad, SHD-GAP-c5e75153b4a7, SHD-GAP-c68ab73fc6b1, SHD-GAP-6c40a1377780, SHD-GAP-ac24f6a3712b, SHD-GAP-f305e763dab8, SHD-GAP-7b168a65d739, SHD-GAP-b758db39978d, SHD-GAP-7db0356386ba

## PLEASURE (G-34) — placer estadistico
- events: 1836 (successes 1824) · emissions: 1838 (milestone 33 · rpe 1805) · milestones: 33 · total magnitude: 51.022448
- units: evaluate, gate_run
- current streaks: evaluate=653 gate_run=44
- 2026-10-10T17:38:38Z [rpe 0.006266 rpe] unit=evaluate streak=649 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-10T17:40:25Z [rpe 0.006265 rpe] unit=evaluate streak=650 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-10T17:40:57Z [rpe 0.006264 rpe] unit=evaluate streak=651 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-10T17:41:00Z [rpe 0.006263 rpe] unit=evaluate streak=652 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-10T17:41:19Z [rpe 0.006262 rpe] unit=evaluate streak=653 — evaluate truth=TRUE cert=True source=op:AND

## Delta vs previous report
- previous: `2026-10-09T15:48:35Z` (fp a773d2564cde621e)
- focus refs added: (none)
- focus refs removed: (none)
- ledger totals delta: {'decisions': 0, 'findings': 0, 'guards': 0, 'claims': 0, 'certs': 0}
- commits since previous: 9
