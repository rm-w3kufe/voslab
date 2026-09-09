# AUDITORÍA COMPLETA: Padre vs vOSlab

## RESUMEN EJECUTIVO

| Categoría | Padre | vOSlab | Faltante | Cobertura |
|-----------|-------|--------|----------|-----------|
| **Plugins** | 39 | 19 | 20 | 49% |
| **Scripts** | 270 | 53 | 217 | 20% |
| **Checks** | 60 | 0 | 60 | 0% |
| **Knowledge** | 6 | 0 | 6 | 0% |
| **System Docs** | 113 | 113 | 0 | 100% |

## DETALLES POR CATEGORÍA

### 1. PLUGINS (49% cobertura)

**Plugins en vOSlab (19):**
- core: vsf-naming-enforcer, vsl-check-on-write, vsl-measure-before-write
- manual: vsf-agent-vsl-gate, vsf-classify-on-write, vsf-hook-instances, vsf-script-classify-on-write, vsf-scripts-manifest-updater, vsl-relocate-on-write
- operational: backbone, cycle, gap-resolver, lifecycle-autopilot, lifecycle-discovery, observe, remind, tool-integration, vsf-event-router, vsf-onboard-reminder

**Plugins FALTANTES (20):**
- core: vsf-policy-enforcer
- manual: (ninguno faltante)
- operational: learning-cycle-scan, scenario-memory, scenario-memory-gap-bridge, test-patch
- operational/handlers: attestation, core-scripts, cyberfilter, gap-resolution, governance, hook-analytics, learning-cycle, lifecycle, services, session-hygiene, session-init, shared, state-reconcile, tasks
- support: vsf-socratic-shell

### 2. SCRIPTS (20% cobertura)

**Scripts ya integrados en vOSlab:**
- vsf-tools: gen_index, http_mixin, surgery_mode, semantic_mapper, tokenizer, vsm_timestamp
- vsf-rsi-core: rsi_* (9 módulos)
- vsf-validation: validators (12 módulos)
- vsf-health: health_predicates
- vsf-hooks-analytics: hook_metrics, deep_audit
- vsf-common: protocol
- vos_kernel: backbone, adapters, covenant, invariants, regulation
- gate_suite: 6 gates

**Scripts FALTANTES por dominio:**
- **ALGEDONIC** (9 scripts): ac_algedonic, ac_classifier, bbs_decisions_bridge, beacon_attestation, g6_algedonic_sink, vsf_algedonic_subscriber, vsf_bbs_poller, vsf_beacon_main, vsf_decision_auth
- **ANALYSIS** (12 scripts): analyze_s401, checo_*, cyberfilter_census, extract_trajectories, fig_topology, k_monitor, markov_analysis, tda_calibrate, viability_forecaster, vsf_graph
- **AUDIT** (15 scripts): pipeline_audit, sa_auditor, vsf-audit-*, check_*, verify_*, exp_s4_01_*
- **S1-KERNEL** (10 scripts): kernel_*, node_registry, k_phi_down_meter, verify_nodes_*, recursion_triage, s3star_query, recovery_exercise, s1_calibration_census, vsf-peripheral-health
- **S3-ALLOCATION** (6 scripts): kpi_spc, omega_zone_calibrate, s3_resource_alloc, s3star_kpi, s3_star_sporadic, supervision_view
- **S4-ORCHESTRATION** (6 scripts): copper_price_feed, markov_*, replay_era5, s4_markov_bridge, s4_store
- **S5-GOVERNANCE** (4 scripts): gen_test_ca, s5_ca_monitor, vsf_s5_agent, vsf_s5_ledger
- **SHARED** (9 scripts): canon_census, docs_reconcile, relocate_vsm, sd_digest, update_manifest_sha, update_scripts_manifest, verify_scripts_manifest, vsf-net-housekeeping, git_*
- **STATE** (30+ scripts): lifecycle_*, monitoring_*, governance_*, services_*, tasks_*, attestation_*, cyberfilter_*, algedonic_*
- **VSL** (20+ scripts): classifier/*, parser/*, tools/*, validator/*

### 3. CHECKS (0% cobertura)

**Checks FALTANTES (60):**
- agent-map-valid, agent-plugin-log-valid, agent-plugin-path-valid
- archive-index-valid, boot-load-test, boot-manifest-valid, boot-ontology-clean
- child-boot-state-archive-gates, child-refs-notify-valid
- classification-tree-valid, classification-valid
- compression-drift-valid, crl-expiry-proximity
- dir-schema-valid, enforcement-consistency-valid
- filenames-valid, format-usage-inventory-baseline
- impl-with-design-valid, incident-registry-valid
- learning-record-valid, not-prose-gate
- ontology-master-coherent, ontology-master-frame, ontology-master-trace
- plan-tree-valid, plugin-behavior-valid, plugin-location-valid, plugin-s2-coherent
- policy-propagation-valid, r15-envelope-valid, r4-1-dispatch-gate-valid
- ratified-version-current, recursion-triage-valid
- relocate-vsm-valid, root-boot-state-archive
- rules-pointer-consistent, socratic-engine-selftest, socratic-gate-valid
- task-format-valid, task-maintenance-valid, tasks-census-converge, tasks-structure-guard
- tokenizer-string-open-line, version-change-plan
- vsl-encoding-valid, vsl-gate-valid
- vslline-manifest-valid, vsl-template-system-valid, vsl-timestamp-required
- vsm-version-coherent, write-gates-valid

### 4. KNOWLEDGE (0% cobertura)

**Knowledge FALTANTE:**
- architecture.vsm
- rsi_identity.vsm
- self_maintaining_patterns.vsm
- vsl_basics.vsm

## PAQUETES NECESARIOS

### Paquetes Nuevos a Crear

| Paquete | Tipo | Contenido |
|---------|------|-----------|
| **vsf-algedonic** | public | Scripts algedonic (9) |
| **vsf-analysis** | public | Scripts de análisis (12) |
| **vsf-audit** | public | Scripts de auditoría (15) |
| **vsf-s1-kernel** | framework | Scripts kernel S1 (10) |
| **vsf-s3-allocation** | framework | Scripts asignación S3 (6) |
| **vsf-s4-orchestration** | framework | Scripts orquestación S4 (6) |
| **vsf-s5-governance** | framework | Scripts gobernanza S5 (4) |
| **vsf-state** | framework | Scripts de estado (30+) |
| **vsf-checks** | public | Checks de validación (60) |
| **vsf-knowledge** | public | Knowledge base (6) |

### Paquetes Existentes a Actualizar

| Paquete | Agregar |
|---------|---------|
| **vsf-tools** | shared scripts (9) |
| **vos-kernel** | handlers (14) |

##-plugins a Agregar

Agregar a opencode.json:
```json
"plugin": [
  "../.opencode/plugins/core/vsf-policy-enforcer.ts",
  "../.opencode/plugins/operational/learning-cycle-scan.ts",
  "../.opencode/plugins/operational/scenario-memory.ts",
  "../.opencode/plugins/operational/scenario-memory-gap-bridge.ts",
  "../.opencode/plugins/operational/test-patch.ts",
  "../.opencode/plugins/support/vsf-socratic-shell.ts"
]
```

##plugins/handlers a Agregar

Los handlers se cargan dinámicamente via event-router, no necesitan estar en opencode.json.

## PRÓXIMOS PASOS

1. Crear paquetes nuevos con scripts faltantes
2. Actualizar vsf-tools con shared scripts
3. Actualizar vos-kernel con handlers
4. Agregar plugins faltantes a opencode.json
5. Migrar checks a vsf-checks
6. Migrar knowledge a vsf-knowledge
