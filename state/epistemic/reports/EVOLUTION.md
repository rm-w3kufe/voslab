# Evolution report — EVOLUTION-2026-10-07

- generated_at: `2026-10-07T15:27:27Z`
- since: `2026-10-06T15:25:50Z`
- fingerprint: `31ddb87a3796bb6e`

## Commits since
- `692fb7f` 2026-10-07T11:33:10-03:00 — docs(boot): focus D-29-POSTRESTART — (c) VERIFIED, (e) evidencia lista, esperando S5
- `8106ea1` 2026-10-07T11:17:08-03:00 — fix(gates): gate-5 dirty excludes 2 runtime auto-appends mas (D-24 rationale +2)
- `a4d94cc` 2026-10-07T10:11:52-03:00 — fix(boot): re-pin 4 artefact hashes + timestamps de codigo + D-30/D-31
- `02af773` 2026-10-07T09:43:53-03:00 — docs(close): session cierre — D-29 idle chain verificada en vivo
- `0c2c639` 2026-10-07T09:32:20-03:00 — feat(f5): serve on-demand CLI live + decisiones de cola registradas
- `c246b71` 2026-10-07T04:47:44-03:00 — feat(f5): recall/FTS con sanitización + ronda completa de reparación
- `ecfbbbf` 2026-10-07T01:40:10-03:00 — docs(plans): R-4 RATIFICADO (a) por S5 — F5 pasa a ready
- `dee8231` 2026-10-07T01:01:49-03:00 — docs(plans): R-4 lote-2 entregado — 5 refs X1..X5 + sanitizacion F5
- `c10564d` 2026-10-07T00:22:28-03:00 — feat(distill): R-3 distill O-6 propose-only — log + cache + veto S5
- `ee9b8dc` 2026-10-06T23:56:00-03:00 — feat(log): P0+P1 calidad de log — session_id, action cap, detail/duration
- `d6b2cde` 2026-10-06T23:24:53-03:00 — docs: execute R-A — demote 2 AGENTS.md blocks to on-demand skills
- `f0cf06d` 2026-10-06T23:12:35-03:00 — docs(plans): record S5 ratifications R-3/R-A/R-4 + log inspection §11.7
- `59f810c` 2026-10-06T21:49:27-03:00 — docs(plans): close F4 — §11.6 measurement + markers + registry done
- `c0ef006` 2026-10-06T21:39:43-03:00 — fix(boot): refresh tool_integration_bridge hash after F4.2 edit
- `319d430` 2026-10-06T21:26:43-03:00 — docs(findings): F4.3 static-first context audit (§5.3)
- `4aeeff8` 2026-10-06T21:19:19-03:00 — feat(kernel): F4.2 abstention-collapse alarm + census (§6.3)
- `fc2d733` 2026-10-06T21:01:35-03:00 — feat(plugins): F4.1 close-checklist persistence nudge (§6.1)
- `2001e60` 2026-10-06T20:17:35-03:00 — feat(cache): F3b L2 onboard digest view + l2-view NC gate (19->20)
- `308ef71` 2026-10-06T19:53:12-03:00 — feat(cache): F2 L1 versioned state_query cache + l1-cache NC gate (18->19)
- `8e81576` 2026-10-06T18:27:19-03:00 — chore(focus): REFS-OPT-001 F1 done — L0 memo + NC 18, detail updated
- `5969fab` 2026-10-06T18:22:37-03:00 — feat(cache): F1 L0 intra-evaluate memo + l0-memo NC gate (17->18)
- `1778f25` 2026-10-06T17:50:01-03:00 — chore(focus): REFS-OPT-001 F3a done — warm 10.3s contract met (detail local, dir gitignored)
- `d160c5f` 2026-10-06T17:44:12-03:00 — docs(plans): F3a measurement — warm 10.3s < 15s contract met (§11.2)
- `d9bf1b1` 2026-10-06T17:36:05-03:00 — perf(gates): agent-log census memoization + pool width 8 — warm floor cut (F3a <15s)
- `1ba41cf` 2026-10-06T17:18:15-03:00 — perf(gates): ssh ControlMaster multiplexing — warm-run floor cut (F3a contract <15s)
- `5ad3f05` 2026-10-06T16:56:43-03:00 — feat(gates): F3a manifest cache — ALWAYS_COLD partition + dirty bypass + kill switch

## Ledgers
- **decisions**: total=21 new=0 no_ts=2 (ts=ts)
- **findings**: total=50 new=0 no_ts=0 (ts=ts)
- **guards**: total=26 new=0 no_ts=0 (ts=ts)
- **claims**: total=150 new=0 no_ts=147 (ts=declared_at)
- **certs**: total=31 new=2 no_ts=0 (ts=observed_at)
  - new: `CRT-F3A-01`
  - new: `CRT-F3A-02`

## Focus
- entries: 40
- active: benchmarks-phase2-compare, publishing-track
- changed: `S5-REFS-ASSIMILATE-2026-10-06` -> done @ 2026-10-06T16:54:10Z
- changed: `S5-EXTERNAL-PATHS-2026-10-06` -> done @ 2026-10-06T15:34:25Z
- changed: `REFS-OPT-001` -> done @ 2026-10-07T12:48:35Z
- changed: `D-29-POSTRESTART` -> done @ 2026-10-07T15:23:38Z

## Snapshots
- days: 2026-10-06, 2026-10-07
- index rows since: 1

## Battery (anti-pantomima)
- latest: `real_state_battery_2026-10-03.json` — 12/12 checks verdes con ground truth;4 huecos declarados (no esconderlos = parte del exit)
- declared gap: {'id': 'G1-idle-post-fix', 'why': 'post-fix idle dispatch requires an idle event to observe — watched via cycle_health, not proven by this battery'}
- declared gap: {'id': 'G2-guard-live-run', 'why': 'R2 runs audit_guards(run=False): liveness is sampled, not exercised end-to-end in-process'}
- declared gap: {'id': 'G3-doc-manifest-stale', 'why': 'doc-manifest staleness is covered by boot-ontology (R7) only for artifacts it declares'}
- declared gap: {'id': 'G4-claims-cadence', 'why': 'claims/certs cadence is a multi-day property — see evolution report cadence (G-03), not a point-in-time check'}

## Drift
- journal rows: 3, latest_drift_count=6

## Shadow (CC-8.1) — would-be, never executed
- entries: total=1540 new=849 blocked-by-bounds=498 aligned=498
- kinds: aligned-blocked=498 would-run-deferred=351
- new: `SHD-GAP-4fa317a87fec` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-31e8df6de41f` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-81fcfb27e9b1` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-2a525c517708` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-150e74821c07` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-fc52fe7740c9` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-fcf60e55e58e` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-38a5f0bc48e7` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-89a649587210` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-5b39aaceee88` [BLOCKED] src=gap-resolver action={"gap":"patch-detection","decision":"UNKNOWN","actions":["OK"]}
- divergences: total=351 explained=351 unexplained=0
- explained: `SHD-GAP-2e1bb7c68c7f` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-2491ed753957` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-97a874dedb2b` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-dd6148d9f42e` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-c0c1c983d38d` via class:RX-DEFERRED-SEMI-AUTO
- guard-would-have-blocked: SHD-GAP-4fa317a87fec, SHD-GAP-31e8df6de41f, SHD-GAP-81fcfb27e9b1, SHD-GAP-2a525c517708, SHD-GAP-150e74821c07, SHD-GAP-fc52fe7740c9, SHD-GAP-fcf60e55e58e, SHD-GAP-38a5f0bc48e7, SHD-GAP-89a649587210, SHD-GAP-5b39aaceee88, SHD-GAP-dc7ee561b917, SHD-GAP-80107d5a93e3, SHD-GAP-ab0970f92555, SHD-GAP-4856e5cbe1cd, SHD-GAP-85b440caec2a, SHD-GAP-84f1c31272dd, SHD-GAP-e09facc6f88a, SHD-GAP-481e8bb9fb2d, SHD-GAP-d3f50d956f72, SHD-GAP-701f983235ab, SHD-GAP-ca7aa5c897e4, SHD-GAP-e99ab7911950, SHD-GAP-e1e01e4954df, SHD-GAP-b01fb641a9db, SHD-GAP-763c39149e57, SHD-GAP-e51a0fe8c3e3, SHD-GAP-5b28a7dccf80, SHD-GAP-121b99cd60a5, SHD-GAP-8e754d0dc3e5, SHD-GAP-8d3fc2088e8f, SHD-GAP-e454e31f4768, SHD-GAP-98b73cfccce5, SHD-GAP-1f2e8bcb63eb, SHD-GAP-ce9e85b58712, SHD-GAP-5d6ae51251be, SHD-GAP-f0b75cb2d7b3, SHD-GAP-32d91d46a170, SHD-GAP-84207d33dce2, SHD-GAP-fadce1d4844e, SHD-GAP-37bbfaeca9cd, SHD-GAP-581899ae58c5, SHD-GAP-58752a77eefe, SHD-GAP-fe54b3aa8dcf, SHD-GAP-1a73a04ef710, SHD-GAP-2fface8cc664, SHD-GAP-b8198696edcd, SHD-GAP-d6e5575bcb61, SHD-GAP-779e50a739cd, SHD-GAP-33d9df3a9cef, SHD-GAP-8baf2b69d624, SHD-GAP-f1f7fe5270f0, SHD-GAP-d2c1c690a963, SHD-GAP-2a3309f93a7b, SHD-GAP-7b9a86ef4277, SHD-GAP-5acec3a34c7f, SHD-GAP-9417c8fb8ac7, SHD-GAP-53838e4f1deb, SHD-GAP-bd0b77d25bf7, SHD-GAP-4c35ac152e35, SHD-GAP-b1dd0b3d4ac3, SHD-GAP-e571db55d45b, SHD-GAP-c22383c2bfcf, SHD-GAP-657ff34f5759, SHD-GAP-14e8c4cb1e4c, SHD-GAP-4bbd5a42bd87, SHD-GAP-c7e8824fdd27, SHD-GAP-c01779dee05e, SHD-GAP-73fd39dbe833, SHD-GAP-1dfbc91cb659, SHD-GAP-aa8f886def77, SHD-GAP-4e887b11117a, SHD-GAP-3f8d45e5872b, SHD-GAP-23943b596549, SHD-GAP-61aecdb83370, SHD-GAP-1175ca2cba93, SHD-GAP-09f12d387779, SHD-GAP-02647b3c514d, SHD-GAP-8f628cfac573, SHD-GAP-42ddfa13747b, SHD-GAP-344b0c056bf0, SHD-GAP-10926a533933, SHD-GAP-5a55e18951c2, SHD-GAP-7d527a5225f9, SHD-GAP-7cb7bb788b6b, SHD-GAP-d56805570a10, SHD-GAP-17ecaecdee8c, SHD-GAP-13047cc2c89b, SHD-GAP-b175b690824d, SHD-GAP-63eff5ab717c, SHD-GAP-772bf1dfe64d, SHD-GAP-6375572b480c, SHD-GAP-1805f29ce784, SHD-GAP-9e33410e7f94, SHD-GAP-045c2c8f871d, SHD-GAP-ffc1e16ae50f, SHD-GAP-8c232d235889, SHD-GAP-6ea63076b239, SHD-GAP-5d30eb20519c, SHD-GAP-8a081870d994, SHD-GAP-3bba682771af, SHD-GAP-e05edc491771, SHD-GAP-9ac524070654, SHD-GAP-d6c05ce16636, SHD-GAP-ed525c8defc7, SHD-GAP-721c55ecac88, SHD-GAP-d253ac0192b0, SHD-GAP-45fd4eac7878, SHD-GAP-f1e05ad6c350, SHD-GAP-c776219efa33, SHD-GAP-76255d469e15, SHD-GAP-fc33ce9fa82b, SHD-GAP-f351601d8e50, SHD-GAP-b41cb0d18efe, SHD-GAP-a5efaa445765, SHD-GAP-ad033649a347, SHD-GAP-faed3cee0110, SHD-GAP-2eb726d2daf7, SHD-GAP-b4869d478bd3, SHD-GAP-b758c75000be, SHD-GAP-0d749c06e007, SHD-GAP-953f010b30b2, SHD-GAP-9da207c3e994, SHD-GAP-82d5e480c685, SHD-GAP-1c44d21b025b, SHD-GAP-81ddcb6d0d6d, SHD-GAP-8519f7d91d0a, SHD-GAP-7a747b236684, SHD-GAP-1776c3c0f545, SHD-GAP-9be68cdeb318, SHD-GAP-36ea93b3f223, SHD-GAP-241c6cf96ecf, SHD-GAP-ac222ed749d4, SHD-GAP-914fd6dbdf6c, SHD-GAP-5385ca5dce84, SHD-GAP-6db723ecdfdd, SHD-GAP-c30a57f5d695, SHD-GAP-88999a413e3e, SHD-GAP-3d317c576451, SHD-GAP-7b4f80e38260, SHD-GAP-11d9b22d1dd6, SHD-GAP-9ed0ec834b93, SHD-GAP-e13d1b365107, SHD-GAP-68cbeec77b4d, SHD-GAP-5e48ecb1991c, SHD-GAP-7b3ad9cedb2a, SHD-GAP-136a7cb4a54e, SHD-GAP-a886a3a0d4a2, SHD-GAP-cd4800666736, SHD-GAP-e0ba5c05627a, SHD-GAP-777d83553c7d, SHD-GAP-78933c9ddd0f, SHD-GAP-db4167e29b1b, SHD-GAP-64276bc8dcfc, SHD-GAP-09f58f870d47, SHD-GAP-207c52e50ea1, SHD-GAP-a63565c39393, SHD-GAP-2f7256ac3336, SHD-GAP-dd03be7f1380, SHD-GAP-6d0a19027087, SHD-GAP-9d367184567a, SHD-GAP-0d976f97ac1c, SHD-GAP-4d4178cb6ceb, SHD-GAP-4abe254ec89d, SHD-GAP-a86db4877762, SHD-GAP-4a5a218ad66a, SHD-GAP-649a43588647, SHD-GAP-9452a48e4df7, SHD-GAP-308e11dd9161, SHD-GAP-498d144cf790, SHD-GAP-0311b5fa4fcb, SHD-GAP-500a382b10e3, SHD-GAP-b32411a3b6bd, SHD-GAP-657acbda16a7, SHD-GAP-0a0f02c97530, SHD-GAP-2a32dfdd8912, SHD-GAP-85fc379cac10, SHD-GAP-938d1e1ef8db, SHD-GAP-00025f0c82dd, SHD-GAP-9c9372ea7a9c, SHD-GAP-04917bdb9576, SHD-GAP-00a74eab1c99, SHD-GAP-1525fa7fac23, SHD-GAP-8ef2a51a09b1, SHD-GAP-8524e01e2af3, SHD-GAP-ff9050963c9b, SHD-GAP-60b42c6a5468, SHD-GAP-a6853575af1c, SHD-GAP-7039e10875c9, SHD-GAP-e0080e655427, SHD-GAP-c5399c2a98a2, SHD-GAP-0b9f3a2586cf, SHD-GAP-f0204272e4fb, SHD-GAP-a27a0de137ef, SHD-GAP-835a8133130a, SHD-GAP-224148f3bb26, SHD-GAP-240ce10bedcf, SHD-GAP-fc9462e2b533, SHD-GAP-10a44bfe8d25, SHD-GAP-77d4f1242316, SHD-GAP-958327537897, SHD-GAP-4a8585a584aa, SHD-GAP-4f8717045b55, SHD-GAP-542ce4905d0a, SHD-GAP-a9f3b0133d20, SHD-GAP-78729d7d1d44, SHD-GAP-99268afe056b, SHD-GAP-8f28da4aa29a, SHD-GAP-f0adec60aa1b, SHD-GAP-bd3f53b20bf2, SHD-GAP-6b6903137747, SHD-GAP-eeb200431773, SHD-GAP-5e70ec56a309, SHD-GAP-c00e74dcacec, SHD-GAP-5e3d5b201e25, SHD-GAP-0e0cb4fcae75, SHD-GAP-75fe3934519e, SHD-GAP-4aeaedbd8ffd, SHD-GAP-5874c2276c77, SHD-GAP-0cc8cc330a95, SHD-GAP-ca2a0cb23f07, SHD-GAP-33bf2be6fafc, SHD-GAP-3af9c5ae6857, SHD-GAP-f3ff7dfefa5e, SHD-GAP-bea896a68a0a, SHD-GAP-2ad2aa53b0eb, SHD-GAP-a6cbeaf7b09e, SHD-GAP-8e817a514756, SHD-GAP-e91133600873, SHD-GAP-63e086d82480, SHD-GAP-323d35879783, SHD-GAP-0ad5a42a98fa, SHD-GAP-2ec0a0189191, SHD-GAP-fd225f8a7bf4, SHD-GAP-e9cda0a930a2, SHD-GAP-94ab573010ad, SHD-GAP-f0d6a7efd272, SHD-GAP-fd3dfbb3d2dd, SHD-GAP-a232c36a3dff, SHD-GAP-d2271a048ac8, SHD-GAP-a24f36e5e32f, SHD-GAP-6968c3dfcb02, SHD-GAP-4cefb97385fe, SHD-GAP-0f90b2b639ff, SHD-GAP-c0582dd1e436, SHD-GAP-9bc6b4f5a388, SHD-GAP-377a9e6f55ac, SHD-GAP-b34a73cbdd1f, SHD-GAP-078391d88e70, SHD-GAP-fd4446946cf3, SHD-GAP-3b9eb121a09b, SHD-GAP-8e43fb27960d, SHD-GAP-2489b086c800, SHD-GAP-add977c6efbd, SHD-GAP-03e5654dc4e4, SHD-GAP-70cb78b0e132, SHD-GAP-389e19b707e7, SHD-GAP-d404d0c9656e, SHD-GAP-e33df7f7fdfd, SHD-GAP-ef0ea0bdded6, SHD-GAP-369832f7013b, SHD-GAP-2b88f078a8ca, SHD-GAP-fd02b4bf7aed, SHD-GAP-c1c2b0420d28, SHD-GAP-d6a4aadc48bf, SHD-GAP-cf44dd5b77f3, SHD-GAP-1f3e9e7bc037, SHD-GAP-8c940cf11fdb, SHD-GAP-fea75d934bcb, SHD-GAP-25cb2ed23573, SHD-GAP-a29cc4993206, SHD-GAP-7e0468044539, SHD-GAP-8f947e8eca69, SHD-GAP-61afffe802b0, SHD-GAP-921525a65548, SHD-GAP-e9c4c3fbbd25, SHD-GAP-2d718fc46fc3, SHD-GAP-0e50b84d0940, SHD-GAP-7feb8ee9f762, SHD-GAP-9e9c51f1bb41, SHD-GAP-adaa6db5d32e, SHD-GAP-ee2cd2405ccf, SHD-GAP-ecfc70f51fd5, SHD-GAP-fbc793b52903, SHD-GAP-683c3810a43c, SHD-GAP-05716be6f13d, SHD-GAP-4ebb383b045b, SHD-GAP-52e82df6a5fd, SHD-GAP-5c3e2c9af4a0, SHD-GAP-cd43b2590294, SHD-GAP-f505d701ad1c, SHD-GAP-a4c00ea78523, SHD-GAP-9f28aea0017c, SHD-GAP-c679c0d5190e, SHD-GAP-cf2a899c0e65, SHD-GAP-25be37bf6662, SHD-GAP-dfbd8f752a2a, SHD-GAP-189f21aa58a8, SHD-GAP-b8e368141ccb, SHD-GAP-9fc1d4107fe1, SHD-GAP-cfd5e00aa0a5, SHD-GAP-1fffa277320a, SHD-GAP-91728a2d61b0, SHD-GAP-5c01d266acca, SHD-GAP-807b0fc3ce73, SHD-GAP-4bcc7e1af0e3, SHD-GAP-a3bb45ed36b8, SHD-GAP-56278520ae47, SHD-GAP-87f3a6b477e6, SHD-GAP-a750cadc4632, SHD-GAP-d2f8921f3cb8, SHD-GAP-a63bd33c8a17, SHD-GAP-8417d370013c, SHD-GAP-012849e268c9, SHD-GAP-766b5cbd079f, SHD-GAP-f04a11b95be1, SHD-GAP-3960984a3306, SHD-GAP-4b396984c58d, SHD-GAP-0ea3dbf68991, SHD-GAP-eef411b9b973, SHD-GAP-609c75a46bea, SHD-GAP-733d7f95a90f, SHD-GAP-09c31ab54bb3, SHD-GAP-8496ea19437d, SHD-GAP-7c5c0c58f4b8, SHD-GAP-2c4b59c1a8ab, SHD-GAP-7c576de0392a, SHD-GAP-e6c9f5f52e86, SHD-GAP-3f6da8dd958f, SHD-GAP-da3ea8ab2243, SHD-GAP-134142460eaf, SHD-GAP-e0237fb74a84, SHD-GAP-7c89c1e2cdd8, SHD-GAP-234bbdbe010e, SHD-GAP-7801ebce858d, SHD-GAP-0ad8dcae4301, SHD-GAP-5819bcb06bc6, SHD-GAP-2832f790726a, SHD-GAP-8de72280b0a8, SHD-GAP-22b338e4dd59, SHD-GAP-a589318e5cfd, SHD-GAP-811c821d26fa, SHD-GAP-a0e052470543, SHD-GAP-0ca7f98c6c43, SHD-GAP-2771b5d5fadf, SHD-GAP-6776933f0f5d, SHD-GAP-1e208b5c9483, SHD-GAP-2dfc94d220bc, SHD-GAP-5d89cbcb6cd1, SHD-GAP-c6cd0964cdb7, SHD-GAP-5629025a093f, SHD-GAP-584bccf55465, SHD-GAP-bdcdcb7bfc68, SHD-GAP-9466091a7d71, SHD-GAP-1e268399459c, SHD-GAP-f3eb2d88aa1d, SHD-GAP-9565bb8bb7aa, SHD-GAP-02431492b362, SHD-GAP-0217a1c8d06a, SHD-GAP-c80caf970551, SHD-GAP-e1c75183f7af, SHD-GAP-02edda5028a5, SHD-GAP-62a43a69e6a0, SHD-GAP-04a324d40179, SHD-GAP-fb9061d38de6, SHD-GAP-10be72e714a7, SHD-GAP-60bd536f5775, SHD-GAP-91c5dfe61b77, SHD-GAP-44d73689ed6c, SHD-GAP-7aba35d90163, SHD-GAP-900efcfe5e28, SHD-GAP-37437c98ca87, SHD-GAP-33ca00a7516e, SHD-GAP-bfda66536e5b, SHD-GAP-8a66cd433b67, SHD-GAP-bc8ac2ed942a, SHD-GAP-147dba1139b2, SHD-GAP-2cae46a0c057, SHD-GAP-69641c419cc4, SHD-GAP-ab11698c4b7e, SHD-GAP-8f65aa0c37d0, SHD-GAP-6690f5fbd5f7, SHD-GAP-d9b5b323f8b0, SHD-GAP-a3f3087f4377, SHD-GAP-a0961ed3d90d, SHD-GAP-37d9c960f06f, SHD-GAP-2bd1aac0ae0d, SHD-GAP-69e7e8369c95, SHD-GAP-49ae9b87061e, SHD-GAP-7bfcd512d57c, SHD-GAP-b1c9f29d9679, SHD-GAP-107211ddfb70, SHD-GAP-3802b72c17d6, SHD-GAP-83aff831c0a4, SHD-GAP-eee50408cad5, SHD-GAP-b596e9350821, SHD-GAP-f01bab6b61d4, SHD-GAP-5e1a6a7a4172, SHD-GAP-8d1d6322ed60, SHD-GAP-40e6cedb99d7, SHD-GAP-ee7381b44ea1, SHD-GAP-a71a4a580eb6, SHD-GAP-c6710a3549e2, SHD-GAP-5ec390e092c6, SHD-GAP-bffc1263065c, SHD-GAP-0bcc0674e608, SHD-GAP-bdab9de571b7, SHD-GAP-c915f73b2bc6, SHD-GAP-dd60f3e9f7ba, SHD-GAP-bcac83f6f193, SHD-GAP-e96b6e4b1a2d, SHD-GAP-f58a0a46aea1, SHD-GAP-ca01e15df190, SHD-GAP-d6a7fd542e11, SHD-GAP-24e99b196d0b, SHD-GAP-43bda2e346d7, SHD-GAP-f923b69f4e66, SHD-GAP-966f0ecb7779, SHD-GAP-4b15e217b3d3, SHD-GAP-0593ddf6a4ef, SHD-GAP-083be4de109d, SHD-GAP-68f1d72c84e5, SHD-GAP-039c451a2399, SHD-GAP-7de0be921b82, SHD-GAP-3a4418c1d922, SHD-GAP-016bb7e09a02, SHD-GAP-ae8cf53816ba, SHD-GAP-4b8306b38473, SHD-GAP-6b59e4d590c8, SHD-GAP-39cf5dac357a, SHD-GAP-fd4c8bfb714e, SHD-GAP-4a93306c68df, SHD-GAP-01c120dce288, SHD-GAP-5b1e1c09cccf, SHD-GAP-5c145bc34f21, SHD-GAP-e9de260f832e, SHD-GAP-dc06d5dac83f, SHD-GAP-d9df64c5d272, SHD-GAP-da64d58faebd, SHD-GAP-abe2139b2c60, SHD-GAP-b27db41f38c0, SHD-GAP-39d1b2247b3e, SHD-GAP-463a13a84643, SHD-GAP-64249a0dda58, SHD-GAP-d246ba06cfa8, SHD-GAP-cd50a2904fae, SHD-GAP-fa1f70c64af3, SHD-GAP-d0bd97f9139f, SHD-GAP-3c9825a8f417, SHD-GAP-e8b064bee438, SHD-GAP-1645561ccecb, SHD-GAP-0b29eea087a6, SHD-GAP-8e2af5e803d5, SHD-GAP-75896f2dcd7c, SHD-GAP-0f001af4db20, SHD-GAP-b585caefada2, SHD-GAP-0bf2bbe57ba1, SHD-GAP-93f25dbc7526, SHD-GAP-5106425f420d, SHD-GAP-a18c116da1b6, SHD-GAP-3fd9f45e573b, SHD-GAP-9c973db083f2, SHD-GAP-bd151ae18b57, SHD-GAP-7ca429b967d9, SHD-GAP-88ca15f4ff78, SHD-GAP-802ff61dae52, SHD-GAP-e42411b2b036, SHD-GAP-b158d138e97b, SHD-GAP-1393dbf00f80, SHD-GAP-d44b4d84f366, SHD-GAP-d7bdeb09203a, SHD-GAP-1391b5f0a5dc, SHD-GAP-68b4e121c7f7, SHD-GAP-e92b55ac09e0, SHD-GAP-19b52d40c886, SHD-GAP-6c8b285b0ff0, SHD-GAP-5e70ccd19490, SHD-GAP-a5ed3bb0075b, SHD-GAP-48f1548b30d2, SHD-GAP-e0c24277b71d, SHD-GAP-7c45b8492811, SHD-GAP-845086d0e41b, SHD-GAP-6ba8f036c7df, SHD-GAP-c90e0c3385b7, SHD-GAP-d2b99113f0a0, SHD-GAP-8fb74014246c, SHD-GAP-e986b78196c8, SHD-GAP-fb8545cc973d, SHD-GAP-552e4f757467, SHD-GAP-0b50183acd36, SHD-GAP-2e4e1b691929, SHD-GAP-14a7966bf746, SHD-GAP-9581b9e29a26, SHD-GAP-bbdf1f678ca9, SHD-GAP-15ffb63aa266, SHD-GAP-fde0db44f1c1, SHD-GAP-ec33b35e3905, SHD-GAP-049eafc2de1d, SHD-GAP-9a76bd320d18

## Delta vs previous report
- previous: `2026-10-06T15:25:50Z` (fp 6cbb66d7080b269f)
- focus refs added: (none)
- focus refs removed: ['S5-EXTERNAL-PATHS-2026-10-06']
- ledger totals delta: {'decisions': 0, 'findings': 0, 'guards': 0, 'claims': 1, 'certs': 2}
- commits since previous: 26
