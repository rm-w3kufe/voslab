# VSF — Marco de Sistemas Viables
### Posicionamiento para inversores y colaboradores — Agosto 2026

> **Documento de outreach.** Excepción D7 documentada: escrito en español por decisión del
> autor (rmw3) para su uso directo en networking con la industria de IA en Chile.
> Contenido técnico verificado contra el kernel operativo y los experimentos del proyecto.

---

## Resumen ejecutivo

**El problema.** Los sistemas autónomos — agentes de IA, sistemas de control, automatización —
toman decisiones sin una teoría de *cuándo dejan de ser viables*. Un agente LLM puede alucinar,
derivar, o actuar fuera de su envolvente segura sin que nadie pueda garantizar lo contrario.
El costo de fallar en sistemas autónomos está subiendo: en minería, energía, manufactura y
operaciones críticas, "esperamos que no falle" ya no es aceptable.

**La propuesta.** VSF (Viable System Framework) da a los sistemas la arquitectura de control
de un organismo vivo — la cibernética de Stafford Beer (VSM, 1972), implementada como kernel
operativo: homeostasis interna, auditoría esporádica, anticipación, y política constitucional.
No es un dashboard ni otro agente: **es la capa de gobierno que los sistemas autónomos no tienen.**

**La pieza clave.** En el kernel de VSF, la separación entre lo *probabilístico* (el modelo de IA)
y lo *determinista* (el enforcement) está escrita como regla constitucional: el enforcement nunca
pasa por el modelo. La envolvente segura tiene un *bound* formal computable en cada tick, el canal
de emergencia es aritmética pura, y el escalamiento al humano está definido por constitución, no por
criterio del momento.

**Estado.** TRL 3–4 como framework (con componentes validados en TRL 4–5). El kernel corre con
datos reales (clima de Chile, ERA5) en 7 contenedores, con experimentos medidos y reproducibles.

**Qué buscamos.** Colaboradores técnicos (cibernética, control, RL, industria) y capital para:
integrar agentes LLM como unidades de trabajo reales (S1), publicar la teoría formal, y validar
en un caso industrial piloto en Chile (minería/energía/operaciones).

---

## 1. El problema — por qué ahora

Los sistemas de cómputo tradicionales (cloud, microservicios, SCADA, OT) tienen una arquitectura
de operación que se puede resumir así:

- El sistema **monitorea** y **alerta** (SRE, dashboards, on-call).
- El sistema **reacciona** a síntomas (auto-scaling, reinicios, runbooks).
- **El humano es el lazo de control**: sin un humano mirando dashboards, el sistema deriva o se cae.

Con la llegada de los agentes LLM, la industria está intentando que el sistema decida solo — pero
sin una capa de gobierno que garantice que esas decisiones se mantienen dentro de una envolvente
segura. Lo que la industria tiene hoy para gobernar agentes:

| Mecanismo actual | Limitación |
|---|---|
| Evals (evaluaciones offline) | Validan antes del despliegue, no durante |
| Guardrails de prompting | Débiles — el modelo puede alucinar su propia salvaguarda |
| Observabilidad / traces | Dicen *qué pasó*, no *qué se garantiza* |
| Rate limiting / kill switch manual | Reacción tosca, no regulación |

El gap: nadie tiene un **sistema de gobierno** para agentes — con garantías formales, un canal de
emergencia que no dependa del modelo, y escalamiento humano definido constitucionalmente.

---

## 2. Qué hace un sistema hoy vs qué hace VSF

| **Hoy (la norma)** | **VSF** |
|---|---|
| **Monitorea y alerta** — el sistema dice "algo está mal" y un humano lo arregla | **Regula** — homeostasis interna: el sistema se corrige solo mientras esté dentro de su envolvente viable Ω |
| **Umbrales fijos** — "CPU > 80% → alerta"; reglas escritas a mano, ciegas al contexto | **Función de viabilidad formal** — Ω con frontera definida matemáticamente: "¿seguimos dentro del espacio donde este sistema es viable?" |
| **Auto-scaling / auto-healing** — reacciona a síntomas | **Auto-gobierno S1–S5** — las unidades trabajan (S1), la coordinación evita pisoteos (S2), el control asigna recursos (S3), la auditoría revisa por sorpresa (S3*), la inteligencia anticipa (S4) |
| **Todas las alertas compiten por atención** | **Canal algedónico** — emergencia que salta capas solo cuando la auto-regulación no puede absorber; el humano ve solo lo que el sistema no pudo resolver solo |
| **Heurísticas de control** — "esto funcionó antes" | **Teoremas** — condiciones formales (Lyapunov, variedad requerida de Ashby) que garantizan viabilidad si se cumplen |
| **El humano es el lazo de control** | **Autonomía con techo** — el sistema opera solo dentro de su autonomía permitida (A5) y pide ayuda humana **solo para cambiar las reglas** (doble-loop) |

**La analogía para no-técnicos:** los sistemas de hoy son *termostatos* — umbral fijo, reacción
local, y si algo raro pasa, suena una alarma. VSF propone que los sistemas tengan un *sistema
inmunológico* — discriminan self/non-self, tienen memoria, responden proporcionalmente, y solo
"llaman al médico" (el humano) cuando la auto-regulación falla.

---

## 3. Las capacidades concretas (lo que la industria busca y VSF ya tiene)

Esto no es metáfora: son piezas del kernel con módulos reales y experimentos medidos.

### 3.1 Guardrails deterministas — el enforcement nunca pasa por el modelo

**Necesidad de la industria:** que la seguridad de un sistema de agentes NO dependa del modelo
probabilístico (un LLM puede alucinar su propia salvaguarda).

**Qué tiene VSF:** la regla **R10** (constitucional): el LLM (Qwen) propone, digiere, sintetiza —
pero **nunca** está en el camino del algedonic, φ↑, φ↓ ni del tick homeostático. Esos son
aritmética pura. El refinamiento R10.1: *"el LLM puede conducir tácticas, nunca hacer cumplir."*
La intención puede venir del modelo; el enforcement es determinista, siempre.

**Evidencia:** `RULES.md` R10/R10.1; `ac_classifier.py` (árbol de decisión determinista, 23 tests,
clasifica en milisegundos donde un LLM tardaría minutos).

### 3.2 Bound formal de envolvente segura — un número, no una esperanza

**Necesidad de la industria:** garantías formales de que el sistema permanece dentro de un espacio
seguro — no "esperamos que no falle".

**Qué tiene VSF:** el **teorema de prevención anticipatoria**: si el kernel aplica un pre-grant con
drift viable, la probabilidad de excursión (salida del espacio viable) está acotada por

```
q_n(σ) ≤ V(σ) / V_E
```

una función computable en cada tick, con el certificador Lyapunov del kernel midiendo la tasa de
contracción (ε_hat) en tiempo real. La misma maquinaria que garantiza convergencia (Lyapunov)
acota la probabilidad de fallo.

**Evidencia:** `docs/spec_revision/system/s4-intelligence/theory-ap-01/anticipatory_prevention.vsm` (teorema 1 y 2,
acoplado Strassen + Foster-Lyapunov); certificador en el kernel (`lyapunov.rs`,
`RecurrentSetCertifier`); `s4_local_lyapunov.vsm` (horizonte de anticipación con bound).

### 3.3 Canal de emergencia determinista — el "circuit breaker" que no depende del modelo

**Necesidad de la industria:** un canal de pánico separado, que funcione aunque el modelo esté
alucinando o caído.

**Qué tiene VSF:** el **canal algedónico** — señal de emergencia con niveles de severidad
(sev-10 = sepsis) que salta capas por un canal propio, sin interpretación del LLM. Es el
"circuit breaker" que los agentes no tienen.

**Evidencia:** `vsf-s5-algedonic` (LXC 104), `vsf-g6-algedonic-sink`, EXP-TRUST-01 (constante de
confianza λ=0.10 medida, con triage automatizado).

### 3.4 Autonomía graduada constitucional — cuándo decide el sistema, cuándo el humano

**Necesidad de la industria:** escalamiento humano definido — no por criterio del momento, sino por
regla.

**Qué tiene VSF:** la **constitución del sistema (covenant)** define el techo de autonomía por capa:
`autonomy(V) ≤ S5.ceiling`. L2 (drift de parámetros) = autónomo; L3 (cambio de axiomas/topología) =
**doble-loop, siempre requiere humano**. El sistema distingue entre *operar dentro de las reglas*
(single-loop, automatizable) y *cambiar las reglas* (double-loop, humano).

**Evidencia:** `covenant_ops.vsm` (axioma A5), decisión D4 (HANDOFF), `docs/spec/strategic_tactical_authority.vsm`.

### 3.5 Auditoría inmutable — cada decisión firmada, no-reescribible

**Necesidad de la industria:** auditar qué decidió el agente, cuándo, y que no se pueda reescribir.

**Qué tiene VSF:** cadena **Merkle de eventos firmados (Ed25519)** — cada evento encadenado por hash,
con verificación diversa que detecta escritores no declarados, manipulación de contenido y
reinicios encubiertos. Auditoría esporádica (S3*) que ve lo que el control normal no ve.

**Evidencia:** `events.jsonl` con hash chain, `vsf-s3-star` (LXC 107, reconciliación cada 5 min).

### 3.6 model ≡ reality — el sistema verifica que su modelo coincide con el mundo

**Necesidad de la industria:** el problema clásico de los agentes: alucinan porque su modelo interno
se desalineó de la realidad.

**Qué tiene VSF:** **reconciliación continua** — el sistema compara lo declarado contra lo observado
y detecta *drift*. Si el modelo interno se desalinea de la realidad, es un bug, no una opinión.
`state.db` es la única fuente de verdad, y la verificación model≡reality es operación de primer
orden (detectó, por ejemplo, un bug real del parser del propio proyecto).

**Evidencia:** `state.db` (única fuente de verdad), verificación de drift operativa en scripts del proyecto.

---

## 4. TRL — estado de madurez (lectura honesta)

Escala NASA: 1 = principios básicos observados … 4 = validación en laboratorio … 7–9 = entorno
operacional/comercial.

| Capa | TRL | Evidencia |
|---|---|---|
| **Framework VSF completo** (S1–S5 integrados, agentes LLM como S1 reales, usuarios externos) | **2–3** | Concepto formulado + prueba de concepto experimental |
| **Kernel como software** (vsf-nucleus, datos reales ERA5/clima, 7 LXCs) | **4** | Corre en entorno relevante, telemetría real, experimentos repetibles |
| **Componentes validados** (certificación Lyapunov, compresión VSL, confianza medida) | **4–5** | Resultados cuantitativos reproducibles (644 checks sin pérdidas, λ=0.10 medido) |

**Por qué no más:** no hay usuarios externos, papers aún no publicados, ni integración con un S1
industrial real — esos son los pasos siguientes.

**Qué falta para subir de nivel:**
1. Integrar agentes LLM como S1 reales (la pieza BBH, pendiente por diseño — R6).
2. Publicar la teoría formal (papers de convergencia y prevención).
3. Un piloto industrial en Chile (minería/energía/operaciones) que valide en entorno operacional.

---

## 5. La arquitectura (para el colaborador técnico)

**Los cinco subsistemas** (Beer, VSM 1972):

```
S1 Operations    — las unidades que hacen el trabajo (agentes, sensores, procesos)
S2 Coordination  — evita que las unidades se pisen entre sí (broker NATS)
S3 Control       — asigna recursos, mantiene homeostasis (kernel, S3 allocator)
S3* Audit        — auditoría esporádica: ve lo que S3 no ve (reconciler, cada 5 min)
S4 Intelligence  — mira el entorno, anticipa (proyección dual-channel, horizonte Lyapunov)
S5 Policy        — la constitución: reglas que nadie puede sobreescribir (covenant, algedónico)
```

**Canales:** φ↑ = telemetría (hijo → padre); φ↓ = política/acciones (padre → hijo). El algedónico
es un canal de emergencia separado que salta capas.

**Implementación operativa (2026):** kernel Rust (`vsf-nucleus`) en el núcleo S3/S4; 7 contenedores
LXC con funciones S1–S5; NATS como broker de coordinación (S2); `state.db` como única fuente de
verdad; cadena Merkle firmada como registro inmutable; Qwen (LLM) en rol de propuesta/digestión
(S4), nunca en el enforcement.

**La pieza teórica:** compresión de especificación VSL (72% de densidad media, cobertura semántica
100% — 644 checks sin pérdidas), que permite que la especificación de un sistema viable sea
exponencialmente más pequeña que su variedad total — la implementación computacional de la Ley de
Variedad Requerida de Ashby.

---

## 6. Evidencia — experimentos medidos

| Experimento | Qué mide | Resultado |
|---|---|---|
| EXP-TRUST-01 | Confianza en el triage automatizado | λ=0.10 medido, canal de confianza operativo |
| EXP-LYAP-CERT | Certificación Lyapunov | r_core recalibrado 0.50→0.20 contra datos |
| Thermal (v1–v4) | Estrés térmico del kernel | TARGET_REACHED 63°C, homeostasis bajo presión |
| Compresión VSL | Densidad de especificación | 9811→2737 líneas, densidad media 72.1%, cobertura 100% |
| Prevención anticipatoria | Bound de excursión | Teorema q_n ≤ V(σ)/V_E, condicional a EXP-S4-01 |

---

## 7. Qué necesitamos — siguientes pasos

**Colaboradores técnicos:**
- Cibernética / teoría de control (validar y extender los teoremas).
- Ingeniería de agentes LLM (integrar agentes como S1 con guardrails constitucionales).
- Industria (minería, energía, manufactura) para un piloto real.

**Capital:**
- Financiar la integración de agentes LLM como S1 (la pieza que convierte el framework en la capa
  de gobierno de agentes — el caso de uso que la industria está buscando).
- Publicación de la teoría (papers, conferencias) para anclar la credibilidad científica.
- Piloto industrial: validar en un entorno operacional real y subir de TRL 4 a TRL 6.

**El argumento en tres frases:**
1. Los sistemas de hoy te dicen cuándo fallan; la industria necesita sistemas que se mantengan
   viables por diseño.
2. VSF tiene en el kernel lo que la industria busca para gobernar agentes: enforcement
   determinista (R10), bound formal de envolvente segura (Lyapunov), canal de emergencia
   algedónico, y escalamiento humano constitucional (A5/D4).
3. Está en TRL 3–4, con componentes validados en TRL 4–5 — y el siguiente paso natural es
   integrar agentes LLM reales y validar en un piloto industrial.

---

## Apéndice A — Glosario mínimo (para no-técnicos)

| Término | Qué significa |
|---|---|
| **VSM / S1–S5** | Arquitectura de control de un organismo vivo (Beer, 1972): unidades de trabajo, coordinación, control, auditoría, inteligencia, política |
| **Homeostasis** | La capacidad del sistema de corregirse solo para mantenerse dentro de su rango viable |
| **Ω (envolvente viable)** | El espacio de estados donde el sistema sigue siendo viable — definido matemáticamente |
| **Algedónico** | Canal de emergencia con niveles de severidad — como el dolor en un organismo: avisa cuando algo no se pudo auto-corregir |
| **φ↑ / φ↓** | Telemetría hacia arriba / política hacia abajo — la comunicación entre capas del sistema |
| **Doble-loop** | Cambiar las reglas del juego (requiere humano) vs jugar dentro de las reglas (automatizable) |
| **Lyapunov** | Herramienta matemática que garantiza estabilidad/convergencia — la base del bound formal |
| **TRL** | Escala NASA de madurez tecnológica (1 = idea, 9 = en producción) |
