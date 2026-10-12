# VSF Writer / Reader / Decider Matrix — Estado y brechas operativas

**Date:** 2026-05-26
**Status:** CANONICAL — referencia para evaluación de estado del sistema
**Companion:** `docs/spec_revision/system/plan/strategy_plan.vsm`, `docs/GAPS_AND_DEBTS.md`, `docs/VSF_VSM_SCORING.md`
**Origin:** sesión 2026-05-26 — usuario pidió consolidar el problema de
"quién escribe / quién lee / quién decide" tras observar invariant_check
con `_samples: 0` en producción.

---

## 0. Por qué este doc existe

Cada subsistema VSM tiene rol triple en el flujo de información:

- **Escritor** — produce variedad observable (emit)
- **Lector** — absorbe variedad para su contexto (subscribe / poll)
- **Decisor** — basado en lo leído, toma acción que se vuelve nueva variedad

Beer: "A viable system maintains its existence through this loop. Information
must FLOW around the system, or the system isn't viable — it's a hierarchy of
disconnected boxes wearing VSM clothing."

VSF tiene la estructura formal (γ.1-.10 + P.1-.4 + s3_star) pero algunas
conexiones writer→reader→decider están abiertas. Este doc:

1. Mapea estado actual writer/reader/decider por subsistema
2. Identifica 6 brechas operativas concretas
3. Mapea cada brecha a tarea pendiente que la cierra
4. Sirve como **medición pre/post** para evaluar cierre

---

## 1. Matriz de estado — quién hace qué

Snapshot a 2026-05-26 (post Tier α Tα.0-A4, pre A0 deploy LXC 107).

| Subsistema | ¿Escribe? | ¿Lee qué? | ¿Decide qué? | Estado | Score VSM |
|---|---|---|---|---|---|
| **S1** (γ.1 canonical emit) | kernel_tick (heartbeat 60s) | nada | nada | ◐ pseudo-doer, sin carga real | 5/10 |
| **S2** | ✗ no escribe | ✗ no lee | ✗ no decide | ◯ no existe módulo | 6/10 |
| **S3** (mixed con s4_operational) | s4-analysis events | /proc + BBS embedded | aplicar Qwen decisions a BBS | ◐ rol mezclado con S4 | 8/10 |
| **S3\*** (vsf-s3-star) | listo: s3_star_sample events | events.jsonl read-only | algedonic on covenant/Merkle drift | ⏳ código listo, no deployado | 5/10 |
| **S4** (Qwen 300s ciclo) | s4-analysis (P.1 dual-write) | /proc + BBS state | decisions JSON (no enforcement) | ◐ decide pero output no acciona | 6/10 |
| **S5** (covenant + policy) | covenant verify @ boot | s5_policy.json + covenant.vsm | abortar boot si drift | ◐ estático, sin agent | 6/10 |
| **γ.4 algedonic gate** | algedonic_emit (nunca disparó en prod) | invariant_checker state | trigger threshold | ◐ deployed dormant | 6/10 |
| **γ.6 invariant_checker** | invariant_check (P.2, datos vacíos) | record_variety/trust/stasis calls (nadie llama) | flag pass/fail | ◐ checker existe sin alimentación | (parte Variety 7/10) |
| **γ.9 bbh_subscriber** | relay BBH events with system_id="bbh" | NATS bbh.> | nada (passthrough) | ✅ funciona idle (BBH no publica) | parte S1 |
| **γ.10 phi_down_subscriber** | param_change events | NATS vsf.<id>.phi_down.params | apply patch → Arc<RwLock> | ✅ end-to-end probado | parte S5 |
| **γ.2 nats_publisher** | nada (relay) | events.jsonl tail | publica a NATS subjects | ✅ relay puro | infra |

---

## 2. Las 6 brechas operativas

Cada brecha es una **conexión emisor↔consumer faltante**. No problema de
diseño — wiring incompleto.

### BRECHA-1 — events.jsonl write-only en producción

| Aspecto | Estado |
|---|---|
| Writers | 6+ módulos (kernel_tick, s4-analysis, invariant_check, algedonic, param_change, bbh ingest) |
| Readers en producción | γ.2 (passthrough tail→NATS) + NADIE con consumo activo |
| Consecuencia | Ledger forense puro, no influye en decisiones |
| Severity | HIGH — sin consumer, las observaciones son inútiles |

### BRECHA-2 — S4 ciego a su propio output

| Aspecto | Estado |
|---|---|
| S4 escribe | s4-analysis a BBS + events.jsonl |
| S4 lee | /proc + BBS state (NO events.jsonl) |
| Consecuencia | S4 decide en metrics, no en contexto histórico de su propio razonamiento |
| Severity | MEDIUM — funciona, pero pierde continuidad |

### BRECHA-3 — invariant_check con cables sueltos

| Aspecto | Estado |
|---|---|
| γ.6 emite | cada 60s con `var1_samples=0, trust1_samples=0, stasis_samples=0` |
| Llamadas a record_variety/trust/stasis | **0 en producción** |
| Consecuencia | Sensor existe + reporta vacío. Variedad real no se mide |
| Severity | MEDIUM — sin S1 con carga, sin datos para invariantes |

### BRECHA-4 — algedonic sin oyente

| Aspecto | Estado |
|---|---|
| γ.4 puede fire → publish a vsf.<id>.algedonic | sí |
| Suscriptores en producción a ese subject | **0** |
| Consecuencia | Si dispara, el grito es en el vacío |
| Severity | HIGH — canal de urgencia inservible sin oyente |

### BRECHA-5 — φ↓ solo manual

| Aspecto | Estado |
|---|---|
| Disparador φ↓ hoy | rmw3 manual via python NATS publish (smoke) |
| S4 decide enviar φ↓ autónomamente | nunca |
| S5 decide enviar φ↓ autónomamente | nunca |
| Consecuencia | Canal control probado, pero solo lo usa humano |
| Severity | MEDIUM-HIGH — viabilidad autónoma requiere φ↓ automático condicionalmente |

### BRECHA-6 — BBS decisions sin enforcement

| Aspecto | Estado |
|---|---|
| S4 publica decisions a BBS | ✓ (msg_id observable) |
| Algo lee BBS para aplicar decisions | **NADA** |
| Consecuencia | S4 piensa, pensamiento no se vuelve acción |
| Severity | HIGH — el output cognitivo más caro (Qwen 40s/cycle) muere ahí |

---

## 3. Plan de cierre — mapeo brecha → tarea

| Brecha | Tarea que la cierra (total o parcial) | Effort | Status |
|---|---|---|---|
| BRECHA-1 (write-only) | **A0 deploy LXC 107** — primer reader activo | 45-60min | pendiente |
| BRECHA-2 (S4 ciego) | NUEVA: S4-CONSUMES-EVENTS — refactor S4 input | 2-3h | no creada |
| BRECHA-3 (samples 0) | **Tier β B1** — synthetic load → record_variety | 0.5d | en roadmap (B1) |
| BRECHA-4 (algedonic sin oyente) | NUEVA: S5-CONSOLE-ALGEDONIC subscriber | 30min | no creada |
| BRECHA-5 (φ↓ manual) | NUEVA: lighter S4→phi_down whitelist bridge (S5 agent es futuro alto riesgo) | 2-3h | no creada |
| BRECHA-6 (BBS dies) | NUEVA: BBS-DECISIONS-BRIDGE — lee BBS → emite phi_down whitelisted | 1-2h | no creada |

---

## 4. Plan en fases

### Fase 1 — Cierres mínimos (~2h, esta sesión)

1. **A0 deploy LXC 107** — primer reader real de events.jsonl
2. **S5-CONSOLE-ALGEDONIC** — wire suscriptor a vsf.alpha.algedonic

**Cierra:** BRECHA-1 + activa potencial BRECHA-4

### Fase 2 — Decisions enforcement (~3-5h, sesión siguiente)

3. **BBS-DECISIONS-BRIDGE** — closing BRECHA-6
4. **S5-CONSOLE-ALGEDONIC alerts visible** — extender S5 console UI

### Fase 3 — Feedback loop S4 (~2-3h)

5. **S4-CONSUMES-EVENTS** — cerrar BRECHA-2

### Fase 4 — Variedad real (~1d, Tier β)

6. **Tier β B1 synthetic load** — cerrar BRECHA-3 sin esperar BBH

---

## 5. Métricas pre-Fase 1 (baseline, este snapshot)

Tomadas de producción 2026-05-26 ~12:00 UTC:

```
events.jsonl (LXC 101):  16,038 events totales desde γ.7 deploy
  12,488 kernel_tick      (78% — heartbeat idle)
   2,906 invariant_check  (18% — empty samples)
     583 s4-analysis      ( 4% — Qwen decisions)
      11 param_change     ( <1% — todos smoke tests)
       6 phase_complete   ( <1% — bbh.smoke tunnel test ayer)

Algedonic emits production:        0
Suscriptores vsf.alpha.algedonic:   0
BBS reads producing actions:        0
φ↓ patches en producción real:      0 (solo smoke)
record_variety/trust/stasis calls:  0
```

**Score VSM pre-fase: 6.1/10**

---

## 6. Métricas post-Fase 1 (objetivo medible)

Después de A0 deploy LXC 107 + S5-CONSOLE-ALGEDONIC:

```
events.jsonl readers activos: γ.2 + vsf-s3-star LXC 107
S3* sample events emitidos: ≥1 por cycle Poisson
Suscriptores vsf.alpha.algedonic: ≥1 (S5 console)
Si covenant drift fires: end-to-end visible en S5 console
```

**Score VSM target post-fase: 6.4-6.5/10** (S3* 5→6 con deploy real, algedonic con oyente)

---

## 7. Cómo re-evaluar después de ejecutar

Después del plan, ejecutar:

```bash
# 1. Contar event types en eventos.jsonl
ssh root@n02 'pct exec 101 -- grep -oE "\"event_type\":\"[^\"]+\"" /var/lib/vsf/vsf_nucleus/events.jsonl | sort | uniq -c'

# 2. Verificar S3* corre en LXC 107
ssh root@n02 'pct exec 107 -- systemctl is-active vsf-s3-star'

# 3. Verificar S5 console suscribe
ssh root@n02 'pct exec 104 -- ps aux | grep algedonic'

# 4. Verificar nuevos event types en events.jsonl
# Esperado: + s3_star_sample, posible algedonic_emit (si drift fires)
```

Comparar contra §5 baseline. Cada brecha cerrada lifta el score VSM.

---

## 8. Referencias

- `docs/spec_revision/system/plan/strategy_plan.vsm` — estrategia Tier α/β/γ
- `docs/GAPS_AND_DEBTS.md` — registro unificado
- `docs/VSF_VSM_SCORING.md` — scoring per subsistema
- `projects/vsf-s3-star/deploy/DEPLOY.md` — A0 deploy procedure
- `core/connection_schema.json` — channel taxonomía
- memory: [[tier-alpha-complete-2026-05-26]]
