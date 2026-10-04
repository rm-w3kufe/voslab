# ESPECIFICACIÓN DE GRÁFICOS Y VISUALES

**Enfoque:** Lógica de dependencias (IF/THEN), no estimaciones temporales.  
**Scope:** Nuevos gráficos + revisión de existentes para VSL-MATH-01 + Experimentos

---

## 1. GRÁFICOS NUEVOS REQUERIDOS

### 1.1 EXP-LY-01: Lyapunov Spectrum (Benettin)

**IF** EXP-LY-01 ejecuta y produce `lyapunov_spectrum.json` (10 Lyapunov exponents + metadata)

**THEN** generar 4 gráficos obligatorios:

#### G_LY-01a: Convergencia de λᵢ (plot individual)
```
Tipo: Line plot (10 curvas)
Ejes: tiempo (t) vs λᵢ (convergencia asintótica)
Datos: λ₁(t), λ₂(t), ..., λ₁₀(t) desde t=0 a t=T
Formato: PNG 1200×800 + TikZ source
Propósito: Mostrar que cada λᵢ converge a valor estable
Validación: cada curva debe alcanzar meseta horizontal
```

#### G_LY-01b: D_KY Real vs D_eff (Proxy Comparison)
```
Tipo: Bar chart + scatter
Subplot 1: D_KY_real = (Σ λᵢ) / |λ_k| vs D_eff = 3.00
Subplot 2: Diferencia relativa en % si divergen
Datos: 1 valor real, 1 valor proxy, intervalo confianza si aplica
Formato: PNG 800×400 + TikZ
Propósito: Validar que proxy fue representativo
Validación: |D_KY_real - D_eff| < 5% OR explicar divergencia
```

#### G_LY-01c: Suma de Lyapunov (Disipatividad)
```
Tipo: Line plot con banda de confianza
Eje Y: Σ λᵢ(t) (suma acumulativa)
Eje X: tiempo t
Valor esperado: converge a valor negativo (sistema disipativo)
Formato: PNG 1200×600 + TikZ
Propósito: Demostrar que E[ΔL] ≤ 0 (Teorema 2 validation)
Validación: Σ λᵢ(∞) < 0 significativamente
```

#### G_LY-01d: Dimensionalidad de Kaplan-Yorke (sumario)
```
Tipo: Table + infografía
Contenido: D_KY valor + intervalo confianza + comparación histórico
Formato: PNG 600×300 (infografía simple)
Propósito: Para §4.5 (validación empírica)
Validación: Fácilmente interpretable por revisor
```

**Total EXP-LY-01:** 4 gráficos nuevos

---

### 1.2 EXP-JAC-01: Jacobiana y Contractividad

**IF** EXP-JAC-01 procesa trajectories y calcula ||∇f₀||_op

**THEN** generar 4 gráficos obligatorios:

#### G_JAC-01a: Distribución de L por región
```
Tipo: Box plot o violin plot (3 cajas: Ω_A, Ω_intermediate, Ω_boundary)
Eje Y: L (Lipschitz constant)
Datos: L_values para cada región (n=100+ samples por región)
Línea horizontal: L=1.0 (límite contractivo)
Formato: PNG 1000×600 + TikZ
Propósito: Mostrar L < 1 en Ω_A, L → 1 en frontera
Validación: Ω_A box está completamente bajo L=1.0
```

#### G_JAC-01b: L vs cos(x) — Scatter plot
```
Tipo: Scatter + línea de tendencia
Eje X: cos(x, x̄) (0.70 a 1.0)
Eje Y: L (0.0 a 1.2)
Puntos coloreados: rojo (Ω_A), naranja (intermediate), azul (boundary)
Línea: tendencia suave (lowess o polynomial fit)
Formato: PNG 1200×800 + TikZ
Propósito: Relación monótona L(cos): L crece hacia frontera
Validación: Patrón claro, correlación cuantificada
```

#### G_JAC-01c: Norma de Jacobiana en tiempo real
```
Tipo: Time series (running max de ||∇f₀(x(t))||_op)
Eje Y: L(t) (máximo visto hasta momento t)
Eje X: tiempo o # iteraciones
Datos: De EXP-JAC-01-validation (kernel run con jacobian_trace)
Formato: PNG 1200×600 + TikZ
Propósito: Validación in-situ (kernel run confirm L < 1)
Validación: Converge y estabiliza < 1.0
```

#### G_JAC-01d: Heatmap — Jacobiana matriz (snapshot)
```
Tipo: Heatmap (matriz 128×128)
Datos: ∇f₀(x_representative) en momento representativo
Colormap: RdBu (rojo=positivo, azul=negativo)
Anotación: L_snapshot valor en corner
Formato: PNG 800×800 + TikZ (o matplotlib export)
Propósito: Visualizar estructura de ∇f₀ (optional, ilustrativo)
Validación: Patrón consistente con f₀ architecture
```

**Total EXP-JAC-01:** 4 gráficos nuevos

---

### 1.3 EXP-NC-01..03: Negative Controls

**IF** EXP-NC-01, EXP-NC-02, EXP-NC-03 ejecutan completamente

**THEN** generar 6 gráficos obligatorios + síntesis:

#### G_NC-01a: S5 Removed — Convergencia vs Recuperación
```
Tipo: Subplot (2 panels)
Panel 1: cos(x,x̄) vs tiempo (baseline vs S5-removed)
Panel 2: Zoom en región de perturbación (0-500 pasos post-perturbación)
Datos: 2 traces: baseline (control) + S5-removed (treatment)
Línea horizontal: cos=0.70 (frontera)
Formato: PNG 1400×600 + TikZ
Propósito: Mostrar convergencia ✓ pero NO recuperación ✗
Validación: S5-removed nunca recupera de cos=0.70
```

#### G_NC-02a: Trust Frozen — Mismo patrón
```
Tipo: Idem G_NC-01a
Contenido: Baseline vs trust-frozen
Línea: cos=0.70
Propósito: Mostrar que frozen trust = sin recuperación
Validación: Resultado similar a NC-01
```

#### G_NC-03a: S2 Removed — Cuenca diferente
```
Tipo: Subplot (2 panels)
Panel 1: cos evolution (baseline vs S2-removed)
Panel 2: Histogram de cos-values en régimen estable
Datos: Baseline muestra cos_stasis≈0.8055, S2-removed muestra cos_stasis≈0.771
Líneas verticales: cos_piso esperado para cada
Formato: PNG 1400×600 + TikZ
Propósito: Mostrar que S2 removal cambia cuenca, no elimina convergencia
Validación: Dos cuencas diferentes, ambas estables pero geometrías distintas
```

#### G_NC-comparative: Tabla síntesis
```
Tipo: Table visual (4 columnas: Baseline, NC-01, NC-02, NC-03)
Filas: cos_piso, convergencia, recuperación, τ_rec, firma de dip
Formato: PNG 1000×400 (tabla coloreada: ✓ verde, ✗ rojo, ~ naranja)
Propósito: Quick reference para §4 (Negative Controls summary)
Validación: Patrón claro: todos convergen, pero solo baseline recupera
```

#### G_NC-combined: Overlay de cos(t) — todas las 4 traces
```
Tipo: Line plot con 4 trazas (baseline, NC-01, NC-02, NC-03)
Colores distintos: baseline (azul), NC-01 (rojo), NC-02 (naranja), NC-03 (verde)
Eje Y: cos(x,t)
Eje X: tiempo / iteraciones
Zoom 1: vista completa (0 a 240 min)
Zoom 2: región post-perturbación (primeros 30 min tras kick)
Formato: PNG 1400×800 + TikZ
Propósito: Visualizar cómo cada component (S5, trust, S2) afecta dinámicas
Validación: Trazas divergen en recuperación, convergen en régimen estable
```

**Total EXP-NC-01..03:** 6 gráficos nuevos

---

## 2. GRÁFICOS EXISTENTES A REVISAR / REINTERPRETAR

**IF** Gráficos de EXP-AB-01, EXP-TSM-01, EXP-TC-01 existen y están archivados

**THEN** revisar para coherencia con VSL-MATH-01:

### 2.1 EXP-AB-01 (Atractor Geometry — Basin Floor)

#### G_AB-01: cos_piso = 0.875 bajo régimen impulsivo
```
Gráfico existente: ✓ (muestra 11 runs con δ=0..1.0)
Revisión requerida: 
  - Añadir anotación: "ε_frontier ≈ 0.78, σ_max ≈ 0.42, margen 1.86x"
  - Overlay líneas: cos=0.70 (frontera viable), cos=0.875 (piso observado)
  - Caption actualizado: "Basin floor emerges from noise certification (§4.3)"
Formato: Mantener PNG existente, update caption/anotaciones en TikZ
Propósito: Validar que piso no es coincidencia, es σ_max limited
```

#### G_AB-02: τ_rec < 30s (Recovery Time)
```
Gráfico existente: ¿? (verificar si existe plot de tiempo de recuperación)
IF existe:
  - Revisar: τ_rec values, estadísticas, distribución
  - Actualizar caption: "Theoretical prediction: τ_rec ≈ (1/(1-L))·(σ_max/ε_frontier) ≈ 22s"
  - Overlay: línea teórica vs observado
IF no existe:
  - Generar: histogram o box plot de τ_rec por experimento
  - 11 valores (uno por run)
  - Línea en 30s, teoría en 22s
```

### 2.2 EXP-TSM-01 / EXP-TSM-65C (Thermal Senescence)

#### G_TSM-*.stasis: cos evolution
```
Gráficos existentes: ✓ (2 plots, uno por temperatura)
Revisión requerida:
  - Anotación: "L < 0.9 demonstrated: stasis_cos maintains 1.0000"
  - Caption: "Contractividad en Ω_A verified: thermal stress ≤ 65°C preserves L < 1"
  - Opcional: overlay Jacobiana snapshot (L value) en corner
Formato: Mantener PNG, mejorar caption
Propósito: Soporte para §4.2 (Contractividad)
```

### 2.3 EXP-TC-01 (Thermal Ceiling)

#### G_TC-01: min_cos en thermal stress
```
Gráfico existente: ✓ (muestra cos evolution hasta SAFETY_HALT @ 72°C)
Revisión requerida:
  - Anotación: "min_cos = 0.9365, ε_frontier = 0.78, margen = 22%"
  - Caption: "Thermal viability boundary: σ_max certification holds at 68°C sustained"
  - Overlay: línea ε_frontier en eje Y (como referencia)
Formato: Mantener PNG, update anotaciones
Propósito: Validar ruido certification bajo thermal stress
```

### 2.4 EXP-OE-01 (Maxwell Demon — Observer Constitutivity)

#### G_OE-01: Lyapunov trace (libre vs controlado)
```
Gráfico existente: ✓ (2 subplots: A=libre, B=demonio)
Revisión requerida:
  - Anotación en subplot B: "E[ΔL] ≤ 0 validated: control reduces ΔL"
  - Caption: "Observer effect: control layer demonstrates Theorem 2 (stochastic Lyapunov)"
Formato: Mantener PNG, update caption
Propósito: Soporte para §4.4 (Teorema invariancia)
```

---

## 3. GRÁFICOS PARA §4 (NUEVA SECCIÓN)

**IF** §4 se escribe e integra en main.tex

**THEN** producir gráficos específicos para sección:

### 3.1 Ω como Politopo (Ilustración)

#### G_OMEGA-01: Proyección de Ω en ℝ³
```
Tipo: 3D plot o isometric projection
Dimensiones: (cos(x), trust, entropía) — 3 variables clave
Datos: Puntos de todas las trajectories en Ω
Volumen dibujado: Ω como poliedro (convex hull visual)
Subvolumen: Ω_A (cos ≥ 0.88) sombreado diferente
Formato: PNG 1000×1000 (o TikZ 3D)
Propósito: Visualizar Ω como región convexa
Validación: Límites claros, estructura visible
```

#### G_OMEGA_2D: Sección 2D (cos vs trust)
```
Tipo: Contour plot o scatter + boundary
Eje X: trust
Eje Y: cos(x)
Relleno: región Ω sombreada
Línea: frontera ∂Ω
Dos colores: Ω_A (cos ≥ 0.88) vs Ω \ Ω_A (cos < 0.88)
Puntos: muestra de states de EXP-TSM-01
Formato: PNG 1000×800 + TikZ
Propósito: Mostrar separación Ω_A / Ω en 2D interpretable
```

### 3.2 Diagrama Conceptual — Two-Layer Viability

#### G_LAYER_DIAGRAM: Arquitectura conceptual
```
Tipo: Infografía / diagrama de bloques
Contenido:
  - Layer 1 (Architecture): Bloques A-G selectan cuenca Ω
  - Layer 2 (Governance): S5 + trust determinan recuperación
  - Atractor: círculo en centro
  - Cuenca Ω: elipse alrededor
  - Ω_A: inner region (contractiva)
  - Flechas: cómo cada layer actúa

Formato: PDF (TikZ ilustración)
Propósito: Abrir §4 con conceptual clarity
Validación: Fácil de entender sin ecuaciones
```

---

## 4. WORKFLOW DE GENERACIÓN

**Flujo lógico (IF/THEN):**

```
IF EXP-LY-01 produce lyapunov_spectrum.json
  THEN ejecutar scripts/plot_lyapunov.py
       OUTPUT: G_LY-01a, G_LY-01b, G_LY-01c, G_LY-01d
       CONDITION: OK IF todas 4 figuras compiladas sin error

IF EXP-JAC-01 procesa jacobian_analysis.json
  THEN ejecutar scripts/plot_jacobian.py
       OUTPUT: G_JAC-01a, G_JAC-01b, G_JAC-01c, G_JAC-01d
       CONDITION: OK IF L distribution claramente < 1 en Ω_A

IF EXP-NC-01..03 completan y logs están disponibles
  THEN ejecutar scripts/plot_negative_controls.py
       OUTPUT: G_NC-01a, G_NC-02a, G_NC-03a, G_NC-comparative, G_NC-combined
       CONDITION: OK IF patrón claro: recuperación presente/ausente

IF G_LY-01d, G_JAC-01a, G_NC-comparative disponibles
  THEN generar resúmenes visuales para captions de §4
       OUTPUT: Snippets para 4.5 (Empirical Validation)
       CONDITION: OK IF fáciles de referenciar desde texto

IF todos gráficos nuevos compilados + revisión de existentes completada
  THEN integrar en main.tex con captions y cross-references
       OUTPUT: main.tex §4 con todas las figuras
       CONDITION: LaTeX compile sin warnings de figura
```

---

## 5. LISTA DE GRÁFICOS — RESUMEN PRODUCCIÓN

| Gráfico | Tipo | Origen | Status | Propósito |
|---------|------|--------|--------|-----------|
| **G_LY-01a** | Line (10 curves) | EXP-LY-01 | NEW | λᵢ convergencia |
| **G_LY-01b** | Bar + scatter | EXP-LY-01 | NEW | D_KY real vs proxy |
| **G_LY-01c** | Line + band | EXP-LY-01 | NEW | Σλᵢ (disipatividad) |
| **G_LY-01d** | Infografía | EXP-LY-01 | NEW | D_KY summary |
| **G_JAC-01a** | Box/violin plot | EXP-JAC-01 | NEW | L distribution |
| **G_JAC-01b** | Scatter + trend | EXP-JAC-01 | NEW | L vs cos |
| **G_JAC-01c** | Time series | EXP-JAC-01-val | NEW | L(t) runtime |
| **G_JAC-01d** | Heatmap | EXP-JAC-01 | NEW | ∇f₀ snapshot |
| **G_NC-01a** | Subplot (2 panel) | EXP-NC-01 | NEW | S5 removal effect |
| **G_NC-02a** | Subplot (2 panel) | EXP-NC-02 | NEW | Trust freeze effect |
| **G_NC-03a** | Subplot (2 panel) | EXP-NC-03 | NEW | S2 removal effect |
| **G_NC-comparative** | Table visual | EXP-NC-01..03 | NEW | Síntesis NC |
| **G_NC-combined** | Line (4 traces) | EXP-NC-01..03 | NEW | Overlay comparativo |
| **G_AB-01** | Scatter | EXP-AB-01 | REVISE | Anotaciones σ_max |
| **G_AB-02** | Histogram/box | EXP-AB-01 | REVISE/NEW | τ_rec distribution |
| **G_TSM-*.stasis** | Line | EXP-TSM | REVISE | Caption L validation |
| **G_TC-01** | Line | EXP-TC-01 | REVISE | Anotaciones ε_frontier |
| **G_OE-01** | Subplot (2) | EXP-OE-01 | REVISE | Caption Teorema 2 |
| **G_OMEGA-01** | 3D / isometric | Theory | NEW | Ω politopo visual |
| **G_OMEGA_2D** | Contour + scatter | Theory | NEW | Ω sección 2D |
| **G_LAYER_DIAGRAM** | Diagram | Theory | NEW | Two-layer conceptual |

---

## 6. PRODUCCIÓN TOTAL

**Gráficos completamente nuevos:** 14  
**Gráficos a revisar/mejorar:** 8  
**Total de artefactos visuales:** 22

**Formatos requeridos:**
- PNG: 18 (exportación de Python / matplotlib)
- PDF: 3 (TikZ diagrams)
- Data files: 5 (.json de análisis para referencia)

**Scripts Python requeridos:**
- `scripts/plot_lyapunov.py` — 4 gráficos
- `scripts/plot_jacobian.py` — 4 gráficos
- `scripts/plot_negative_controls.py` — 5 gráficos
- `scripts/plot_omega_geometry.py` — 2 gráficos

**Dependencia crítica:**
- IF scripts generan PNG/PDF correctamente THEN main.tex integración es limpia
- IF algún gráfico falla THEN iteration needed antes de compilación final

---

## 7. CHECKLIST DE VALIDACIÓN POR GRÁFICO

**Para cada gráfico nuevo, validar:**

```
[ ] Datos extraídos correctamente de .json
[ ] Ejes etiquetados con unidades
[ ] Leyenda clara y completa
[ ] Colores distinguibles (rojo/verde colorblind-safe)
[ ] Resolución ≥ 1200 px (ancho mínimo)
[ ] Formato PNG o PDF según req
[ ] Caption redactado y coherente con §4
[ ] Cross-reference en main.tex apunta correctamente
[ ] No hay warnings de LaTeX ([h] vs [!h] placement)
```

**Para revisión de gráficos existentes, validar:**

```
[ ] Caption actualizado con referencias a VSL-MATH-01
[ ] Anotaciones nuevas (σ_max, ε_frontier, L values) visibles
[ ] Datos no cambiados, solo interpretación mejorada
[ ] Coherencia con narrativa de §4
```

---

## 8. RESUMEN FINAL

**Producción de gráficos es modular y lógicamente secuencial:**

1. **IF** EXP-LY-01 ✓ **THEN** generar G_LY-01* (4 gráficos)
2. **IF** EXP-JAC-01 ✓ **THEN** generar G_JAC-01* (4 gráficos)
3. **IF** EXP-NC-01..03 ✓ **THEN** generar G_NC-* (5 gráficos)
4. **IF** todos los anteriores ✓ **THEN** revisar G_AB, G_TSM, G_TC, G_OE (8 gráficos)
5. **IF** §4 redactado **THEN** generar G_OMEGA, G_LAYER (3 gráficos)
6. **IF** todos los gráficos compilados **THEN** integrar en main.tex

**No hay dependencias circulares. Flujo es DAG (directed acyclic graph).**

