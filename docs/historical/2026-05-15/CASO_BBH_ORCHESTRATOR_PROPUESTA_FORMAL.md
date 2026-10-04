# CASO DE USO: BBH Orchestrator v1.0
## Propuesta Formal para Evolución de vsf-bbh

**Fecha:** 2026-05-15  
**De:** rmw3 (S5, Kali VM100)  
**A:** VSF Governance (S5 collective decision)  
**Estado:** PROPUESTA FORMAL — Listos para iteración  
**Referencia:** ~/vsf/projects/vsf-bbh/ (v0.2-alpha → v1.0)

---

## PARTE I: CONTEXTO Y RAZONAMIENTO

### Situación Actual

El proyecto BBH (Bug Bounty Hunter) ha estado evolucionando en paralelo con el framework VSF:

**VM 100 (Kali WSL2)** ejecuta pipeline de 6 fases: profile → passive → active → enum → vuln → report.  
**bbh-prod (LXC 105)** disponible para ejecución remota.  
**vsf-bbh (v0.2-alpha)** existe como proyecto VSF en `~/vsf/projects/vsf-bbh/` pero es incompleto.

**Problema:** El pipeline BBH funciona, pero está **incompletamente integrado con VSF**:
- ❌ Flujos de ejecución NO formalizados
- ❌ Decisiones hardcoded en scripts (no policy engines)
- ❌ Eventos phi_up/phi_down parcialmente implementados
- ❌ No hay autonomía de agente — requiere supervisión constante
- ❌ 8 P1 gaps identificados sin solución clara

### Solución Propuesta

Entre 2026-05-11 y 2026-05-14, completamos **FASE A de documentación exhaustiva**:
- ✅ Mapeamos infraestructura BBH ← → VSF (7 interfaces clave)
- ✅ Formalizamos decisiones en 5 árboles (phase gates, escalation, prioritization, thermal, triage)
- ✅ Documentamos 7 flujos de ejecución (happy path + 6 desvíos por anomalías/gates)
- ✅ Creamos taxonomía de frameworks/vulnerabilidades (OWASP/MITRE)
- ✅ Planeamos investigación sistemática de 100 scopes para sintetizar estrategias

**Resultado:** Tenemos **roadmap claro de cómo convertir vsf-bbh v0.2 en v1.0 completamente competente**.

---

## PARTE II: ARTEFACTOS COMPLETADOS (FASE A)

### Documentos Fuente (entregables finales)

Todos en: `~/claude/outputs/` (ruta absoluta: `/home/rmw3/claude/outputs/`)

#### 1. **bbh_infrastructure_map.md** (450+ líneas)
**Creado:** 2026-05-13 23:40  
**Propósito:** Mapa exhaustivo de cómo BBH se integra con VSF.

**Secciones:**
```
├─ Macro architecture (S1-S5, BBS, thermal scheduler)
├─ Data flow 0→1→2→3→4→5→H1 (con signal points)
├─ Key interfaces (estado actual vs ideal)
├─ Data schemas (findings.db, queue.json, vsf_params.json proposal)
├─ Thermal model (SAFE_MODE State 3/3, slot allocation)
├─ 8 P1 gaps identificados + causas raíz
└─ Integration readiness checklist (8 items pre-go-live)
```

**Clave:** Define exactamente qué interfaces VSF ↔ BBH necesitan estar formalizadas.

---

#### 2. **bbh_decision_trees.md** (400+ líneas)
**Creado:** 2026-05-13 23:41  
**Propósito:** Formalizar todas las decisiones del pipeline en árboles declarativos.

**5 Árboles Completos:**

```yaml
# Tree 1: Phase Execution Gate
cuando: "¿puedo avanzar a siguiente fase?"
decisiones:
  Phase 0 → 1: [scope_confirmed, profile_valid]
  Phase 1 → 2: [has_passive_output, error_rate < 30%]
  Phase 2 → 3: [has_active_output, rate_limit_ok]
  Phase 4 → 5: [has_vuln_output, trial_reports > 0]

# Tree 2: Finding Escalation / Triage
cuando: "¿es este hallazgo reportable?"
decisiones:
  CVSS >= 7.0 → escalate to S5 (rmw3) for approval
  duplicado_detectado → discard
  out_of_scope → hold + notify

# Tree 3: Target Prioritization
cuando: "¿en qué orden ejecuto targets?"
decisiones:
  effort/bounty_ratio → ranking
  threat_score (S4 input) → reorder
  programa_actividad → boost priority

# Tree 4: Thermal Allocation (SAFE_MODE vs cool/mild/warm)
cuando: "¿cuántos slots de ejecución tengo?"
decisiones:
  SAFE_MODE (VM 100) → 1 input / 1 output
  cool zone → 4 input / 2 output
  warm zone → 2 input / 1 output
  hot zone → pause

# Tree 5: Covenant Compliance Check
cuando: "¿violo algún axiom antes de ejecutar?"
decisiones:
  scope_confirmed? → proceed
  out_of_scope_detected? → halt + φ↑
  error_rate > 30%? → circuit_breaker
```

**Clave:** Reemplaza todo el hardcoding con lógica declarativa, parameterizable, auditable.

---

#### 3. **bbh_workflow_flows.md** (600+ líneas)
**Creado:** 2026-05-14 00:53  
**Propósito:** Documentar los 7 caminos posibles de ejecución del pipeline.

**7 Flujos Formalizados:**

```
A: HAPPY PATH (normal)
   [0] → [1] → [2] → [3] → [4] → [5] → [H1 SUBMIT] → [END]
   Eventos: phase_start, phase_complete (x6), h1_submit, workflow_complete

B: ANOMALÍA DETECTADA (z > 2.5σ)
   [PHASE N] → [anomaly_detected] → [HOLD] → await S5 → 
   {continue | skip_phase | abort}

C: CIRCUIT BREAKER (error_rate > 30%)
   [PHASE N] → [error tracking] → [KILL] → [QUARANTINE 2h] → 
   await S5 resume_decision

D: MULTI-TARGET CONCURRENTE
   Scheduler maneja 2+ targets paralelo respetando SAFE_MODE slots
   Eventos: multi_target_started, thermal_event, queue_update, multi_target_complete

E: S4 ORCHESTRATOR (phi_down proposal)
   [S4 Qwen decide] → [proposal phi_down] → [BBH consume] → 
   [reorder queue + apply dynamic params]

F: CRITICAL FINDING (CVSS >= 7.0)
   [4_VULN detecta] → [finding_critical emitido] → [HOLD] → 
   await rmw3 triage → {approve | hold | discard}

G: REVALIDACIÓN (delta check semanal)
   [Phase 1 baseline] → [7 days later delta check] → 
   if delta > 5% → queue Phase 2 delta (partial rerun)
```

**Clave:** Define state machine explícito con transitions, hold points, eventos por flujo.

---

#### 4. **bbh_framework_taxonomy.json** (200+ líneas)
**Creado:** 2026-05-14 00:52  
**Propósito:** Taxonomía de frameworks, lenguajes, tipos de vulnerabilidades.

**Estructura:**
```json
{
  "frameworks": {
    "react": { "fingerprint": "React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED", ... },
    "django": { "fingerprint": "csrftoken cookie", ... }
  },
  "languages": {
    "javascript": { "patterns": ["proto pollution", "template injection", ...] },
    "python": { "patterns": ["pickle deserialization", "exec/eval", ...] }
  },
  "vulnerabilities": {
    "xss": { "owasp": "A03:2021", "mitre": "CWE-79", "cvss_range": [3.1, 8.6], ... },
    "sqli": { "owasp": "A03:2021", "mitre": "CWE-89", "cvss_range": [5.9, 9.8], ... }
  }
}
```

**Clave:** Input para S4 reasoning, classification automática de findings, CVSS estimation.

---

#### 5. **bbh_scope_analysis_investigation_plan.md** (300+ líneas)
**Creado:** 2026-05-14 00:48  
**Propósito:** Plan para investigación sistemática de 100 scopes HackerOne.

**Metodología:**
```
1. Analizar 100 programas H1 activos
2. Extraer patrones de vulnerabilidades exitosas (por programa type)
3. Mapear técnicas efectivas (reconocimiento → enumeración → explotación)
4. Sintetizar estrategias de hunting por vertical (SaaS, fintech, etc.)
5. Alimentar S4 con threat_score + effort/bounty_ratio
```

**Clave:** Proporciona inteligencia cuantificada para S4 en target prioritization.

---

### Documentos Secundarios (referencia)

También completados en Fase A (referencia para arquitectura):

- **FASE_A_DOCUMENTACION_ESTADO_FINAL.md** (2026-05-14 00:50)
  — Resumen de estado + artifact status de 5 artefactos principales
  
- **VSF_ARCHITECTURE_ASSESSMENT_20260511.md** (2026-05-11 11:27)
  — Análisis de viabilidad VSF score 92%, 3 gaps abiertos

- **BBH_INFRASTRUCTURE_MAP.md, BBH_DECISION_TREES.md, BBH_WORKFLOW_FLOWS.md**
  — 5/5 artefactos completados, listos para implementación

---

## PARTE III: DECANTAR EL PROCESO

**"Decantar"** = Separar, clarificar, formalizar.

En este contexto, hemos:

1. **Separado** la lógica de negocio (7 flujos, 5 decisiones) del código imperativo
2. **Clarificado** las interfaces VSF ↔ BBH (phi_up, phi_down, algedonic)
3. **Formalizado** la gobernanza (covenant + roe, policy engines, audit trail)

**Resultado:** Tenemos **blueprint completo** para construir agente autónomo que:
- Entienda los 7 flujos
- Aplique los 5 árboles de decisión
- Emita eventos VSF (phi_up)
- Responda a directivas VSF (phi_down)
- Sea 100% auditable y compliant

---

## PARTE IV: PROPUESTA TÉCNICA

### Objetivo v1.0

Evolucionar `vsf-bbh` a sistema **completamente autónomo y competente**:

| Capability | v0.2-alpha | v1.0 |
|------------|-----------|------|
| **7 flujos formalizados** | No | ✅ |
| **5 decision trees** | Hardcoded | ✅ Policy engine |
| **phi_up eventos completos** | Partial | ✅ Complete |
| **phi_down response** | No | ✅ S4 proposals |
| **Autonomía** | Supervisado | ✅ Auto (con gates) |
| **Agente competente** | No | ✅ bbh-orchestrator-v1 |
| **P1 gaps cerrados** | 8 | ✅ 0 |

### Arquitectura Propuesta

```
~/bbh/ (proyecto hijo de VSF)
├── agents/bbh-orchestrator-v1/
│   ├── CLAUDE.md
│   ├── bbh_orchestrator.py       # State machine (7 flujos)
│   ├── decision_engine.py        # Policy trees (5 árboles)
│   ├── event_emitter.py          # phi_up generator
│   ├── phi_down_consumer.py      # S4 proposal handler
│   ├── algedonic_notifier.py     # Circuit breaker alerts
│   └── tests/
│
├── spec/
│   ├── viability_v1.0.yaml       # VSF system definition
│   ├── roe_v1.0.yaml             # Rules of engagement (enhanced)
│   ├── workflows.vsm             # 7 flujos en VSM notation
│   └── decision_trees.vsm        # 5 árboles en VSM notation
│
├── data/
│   ├── framework_taxonomy.json   # From Fase A
│   ├── scope_patterns.json       # From investigation plan
│   └── hunting_strategies.json   # Synthesized
│
└── logs/
    └── orchestration.jsonl       # All phi_up events
```

### 4 Fases de Implementación

#### **B1: Iteración (2-3 horas)**
- [ ] Revisar Fase A docs + propuesta con VSF S5
- [ ] Refinar viability_v1.0.yaml
- [ ] Mejorando roe_v1.0.yaml con gates + algedonic
- [ ] Crear workflows.vsm (7 flujos formalizados)

**Deliverables:**
- viability_v1.0.yaml
- roe_v1.0.yaml
- workflows.vsm

#### **B2: Agente (4-6 horas)**
- [ ] Crear `.claude/agents/bbh-orchestrator-v1/`
- [ ] Implementar state machine (7 flujos)
- [ ] Implementar policy engine (5 trees)
- [ ] Implementar event emitter (phi_up)
- [ ] Integrar phi_down consumer

**Deliverables:**
- bbh_orchestrator.py
- decision_engine.py
- event_emitter.py
- phi_down_consumer.py
- Unit + integration tests

#### **B3: Validación (1-2 horas)**
- [ ] VSL-TEST-BBH-ORCHESTRATOR-v1 (6+ tests)
- [ ] Dry-run con target sandbox
- [ ] Covenant compliance verification
- [ ] phi_up emission validation

**Deliverables:**
- test_results.json
- covenant_compliance_report.md

#### **B4: Go-Live (0.5 horas)**
- [ ] Register agente en CLAUDE.md
- [ ] Actualizar vsf-bbh/viability.yaml → v1.0
- [ ] Primer orchestration run
- [ ] Commit + push

**Timeline Total:** ~8-12 horas (puede ser 2-3 días)

---

## PARTE V: LLAMADA A ACCIÓN

### Próximos Pasos

**HITO 1: Esta semana (2026-05-15 a 2026-05-17)**
```
2026-05-15 (Hoy): Presentación formal + feedback VSF
2026-05-16 (Mañana): Iniciar Fase B1 (refinement + specs)
2026-05-17 (Viernes): Entregar agente v1.0 + tests
```

**HITO 2: Siguiente semana (2026-05-19+)**
```
2026-05-19: Go-live con primer target real
2026-05-20+: Monitorear anomalías, ajustar policies según datos
```

### Dependencias Resueltas

- ✅ Documentación de infraestructura → bbh_infrastructure_map.md
- ✅ Formalización de decisiones → bbh_decision_trees.md
- ✅ State machine definido → bbh_workflow_flows.md
- ✅ Taxonomía de vulnerabilidades → bbh_framework_taxonomy.json
- ✅ Plan de investigación → bbh_scope_analysis_investigation_plan.md
- ✅ VSF framework existente → ~/vsf/ operativo
- ✅ Phase 1.5 validación → 7/7 tests PASS
- ✅ Thermal scheduler estable → SAFE_MODE validado

### Riesgos Mitigados

| Riesgo | Mitigación |
|--------|-----------|
| Complejidad state machine | Tests exhaustivos + dry-run sandbox |
| phi_up/phi_down format divergence | Validar contra VSL spec |
| Decision tree correctness | Unit tests + manual validation |
| Escalación spam a S5 | CVSS >= 7.0 threshold bien calibrado |
| Autonomía prematura | Gates explícitos mantienen S5 control |

---

## PARTE VI: CONCLUSIÓN

**Tenemos todo lo que necesitamos para hacer vsf-bbh v1.0 realidad.**

Los documentos de Fase A no son teóricos — son **blueprint de implementación** que:
- Define exactamente qué código escribir (7 flujos = 7 branches en state machine)
- Especifica qué decisiones automatizar (5 trees = 5 policy modules)
- Establece qué eventos emitir (15+ evento types definidos en bbh_workflow_flows.md)
- Cierra los 8 P1 gaps con soluciones concretas

**El siguiente paso es ITERACIÓN con VSF + IMPLEMENTACIÓN del agente.**

Si se aprueba esta propuesta, podemos comenzar **Fase B1 mañana (2026-05-16)** y entregar agente competente completo **para el viernes (2026-05-17)**.

---

## REFERENCIAS Y ARTEFACTOS

### Documentos Fuente (Fase A)
Todos en `/home/rmw3/claude/outputs/`:

1. `bbh_infrastructure_map.md` — 450+ líneas, 7 sections
2. `bbh_decision_trees.md` — 400+ líneas, 5 formalized trees
3. `bbh_workflow_flows.md` — 600+ líneas, 7 workflows + state diagram
4. `bbh_framework_taxonomy.json` — 200+ líneas, OWASP/MITRE mapping
5. `bbh_scope_analysis_investigation_plan.md` — 300+ líneas, systematic investigation

### Documentos VSF Existentes
En `~/vsf/projects/vsf-bbh/`:

- `viability.yaml` (v0.2-alpha) — actual system definition
- `roe.yaml` — rules of engagement (2026-04-26)

### Propuesta Formal
En `~/vsf/projects/vsf-bbh/`:

- `PROPUESTA_AGENTE_COMPETENTE_2026-05-15.md` — Detailed implementation roadmap

### Este Documento
En `~/vsf/`:

- `CASO_BBH_ORCHESTRATOR_PROPUESTA_FORMAL_2026-05-15.md` — Formal case presentation

---

**Versión:** 1.0  
**Creado:** 2026-05-15  
**Estado:** PROPUESTA FORMAL — Listos para iteración  
**Próxima Acción:** Feedback VSF → Fase B1 mañana

---

## FIRMA

**Propuesto por:** rmw3 (S5, Kali VM100)  
**Para:** VSF Governance (S5 collective)  
**Scope:** Evolution of vsf-bbh v0.2-alpha → v1.0  
**Autoridad:** covenant.vsm, roe.yaml, viability.yaml  

---

*Documento formal presentado a VSF para iteración y aprobación.*  
*Todos los artefactos de Fase A están completos y auditables.*  
*Listos para Fase B (Implementación) cuando VSF autorice.*
