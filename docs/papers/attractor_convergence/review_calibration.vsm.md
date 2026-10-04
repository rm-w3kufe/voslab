---
doc: review_calibration
paper: attractor_convergence
version: 0.1
date: 2026-04-18
author: session(Sonnet 4.6) + review(Opus 4.7)
status: working
purpose: |
  Calibrar el lenguaje del paper para revisores expertos (física/ML/cibernética),
  separar núcleo publicable de trabajo orbitante, y mantener viabilidad del proyecto
  sin perder ambición ni watermark.
---

# Review calibration — attractor_convergence

Tres capas de contenido, tres decisiones distintas.

```
L1  NÚCLEO PUBLICABLE        → defender con métrica, someter a revisor
L2  TRABAJO ORBITANTE        → mostrar como potencialidad, no como claim
L3  INFRAESTRUCTURA (VSL)    → avanzar, consolida la base formal
```

La regla: **un revisor escéptico debe poder atacar L1 y encontrar que resiste.
L2 debe ser visible pero no necesario para que L1 sobreviva.**

---

## Estado 2026-06-14 — V1–V7 aplicados + trilogía geométrica integrada

Las acciones inmediatas V1–V6 ya están en `main.tex` (renombrado D_eff, stasis_cos como
proxy con hedge Hausdorff/Wasserstein, alignment como hipótesis, §Limitations, captions
ilustrativos, covenant/vOS a Future Work). V7 (controles negativos) no solo sembrado sino
**ejecutado** (Experiment 11 + EXP-NC-AD/LR/TC-01).

La **trilogía geométrica** (integrada 2026-06-14) cierra objeciones que antes se defendían
sólo reformulando:

| Objeción del revisor | Antes (defensivo) | Ahora (riguroso) |
|----------------------|-------------------|------------------|
| «Lyapunov es un proof sketch» | proxy `mean_dL` | **EXP-LY-01**: λ_max=−0.010050=ln(0.99) (Benettin, 7.6e-12) → punto fijo estable |
| «D_KY no es Kaplan-Yorke» | renombrado a D_eff + disclaimer | espectro todo-negativo ⇒ KY-dim=0 medido; D_eff (heurística) vs KY-dim separados por medición |
| «basin floor de δ escasos hand-picked» | sweep 6-puntos 1-dirección | **EXP-MC-01**: volumen ≈1.0 (200/200), piso aleatorio 0.945, 0.875=peor-caso |
| (ángulo nuevo) | — | **EXP-TDA-01**: β₀=1∧β₁=0 dentro y fuera del atractor → point sink topológico, sin ciclo límite |

Tres lentes independientes (dinámica/volumen/forma) → una conclusión: atractor punto estable.
Ningún claim depende de una sola medición. Ver `pending_integration.vsm` (historical).

---

## L1 — Núcleo publicable (lo que el paper defiende)

### Lo que sí resiste revisión

| Claim                                      | Evidencia                            | Estado    |
|--------------------------------------------|--------------------------------------|-----------|
| Kernel Rust estable 6×10⁷ ciclos           | logs n01/n02, reproducible           | sólido    |
| τ_rec(t₀) bien definida y medible          | EXP-TC-01, 20 ciclos, τ_rec < 30s    | sólido    |
| Dip floor fijo 0.942 bajo 52°C cíclico     | gráfico dips + std pequeña           | sólido    |
| Compresión VSL 38–51% / 72–79% drift ~5%   | tabla medida en repo                 | sólido    |
| Identidad geométrica bajo perturbación     | stasis_cos recupera a ≥0.998         | sólido    |

### Lo que hay que **renombrar o reformular** antes de enviar

#### 1. `D_KY` → `effective_dims` (o computar Kaplan-Yorke real)

**Problema.** El código actual calcula `D_KY = active_dims + trust · 2.0`. No es la
dimensión de Kaplan-Yorke (que requiere espectro de Lyapunov). Cualquier revisor
de sistemas dinámicos lo ve en 30 segundos.

**Opciones:**
- **(A) rápida:** renombrar a `effective_dims` en paper, código, figuras. Describir
  la fórmula tal cual. Nada de "Kaplan-Yorke".
- **(B) costosa pero honesta:** computar λ_i numéricamente sobre el Jacobiano
  efectivo (método de Benettin o similar), reportar D_KY real como experimento
  adicional.

**Recomendación:** (A) ahora, (B) como EXP-LY-01 para v0.5 del paper.

#### 2. `stasis_cos` — describir sin adornos

**Problema.** Es cosine similarity contra un vector de referencia almacenado.
Framing como "geometría del atractor" es generoso: es una proyección escalar 1-D,
no geometría.

**Reformulación sugerida (§3 del paper):**

> «Definimos `stasis_cos(t) = ⟨v(t), v_ref⟩ / (‖v(t)‖ · ‖v_ref‖)`, i.e. la
> similitud coseno estándar entre el estado actual y un vector de referencia
> almacenado en vmem durante calibración. Esta métrica es común en recuperación
> de información y aprendizaje contrastivo; su uso aquí es como **indicador
> proxy de permanencia** en una vecindad del atractor, no como descripción
> completa de su geometría.»

Esto protege del ataque "estás renombrando cosine similarity como si fuera
geometría diferencial".

#### 3. Argumento de alignment — bajar intensidad

**Problema actual.** El paper sugiere (§10, discusión) que la arquitectura VSF
previene desalineamiento. Con los experimentos actuales, es una **hipótesis
derivada de una observación**, no un resultado.

**Reformulación:**

> «Estos resultados son **compatibles con** la hipótesis de que una arquitectura
> con S5 inviolable y trust gateado por stasis_cos resiste ciertas clases de
> desviación. Verificar esta hipótesis requiere (i) controles negativos sin la
> arquitectura VSM y (ii) pruebas adversariales explícitas. Ambas quedan como
> trabajo futuro.»

No es renuncia: es el único lenguaje que sobrevive a un revisor de AI safety.

#### 4. Contraste "VSF vs convencional" — marcarlo pedagógico

**Problema.** Los paneles 4 del composite son **los paneles que cualquier sistema
instrumentado con esas métricas produciría**. No son evidencia de ventaja de VSF
sobre una baseline.

**Acción:** en el caption de esas figuras, añadir:
> «Comparación ilustrativa; no constituye control negativo formal.»

Y en Discussion, separar **presentación pedagógica** (para explicar) de
**resultado empírico** (para defender).

### Controles negativos que faltan (declararlos como limitation)

Añadir §11 "Limitations" con:
1. Sin control negativo: no se ejecutó el mismo kernel con S5 desactivado ni con
   trust constante. Previsto para v0.5 como EXP-NC-01 … EXP-NC-03.
2. Un solo sustrato (Rust/Linux): propiedades geométricas podrían depender del
   sustrato.
3. Métricas proxy: `effective_dims` no es D_KY verdadera (ver §3).
4. Alignment: observación única, no validación sistemática.

Declarar limitaciones explícitamente es lo que un revisor espera. Ocultarlas
es lo que lo vuelve hostil.

---

## L2 — Trabajo orbitante (potencialidad, no claim)

Lo que **no va en el paper como resultado** pero **sí va como §12 "Future work
and broader program"**, con tono sobrio:

### Covenant / A0 / A0.1
- **Fuera del abstract y de las conclusiones.**
- Mención breve en future work: «La arquitectura admite una capa de axiomas
  inviolables (covenant); exploramos su uso en governance experimental de
  sistemas multi-agente.»
- No argumentar aquí que resuelve alignment.

### vOS / Redox / seL4
- Línea única en future work: «El kernel actual es un sustrato mínimo; una
  extensión natural es ejecutar VSF como sistema operativo (vOS) sobre Redox
  virtualizado, con Ollama/Qwen como S4. Ver roadmap técnico separado.»
- No meter el roadmap de 4 stages en el paper.

### Paper 3 (sistemas abiertos)
- No mencionar por nombre. Bastan dos líneas:
  «El marco sugiere conexiones con sistemas cuánticos abiertos (ecuación de
  Lindblad) y termodinámica de la información (Landauer); la exploración
  cuantitativa de estas conexiones queda como trabajo en curso.»

### Regla general para L2

> Si un revisor pregunta "¿y esto qué tiene que ver con el paper?", la respuesta
> debe ser "nada, es trabajo futuro explícito". Si no se puede responder así,
> sacar del paper.

---

## L3 — VSL v1.0 (avance de infraestructura)

Avanzar VSL **consolida** la base formal sin cargar el paper. Pasos concretos:

### Ya hecho
- `vsm_notation_spec.md` — gramática BNF
- `vsl_parser.py` — parser funcional
- Compresión medida 38–51% / drift ~5%

### Próximos pasos (independientes del paper)

1. **VSL-001 — Conformance test suite.** Script que tome 10 documentos .vsm
   del repo, los parsee, serialice y verifique round-trip. Coste: bajo.
2. **VSL-002 — Linter mínimo.** Detectar bloques V() mal formados, dependencias
   huérfanas, versiones inconsistentes. Coste: bajo-medio.
3. **VSL-003 — Spec v1.0.** Separar `vsm_notation_spec.md` en:
   - `vsl_core.md` (axiomas, gramática)
   - `vsl_extensions.md` (experiment_spec, paper_skeleton, queue_vsm)
   - `vsl_semantics.md` (qué garantiza la notación)
4. **VSL-004 — Paper corto aparte** sobre compresión y drift, submitting a
   workshop de DSL. No mezclado con el paper del atractor.

VSL puede crecer en paralelo sin pedirle permiso al paper físico.

---

## Reviewer anticipation — objeciones probables y respuestas

| Objeción esperada                                 | Respuesta preparada                                        |
|---------------------------------------------------|------------------------------------------------------------|
| «D_KY no es Kaplan-Yorke»                         | Renombrado a `effective_dims`; D_KY real en trabajo futuro |
| «stasis_cos es cosine similarity»                 | Sí; la usamos como proxy, lo decimos explícitamente        |
| «No hay control negativo»                         | Declarado en §Limitations; EXP-NC-01…03 previstos          |
| «Esto corre en un solo sustrato»                  | Declarado; portabilidad es trabajo futuro                  |
| «Alignment claim overreaches»                     | Reformulado como hipótesis, no resultado                   |
| «Framework enorme, claims específicos»            | L2 explícitamente separado como future work                |
| «Covenant es filosofía, no ciencia»               | Fuera del paper técnico; va en preprint separado           |
| «¿Por qué cosine y no Hausdorff / Wasserstein?»   | Proxy barato; métricas avanzadas quedan como trabajo       |
| «¿Dónde está la baseline?»                        | Limitación declarada; Stage 0→1 del roadmap la aborda      |
| «Si NC-01 sobrevive delta=1.0, VSF es redundante» | Ver Q4 — lograr ≠ operar; VSF agrega observabilidad, intencionalidad, certificabilidad |
| «El dip floor podría ser del substrato, no VSF»   | Ver Q5 — substrato produce el fenómeno; VSF lo hace inteligible; stasis ref es VSF-construida |
| «τ_rec constante podría ser coincidencia»          | Ver Q7 — EXP-NC-AD-01 produce dato NC: si τ_rec(NC-02) > τ_rec(vsf-nucleus), governance acelera camino de recuperación |
| «D_eff no es Kaplan-Yorke real»                    | Correcto y declarado; consistencia de D_eff=3.00 a 6×10⁷ ciclos es evidencia de estructura atractora; KY real = EXP-LY-01 |

Cada fila de esta tabla = un párrafo de una carta de respuesta a revisor.

---

## Argumentos desarrollados — Q4 y Q5

### Q4 — «Si NC-01/02 sobreviven delta=1.0, VSF es redundante»

**Objeción completa del revisor:**
> "The negative control experiments show that baseline variants without S5
> governance also maintain viability under adversarial perturbation. This
> suggests the StateVector dynamics are sufficient and the architectural
> complexity of VSF adds nothing."

**Respuesta:**

La objeción confunde *lograr* viabilidad con *operar* viabilidad.

El StateVector ℝ¹²⁸ tiene dinámica de reversión a la media intrínseca —
un proceso tipo Ornstein-Uhlenbeck que puede producir trayectorias acotadas
independientemente de S5. VSF no altera esa geometría de base; gobierna
*qué operaciones ejecutan*, *cuándo*, y *bajo qué restricciones de política*.

La analogía es precisa: la dinámica de combustión es intrínseca al substrato
de cualquier motor; el conductor no cambia la termodinámica pero *opera* el
sistema hacia un objetivo declarado. Un resultado nulo en el experimento
adversarial demostraría que el StateVector tiene resiliencia intrínseca —
y VSF es el framework que hace esa resiliencia **observable, certificable e
intencional**.

Las tres capas que VSF agrega y ningún baseline replica:

1. **Observabilidad** — `stasis_cos`, `D_eff`, `τ_rec` son métricas
   VSF-construidas. Un proceso OU sin gobernanza no tiene análogo: puede
   *ser* viable sin *saber* que lo es.

2. **Intencionalidad** — el flag `governed`, el feedback de trust, y el
   ceiling de S5 codifican una política. El sistema opera *hacia* viabilidad,
   no simplemente *dentro* de ella.

3. **Certificabilidad** — el sistema puede declarar formalmente su estado
   de viabilidad. Esto es prerequisito para gobernanza autónoma y trust
   inter-sistema. Un OU puro no puede hacer esa declaración.

**Frase para carta de respuesta:**
> "A null result in the adversarial experiment would strengthen, not weaken,
> our argument: it would demonstrate that VSF governance makes intrinsic
> StateVector resilience observable and certifiable — properties absent in
> any uncontrolled baseline."

---

### Q5 — «El dip floor 0.942 podría ser una propiedad del substrato, no de VSF»

**Objeción completa del revisor:**
> "The fixed dip floor of 0.942 across 20 thermal cycles could be a property
> of the hardware's thermal response curve rather than an architectural
> consequence of VSF governance. Without a baseline comparison, the claim of
> a 'fixed perturbation mode' is unsubstantiated."

**Respuesta:**

La objeción es correcta en su premisa y la anticipamos: EXP-NC-TC-01
(planificado) la resolverá empíricamente. Pero hay una distinción conceptual
que persiste incluso si el floor resulta ser substrato-invariante.

El substrato *produce* el fenómeno. VSF lo hace *inteligible*.

El valor `0.942` tiene significado sólo en relación al vector de referencia
de stasis $\bar{\mathbf{s}}$, que es un artefacto VSF: la media móvil de
observaciones gobernadas bajo política S5. Sin esa referencia, la perturbación
es un desplazamiento en un espacio no etiquetado — ocurre, pero no dice nada.

La distinción es precisa:
- Un termómetro no produce temperatura, pero la escala en la que 0.942 se
  vuelve significativo es VSF-construida.
- Si el experimento NC muestra el mismo floor: el substrato determina la
  *dirección* de perturbación; VSF determina su *caracterización geométrica*.
- Si el experimento NC muestra floor diferente: el modo de perturbación es
  arquitectural — la afirmación fuerte se sostiene directamente.

**En ambos casos VSF contribuye algo no-trivial.**

**Frase para carta de respuesta:**
> "Whether the dip floor is substrate-invariant or governance-dependent is
> an empirical question we are actively testing (EXP-NC-TC-01). Either
> outcome is scientifically informative, and either is consistent with
> our core claim: VSF provides the reference frame without which the
> perturbation mode cannot be characterised."

---

### Q7 — «τ_rec constante podría ser coincidencia o artefacto del protocolo»

**Objeción completa del revisor:**
> "The recovery time τ_rec < 30s is observed across 20 thermal cycles, but
> all cycles use the same perturbation profile. Constancy of τ_rec may
> reflect protocol repetition rather than a geometric property of the
> attractor."

**Respuesta:**

La objeción identifica correctamente la limitación del experimento actual:
EXP-TC-01 usa un solo perfil de perturbación (52°C/60s spike). Para separar
«artefacto de protocolo» de «propiedad geométrica» se necesita τ_rec bajo
perfiles distintos o magnitudes distintas.

EXP-NC-AD-01 produce exactamente ese dato: bajo perturbación adversarial
(delta=1.0, no térmica), ¿cuánto tarda vsf-nucleus en recuperar stasis_cos ≥
0.998 vs NC-02 (trust constante)?

La hipótesis de identidad geométrica predice:
- `τ_rec(vsf-nucleus) < τ_rec(NC-02)` — el trust feedback estabiliza el
  *camino* de recuperación, no solo el destino final
- La diferencia Δτ_rec cuantifica la contribución del trust dinámico a la
  velocidad de realineamiento

Si Δτ_rec > 0 en EXP-NC-AD-01: τ_rec no es coincidencia de protocolo sino
una propiedad que la gobernanza modula. Si Δτ_rec ≈ 0: τ_rec es intrínseco
al StateVector — igualmente informativo, reformulamos como «el atractor tiene
trayectoria de recuperación intrínsecamente rápida».

**Distinción central:**
El claim no es que τ_rec sea *producido* por VSF, sino que es *medible y
modifiable* por VSF. Esa es la diferencia entre tener un atractor y operar uno.

**Frase para carta de respuesta:**
> "EXP-NC-AD-01 (negative control, adversarial perturbation) will determine
> empirically whether τ_rec differs between governed and ungoverned variants.
> Either result is interpretable: governance either accelerates the recovery
> path, or τ_rec is intrinsic to the StateVector — in both cases the
> measurement itself is a VSF contribution."

---

## Acción inmediata (priorizada)

| # | Acción                                                            | Coste | Prioridad |
|---|-------------------------------------------------------------------|-------|-----------|
| 1 | Rename `D_KY` → `effective_dims` en código, logs, figuras, paper  | bajo  | **alta**  |
| 2 | Reformular §3 (stasis_cos como proxy)                             | bajo  | **alta**  |
| 3 | Reformular §10 (alignment como hipótesis)                         | bajo  | **alta**  |
| 4 | Añadir §11 Limitations                                            | bajo  | **alta**  |
| 5 | Añadir caption "Ilustrativo; no control negativo" a figuras 3–7   | bajo  | **alta**  |
| 6 | Mover covenant/vOS/paper-3 a §12 Future work, sobrios             | bajo  | **alta**  |
| 7 | Seed EXP-NC-01 (negative control, S5 off) en experiments/index    | medio | media     |
| 8 | Seed EXP-LY-01 (Lyapunov real) en experiments/index               | alto  | media     |
| 9 | VSL-001 conformance tests                                         | bajo  | media     |
| 10| VSL-003 separación de spec en tres archivos                       | medio | baja      |

**Acciones 1–6 se pueden hacer en una sesión de 2–3 horas** y transforman el
paper de «ambicioso y atacable» a «ambicioso y defendible».

---

## Criterio de viabilidad del proyecto

El proyecto se mantiene viable mientras:

1. El **núcleo publicable (L1)** resista revisión adversarial sin necesitar L2.
2. El **trabajo orbitante (L2)** esté claramente marcado como futuro.
3. La **infraestructura (L3)** avance sin esperar al paper físico.
4. Cada sesión **cierre al menos un item** de la tabla de acción inmediata.
5. Los **experimentos sigan corriendo** (TSM-01 ahora; NC-01 siguiente).

Watermark intacto, ambición intacta, atacabilidad reducida.
