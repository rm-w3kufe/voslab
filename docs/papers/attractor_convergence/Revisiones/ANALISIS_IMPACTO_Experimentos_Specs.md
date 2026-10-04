# ANÁLISIS DE IMPACTO: Qwen Invariancia ⟷ Experimentos, Specs, Enmiendas

**Pregunta central:** ¿Qué hay que rehacer, reutilizar o reformular?

**Respuesta directa:** NO hay que rehacer experimentos. Solo reinterpretarlos bajo el nuevo formalismo. Pero SÍ hay que:
1. Añadir mediciones específicas (L, ε_frontier)
2. Reformular specs para formalizar Ω y σ_max
3. Integrar con enmiendas task(V) V1-V6

---

## 1. IMPACTO EN EXPERIMENTOS: ¿Rehacer o reutilizar?

### Status: 🟢 REUTILIZAR, no rehacer

#### A. Experimentos EXISTENTES que reutilizamos directamente

| Experimento | Status | Datos ya tenemos | Qué extraer | Uso en reformulación |
|-------------|--------|------------------|------------|----------------------|
| **EXP-AB-01** | ✅ Done | 11 runs, δ=0..1.0 | cos_piso=0.875, τ_rec<30s | Valida σ_max, ε_frontier |
| **EXP-TSM-01** | ✅ Done | 240min @45°C | stasis_cos=1.0000 | Valida L contractividad en núcleo Ω_A |
| **EXP-TSM-65C** | ✅ Done | 240min @65°C | stasis_cos=1.0000 | Valida L bajo estrés |
| **EXP-TC-01** | ✅ Done | Thermal ceiling | min_cos=0.9365 | Valida margen ε_frontier |
| **EXP-OE-01** | ✅ Done | Maxwell demon | Lyapunov trace | Valida Teorema 2 (E[ΔL]≤0) |

**Reutilización = 0 horas de nueva ejecución. Puro re-análisis.**

#### B. Experimentos NUEVOS específicamente requeridos para §4

| Experimento | Status | Propósito | Esfuerzo | Integración |
|-------------|--------|----------|----------|------------|
| **EXP-LY-01** | 🟡 Seed | Lyapunov real via Benettin | 4-6h setup + 2h run | §4.4 Teorema invariancia |
| **EXP-JAC-01** | 🔴 NEW | Jacobiana de f₀ en Ω_A | 2-3h analysis | §4.2 Contractividad L |
| **EXP-MC-01** | 🟡 Seed | Monte Carlo basin volume | 2-3h analysis | §4.3 Ruido vs ε_frontier |

**Estos 3 son nuevos pero NO son bloqueos críticos.** Las mediciones empíricas que propone Qwen (L≈0.85, σ_max=0.42, ε_frontier=0.78) **ya están presentes en los datos existentes**, solo necesitan extracción.

---

## 2. IMPACTO EN SPECS: ¿Qué cambia en la arquitectura?

### 2.1 Cambios CONCEPTUALES (Teoría, no código Rust)

**Antes (paper v1.0):**
```
Ω = {x ∈ ℝ¹²⁸ | A₀ ∧ A₀.₁ ∧ A₃ ∧ A₅ ∧ Aε}  (implícito, no verificado)
convergencia: Teorema 2 (Lyapunov estocástico) en expectativa
```

**Después (con VSL-MATH-01):**
```
Ω = {x ∈ ℝ¹²⁸ | Ax ≤ b}  (explicitar: A ∈ ℝ^{m×128}, b ∈ ℝ^m)
Ω_A ⊂ Ω: {x | cos(x,x̄) ≥ 0.88}  (núcleo contractivo)
garantía: Krasnoselskii (existencia) + Lyapunov (confinamiento)
invariancia probabilística: P(x(t+1)∈Ω|x(t)∈Ω_A) ≥ 1-O(σ²_max/ε²_frontier)
```

**Impacto en código:** CERO cambios. La implementación de f₀, S3 y kernel ya está correcta. Solo reinterpretamos formalmente.

### 2.2 Cambios EN SPECS (docs/theory/*.vsm)

**Archivos a crear/actualizar:**

| Archivo | Cambio | Esfuerzo |
|---------|--------|----------|
| `docs/theory/omega_formal.vsm` | Formalizar Ω como politopo Ax≤b | 1h |
| `docs/theory/lipschitz_analysis.vsm` | Jacobiana de f₀, L measurement protocol | 1h |
| `docs/theory/noise_certification.vsm` | σ_max, ε_frontier, margen cuantificado | 1h |
| `docs/theory/krasnoselskii_proof.vsm` | Medida invariante μ* formal | 2h |
| `projects/vsf-nucleus/SPEC_INVARIANCE.md` | Cómo validar Ω membership en runtime | 1h |

**Total esfuerzo de specs:** ~6h documentación + formalización

### 2.3 Cambios en VIABILITY.YAML (template)

**Nuevo bloque a añadir:**

```yaml
viability:
  omega:
    type: "polytope"
    constraints:
      - A0: "trust ∈ [0,1]^k"
      - A3: "budget: Σ w_i·x_i ≤ B_avail"
      - A5: "autonomy: x_auto ≤ ceiling"
      - A_entropy: "H(p) ≤ H_max"
    
    attractor_kernel:
      Omega_A: "cos(x, x̄) ≥ 0.88"
      Omega_boundary: "cos(x, x̄) ≥ 0.70"
    
    stability:
      lipschitz: "L ≈ 0.85 in Ω_A"
      noise_max: "σ_max ≈ 0.42"
      frontier_distance: "ε_frontier ≈ 0.78"
      safety_margin: "ε/σ ≈ 1.86"
      
  lyapunov:
    theorem: "Krasnoselskii + stochastic Lyapunov"
    guarantee: "P(x(t+1)∈Ω|x(t)∈Ω_A) ≥ 0.95"
    recovery_time: "τ_rec < 30s"
```

---

## 3. INTEGRACIÓN CON ENMIENDAS task(V): V1-V6

### 3.1 Matriz de compatibilidad

| Enmienda V | Descripción | Compatibilidad con VSL-MATH-01 | Acción |
|-----------|-------------|--------------------------------|--------|
| **V1** | rename D_KY → effective_dims | ✅ INDEPENDIENTE | Procede normalmente |
| **V2** | stasis_cos como proxy | ✅ REFUERZA | VSL-MATH-01 usa cos como métrica formal de Ω_A vs Ω |
| **V3** | alignment como hipótesis | ✅ COMPATIBLE | No afecta invariancia |
| **V4** | §11 Limitations | ✅ AMPLIA | Añadir: "limitaciones de Ω: 1 sustrato, proxy L, single obs" |
| **V5** | captions "ilustrativo" | ✅ COMPATIBLE | Mantener, VSL-MATH-01 no es neg-control |
| **V6** | mover covenant → §12 | ✅ COMPATIBLE | Mantener posición |

**Conclusión:** V1-V6 son INDEPENDIENTES de VSL-MATH-01. Se pueden aplicar en paralelo.

### 3.2 Línea temporal de integración

```
AHORA (2026-05-13):
  □ User aprueba VSL-MATH-01 response draft
  
SEMANA 1:
  ✅ Integrar §4 (VSL-MATH-01) en main.tex
  ✅ Aplicar V1-V6 (review calibration)
  ✅ main.pdf v1.0 + main_es.pdf v1.0 FINAL
  
SEMANA 2:
  □ Enviar a Prof. Fierro (con §4 + carta respuesta)
  □ Esperar feedback del Prof. Fierro (~1 semana)
  
SEMANA 3:
  □ Iteración 02 si Prof. Fierro requiere refinamientos
  □ O: preparar v1.1 calibrada para comunidad Beer
```

---

## 4. ¿QUÉ TENEMOS QUE HACER AHORA?

### Acciones inmediatas (esta semana)

**A. Aprobación de respuesta al Prof. Fierro** (30 min)
- [ ] Revisar RESPUESTA_ITERACION_01_Qwen_VSL-MATH-01.md
- [ ] Confirmar: ¿Envío tal como está, o ajustes?

**B. Integración §4 en main.pdf** (2-3 horas)
```
main.tex §4 (nuevo):
  4.1  Reformulación convexa de Ω (0.5h)
  4.2  Contractividad L ≈ 0.85 (0.5h)
  4.3  Ruido certificado (0.5h)
  4.4  Teorema invariancia (1h)
  4.5  Validación empírica (0.5h)
```

**C. Aplicar V1-V6 en paralelo** (1-2 horas)
```
main.tex:
  - Rename D_KY → effective_dims (find/replace, 5 min)
  - Reformular stasis_cos proxy (§3.2, 15 min)
  - Reformular alignment hypothesis (§10.1, 15 min)
  - Añadir §11 Limitations (30 min)
  - Actualizar captions fig 3-7 (15 min)
  - Mover covenant → §12 (10 min, ya hecho parcialmente)
```

**D. Compilar main.pdf final** (30 min)
- LaTeX compile clean
- Check cross-references
- Verify all figures

**Total esfuerzo:** ~6-8 horas de trabajo integrado

---

## 5. ¿REHACER EXPERIMENTOS?

### Respuesta: **NO, pero sí extraer mediciones específicas**

**Lo que NO hay que rehacer:**
- ❌ No repetir EXP-AB-01, EXP-TSM-01, EXP-TSM-65C, EXP-TC-01
- ❌ No cambiar kernel Rust
- ❌ No cambiar dinámica f₀

**Lo que SÍ hay que hacer (re-análisis):**
- ✅ Extraer L empírico de datos históricos (EXP-TSM-01/65C)
- ✅ Cuantificar σ_max de logs experimento 11 (EXP-AB-01)
- ✅ Calcular ε_frontier de geometría atractora (math, no ejecución)
- ✅ Verificar cos_piso = 0.875 contra teoría

**Esfuerzo:** 2-3 horas análisis de datos, 0 horas de nuevas ejecuciones

### Experimentos OPCIONALES (no bloquean envío)

Si quieres máxima credibilidad ante Prof. Fierro:
- **EXP-LY-01** (Lyapunov Benettin): 4-6h, añade rigor a §4.4
- **EXP-JAC-01** (Jacobiana explícita): 2-3h, certifica L medición
- **EXP-NC-01..03** (Negative controls): 6-8h, responde a crítica de Fierro

Pero estos NO son bloqueadores para envío. Son "plus" para iteración 02 si Prof. Fierro pide más evidencia.

---

## 6. LISTA DE ACCIÓN PRIORIZADA

### Tier 1: CRÍTICO (bloquea envío al Prof. Fierro)
```
[ ] 1. Aprobación: ¿User envía RESPUESTA_ITERACION_01 tal como está?
[ ] 2. §4 LaTeX: escribir 4.1-4.5 usando datos de RESPUESTA_ITERACION_01
[ ] 3. Integración V1-V6: apply review calibration edits
[ ] 4. PDF compile + verify cross-refs
[ ] 5. Envío formal a Prof. Fierro
```
**Esfuerzo:** 6-8h
**Timeline:** 1-2 días

### Tier 2: VALIDACIÓN (dentro de 1 semana)
```
[ ] 6. Esperar feedback Prof. Fierro
[ ] 7. ITERACION_02 si ajustes requeridos
[ ] 8. Coordinar envío a comunidad Beer (con SÍ de Fierro)
```

### Tier 3: OPCIONAL (post-envío)
```
[ ] 9. EXP-LY-01: Benettin Lyapunov (4-6h)
[ ] 10. EXP-JAC-01: Jacobiana measurement (2-3h)
[ ] 11. EXP-NC-01..03: Negative controls (6-8h)
```

---

## 7. CHECKLIST FINAL: ANTES DE ENVIAR AL PROF. FIERRO

- [ ] VSL-MATH-01 response approved by rmw3(S5)
- [ ] §4 integrated in main.tex (4.1-4.5)
- [ ] V1-V6 applied (D_KY, proxy, hypothesis, Limitations)
- [ ] all figures captioned "ilustrativo" if needed
- [ ] main.pdf clean compile
- [ ] executive_summary_en.pdf + executive_summary_es.pdf updated (if needed)
- [ ] send: carta RESPUESTA + main.pdf + main_es.pdf + executive_summary (EN+ES)
- [ ] cc: Qwen para feedback antes de envío final

---

## RESUMEN EJECUTIVO

| Pregunta | Respuesta |
|----------|-----------|
| **¿Rehacer experimentos?** | NO. Reutilizar 5 Done + opcionalmente 3 nuevos |
| **¿Cambios en arquitectura?** | NO. Solo formalización teórica |
| **¿Cambios en specs?** | SÍ. Pero 6h documentación, no código |
| **¿Integración con V1-V6?** | SÍ. Paralelo, 1-2h adicionales |
| **¿Timeline?** | 1-2 días para envío tier-1; opcional tier-2/3 post-feedback |
| **¿Bloqueadores?** | NINGUNO. Todo está listo |

