# Evolution report — EVOLUTION-2026-10-28

- generated_at: `2026-10-28T02:18:27Z`
- since: `2026-10-26T22:24:13Z`
- fingerprint: `bed9b0f54970cade`

## Commits since
- `18e68ec` 2026-10-27T16:10:46-03:00 — chore(vsf-agent): add .gitignore to exclude target/ build artifacts
- `c510166` 2026-10-27T16:07:18-03:00 — fix(deps): create vsf-agent crate + resolve vsf-nucleus compilation errors
- `5c7a5dc` 2026-10-27T13:19:50-03:00 — exp(a01-01): Phase 2 complete - Rust detector integrated into kernel
- `85f41ff` 2026-10-27T10:05:20-03:00 — sidecard(phase-c): final report - 100% accuracy achieved with heuristic v12
- `f93d106` 2026-10-27T09:58:24-03:00 — exp(a01-01): heuristic detector v12 achieves 100% accuracy on massive corpus
- `1f4141d` 2026-10-27T05:15:37-03:00 — sidecard(phase-a): final report - heuristic v5 outperforms all tested LLMs
- `3a48de7` 2026-10-27T04:46:27-03:00 — sidecard(phase-a): v2 progress report - Qwen3-0.6B and 1.7B fail, 8B in progress
- `e1e4637` 2026-10-27T02:13:03-03:00 — exp(a01-01): Phase C massive corpus test - 80% accuracy on 800 streams
- `8bcd1b6` 2026-10-27T01:29:28-03:00 — audit: covenant alignment report for EXP-A01-01 corpus
- `461a489` 2026-10-27T00:59:18-03:00 — audit: covenant alignment report for EXP-A01-01 corpus
- `62ebe52` 2026-10-27T00:10:38-03:00 — sidecard: Phase C vs Phase A comparison report

## Ledgers
- **decisions**: total=182 new=0 no_ts=2 (ts=ts)
- **findings**: total=50 new=0 no_ts=0 (ts=ts)
- **guards**: total=26 new=0 no_ts=0 (ts=ts)
- **claims**: total=6179 new=0 no_ts=6176 (ts=declared_at)
- **certs**: total=31 new=0 no_ts=0 (ts=observed_at)

## Focus
- entries: 5
- active: paper-audit-critical-reading

## Snapshots
- days: 2026-10-27
- index rows since: 1

## Battery (anti-pantomima)
- latest: `real_state_battery_2026-10-03.json` — 12/12 checks verdes con ground truth;4 huecos declarados (no esconderlos = parte del exit)
- declared gap: {'id': 'G1-idle-post-fix', 'why': 'post-fix idle dispatch requires an idle event to observe — watched via cycle_health, not proven by this battery'}
- declared gap: {'id': 'G2-guard-live-run', 'why': 'R2 runs audit_guards(run=False): liveness is sampled, not exercised end-to-end in-process'}
- declared gap: {'id': 'G3-doc-manifest-stale', 'why': 'doc-manifest staleness is covered by boot-ontology (R7) only for artifacts it declares'}
- declared gap: {'id': 'G4-claims-cadence', 'why': 'claims/certs cadence is a multi-day property — see evolution report cadence (G-03), not a point-in-time check'}

## Drift
- journal rows: 7, latest_drift_count=6

## Shadow (CC-8.1) — would-be, never executed
- entries: total=7231 new=161 blocked-by-bounds=63 aligned=63
- kinds: aligned-blocked=63 would-run-deferred=98
- new: `SHD-GAP-9a62a90cb422` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"QUALITY_OK","actions":["OK"]}
- new: `SHD-GAP-2463f04e174f` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-1846bd38d60d` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-bcc927819f16` [BLOCKED] src=gap-resolver action={"gap":"conflict-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-ec62b7be459b` [would-run] src=gap-resolver action={"gap":"patch-detection","decision":"STALE_PATCH","actions":["ALERT: Patch is st
- new: `SHD-GAP-fa6246ffb0b8` [would-run] src=gap-resolver action={"gap":"quality-gates","decision":"QUALITY_OK","actions":["OK"]}
- new: `SHD-GAP-b37612852f95` [BLOCKED] src=gap-resolver action={"gap":"dependency-validation","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-302d3fac9857` [would-run] src=gap-resolver action={"gap":"code-classification","decision":"OK_DIR","actions":["OK"]}
- new: `SHD-GAP-bd194bd32261` [BLOCKED] src=gap-resolver action={"gap":"conflict-detection","decision":"UNKNOWN","actions":["OK"]}
- new: `SHD-GAP-aa3203c6d933` [would-run] src=gap-resolver action={"gap":"patch-detection","decision":"STALE_PATCH","actions":["ALERT: Patch is st
- divergences: total=98 explained=98 unexplained=0
- explained: `SHD-GAP-9a62a90cb422` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-1846bd38d60d` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-ec62b7be459b` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-fa6246ffb0b8` via class:RX-DEFERRED-SEMI-AUTO
- explained: `SHD-GAP-302d3fac9857` via class:RX-DEFERRED-SEMI-AUTO
- guard-would-have-blocked: SHD-GAP-2463f04e174f, SHD-GAP-bcc927819f16, SHD-GAP-b37612852f95, SHD-GAP-bd194bd32261, SHD-GAP-eb6653b0a0d7, SHD-GAP-af0092527576, SHD-GAP-79470de0e6cf, SHD-GAP-9ad8bc10fd24, SHD-GAP-b90cd9196dce, SHD-GAP-739e36a7fc05, SHD-GAP-34bd5b73d85e, SHD-GAP-0f8e0f75d307, SHD-GAP-9eafc5276228, SHD-GAP-27507bba6423, SHD-GAP-ee81b4cc69c0, SHD-GAP-7bc07457e0f5, SHD-GAP-e0a78145d4a4, SHD-GAP-74286b6b06f3, SHD-GAP-cfac0d8ab1f7, SHD-GAP-5613d6c2ea2a, SHD-GAP-af89e463d0ae, SHD-GAP-27a19bf563de, SHD-GAP-8bdb4975c9ea, SHD-GAP-fc05f4512491, SHD-GAP-13baecab9f83, SHD-GAP-b5183f3c5c1c, SHD-GAP-d12961604e10, SHD-GAP-097bde8ea23a, SHD-GAP-962d5087e40e, SHD-GAP-b8de94ee76d3, SHD-GAP-cc38f152f058, SHD-GAP-bf4fd360549e, SHD-GAP-39d4752dea0d, SHD-GAP-651aed9ad2eb, SHD-GAP-4f4ecf48943b, SHD-GAP-1ac5890712c1, SHD-GAP-372bcf2f0821, SHD-GAP-0e53d7fdcc60, SHD-GAP-cf7b825c1437, SHD-GAP-3c7955eb84a2, SHD-GAP-21a766e6af0f, SHD-GAP-3aeab9c026bd, SHD-GAP-916231036ee9, SHD-GAP-630604c313db, SHD-GAP-3cd58314830c, SHD-GAP-439487e97154, SHD-GAP-f1a9e974235a, SHD-GAP-25588437962c, SHD-GAP-66227f61aa25, SHD-GAP-66ad690fcf2e, SHD-GAP-ea54807e195d, SHD-GAP-5751cd9be9b4, SHD-GAP-d79b90540d41, SHD-GAP-986ca449989d, SHD-GAP-37af1f5b34a5, SHD-GAP-d3a3aba57f35, SHD-GAP-f501a7975fb5, SHD-GAP-cdbd62e143f2, SHD-GAP-a8cc957988d8, SHD-GAP-104ba865f14b, SHD-GAP-4563fcf527bf, SHD-GAP-72b1d23a27fb, SHD-GAP-46214502af38

## PLEASURE (G-34) — placer estadistico
- events: 1513 (successes 1493) · emissions: 1527 (milestone 38 · rpe 1489) · milestones: 38 · total magnitude: 27.036149
- units: evaluate, gate_run
- current streaks: evaluate=795 gate_run=120
- 2026-10-27T19:08:34Z [rpe 0.005517 rpe] unit=evaluate streak=791 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-27T19:10:46Z [rpe 0.005516 rpe] unit=evaluate streak=792 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-27T19:10:46Z [rpe 0.005515 rpe] unit=evaluate streak=793 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-27T19:10:49Z [rpe 0.005514 rpe] unit=evaluate streak=794 — evaluate truth=TRUE cert=True source=op:AND
- 2026-10-27T19:10:53Z [rpe 0.005514 rpe] unit=evaluate streak=795 — evaluate truth=TRUE cert=True source=op:AND

## Distill candidates (R4) — propose-only triage view
- total: 102 caution_signal=1 error_pattern=50 tool_pattern=51 | status: adopted=15 closed=1 proposed=17 rejected=69
- oldest: 2026-10-07T03:18:22Z · newest: 2026-10-27T19:13:38Z
- would-expire (>60d proposed tool_pattern): 0 (view only — S5 batch applies)

## Scenarios (R6) — retrieval baseline
- store: 727 scenarios
- consult events today: 0
- outcome linkage: NOT YET LOGGED (precision follow-up per plan R6)

## Delta vs previous report
- previous: `2026-10-28T02:18:27Z` (fp bed9b0f54970cade)
- focus refs added: (none)
- focus refs removed: (none)
- ledger totals delta: {'decisions': 0, 'findings': 0, 'guards': 0, 'claims': 0, 'certs': 0}
- commits since previous: 11
