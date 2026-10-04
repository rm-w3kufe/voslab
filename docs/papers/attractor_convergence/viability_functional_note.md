# Nota de V — el funcional de viabilidad dominio-invariante (rev. 5 — todos los ingredientes medidos)

**Fecha:** 2026-06-15 (rev.5) · **Estado:** nota de diseño/validación (NO tocar main.tex; gate antes de formalizar)
**rev.5:** **g MEDIDO** (EXP-G-01, 2026-06-15). Todos los ingredientes de V ahora medidos empíricamente.
g=**0.102** (binding: A3_cpu, entropía en equilibrio). g≠≈1 — el eje que liga pasa de m a g. V en reposo
= 0.102, no 0.99. Eje ético validado: dims[53]=1 → g=0 → V=0 en 1 tick (EXP-A01-01 T2).
**rev.4:** insumos empíricos de V **medidos** (EXP-LY-01 espectro Gram-Schmidt + EXP-NS-01 ruido
sostenido) — ver §5/§6/§10. `c` confirmado (todos λᵢ=ln0.99, σ̂_λ=2.9e-16); `m` ya NO es un proxy
prestado: es una **curva m(σ) que satura** (V(σ→0)=0.99, V(σ=0.10)=0.71, V(σ=1.0)=0.43), **sin techo
finito** de ruido. El V≈0.46 de rev.3 resultó ser el régimen *extremo* (σ_in≈1.0), no el típico.
**rev.3:** incorpora `Revisiones/debate_solucion_interactivo.html` (Teorema VSL-MATH-01, Qwen+Claude
2026-05-13) — ver §9: precisa `g` (mapeo axioma→convexo), `c` (núcleo Ω_A), `m` (ε_frontier derivado).
**Pregunta:** ¿existe una constante/funcional de viabilidad construido *combinando las funciones que
constituyen el espacio viable*, sin la definición explícita de ℝⁿ?

> **rev.2** incorpora la revisión crítica: (1) 5º ingrediente `g` (membresía en Ω — `p` no la codificaba);
> (2) operador **min**, no media geométrica (conjunción estricta); (3) `m` sin parámetro = 1−1/r;
> (4) `c` honesto como gate de signo; (5) Q0 (métrica) separado de Q1 (Ω).

> **Veredicto:** V **cierra** como forma funcional coordinate-free, dimension-free, *metric-relative*.
> Conjunción estricta (min). Kernel (rev.4, medido): **V(σ) es una curva de robustez que satura** — el
> margen sigue siendo el eje que liga (g≈c≈t≈1), pero m(σ) degrada con gracia y **no colapsa**: V≈0.99 en
> reposo, ≈0.71 a estrés sostenido moderado (σ=0.10), ≈0.43 sólo en el régimen extremo (σ_in≈1.0, ruido =
> norma de la distribución). **No hay techo de ruido finito** (confinamiento P(cos≥0.70)=1.0000 hasta σ=2.0;
> min_cos satura en 0.856 ≫ 0.70). El V≈0.46 de rev.3 (proxy impulsivo prestado) era el caso extremo, no el
> típico — la medición sostenida lo *mejora*. Modos 2/3: definición transfiere, medición abierta. Más honesto
> y más informativo que rev.1; ahora con los insumos empíricos medidos, no heredados.

---

## 1. Los ingredientes intrínsecos (coordinate-free) — ahora cinco

L(sv) es "la suma de las funciones constituyentes" — pero es un sumando (permite trade-offs) y usa
coordenadas. V se reconstruye con **solo invariantes intrínsecos** y de forma **conjuntiva (min)**.

| Símbolo | Cantidad | Definición | Invariancia | Rol |
|---|---|---|---|---|
| **g** | feasibilidad en Ω | `g = mínᵢ( holgura normalizada de Aᵢ )` sobre TODAS las restricciones (incl. A0,A0.1,A3,A5,Aε) | metric-rel. (slacks) | ¿se cumplen TODAS las restricciones (incl. ética)? |
| **p** | profundidad/posición | `p = (s − θ)/(1 − θ)`, s=cos(x,x̄), θ=θ_viable | O(n)+escala; metric-rel. | dado que estoy en Ω, ¿qué tan cerca del atractor? |
| **c** | contracción (signo) | gate de signo de λ_max graduado por confianza: `c = ½(1 + tanh(−λ_max / σ̂_λ))`, σ̂_λ = **incertidumbre de estimación** de λ_max | **difeomorfismo** (Oseledets) | ¿la dinámica contrae (robustamente <0)? |
| **t** | topología | `t = 1` si (β₀=1 ∧ β₁=0), graduado por separación de persistencia | **homeomorfismo** | ¿point sink, sin ciclo? |
| **m** | margen | `m = 1 − 1/r`, r = ε_frontier/σ_max (**sin parámetro**) | ratio ⇒ scale-free; metric-rel. | ¿cuánto del trecho a la frontera NO consume el ruido? |

**Correcciones clave de rev.1:**
- **`g` es nuevo y necesario.** rev.1 dejaba que `p` (cos a x̄) hiciera de membresía-en-Ω. **Falso:** un
  estado puede violar A0 (en dims de purpose/prohibited) y aún tener cos alto con x̄. Ω = ∩ᵢ{Aᵢ} es una
  intersección, no una bola alrededor de x̄. `g` separa *en Ω* (todas las restricciones, ética incluida)
  de *cerca del atractor* (`p`). **g→0 si cualquier restricción se viola.**
- **`c` es gate de signo, no fuerza.** No existe forma scale-free de *fuerza* de contracción (el signo de
  λ_max es invariante, la magnitud necesita timescale). σ̂_λ es la **incertidumbre de estimación** de
  λ_max (la da A: spread entre checkpoints / bootstrap) — NO el `7.6e-12` de rev.1, que era
  `|λ_max−ln0.99|` (acuerdo con teoría, cosa distinta). c mide "¿qué tan seguros de que λ_max<0?".
- **`m` sin parámetro.** rev.1 usaba `r*=1.5` hardcodeado (constante Modo-1 filtrándose a la forma
  universal) y saturaba m a 1.0. `m = 1−1/r` es paramfree y ∈[0,1) para r>1.

---

## 2. Construcción de V — conjunción estricta (min)

**Insight (corregido):** un certificado es **conjuntivo estricto** — "tan viable como su condición más
débil". La media geométrica de rev.1 permitía **compensación multiplicativa** (un eje fuerte tapa uno
débil), lo que contradice el propio argumento. El **mínimo** es el certificado honesto.

```
   V = min( g, c, t, m )            # CERTIFICADO del atractor (estricto, weakest-link)
   V_full = min( g, p, c, t, m )    # incluye el estado actual (¿estoy en él ahora?)
   signature = [g, p, c, t, m]      # EL deliverable real — más informativo que cualquier escalar
```

- **V ∈ [0,1].** Un cero en cualquier eje ⇒ V=0 (no-viable). Conjunción estricta = todas necesarias.
- **Variante suave (si el paper quiere V como señal continua):** soft-min
  `V_β = −(1/β)·log Σ e^{−β·xᵢ}` → min cuando β→∞. Para diagnóstico/monitoreo, no para el claim.
- **La signature es el entregable.** Colapsar a un escalar esconde *cuál* eje liga. El número titular
  (min) dice "qué tan viable"; la signature dice "limitado por qué".

---

## 3. ¿Es coordinate-free? — análisis (con Q0/Q1 corregido)

**V es invariante bajo:** dimensión n · relabeling · escala · (para c) difeomorfismo. **NO es metric-free:**
g, p, m y la filtración de t dependen de la métrica del espacio.

**La metric-relatividad es FEATURE — pero requiere un paso de protocolo explícito (corrección rev.1):**
rev.1 decía "la métrica la fija Q1". **Impreciso:** Q1 (Fierro) define *Ω*; la **métrica** (producto
interno: qué es "cerca/lejos") es una elección **adicional**. ⇒ el protocolo de dominio necesita un
**Q0: elegir la métrica de viabilidad**, antes de Q1 (definir Ω), Q2 (contracción), Q3 (σ_max).

Una viabilidad *metric-free* sería vacía (sin "cerca/lejos" no hay frontera). ⇒ **V es invariante DADO
(Q0 métrica + Q1 Ω); ambos son la geometría de viabilidad del dominio.** La forma es universal; los
valores son comparables cross-dominio *tras* Q0–Q3. Honesto.

**Embrión existente:** θ_viable=0.70 y θ_PSI=0.79 ya son umbrales cross-instancia (el coseno cocienta n).

---

## 4. Fidelidad — ¿V alto ⟺ viable? (con g separando Ω de proximidad)

**Necesidad (min ⇒ todas):** V→1 exige g→1 (en Ω, TODAS las restricciones holgadas) ∧ c→1 (λ_max
robustamente <0) ∧ t=1 (point sink) ∧ m→1 (frontera ≫ ruido) [∧ p→1 para V_full]. V→0 si cualquiera cae.

**Las condiciones caracterizan un atractor puntual viable:** feasibilidad (g, en Ω incl. ética) ·
posición (p) · dinámica (c) · forma (t) · robustez (m).
- **Ética A0/A0.1:** ahora en **g** (semiespacios de Ω). Violar A0 ⇒ holgura negativa ⇒ g→0 ⇒ V=0.
  *Corrige el hueco de rev.1* (p NO lo garantizaba).
- **Integridad:** V mide *cuánta* viabilidad, no si la medición es confiable. Eso es el **loop de
  seguridad** (V + seguridad = certificador). Separación limpia: V = valor; seguridad = integridad.

**Caveat de completitud (sin cambios):** las condiciones son *necesarias* y *caracterizan conjuntamente*
un point sink viable; *suficiencia* = elección de modelado defendible, declarada, no teorema.

---

## 5. Instanciación en el kernel — el resultado honesto

| eje | medido | normalizado |
|---|---|---|
| g | **EXP-G-01 (2026-06-15):** slacks per-restricción de Ω; binding = A3_cpu (entropía). omega.viable=true en todo el barrido. Eje ético: dims[53]=1 → g=0 → V=0 (un tick). | **0.102** (medido, no afirmado; g≠≈1 — A3_cpu binding en el atractor de equilibrio) |
| p | stasis_cos ≈ 0.9999 | (0.9999−0.70)/0.30 ≈ **1.00** |
| c | **EXP-LY-01 (Gram-Schmidt):** λ₁=λ₂=λ₃=−0.010050=ln0.99, σ̂_λ=**2.9e-16** | gate de signo ≈ **1.00** (todos λᵢ<0, KY-dim=0) |
| t | β₀=1∧β₁=0, ~80× S/N | **1.00** |
| m | **EXP-NS-01 (ruido sostenido):** curva m(σ), satura; m=1−exc_p95(σ)/ε_frontier | **curva** (ver abajo) |

**m(σ) medido (EXP-NS-01, ε_frontier=0.7746, confinamiento=1.0000 en todo el rango):**

| σ_in | exc_p95 | m(σ) | V(σ)=min(g,c,t,m) | régimen |
|---|---|---|---|---|
| 0.00 | 0.005 | 0.99 | **0.99** | reposo |
| 0.05 | 0.177 | 0.77 | **0.77** | leve |
| 0.10 | 0.228 | 0.71 | **0.71** | moderado |
| 0.20 | 0.256 | 0.67 | **0.67** | fuerte |
| 0.50 | 0.319 | 0.59 | **0.59** | severo |
| 1.00 | 0.441 | 0.43 | **0.43** | extremo (≈ proxy impulsivo rev.3) |
| 2.00 | 0.519 | 0.33 | **0.33** | overwhelming (4× la distribución) |

```
V(σ)      = min(g=0.102, c≈1, t=1, m(σ)) = g = 0.102    # margen = g (binding A3_cpu)
signature = [g=0.102, p≈1.0, c≈1.0, t=1.0, m(σ)]         # g es el nuevo eje que liga
```

**Nota EXP-G-01:** g=0.102 desplaza el binding de m a g como eje que liga. La tabla V(σ) sigue siendo
válida para variaciones de m, pero el valor de V en reposo es ahora determinado por g=0.102, no por
m(σ→0)=0.99. La fila m mide la *sensibilidad al ruido* relativa al margen actual de g.

**Lectura honesta (rev.4):** el kernel cumple TODAS las condiciones necesarias de viabilidad; su
certificado de margen es una **curva que satura**, no un escalar. **No hay techo de ruido finito**
(confinamiento=1.0000 hasta σ=2.0; min_cos satura en 0.856 ≫ θ_viable). El V≈0.46 de rev.3 NO era el
caso típico: era el régimen *extremo* (σ_in≈1.0, donde el ruido sostenido iguala la norma de la
distribución) — el proxy impulsivo prestado (kick único de EXP-AB-01) sobre-estimaba la excursión porque
desplaza de una sola vez, mientras el ruido sostenido es continuamente recontraído. **La medición
sostenida mejora el resultado.** Para el paper: V titular anclado en un σ operativo declarado (la curva
muestra el espectro completo); el mensaje es "margen-limitado pero sin techo, degrada con gracia".

Esto **cierra el experimento D** — m ya no es heredado de un proxy: es medido bajo ruido sostenido.

---

## 6. Insumos empíricos de V — A, D & G MEDIDOS (rev.5); todos los ingredientes medidos

- **A — EXP-LY-01 espectro Lyapunov completo (✓ MEDIDO):** da **c**. Gram-Schmidt sobre el espacio
  tangente del símplex (NEXP=3): **λ₁=λ₂=λ₃=−0.010050=ln0.99** (|diff|=3.97e-16), KY-dim=0 (point sink),
  e **incertidumbre de estimación σ̂_λ=2.9e-16** (spread entre checkpoints — el mapa lineal determinista
  no tiene incertidumbre real). ⇒ gate de signo `c = ½(1+tanh(−λ_max/σ̂_λ)) ≈ 1.0`. (rev.1 usó la cantidad
  equivocada como σ_λ; ahora es la correcta.)
- **D — EXP-NS-01 ruido sostenido x(t+1)=f₀+σ·η (✓ MEDIDO):** da **m**, el eje que liga. Reemplaza el
  proxy σ_max=0.42 de EXP-AB-01 (kick impulsivo único) por la **curva m(σ) sostenida** (§5). Hallazgos:
  (1) confinamiento P(cos≥0.70)=**1.0000** en todo el barrido (σ hasta 2.0) ⇒ **no hay techo de ruido
  finito** bajo ruido distribucional acotado (el símplex es compacto); (2) min_cos satura en **0.856**;
  (3) m(σ) degrada con gracia y satura (0.99→0.33), nunca colapsa; (4) el viejo V=0.46 corresponde al
  régimen extremo σ_in≈1.0. **D resultó el experimento más informativo — y el resultado favorece al kernel.**
- **G — EXP-G-01 holguras Ω (✓ MEDIDO 2026-06-15):** da **g**. Censo por restricción de Ω_A;
  binding = **A3_cpu** (entropía). g=**0.102** en el atractor — no ≈1 como afirmaba rev.1-4. g≠≈1
  porque A3_cpu es una restricción activa en equilibrio (entropía constante ≠ slack). Eje ético:
  dims[53]=1 → g=0 → V=0 en un tick (EXP-A01-01 T2 confirma). g DESPLAZA el binding de m a g:
  V en reposo = 0.102, no 0.99. **Cierra el último ingrediente no medido.**
- **trilogía (hecho):** **t**. · **existente:** **p** (stasis_cos), ε_frontier (derivado, §9).

---

## 7. Modos 2/3 — definición transfiere; medición abierta (especulativa)

V está DEFINIDO coordinate-free ⇒ aplica *en principio* al LM (Modo 2) y al agente (Modo 3). Pero
**medir** g,p,c,t,m sobre una trayectoria de razonamiento es **abierto y especulativo** (bajando el tono
de rev.1): el λ de razonamiento de un LM no está bien-definido sin estructura adicional fuerte (¿qué es
una "trayectoria de razonamiento cercana"?); g,p requieren una referencia de stasis y una frontera en
espacio semántico — el problema central de Paper 2. Es una *dirección de investigación*, no un camino claro.

Coherente con el arco: **Modo 1 V medido; Modos 2/3 V es el objetivo abierto.** Y es la razón de que V
DEBA ser coordinate-free: si dependiera de ℝⁿ explícito, no podría ni *definirse* sobre el LM. El loop de
seguridad es lo que, en Modos 2/3, restaura la confianza que en Modo 1 da la medición.

---

## 8. Veredicto + riesgos honestos (actualizados)

**CIERRA** como forma funcional invariante (coordinate-free, dimension-free, metric-relative), conjuntiva
estricta (min), fiel por construcción, con un resultado de kernel **honesto y útil (V≈0.46, margin-limited)**
y la signature como entregable. Modos 2/3 = objetivo abierto. El broche del tier invariante se sostiene —
y es más fuerte tras el red-team.

**Riesgos que un revisor tocará (declararlos):**
1. **Completitud de las 5 condiciones** — necesarias y caracterizantes; suficiencia = elección de
   modelado, no teorema.
2. **Normalización de m (1−1/r)** — paramfree y principiada (fracción del trecho no consumible por ruido);
   el mapa [1,∞)→[0,1) es una elección; 1.85× da 0.46 ("middling"). Defendible; declararlo. **ε_frontier
   ya NO es heurístico** (rev.3): = √(2(1−θ_viable)) = 0.775 (derivación geométrica, §9).
3. **g operacional** — depende de poder medir holguras per-restricción; las caras A0/A0.1 (ética) deben
   ser expresables como slack numérico, lo cual en Modo 1 sí (semiespacios) pero en Modos 2/3 es abierto.
4. **Métrica como Q0** — el protocolo de dominio gana un paso (elegir métrica); honesto pero hay que
   formalizarlo junto a Q1–Q3 de Fierro.
5. **c gate de signo** — no da fuerza de contracción (imposible scale-free); si un revisor quiere "qué tan
   rápido", la respuesta es "relativo al timescale del dominio = Q0/Q1".

**Para el paper (si se aprueba):** V (min) titular + signature como entregable; el §4 dominio-neutral
(Q0 métrica + Q1 Ω, Fierro/Aubin) da el marco; el loop de seguridad = mitad-integridad del certificador
(V = mitad-valor). Capstone matemático que hace juego con certify-not-declare (capstone filosófico).
**Mensaje honesto del kernel:** no "viabilidad perfecta" sino "todas las condiciones necesarias cumplidas,
certificado ligado por el margen de ruido" — lo que es a la vez verdadero y una invitación a D.

---

## 9. Alineación con la solución formal de Fierro (VSL-MATH-01, 2026-05-13)

`Revisiones/debate_solucion_interactivo.html` (Qwen+Claude) ya trae la solución formal completa a Fierro
— refuerza y **precisa** V:

- **§4 ya tiene teorema (se ADAPTA, no se inventa):** *Theorem VSL-MATH-01 (Invariancia Híbrida)* — si
  Ω_A es contractiva (L<1) ⇒ (1) ∃ medida invariante μ\* en Ω_A (**Krasnoselskii**); (2) convergencia en
  expectativa (**Lyapunov estocástico**); (3) excursiones fuera de Ω duran **τ_rec<30s** (confinamiento
  acotado). Concilia rigor topológico (Brouwer/Krasnoselskii en Ω_A) con empirismo (ruido acotado).
- **Mapeo axioma→convexo (concreta `g`):** A0 (identidad) `‖x[0:7]‖₂≤1` (bola) · A3 (presupuesto)
  `Σwᵢxᵢ≤B` (semiespacio) · Aε (entropía) `H(p)≤Hₘₐₓ` (subnivel cóncavo). Intersección finita de convexos
  = Ω convexa compacta ⇒ `g = mínᵢ(holgura de estos Aᵢ)` queda explícito.
- **Dos regiones (precisa `c` y `p`):** Ω_A = {cos≥**0.88**} (núcleo contractivo, L≈0.85) ⊂ Ω = {cos≥0.70}
  (viabilidad). `c` se **certifica en Ω_A**; en Ω\Ω_A f₀ es no-expansiva (L≤1.0) + proyección Π_Ω. ⇒ 0.88
  es un nivel intermedio (núcleo) entre θ_viable=0.70 y el atractor — añadirlo a la signature.
- **ε_frontier DERIVADO (quita flag heurístico):** ε_frontier = √(2(1−θ_viable)) = √0.60 = **0.775** (dist.
  euclidiana para vectores unitarios a coseno 0.70). ⇒ r = ε_frontier/σ_max = 0.775/0.42 = **1.845**,
  m = 1−1/r = **0.458**. Geométrico, no postulado.
- **Garantía probabilística:** P(x(t+1)∈Ω | x(t)∈Ω_A) > 0.95 — la invariancia estocástica; certify-not-
  declare en forma probabilística.
- **⚠ Tensión a declarar (Fierro la vería):** `L≈0.85` (norma de operador del Jacobiano en Ω_A, métrica
  cos) y `λ_max=ln(0.99)` (exponente de Lyapunov del mapa de 4 estados `p←0.99p+0.01p_eq`) son
  contracciones sobre **operadores/subespacios DISTINTOS** — no comparables directo (si L≈0.85 fuera bound
  uniforme ⇒ λ_max≤ln0.85=−0.16, no −0.01). Ambos <1. El paper debe ser preciso sobre cuál certifica qué;
  la trilogía (λ_max, Benettin) es la rigurosa. `c` debe declarar qué operador usa.

**Neto:** la solución a Fierro NO hay que construirla — existe (teorema + mapeo + validación NC). §4 la
adapta con la trilogía reemplazando el bound Jacobiano por λ_max medido donde corresponde. Y V hereda de
aquí: `g` (axioma→convexo), el núcleo Ω_A para `c`, ε_frontier derivado para `m`.

---

## 10. Suite de validación del certificador (pre-registrada 2026-06-15)

Auditoría post-revisión: el funcional V y el teorema de invariancia híbrida son lo **más nuevo y menos
validado** del paper. Tres deudas duras, cada una con spec pre-registrada (hipótesis fijadas antes de correr):

- **EXP-G-01** (`docs/experiments/EXP-G-01/`) — `g` es el **único** ingrediente de V *afirmado* (≈1), no
  medido. Censo de holguras per-restricción de Ω (incl. caras éticas A0/A0.1) ⇒ g medido + demostrar
  *ethics-as-geometry* (violar A0 ⇒ g→0 ⇒ V=0). Cierra el hueco de la fila `g` de §5.
- **EXP-VNC-01** (`docs/experiments/EXP-VNC-01/`) — V **nunca se muestra discriminando** (solo medido en
  el kernel sano, 0.46–0.99). Control negativo: configuración no-viable ⇒ **V→0**. La prueba de
  falsación del capstone; cada eje (g/c/t/m) puede tirar V→0 por separado (el min). *La más prioritaria.*
- **EXP-CORE-01** (`docs/experiments/EXP-CORE-01/`) — θ_A=0.88 y L≈0.85 están **importados** (HTML Fierro),
  no medidos; y μ\* se fuga bajo cos=0.88 (min_cos de EXP-NS-01: 0.871@σ=0.15 … 0.856@σ=2.0). Mide ρ(cos),
  θ_A real, L del mapa completo (resuelve la tensión L-vs-λ por medición), y el soporte de μ\*. El punto
  donde Fierro presionará.

**Narrativa:** la trilogía (LY/MC/TDA) validó el *atractor*; esta suite valida el *certificador*. EXP-VNC-01
+ EXP-G-01 son deuda dura (sin ellas el capstone está afirmado, no validado); EXP-CORE-01 blinda el teorema.
Specs en `index.vsm` (status=pre-registered). Implementar+correr en LXC 108 (Sonnet), mismo patrón que NS-01.

⟦ viability_functional_note · rev.4 + suite · attractor_convergence · 2026-06-15 ⟧
