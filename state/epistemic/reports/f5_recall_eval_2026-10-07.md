# F5 E1 — recall hit-rate (mini-CTC)

- fecha (UTC): 2026-10-07T07:41:03+00:00
- corpus: root=/home/rmw3/vOSlab, indexed=10836, por origen={'doc': 747, 'focus': 39, 'log': 10000, 'candidate': 50}, fail-closed dropped={'empty_content': 1}
- límite de log: 10000 newest records (DEFAULT_MAX_LOG_RECORDS); ancla de frescura (ref_ts)=2026-10-07T07:40:56.258722+00:00
- k=5, max_hit_chars=2000, max_total_chars=8000
- ranking: tf-idf log-damped × origin-weight {'doc': 3.0, 'focus': 2.0, 'log': 1.5, 'candidate': 1.0} × freshness 1/(1+age_days/30) con age anclado al ts max de la corpus (no a now)
- tokenización: \w{2,} lower-case, términos únicos
- recall.py sha256_12=86e44826d4d9
- modo: evaluación directa build_index→search→sanitize (sin env; el serve live es solo para evidencia)

| # | query | esperado | top-k | hit |
|---+-------|----------|-------+-----+-----|
| 1 | pleasure channel algedonico placer milestones | docs/plans/pleasure_channel_proposal.vsm | docs/plans/pleasure_channel_proposal.vsm, docs/plans/system_backlog.vsm, docs/plans/plan_registry.vsm | **SÍ** |
| 2 | NC-21 recall-sanitize negative control | docs/plans/r4_lote2_proposal.vsm | docs/archive/root_tasks_sessions_ARCHIVE.vsm, docs/plans/r4_lote2_proposal.vsm, docs/plans/refs_optimization_proposal.vsm | **SÍ** |
| 3 | D-25 repo hermano state-canon guards | docs/plans/system_backlog.vsm | docs/archive/root_tasks_sessions_ARCHIVE.vsm, docs/plans/system_backlog.vsm, docs/sessions/tasks_closed/closed-a.vsm | **SÍ** |
| 4 | l2-view probe A-G freshness stamped | docs/plans/refs_optimization_proposal.vsm | docs/archive/root_tasks_sessions_ARCHIVE.vsm, docs/spec_revision/system/s4-intelligence/s4-anticipation-01/s4_anticipation.vsm, docs/plans/refs_optimization_proposal.vsm | **SÍ** |
| 5 | F3a manifest cache warm 15 segundos | docs/plans/refs_optimization_proposal.vsm | docs/plans/refs_optimization_proposal.vsm, docs/archive/root_tasks_sessions_ARCHIVE.vsm, docs/plans/plan_registry.vsm | **SÍ** |
| 6 | tasa UNKNOWN compliance bias K6 | docs/plans/refs_optimization_proposal.vsm | docs/plans/refs_optimization_proposal.vsm, docs/plans/r4_lote2_proposal.vsm, docs/reference/ecosystem_refs.vsm | **SÍ** |
| 7 | VOS_SESSION_ID esquema B session_id | docs/plans/plan_registry.vsm | docs/plans/refs_optimization_proposal.vsm, docs/sessions/tasks_closed/closed-a.vsm, docs/archive/root_tasks_sessions_ARCHIVE.vsm | no |
| 8 | REFS-OPT-001 foco activo trabajo | current_focus.json | docs/archive/root_tasks_sessions_ARCHIVE.vsm, docs/plans/refs_optimization_proposal.vsm, docs/sessions/tasks_closed/closed-a.vsm | no |
| 9 | context rot degradación longitud retrieval | docs/plans/r4_lote2_proposal.vsm | docs/plans/r4_lote2_proposal.vsm, docs/plans/refs_optimization_proposal.vsm, docs/archive/root_tasks_sessions_ARCHIVE.vsm | **SÍ** |
| 10 | sanitización delimitadores no-ejecución VOS-RECALL | docs/plans/r4_lote2_proposal.vsm | docs/plans/r4_lote2_proposal.vsm, docs/plans/refs_optimization_proposal.vsm, docs/archive/root_tasks_sessions_ARCHIVE.vsm | **SÍ** |
| 11 | learning-cycle-scan session.idle activation | agent_plugin / docs/plans/system_backlog.vsm | docs/archive/root_tasks_sessions_ARCHIVE.vsm, docs/sessions/ds/2026-07-a.vsm, docs/plans/system_backlog.vsm | **SÍ** |
| 12 | broken noop gate negative control exit code | state/distill/candidates.jsonl / agent_plugin | docs/archive/root_tasks_sessions_ARCHIVE.vsm, docs/plans/system_backlog.vsm, docs/sessions/ds/2026-07-a.vsm | no |

**hit-rate: 9/12**
