# Evolution report — EVOLUTION-2026-10-11

- generated_at: `2026-10-11T17:45:12Z`
- since: `2026-10-10T17:44:13Z`
- fingerprint: `b26394908eaf54ed`

## Commits since
- `42d8a3f` 2026-10-11T12:08:01-03:00 — feat(epistemic-graph): fase-3d puente al plan integrado (bridge view)
- `8348353` 2026-10-11T11:49:43-03:00 — feat(epistemic-graph): fase-3c decisiones topologia (enmienda ratified)
- `642524f` 2026-10-11T11:24:47-03:00 — feat(epistemic-graph): fase-3b motor de descubrimiento (discovery queue)
- `4b8ddc2` 2026-10-11T10:53:41-03:00 — feat(epistemic-graph): fase-3a baseline topologico + ratificacion plan fase-3
- `92805d5` 2026-10-11T09:53:21-03:00 — docs(plans): grafo epistemico fase-3 — plan formal con fundamentos matematicos (descubrimiento de aristas)
- `0733766` 2026-10-11T03:53:08-03:00 — docs(plans): plan integrado de ejecucion (pre-voslab VSF + vOSlab) — inventario + provenance para triage S5
- `0b4e6b3` 2026-10-11T03:29:20-03:00 — fix(kernel): flake suite 239MB tree_traces — rotación por bytes + aislamiento tests; fix gate_suite _cleanup directorios
- `a3f77ea` 2026-10-11T00:51:47-03:00 — docs(analysis): NB05 — 'Pendiente S5 epistemic_graph/FASE-2' -> RESUELTO, pointer a NB08
- `096a828` 2026-10-10T22:57:55-03:00 — feat(epistemic-graph): S5 — retiro 12 canon mirrors + FASE-2 grafo (10 aristas) + recalib models
- `9ff1d06` 2026-10-10T21:57:02-03:00 — feat(epistemic-graph): S5 — cola 70/70 local-wins + D3/D4 ratificados + MVP + NB08 + Fierro Q1-Q3
- `9bc985b` 2026-10-10T19:21:41-03:00 — feat(doc-tracking): F5 — verify_docs.py + changelog + cola 70 modified (QUEUE-EXEC CERRADO)
- `a839a16` 2026-10-10T18:13:18-03:00 — fix(gap-resolver): F4 B2 — detector SYNTAX_ERROR via esbuild (falso+ .ts cerrado)

## Ledgers
- **decisions**: total=21 new=0 no_ts=2 (ts=ts)
- **findings**: total=50 new=0 no_ts=0 (ts=ts)
- **guards**: total=26 new=0 no_ts=0 (ts=ts)
- **claims**: total=216 new=0 no_ts=213 (ts=declared_at)
- **certs**: total=31 new=0 no_ts=0 (ts=observed_at)

## Focus
- entries: 57
- active: (none)
- changed: `GRAPH-EPISTEMIC-MVP-2026-10-10` -> done @ 2026-10-11T00:35:40Z
- changed: `QUEUE-EXEC-2026-10-08` -> done @ 2026-10-10T21:47:24Z
- changed: `CANON-RETIRE-2026-10-11` -> done @ 2026-10-11T01:45:40Z
- changed: `GRAPH-FASE2-2026-10-11` -> done @ 2026-10-11T01:45:40Z
- changed: `PLAN-INTEGRADO-2026-10-11` -> done @ 2026-10-11T06:50:11Z
- changed: `GRAPH-FASE3-PLAN-2026-10-11` -> done @ 2026-10-11T14:15:18Z
- changed: `GRAPH-FASE3-3B-2026-10-11` -> done @ 2026-10-11T14:15:18Z
- changed: `GRAPH-FASE3-3C-2026-10-11` -> done @ 2026-10-11T14:48:02Z
- changed: `GRAPH-FASE3-3D-2026-10-11` -> done @ 2026-10-11T15:07:23Z
- changed: `NB12-NB13-VISUALIZATION-2026-10-11` -> done @ 2026-10-11T17:41:44Z

## Snapshots
- days: 2026-10-10, 2026-10-11
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
- entries: total=3187 new=537 blocked-by-bounds=282 aligned=282
- kinds: aligned-blocked=282 would-run-deferred=255
- new: `SHD-GAP-fc9345b2fe27` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-66f8b263da2b` [would-run] src=gap-resolver action={"gap":"patch-detection","decision":"CONFLICT_PATCH","actions":["ALERT: Patch ha
- new: `SHD-GAP-5d428dc55571` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-04de27b1ffdb` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"SYNTAX_ERROR","actions":["BLOCK: Syntax error
- new: `SHD-GAP-454f2b91d15c` [would-run] src=gap-resolver action={"gap":"conflict-detection","decision":"FUNCTION_OVERLAP","actions":["ALERT: Fun
- new: `SHD-GAP-07120c15b7f6` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-5d2a6ef78cc4` [would-run] src=gap-resolver action={"gap":"patch-detection","decision":"STALE_PATCH","actions":["ALERT: Patch is st
- new: `SHD-GAP-7657a46b9bd3` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-a57dc733a05e` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"QUALITY_OK","actions":["OK"]}
- new: `SHD-GAP-33c25d56f9d7` [BLOCKED] src=gap-resolver action={"gap":"conflict-detection","decision":"UNKNOWN","actions":["OK"]}
- divergences: total=255 explained=255 unexplained=0
- explained: `SHD-GAP-fc9345b2fe27` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-66f8b263da2b` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-04de27b1ffdb` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-454f2b91d15c` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-07120c15b7f6` via class:RX-DEFERRED-SEMI-AUTO
- guard-would-have-blocked: SHD-GAP-5d428dc55571, SHD-GAP-7657a46b9bd3, SHD-GAP-33c25d56f9d7, SHD-GAP-d203af881f09, SHD-GAP-612d4547bbcb, SHD-GAP-9a2427d77b93, SHD-GAP-eb723ba43cc1, SHD-GAP-8921f882166b, SHD-GAP-bef9f7e6f4a0, SHD-GAP-3774836c49cf, SHD-GAP-99df303026d6, SHD-GAP-4f620509ed37, SHD-GAP-877a8d0b5dfd, SHD-GAP-cf7247a012af, SHD-GAP-34ce7ed2b882, SHD-GAP-4f778e7a2cab, SHD-GAP-6102da6f8497, SHD-GAP-02a31c673547, SHD-GAP-d4314e77214b, SHD-GAP-5a68c153d620, SHD-GAP-eda3b0656ac7, SHD-GAP-bc50c335d7b9, SHD-GAP-caa17a34fa4d, SHD-GAP-b9fd47d04da0, SHD-GAP-1260fcc0c73b, SHD-GAP-38690eda281a, SHD-GAP-c35f46359b61, SHD-GAP-27317620dd92, SHD-GAP-a82cd6694a85, SHD-GAP-2a695aa176a9, SHD-GAP-8847959e4961, SHD-GAP-ead06b3baa15, SHD-GAP-7fdb704d772f, SHD-GAP-0ff3cb201655, SHD-GAP-ffee2715738f, SHD-GAP-19d560eee9f0, SHD-GAP-151c9107505d, SHD-GAP-ba0da68d8d16, SHD-GAP-c33772dfe116, SHD-GAP-9c26b4dd45ea, SHD-GAP-2a35ff353efd, SHD-GAP-1ea70311a295, SHD-GAP-cd9cf576b96c, SHD-GAP-57e44571bf23, SHD-GAP-26c8ac9051d6, SHD-GAP-855b607d99ce, SHD-GAP-93c5777a23e2, SHD-GAP-c274c4dca664, SHD-GAP-0c922c46279d, SHD-GAP-bb4718d66aba, SHD-GAP-a53314c4cbfe, SHD-GAP-97c40ed7948e, SHD-GAP-f05287fca860, SHD-GAP-42932a5b856c, SHD-GAP-f0e399900170, SHD-GAP-d12cdd1d48ce, SHD-GAP-2028c4ae9911, SHD-GAP-67e28de2ea59, SHD-GAP-243629eea724, SHD-GAP-92b7a25f30bf, SHD-GAP-0a8604a8f8fb, SHD-GAP-1ddf23bb9dcb, SHD-GAP-5a522c574a82, SHD-GAP-aa17f23fd7f7, SHD-GAP-fa62649c0f17, SHD-GAP-4344ac9f63c3, SHD-GAP-101c38186a09, SHD-GAP-7b64e8620b80, SHD-GAP-5ffdcaf96998, SHD-GAP-4a8a34fb9a80, SHD-GAP-0fc7d2415294, SHD-GAP-00bda9ff9c99, SHD-GAP-ffba50550787, SHD-GAP-cf23ffff2265, SHD-GAP-3229d61c524a, SHD-GAP-f1d6415ddbd5, SHD-GAP-fd8f7094efa7, SHD-GAP-bcee291c8dce, SHD-GAP-67c7eb566f7c, SHD-GAP-dcdd54ba6386, SHD-GAP-3dd8cb65a671, SHD-GAP-0dbfb8694350, SHD-GAP-a17d3393210b, SHD-GAP-580f1271f425, SHD-GAP-4671a54cf8ed, SHD-GAP-f2a29bda8f00, SHD-GAP-f1766fedc4e8, SHD-GAP-d3a6390d91ad, SHD-GAP-157c21f5c91e, SHD-GAP-18f0ee234573, SHD-GAP-8425516201a2, SHD-GAP-364ca0feb61f, SHD-GAP-9913c875a8b3, SHD-GAP-084f75f44b08, SHD-GAP-71a550530948, SHD-GAP-f83294e0ac30, SHD-GAP-cc595e7ccfaa, SHD-GAP-812e100ad56c, SHD-GAP-3e2bc270c45c, SHD-GAP-f46922203830, SHD-GAP-fd5d606c1048, SHD-GAP-4c05ba4bc0dc, SHD-GAP-9d1ac6f1f6ba, SHD-GAP-5aa14296aa58, SHD-GAP-f4c2ec315ffc, SHD-GAP-9a1957eb4631, SHD-GAP-6ec80d2e2c01, SHD-GAP-339db64d6919, SHD-GAP-6abb7f530712, SHD-GAP-1b74ca89b2de, SHD-GAP-b5ee55da275d, SHD-GAP-ab8cc22649b8, SHD-GAP-b19bc7576d2a, SHD-GAP-aeee70e5471e, SHD-GAP-7e67a08996d7, SHD-GAP-e51a3a84cd5d, SHD-GAP-9ce15ad88920, SHD-GAP-ceee10536dd0, SHD-GAP-96abdee1c957, SHD-GAP-ce2ddab4f6c8, SHD-GAP-1be0a1cf4821, SHD-GAP-129c941cb407, SHD-GAP-e5794e580473, SHD-GAP-987460c363ea, SHD-GAP-064ba756f4de, SHD-GAP-daa8d878d531, SHD-GAP-8221b65292ff, SHD-GAP-75e83660d5d0, SHD-GAP-44603f5e14e7, SHD-GAP-1d83f8a584e0, SHD-GAP-a215abad7297, SHD-GAP-e1debb8d4dcd, SHD-GAP-cc38dc1e8db1, SHD-GAP-86ece84b49a8, SHD-GAP-136a1dbfc535, SHD-GAP-bf0204e01b34, SHD-GAP-ec9e46f15019, SHD-GAP-473a3102799c, SHD-GAP-af902ad2770e, SHD-GAP-58313b67141f, SHD-GAP-dec6ec618157, SHD-GAP-02054dc97124, SHD-GAP-11d3f42a055a, SHD-GAP-56fb50cf77d8, SHD-GAP-ba6c5b5a5444, SHD-GAP-842a802bdc5d, SHD-GAP-befa024f648e, SHD-GAP-bac6ac8d0030, SHD-GAP-44e42d57e0b3, SHD-GAP-4ba156f55892, SHD-GAP-54d4373b6040, SHD-GAP-44d612ab542e, SHD-GAP-4a72750e152d, SHD-GAP-4eb794f2896a, SHD-GAP-72cdb914686f, SHD-GAP-9cc8bf4bee90, SHD-GAP-7d129e0cb727, SHD-GAP-c917fe8a075f, SHD-GAP-756f37f7e57d, SHD-GAP-a54ffa0e6c33, SHD-GAP-a4c026eea44d, SHD-GAP-6d5324b5a47e, SHD-GAP-5be787e29fa9, SHD-GAP-20aff195c212, SHD-GAP-311fc221074d, SHD-GAP-d521f11da656, SHD-GAP-599000188355, SHD-GAP-eb5074b2d3e9, SHD-GAP-0e8858eae4a4, SHD-GAP-9e5d7a59f64e, SHD-GAP-b35466599c69, SHD-GAP-eb6cfd96a4db, SHD-GAP-37a6f38b64d5, SHD-GAP-605c579e31fb, SHD-GAP-85a29cb8c968, SHD-GAP-110a92e0d7f0, SHD-GAP-bd040b1231a3, SHD-GAP-f1501bbde85e, SHD-GAP-586087cf0d86, SHD-GAP-2452b728d779, SHD-GAP-91f661410df8, SHD-GAP-6933b03dabfa, SHD-GAP-275410f30a21, SHD-GAP-00589dbdfb3a, SHD-GAP-177649212e38, SHD-GAP-05cbb44ab861, SHD-GAP-b07200ae13f6, SHD-GAP-32afe700f16f, SHD-GAP-c8f67a6fedfa, SHD-GAP-4e7cf84683bd, SHD-GAP-0faef4d3390f, SHD-GAP-c801bd8e73cf, SHD-GAP-926ef1a35bbb, SHD-GAP-c4000b223a46, SHD-GAP-5681df20bf02, SHD-GAP-6e40d5a174ae, SHD-GAP-bbe1d2135b59, SHD-GAP-daba91c6798b, SHD-GAP-006f3cf9bba1, SHD-GAP-505d7a93b60b, SHD-GAP-59e4e8d83008, SHD-GAP-2688ab26c871, SHD-GAP-848075a7e9c0, SHD-GAP-a3b224ff67de, SHD-GAP-991c650793a9, SHD-GAP-2af8ba113d2e, SHD-GAP-cc70f5a18cd7, SHD-GAP-66812895d2d3, SHD-GAP-ce90496abfa2, SHD-GAP-f002deffa60a, SHD-GAP-752ee7b18e91, SHD-GAP-a9fc09d31174, SHD-GAP-94eebbd8fcf4, SHD-GAP-29be9d7f74f6, SHD-GAP-09daef4c73d4, SHD-GAP-6986e20a470b, SHD-GAP-cd9b6a97df3e, SHD-GAP-7451b65c8ba1, SHD-GAP-000d5b1fe15c, SHD-GAP-84045367abfc, SHD-GAP-86c6f8578deb, SHD-GAP-cbb75dd1f62a, SHD-GAP-ccb37524f8ea, SHD-GAP-71c87f9b7e37, SHD-GAP-4f2e22f13da5, SHD-GAP-aa91a31883c7, SHD-GAP-2ee71eaf974c, SHD-GAP-15d900317f40, SHD-GAP-858e95770b50, SHD-GAP-b8ad4b01de12, SHD-GAP-63fdbe7d5fe9, SHD-GAP-acfa9117cac6, SHD-GAP-fd05868e023f, SHD-GAP-ec87057fea95, SHD-GAP-ab73367f1b48, SHD-GAP-77e60f3e9a9c, SHD-GAP-cc61eb89d96f, SHD-GAP-48ad3cbc2b91, SHD-GAP-ed9311d06109, SHD-GAP-ea4840f0bf77, SHD-GAP-f98d5a6669fc, SHD-GAP-aabc2c8fa017, SHD-GAP-ff72fcb3b9cf, SHD-GAP-7917fb9fdcce, SHD-GAP-bfcb1e7f079b, SHD-GAP-9c866a26acbd, SHD-GAP-e40931f85be9, SHD-GAP-09a431e438cf, SHD-GAP-2dc90ba8837c, SHD-GAP-3a36d4a8fa6b, SHD-GAP-6c3d96ee44e1, SHD-GAP-1a82925767b3, SHD-GAP-c3cc2bf8f1d0, SHD-GAP-f6321ea88fd9, SHD-GAP-1784866f6c3b, SHD-GAP-4ee6bb13b24d, SHD-GAP-fc784dde813c, SHD-GAP-6258fdb9804d, SHD-GAP-0ecd0ea66d2b, SHD-GAP-69cf07ed2470, SHD-GAP-7398c3a62d28, SHD-GAP-fbb9624f2401, SHD-GAP-1180ecf0cede, SHD-GAP-46c3c948d4cb, SHD-GAP-ae4a8cce4099, SHD-GAP-0e2810133236, SHD-GAP-a7582bd634da, SHD-GAP-a10d89aa7d22, SHD-GAP-a582f1cd9a52, SHD-GAP-f66d9ad990ec, SHD-GAP-b0bdb206360a, SHD-GAP-34d61a98cceb, SHD-GAP-67c4572c6a6c, SHD-GAP-9dc3cfa0a799, SHD-GAP-284702491b7b, SHD-GAP-74a80fc0a61d, SHD-GAP-f83b8934cfd9, SHD-GAP-d1d0984d1a23, SHD-GAP-01910745ba1c, SHD-GAP-203935a862c2, SHD-GAP-8ff3b1ac8f7b, SHD-GAP-c8511e053ac5

## PLEASURE (G-34) — placer estadistico
- events: 2079 (successes 2077) · emissions: 2077 (milestone 17 · rpe 2060) · milestones: 17 · total magnitude: 49.189917
- units: evaluate, gate_run, unit_x
- current streaks: evaluate=646 gate_run=53 unit_x=9
- 2026-10-11T17:42:47Z [rpe 0.004896 rpe] unit=evaluate streak=641 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-11T17:42:50Z [rpe 0.004895 rpe] unit=evaluate streak=643 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-11T17:43:15Z [rpe 0.004895 rpe] unit=evaluate streak=644 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-11T17:43:18Z [rpe 0.004894 rpe] unit=evaluate streak=645 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-11T17:43:29Z [rpe 0.004893 rpe] unit=evaluate streak=646 — evaluate truth=TRUE cert=True source=op:AND

## Delta vs previous report
- previous: `2026-10-10T17:44:13Z` (fp 83df1a94ce39b001)
- focus refs added: (none)
- focus refs removed: ['QUEUE-EXEC-2026-10-08']
- ledger totals delta: {'decisions': 0, 'findings': 0, 'guards': 0, 'claims': 66, 'certs': 0}
- commits since previous: 12
