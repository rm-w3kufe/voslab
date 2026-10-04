# Boceto de revisión del relato — attractor_convergence (pre-formalización)

**Fecha:** 2026-06-14 · **Estado:** boceto para revisión (NO tocar main.tex aún)
**Origen:** sesión 2026-06-14 — costura instancia↔invariante + reparación Fierro + capstone de constante de viabilidad.

> Regla de la revisión: el paper debe sostener DOS afirmaciones sin que se pisen —
> (a) *este* kernel converge a un point sink limpio (descriptivo, medido = trilogía);
> (b) *cualquier* sistema axioma-gobernado mantiene viabilidad certificable (invariante = método + Q1-Q3).
> La trilogía sirve a (a). Fierro/Q1-Q3 + el marco agnóstico sirven a (b). Hoy (b) está disperso.

---

## La costura central: instancia ↔ invariante

| | INVARIANTE (transfiere a cualquier VSF) | INSTANCIA (vsf-nucleus) |
|---|---|---|
| Espacio | "el dominio induce un ℝⁿ" | n=128, 7 bloques A–G |
| Existencia | atractor puntual bajo axiomas consistentes | λ_max=ln(0.99), D_eff≈3, β₀=1 |
| Estabilidad | estocástica en expectativa (Teorema 2) | dip floor 0.942, Ω concreto |
| Certificación | protocolo Q1–Q3 (Fierro) | σ_max=0.42, margen 0.175 |
| Gobernanza | 2 tiers: arquitectura elige cuenca / gobernanza opera recuperación | la cuenca de este kernel |

Todo el relato revisado consiste en **hacer visible esta tabla** en el lugar correcto.

---

## Cambios por sección (qué dice hoy → qué debería decir → por qué)

### §1 Introduction
- **Hoy:** ya enmarca ℝ¹²⁸ como *"a concrete computational artefact"* y ya nombra los dos tiers
  (arquitectura/gobernanza). Buena base.
- **Cambio:** una frase que declare explícitamente que ℝ¹²⁸ es **una realización**, no el objeto de
  estudio en sí; que lo que se estudia es *cómo* la estructura VSM produce viabilidad certificable,
  *medido* en una instancia completamente instrumentada.
- **Por qué:** prepara al lector para leer los números específicos como evidencia de existencia,
  no como ley universal.

### §2 State Space Formalism
- **Hoy:** *"the complete state of a vOS kernel… ∈ ℝ¹²⁸"* — presentado como fijo.
- **Cambio:** párrafo nuevo **"State space as a domain-induced object"**:
  las dimensiones son las **variables relevantes a la viabilidad** de *este* sistema; otro sistema
  viable induce otro ℝⁿ; lo que persiste no es n sino la estructura de bloques (identidad / recursos /
  entropía / operaciones / canales / memoria de atractor / inteligencia).
- **Por qué:** es el primer punto donde el lector podría pensar "128 es arbitrario". Hay que
  responderlo ahí mismo: 128 = consecuencia de *este* dominio, no del marco.

### §3 The Feasible Region Ω  +  §4 Lyapunov  (aquí entra Fierro, dominio-neutral)
- **Hoy:** Ω = ∩{A_i} (no convexo); existencia *"By Brouwer's fixed-point theorem"* sobre ese Ω;
  el problema solo se confiesa en §Limitations; Fierro acreditado genéricamente.
- **Cambio (la edición clave):**
  1. Presentar Ω y la existencia **en forma dominio-neutral primero**, luego instanciar a ℝ¹²⁸.
  2. Soltar Brouwer-sobre-no-convexo. Reemplazar por:
     - relajación convexa explícita Ω_conv = {x : Ax ≤ b}  →  existencia por **Krasnoselskii**
       (compacto + mapa continuo en convexo);  **o**
     - marco de **viabilidad estocástica (Aubin 1991)**: Ω como conjunto de viabilidad *en
       probabilidad*; el Teorema 2 (E[ΔL]≤0, **ya está**) carga la convergencia.
  3. El **λ_max<0 medido** (trilogía) convierte "existe atractor" de *proof sketch* a **contracción
     medida**: Brouwer deja de ser necesario.
  4. Citar Aubin / Krasnoselskii en references.bib (hoy ausentes). Acreditar a Fierro con sustancia
     (su crítica produjo *esta* corrección) — footnote o párrafo, no solo Acknowledgements.
- **Por qué:** el marco de Aubin **no depende de n** → la reparación Fierro *es* el lado invariante.
  Una sola edición resuelve la objeción matemática más profunda Y entrega el marco agnóstico.
- **YA EXISTE la solución (adaptar, no inventar):** `Revisiones/debate_solucion_interactivo.html` trae el
  **Teorema VSL-MATH-01 (Invariancia Híbrida)**: Ω_A contractiva (L<1) ⇒ medida invariante (Krasnoselskii)
  + convergencia en expectativa (Lyapunov estocástico) + τ_rec<30s (confinamiento). Mapeo axioma→convexo
  (A0 bola · A3 semiespacio · Aε subnivel cóncavo). Núcleo Ω_A={cos≥0.88}⊂Ω={cos≥0.70}. ε_frontier=
  √(2(1−θ))=0.775 derivado. §4 = adaptar esto + trilogía (λ_max medido reemplaza el bound Jacobiano).
  ⚠ declarar la tensión L≈0.85 (Jacobiano Ω_A) vs λ_max=ln0.99 (4-estados) — operadores distintos.

### §6.3 + §7 (trilogía — ya integrada)
- **Cambio menor:** una frase-puente que marque los números como **instancia**:
  *"these values (λ=ln 0.99, D_eff≈3, β₀=1) certify this realization; the method, not the numbers,
  is what transfers."*
- **Por qué:** desactiva "mediste tu propio objeto" justo donde los números son más específicos.

### §Discussion / §Future Work — subsección NUEVA: "What VSF can model"
- **Contenido:** la receta de modelado + la clase de sistemas + Q1-Q3 como transferencia + Papers 2–5
  como instancias-ℝⁿ distintas. (detalle abajo)
- **Por qué:** VSF se define como *domain-agnostic* y el paper insignia no lo carga. Esta subsección
  es donde el claim agnóstico se vuelve preciso y acotado.

---

## Subsección nueva: "What can be modeled in a VSF" (esqueleto)

> Un sistema admite modelado VSF si y solo si:
> 1. sus **variables relevantes a la viabilidad** son enumerables → eso *es* su ℝⁿ;
> 2. sus axiomas/restricciones se expresan como un **recorte de una región Ω**;
> 3. su dinámica es **actualización determinista + perturbación estocástica acotada** (f₀ + σ·η).
>
> Frontera honesta (qué *no* se modela): sistemas sin variables de viabilidad enumerables,
> o cuyos axiomas no son expresables como restricciones, o con perturbación no acotada.
>
> Mecanismo de transferencia = **protocolo Q1–Q3** (`domain_validation_protocol.vsm`):
> cada dominio re-corre Q1 (definir Ω en su ℝⁿ), Q2 (certificar contracción L<1), Q3 (hallar σ_max).
> Disciplina de claim: *el método transfiere; que todo dominio produzca un atractor puntual es una
> pregunta empírica por dominio* — por eso Q1–Q3 se re-corre, no se asume.
>
> Instancias (Papers 2–5, herencia en `fierro_bridge_to_operations.vsm`):
> cada una es un ℝⁿ distinto heredando el método — substrato simbólico (VSL), sistemas abiertos
> (Landauer), compresión atractora (D_eff≪N), gobernanza financiera (ℝ^banca).

---

## Arco substrate-spanning: tres modos de instanciación (desarrollo del corolario)

> El claim agnóstico, llevado al límite, revela que VSF se instancia sobre sustratos que difieren
> en **cómo se impone Ω** y en **si la viabilidad se certifica o se enacta**. No son dos modos
> (numérico / semántico) — son **tres**, porque el LM crudo y el *agente* que lo envuelve son
> sistemas distintos.

| | **Modo 1 — Numérico** (kernel) | **Modo 2 — Semántico** (LM crudo) | **Modo 3 — Cibernético** (agente) |
|---|---|---|---|
| Sustrato | ℝ¹²⁸, Rust | espacio latente ℝ^d_model | LM + tools + DBs + memoria + loops + VSL |
| Ω | explícito (Ax≤b), restricción dura | implícito, restricción **blanda** de razonamiento | impuesto por la **orquestación** (audit loops, gates A5, covenant fail-closed) |
| Viabilidad | **certificada** (λ_max, β, stasis_cos medidos) | **enactada** (razona "como si" viable) | **híbrida** (razonamiento enactado + estado/audit certificados en DBs) |
| Realización VSM | simulada en un proceso | ninguna estructural — adopta la *lógica* | la **más literal**: S1=tools · S2=VSL/harness · S3=loop de control · S3\*=reconcilers · S4=LM+memoria · S5=covenant |
| Capa (D6) | L0/L1 (sin LLM) | L≥2 (cognitivo) | L≥2, con estado y recursión |
| Estado en el programa | **Paper 1 (medido)** | semilla Paper 2 (VSL, EXP-PHI-01) | semilla vOS / programa amplio |

**El gradiente:** certificada → enactada → híbrida. El eje es *certificar-vs-declarar* (DSN-EVC-01).

**Modo 3, el punto que agregaste:** el método de razonamiento del agente **no vive en los pesos del
LM** — vive en la *arquitectura*: las revisiones (S3\* doble-loop), los loops, las bases de datos
(state.db, memoria, events.jsonl), y el lenguaje formal (VSL). Un predictor de siguiente-token sin
estado se vuelve un razonador **con estado, auto-corrector y viable** precisamente por esa
orquestación cibernética. Es el VSM más literal de los tres: tiene S1–S5 realizados en software.

**Remate recursivo:** el agente (un VSM) **instancia y gobierna** el kernel numérico (otro VSM) — es
`recursive_vsm_theory` vuelto operación. La memoria de DBs juega el rol de V_mem; los reconcilers
juegan S3\*; el covenant/CLAUDE.md juega S5. Apunta directo a vOS (LLM=S4 en el stack completo).

**Cómo V abarca los tres:** el funcional coordinate-free **V** es el candidato a certificado para
los tres modos — en Modo 1 se *mide*; en Modos 2–3 es el *objetivo abierto* (no afirmar que ya
certifica). V es lo que unifica el espectro: el mismo invariante de viabilidad, distinto sustrato.

### Disciplina de claim (la línea que NO se cruza)
- **Cuerpo de Paper 1 = solo Modo 1** (medido). Abstract/Contributions/resultados: intactos.
- **Modos 2–3 = semillas sobrias en Future Work.** Modo 2 → Paper 2 (VSL inter-LLM). Modo 3 → vOS /
  programa amplio. Una frase cada uno + el puente a V.
- **El ángulo auto-referencial** (este paper fue co-creado por un agente Modo 3 operando bajo VSF) =
  **FUERA del cuerpo riguroso.** Es evidencia vivencial pero **circular** — un revisor lo destroza.
  Aside filosófico para Paper 2 / framing, no claim.
- **Camino falsable existe** (Modo 2/3: ¿el LM con axiomas se mantiene en las restricciones más que
  sin ellos? — conductual, como los controles negativos) pero es **metodología de Paper 2**, no de éste.

---

## Qué SALE a Paper 2 (extracción para limpiar) + qué se queda

**Simetría:** lo que sacas para limpiar (el buceo profundo en Modo 2) es justo lo que, reemplazado por
una mención sobria del espectro, le da a Paper 1 su alcance agnóstico **sin** sobre-afirmar. Paper 1
queda = Modo 1 medido + un mapa sobrio del territorio. Más limpio Y más amplio a la vez.

### SACAR → Paper 2
- **§VSL: Semantic Compression as Inter-Layer Protocol** (~120 líneas, hoy entre Exp 11 y §Physical
  Substrate). Es **Modo 2 puro** (el sustrato semántico): compresión 38–51% / schema 72–79%,
  replicación cross-model (Gemini/Qwen/Claude), y el hallazgo **structural≈100% vs semantic≈40%**
  (context substitution + el ancla `domain_context`). Está *off-thesis* para Paper 1 (atractor) y es
  el **ancla empírica natural de Paper 2** (`project_paper2_seed`: VSL inter-LLM, EXP-PHI-01).
  - Ya estaba señalado por `review_calibration` (VSL-004: "paper corto aparte, no mezclado con el atractor").
  - El drift structural-vs-semantic *es* una medición de viabilidad del Modo 2 (¿el significado sobrevive
    al cruce de sustrato?) → corazón de Paper 2, no aside de Paper 1.
  - **Paper 1 conserva 1 frase**: "los protocolos se comunicaron en VSL, notación compacta cuya
    compresión y fidelidad cross-agente se caracterizan por separado [Paper 2]."

### NO sacar (parece orbital, es Modo 1 medido y load-bearing)
- **Exp 10 Maxwell / Observer Constitutivity** — incl. "Contrast: conventional implementation". NO es
  orbital: es el **argumento de observabilidad (tier b) hecho concreto y medido** (D_eff 4→3 bajo
  observación; el baseline convencional no tiene Ω, ni stasis_cos, ni separación observador/sistema).
  Es una de las mejores respuestas-Q4 del paper. Se queda. *(Stitch leve: la subsección "VSL as the
  Demon's apparatus" referencia VSL — reescribir a un puntero de 1 línea a Paper 2 al extraer §VSL.)*
- **§Physical Substrate as Governance Layer** — Modo 1 (hardware como frontera externa). Se queda.
- Trilogía, térmicos, basin, controles negativos, Lyapunov — Modo 1. Se quedan.

### Verificar tono (mantener geometría, mover cualquier sobre-claim)
- **§"Ethical axioms as stability conditions"** (A0/A0.1): mantener como *geometría de restricción*
  (violar A0 = salir de Ω, hecho geométrico, Modo 1). Mover a future-work cualquier "esto resuelve
  alignment / covenant gobierna multi-agente" (Modo 2/3).

### AÑADIR como menciones (el espectro que pediste)
- El **arco de 3 modos** (sobrio) en "What VSF can model" + un párrafo de Future Work. Es lo que da
  cuenta del espectro VSM/VSF en campos más amplios que el numérico — **sin** que ninguno entre como
  resultado. Modo 1 medido; Modo 2 → Paper 2 (donde aterriza el §VSL extraído); Modo 3 → vOS.

**Neto:** sacas un buceo Modo-2 que diluye el foco → se vuelve el ancla de Paper 2; y lo reemplazas por
un mapa sobrio de los 3 modos → Paper 1 *gana* amplitud agnóstica siendo más limpio.

---

## Linaje Beer: herencia y divergencia + la capa de seguridad

> El paper ya tiene la semilla ("a rediscovery… los principios que Beer articuló hace medio siglo",
> intro) pero **no dice qué hereda, dónde se separa, ni POR QUÉ** se separa. La respuesta del autor es
> correcta: la divergencia se explica por **instrumentos que Beer no tenía** (1971–79).

### Hereda de Beer (VSM 1972 / Heart of Enterprise 1979 / Cybersyn 1971) + Ashby
S1–S5 recursivo · S3\* auditoría esporádica · canales algedónicos · recursión · variedad requerida ·
homeostasis-como-viabilidad · los patrones Cybersyn (Cybernet/Cyberfilter/Cyberstride/CHECO/Opsroom).
*(Citar Medina 2011 para Cybersyn — hoy ausente en references.bib.)*

### Diverge / extiende — y POR QUÉ (instrumentos no disponibles en 1971–79)
| Beer (cibernética **estructural**) | VSF (cibernética **medida + certificada**) | Instrumento que faltaba |
|---|---|---|
| describe la viabilidad cualitativamente | la **mide**: λ_max (Benettin), β (homología persistente), ℝ¹²⁸ a 6×10⁷ ciclos | Benettin (~1980), TDA (s.XXI), sustrato computacional |
| VSM = lente **diagnóstico** (¿la org tiene los 5 sistemas?) | viabilidad **certificable** (Q1–Q3 + certificador embebido) | formalización + cómputo |
| S5 = política/identidad | **loop de seguridad criptográfico** que vuelve el certificado *infalsificable* | criptografía (no parte del aparato de Beer) |
| CHECO (modelos estadísticos) como S4; Cybersyn (telex/mainframe) | **LLM como S4** + el agente como VSM operacional recursivo | LLMs, Rust, VSL |

**Encuadre honesto:** VSF no mejora la *teoría* de Beer — **mide y certifica lo que Beer solo pudo
describir**, con instrumentos que no existían. Humilde (Beer tenía razón) Y fuerte (lo volvimos
cuantitativo + a prueba de manipulación). Linaje claro + delta honesto = lo que un revisor respeta.
*(Conexión: la agnosticidad de los 3 modos + V coordinate-free es la* realización operacional *de la
independencia-de-sustrato que Beer ya intuía — ahora con los instrumentos para medirla.)*

### La capa de seguridad = el lado integridad del certificador (única, parte de V)
> Estoy de acuerdo: el loop de seguridad es único y **es parte del certificador de viabilidad** — pero
> con ubicación precisa para no romper rigor.

- **Por qué es parte del certificador:** un certificado de viabilidad que se puede **forjar** no vale
  nada. El loop de seguridad (covenant SHA256 + boot fail-closed · φ↑ firmado Ed25519 · telemetría
  Merkle-encadenada · CA offline · verificación de testigos) es lo que **ata el certificado al estado
  real medido**. V dice *cuánta* viabilidad; el loop de seguridad garantiza que ese valor **no se
  puede falsificar**. Juntos = el certificador completo: **V (qué) + seguridad (confiable cómo).**
- **Conexión con los 3 modos:** en Modo 1 la confianza viene de la **medición** (no puedes falsear
  λ_max). En Modos 2/3 (LM/agente), donde no puedes medir el sustrato directamente, **el loop de
  seguridad es lo que restaura la confianza** — atestaciones firmadas, cadena Merkle, gates
  fail-closed. Es el mecanismo de certificación *justo donde la medición directa falla.* Eso lo ata al
  arco de 3 modos Y a V.
- **Ubicación en Paper 1 (disciplina):**
  - **Modo 1 / cuerpo:** la cara A0/A0.1 de Ω **se enforce fail-closed** — el kernel verifica el hash
    del covenant al boot y **se niega a arrancar** si hay drift (exit 2). El paper hoy dice "violar A0 =
    salir de Ω" (descriptivo); agregar que está **enforced**, no solo descrito. Mención Modo-1 legítima.
  - **Loop cripto completo (CA, firmas, Merkle, testigos):** mención sobria + puntero a anexo
    operacional / al certificador. NO como resultado (es infraestructura Modo-3). Enmarcado como "lo que
    vuelve la certificación tamper-evident" + divergencia-Beer + lo que hace a V confiable.

---

## Capstone — la constante/funcional de viabilidad invariante  ✅ CIERRA (ver `viability_functional_note.md`)

> **Veredicto 2026-06-14 (rev.2, post red-team):** V = **min(g,c,t,m)** (5 ingredientes; g=feasibilidad
> en Ω separa membresía de proximidad; operador **min** = conjunción estricta) **cierra** como forma
> coordinate-free, dimension-free, *metric-relative* (métrica = nuevo paso **Q0**; Ω = Q1). Kernel:
> **V≈0.46, limitado por el margen** (no 1.0 cosmético) — la signature `[g,p,c,t,m]=[~1,~1,~1,~1,0.46]`
> es el entregable. ⇒ **D** (σ_max sostenido) es el experimento crítico (mide el eje que liga).
> Modos 2/3: definición transfiere, medición abierta/especulativa. Detalle en `viability_functional_note.md`.

> Pregunta abierta del autor (2026-06-14): ¿existe una **constante de viabilidad dominio-invariante** —
> un funcional construido *sumando las funciones que constituyen el espacio viable*, sin la definición
> explícita de ℝⁿ?
>
> Observación: la **función de Lyapunov L(sv)** YA es "la suma de las funciones constituyentes":
> L = α(1−cos) + β·H_KS/H_max + γ·max(0,B−B_av) + δ·ReLU(H_drift), con Σpesos=1.
> Lo que falta para volverla *invariante* es construirla solo con **ingredientes coordinate-free**.
> Si cierra: este es el verdadero broche del tier invariante — la cantidad que la costura
> instancia↔invariante venía señalando todo el tiempo.
>
> **Decisión tomada (2026-06-14):** forma funcional invariante + *signature* [λ-spectrum, β-firma,
> razón-de-margen]; el comparador escalar cross-dominio es corolario "comparable-tras-normalización Q1-Q3".
>
> **Ingredientes intrínsecos:** λ_max (exponente Lyapunov, invariante de coordenadas) · β₀,β₁
> (invariantes topológicos) · stasis_cos (∈[−1,1] independiente de n) · razón de margen (adimensional).
> Evidencia de que ya existe embrionariamente: θ_viable=0.70 y θ_PSI=0.79 ya se usan como umbrales
> **cross-instancia** (el coseno cocienta n).
>
> **Insumos empíricos que V consume:** A (espectro completo) → λ-signature · D (σ_max sostenido) →
> razón-de-margen · trilogía → β-firma. La nota de V *es el hub que define qué deben medir A y D*.
>
> **Tres destinatarios de V** (no dos): Modo 1 kernel (V *medido*) · Modo 2 LM (V objetivo, semántico) ·
> Modo 3 agente (V objetivo, cibernético). V coordinate-free es lo único que podría certificar 2 y 3 —
> por eso *no* puede depender de ℝⁿ explícito. El corolario LM/agente es la motivación más fuerte de V.
>
> Se desarrolla en **nota aparte** antes de comprometerlo al cuerpo (acuerdo 2026-06-14).
>
> **El certificador completo = V + loop de seguridad.** V es el *valor* de viabilidad; el loop de
> seguridad es la *integridad* que lo vuelve infalsificable (ver §"Linaje Beer + capa de seguridad").
> Sin el loop, V en Modos 2/3 sería declarado, no certificado.

---

## Cómo interactúa con la reorientación de gobernanza (Q2)
Lo que transfiere entre dominios es la **estructura de gobernanza** (los dos tiers), no la geometría.
El marco agnóstico y la reponderación hacia gobernanza son el mismo movimiento: "lo importante de VSF
no es *este* atractor, es *cómo cualquier* sistema axioma-gobernado mantiene viabilidad certificable."

## Deudas honestas adicionales (disclosure · filosofía · scoping)

**Disclosure (front matter):**
- **Funding:** "independent research, no external funding." (falta; requerido para submit)
- **Data availability:** code-avail ya existe ("on request"); añadir *data* (telemetría / CSVs de figuras)
  y notar que la telemetría es **Merkle-encadenada (tamper-evident)** → fortaleza de reproducibilidad,
  no solo disponibilidad. (Ata con el loop de seguridad.)

**Filosofía / metodología:**
- **Grounding terminológico:** nota breve mapeando términos cibernéticos a definiciones operacionales
  (trust = escalar [0,1] EMA · governance = canal de restricción S5 · viable = ∈ Ω · intelligence =
  S4 = LLM/observador). Desarma "esto es metáfora/antropomorfismo".
- **Falsabilidad:** enunciado explícito — la tesis es falsable; una perturbación que rompa Ω sin
  recuperación la refutaría; ninguna hallada en el envelope; basin + σ_max definen dónde *fallaría*.
- **Certify-not-declare = epistemología explícita (la espina):** la viabilidad es claim *certificado*,
  no declarado. Unifica Q1–Q3 (certifica la matemática) + seguridad (certifica la integridad) + V (el
  valor del certificado) + los 3 modos (medido vs enactado). **Capstone filosófico que hace juego con V.**

**Modo 3 / scoping (infraestructura — lo que pediste):**
- El kernel se despliega como **S1 de un VSM distribuido** (S1–S5 en contenedores, canales φ↑/φ↓
  reales, state.db); los experimentos miden el **S1 aislado en un nodo**. Grounding del "operacional"
  + scoping honesto de la medición (se midió un kernel, no el VSM completo). → §Implementation Notes.

### #4 elevado — el límite double-loop = **human-in-the-loop**
> El punto del autor (2026-06-14): A5 no es solo el double-loop de Beer; en el contexto actual **ES**
> lo que se llama *human-in-the-loop* (HITL), relevante para **cualquier** proyecto de autonomía hoy.

- **Otra redescubrimiento-Beer:** double-loop (Beer 1979) = HITL (discurso de autonomía 2020s),
  convergencia independiente. VSF lo hace **formal y medible**: un hiperplano en la dimensión de
  gobernanza de Ω. Cruzarlo sin autorización = salir de Ω = **no-viable**. El HITL no es un *wrapper*
  de safety pegado encima — es una **restricción constitutiva** de la región viable.
- **Posiciona a VSF honestamente en el espectro de autonomía:** *no* "IA autónoma", sino **sistema de
  autonomía-acotada con techo humano formal y medible**. Single-loop autónomo dentro del envelope;
  double-loop (política, redefinición de clase) requiere el metasistema = humano. (D4/A5 ya es regla
  dura del proyecto — el paper solo no lo nombró como contribución.)
- **Conecta tres hilos:** Beer (lineage) · loop de seguridad (que **enforce** el techo fail-closed) ·
  certify-not-declare (el humano es el **certificador final** del double-loop).
- **Disciplina:** es contribución a la **ingeniería de autonomía** (un límite principiado y medible),
  NO una solución de alignment/safety. El claim es "la viabilidad requiere mantenerse bajo el techo",
  *no* "el sistema es provablemente seguro". Sin esto, una mención HITL derrapa al claim de alignment.
- **Por qué importa que esté:** un paper sobre un kernel viable *autónomo* que **ignora** HITL sería
  marcado como ingenuo o evasivo por cualquier revisor consciente de safety. Nombrarlo lo sitúa en el
  discurso actual y lo blinda.

## Recursos visuales + glosario (deudas de producción, diferidas)

### Diagramas conceptuales (diferido — necesita herramienta/especialista; honestidad sobre capacidad)
Los gráficos de **datos** (fig 1–10) están; faltan diagramas **conceptuales/organizacionales** (flujos,
árboles de decisión, mapas). División por tipo:

- **VSF-native** (lo que construimos, sin template externo "correcto"): bloque ℝ¹²⁸→A–G · flujo
  φ↑/φ↓/algedónico · **árbol D4** (single/double-loop) · el **certificador** (V + seguridad) · arco de
  3 modos · **techo HITL** (envelope single-loop + frontera double-loop) · protocolo Q0–Q3.
  → **TikZ / Mermaid** (reproducible, compila al paper, versionado). *Esto sí puedo bosquejarlo bien* —
  es código, no dibujo espacial.
  - **Bocetados ya en la solución Fierro** (`debate_solucion_interactivo.html`, re-hacer en TikZ):
    **Ω como politopo convexo** (proyección 3D cos/trust/entropía) · **Ω_A⊂Ω anidados** (núcleo cos≥0.88
    dentro de viabilidad cos≥0.70, con cos_piso 0.875) · **dos capas** (arquitectura selecciona cuenca /
    gobernanza determina recuperación, τ_rec<30s). Conceptos listos; falta el render reproducible.
- **Canónico Beer VSM**: requiere **template fiel atribuido o especialista**. Las convenciones de Beer
  (cajas anidadas, el entorno, el eje de mando S1–S5, canales S2/S3\* laterales) son
  espaciales/estéticas — *por eso lo produzco inconsistente cada vez que lo pides*. Solución honesta:
  figura de referencia *sourced* (citar Beer/Espejo) o herramienta dedicada, **no re-improvisar**.

Herramienta ya en el ecosistema: **formaid** (opsroom LXC 109 — genera/exporta mermaid). Candidato
natural + una librería de templates; o un **skill/agente especialista** en mapas conceptuales.
*No se resuelve ahora* — queda el **inventario** (arriba) como deuda durable.

### Glosario técnico (esto SÍ está en mi capacidad — construible completo)
Un paper que cruza **cibernética + sistemas dinámicos + topología + termodinámica + CS** necesita un
glosario **por dominio** para que cada comunidad lo lea. Es el compañero léxico de la amplitud agnóstica
y la versión durable del *grounding terminológico* (#3).

- **Grupos:** cibernética (Beer/Ashby) · dinámica (Lyapunov, atractor, basin, KY-dim) · topología
  (Betti, homología persistente, VR) · termo (Landauer, demonio de Maxwell, entropía) · VSF (Ω,
  stasis_cos, D_eff, φ↑/φ↓, algedónico, S1–S5, covenant, VSL, trust axes) · **artefactos Rust**.
- **Registro de artefactos Rust (alto valor):** cada cantidad medida → archivo/función que la computa
  (stasis_cos → `state_vector.rs` · λ_max → subcomando `lyapunov_spectrum` · Ω → `omega_validator.rs` ·
  β → `vr_complex.rs` · constantes → `calibration.rs`). Vuelve cada claim **trazable al código** —
  reproducibilidad + es **certify-not-declare hecho léxico** (claim → artefacto auditable).
- **Semilla existente:** `docs/glossary.vsm` (ya en el proyecto) → reconciliar + barrido de términos del
  paper + artefactos → apéndice completo. Extracción/organización, no dibujo: **mi wheelhouse.**

## Decisión de integración (2026-06-14)
**Todo entra al paper.** Fierro entra al loop con el **cuerpo completo** (no outline-first): se
construye el paper revisado entero y él revisa la corrección en su contexto.

## Orden de formalización (cuando se apruebe)
0. **Nota de V aparte** (hub de diseño) → si cierra, define qué miden A y D.   ← gating
1. **A** (espectro Lyapunov completo) + **D** (σ_max sostenido) — los insumos empíricos de V (en 108).
2. §3+§4 dominio-neutral + reparación Fierro (Krasnoselskii/Aubin) + refs.  ← lado invariante (= B)
3. §2 declaración de instancia + frase-puente en §6.3/§7.
4. Subsección "What VSF can model" + **arco de 3 modos** (Modo 1 medido; 2–3 semillas sobrias).
5. **Linaje Beer** (herencia/divergencia/por-qué) — extender intro + §Discussion; citar Medina 2011.
6. **Capa de seguridad:** A0 fail-closed en cuerpo (Modo 1) + loop cripto como mención + anexo.
7. Capstone V en el cuerpo — **solo si** la nota cierra (V + seguridad = certificador completo).
8. Future Work: semilla Modo 2 (Paper 2) + Modo 3 (vOS) + puente a V.
9. **Deudas honestas:** funding · data-avail + Merkle · grounding terminológico · falsabilidad ·
   certify-not-declare (epistemología) · scoping de infraestructura · **double-loop = HITL** (#4 elevado).
10. **EXTRAER §VSL → Paper 2** (+ stitch de 1 línea en Exp 10 Maxwell).
11. **Glosario** (apéndice por dominio + registro de artefactos Rust) — construible ya, mi wheelhouse.
12. **Diagramas VSF-native** (TikZ/Mermaid: D4, certificador, 3 modos, HITL, Q1-Q3) + inventario.
    Beer VSM canónico → diferido a template/especialista (formaid o skill dedicado). NO ahora.
13. **C** (D4 gobernado vs congelado) post-gate 06-18 — respalda el tier gobernanza.
14. → Fierro revisa el cuerpo completo.

Prerequisitos de código (en 108, mismo patrón que dumps de figuras; no tocan prod):
`VSF_D4_FREEZE_LIFECYCLE=1` (toggle para C) · inyección de ruido sostenido σ·η con σ ajustable (para D).

⟦ narrative_revision_sketch | attractor_convergence | 2026-06-14 ⟧
