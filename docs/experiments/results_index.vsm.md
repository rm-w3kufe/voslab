# Experimental Results Index — vsf-nucleus

```
@vsm 0.3
// docs/experiments/results_index.vsm — master record of all experiment results
// Updated: 2026-04-15
// Format: result(id) = { date, hardware, ticks/duration, key_metrics, interpretation }
```

---

## Hardware baseline (n02 — Proxmox, Intel Skylake 4c)

| Parámetro | Valor |
|-----------|-------|
| Node | n02, 192.168.0.168, Proxmox |
| Kernel | Linux 6.17.2-1-pve |
| CPU | Intel Skylake, 4 cores |
| cgroup | v2, `/sys/fs/cgroup` |
| Temp baseline | 33–46°C idle |
| Temp ceiling (hw throttle) | 67–71°C |
| Thermal safety gate (vsf) | 70°C |

---

## Resultados completos

### spec_boot — serie de convergencia

| Experimento | Ticks | cycles | stasis_cos | mean_dL | D_KY | V_mem entries | viable_full | Fecha |
|-------------|-------|--------|-----------|---------|------|---------------|-------------|-------|
| spec_boot_300t | 300 | 4 | 0.9974 (scalar) | n/a | 5.31 | n/a | true | 2026-04-12 |
| spec_boot_300t_sv | 300 | 4 | 0.8169 (128-dim) | n/a | 5.31 | n/a | true | 2026-04-12 |
| spec_boot_1000t | 1000 | 14 | ~0.85 | -0.012 | 3.00 | 2 (13 merges) | true | 2026-04-12 |
| spec_boot_1000t_b | 1000 | — | — | — | — | — | true | 2026-04-13 |
| spec_boot_2000t | 2000 | 28 | 0.8055 | -0.00521 | 3.00 | 2 (27/29 merged) | true | 2026-04-13 |
| spec_boot_10000t | 10000 | 141 | 0.8896 | -0.00122 | 3.00 | 1 (139/141 merged) | true | 2026-04-13 |
| long_run_senescence | ~110 min | 60,492,497 | 0.9688–0.9996 | -0.00000 | 3.00 | 1 (60.5M merged) | true | 2026-04-14 |

**Hallazgos clave — convergencia:**
- D_KY estabiliza en 3.00 desde 1000t en adelante — dimensionalidad del atractor fija
- mean_dL → 0 asintóticamente (converge en ~1000 ciclos)
- V_mem colapsa a 1 entrada en runs largos — atractor de PUNTO, no región
- stasis_cos oscila entre 0.97–1.00 — oscilación natural del ciclo soplo, no deriva

---

### Senescencia — análisis trust decay

| Métrica | Valor observado | Diagnóstico |
|---------|-----------------|-------------|
| H_rest después 110 min | 0.400 (FLAT) | H_REST es constante en código — no puede derivar |
| trust después 110 min | 0.000–0.002 | Atractor de bajo-trust (bifurcación dinámica) |
| V_mem después 60M ciclos | 1 entrada | Atractor de punto — extrema convergencia |

**Diagnóstico trust decay:**
```
stasis:  trust += 0.002 / tick
degen:   trust -= 0.001 / tick  ×  TAU_RECOVERY (50 ticks min)
balance: -0.001×50 = -0.05 vs +0.002×N_stasis_ticks
```
Cuando trust < ~0.3: presión sube → INHALE dispara casi inmediatamente →
muy pocos ticks stasis → no recupera. **Atractor de bajo-trust estable.**

**Diagnóstico H_rest plano:**
`h_rest = H_REST_RATIO * N_ORGANELLES.log2() = 0.20 * 2.0 = 0.400` — constante hardcoded.
Para observar senescencia real, h_rest debe ser variable adaptativa.

**Implicación para paper:** senescencia bajo spec_boot sintético = cero.
Senescencia requiere: (a) h_rest adaptativo, O (b) estrés externo real
(temperatura, kernels competidores, señales ruidosas).

---

### Experimentos térmicos

| Experimento | Peak temp | viable_full | Resultado | Fecha |
|-------------|-----------|-------------|-----------|-------|
| thermal_stress_v1 | 49°C | true | single-thread ceiling | 2026-04-12 |
| thermal_stress_v2 | 54°C | true | per-tick thread spawn, overhead alto | 2026-04-12 |
| thermal_stress_v3 | 63°C | true | persistent workers + barrier — TARGET REACHED | 2026-04-12 |
| thermal_ceiling_v4 | HALT@t=0 | n/a | hw ya en 71°C post-critical_angle | 2026-04-13 |
| critical_angle | 65–69°C | TRUE throughout | min_stasis_cos=0.9377, θ_PSI not reached | 2026-04-13 |
| thermal_ceiling_v4_bis | 70°C (HALT) | TRUE throughout | min_cos=0.9365, cos RECOVERS at hold, viable always | 2026-04-18 |

**Hallazgos:**
- Límite térmico hw: 67–71°C (throttling del procesador)
- viable_full = true incluso a 70°C bajo throttling
- θ_PSI < 0.9377 (upper bound desde critical_angle)
- min_cos=0.9365 (20.5°) — dentro del cono del atractor
- **stasis_cos se recupera durante la fase hold** (0.9770 → 0.9953 antes del SAFETY_HALT) — basin tiene resiliencia activa

---

### Perturbación de activación — theta_psi_stress

| Delta (δ) | min_cos | viable_full | Notas |
|-----------|---------|-------------|-------|
| 0.1 | — | true | estrés mínimo |
| 0.3 | — | true | estrés moderado |
| 0.7 | — | true | estrés alto |
| 1.0 | 0.79 | **true** | máximo probado — basin floor ≈ 0.79 |

**Hallazgo clave:** `viable_full=false` **no fue alcanzado en ningún δ ≤ 1.0.**

**Redefinición de θ_PSI:**
- Definición original: "ángulo donde viable_full=false por primera vez" — **el cruce no existe empíricamente**
- Definición revisada: **θ_PSI = 0.79 como umbral PRECAUTORIO** (basin floor observado, máx. estrés)
- PSI/1.0 L2 = intervención preventiva, no rescate de colapso
- L3 (viable_full=false) puede ser estructuralmente inalcanzable bajo operación normal

---

### Geometría del atractor — multikernel

| Métrica | Valor | Interpretación |
|---------|-------|----------------|
| mean pairwise cos | 0.9854 | todos en la misma cuenca |
| mean pairwise angle | 9.8° | mucho más estrecho que cono 18.2° |
| min cos | 0.9607 (k0,k3) | ángulo = 16.1° — dentro del cono |
| verdict | SAME BASIN | H1 confirmada |
| trust_init range | 0.55–0.85 | condiciones iniciales irrelevantes |

**H1 confirmada:** el atractor es insensible a condiciones iniciales (trust_init).
**Cono del atractor:** 18.2° = arccos(0.95) — 87% observaciones convergen a este radio.

---

### Resiliencia del sistema

| Experimento | Resultado | Axioma confirmado |
|-------------|-----------|-------------------|
| s3_failure_resilience | viable_all=100% en fase sin S3 | **A_auto** |
| cgroup_multikernel | viable_all=100% bajo presupuesto térmico compartido | A6 + A3 |
| fuzz_suite | 60,000 assertions, 0 failures | T1 invariants |
| T1-T4 test_suite | ALL PASS | lifecycle gate |

---

## Hipótesis — estado formal

```
@vsm 0.3

H1: "el atractor es insensible a condiciones iniciales"
  status: CONFIRMED
  evidence: multikernel_geometry (mean_cos=0.9854, trust_init=[0.55..0.85])
  ref: session 2026-04-13b

H2: "S1 kernels mantienen viabilidad sin S3 (A_auto intrínseca)"
  status: CONFIRMED
  evidence: s3_failure_resilience (viable_all=100% phase2)
  ref: session 2026-04-13b

H3: "el atractor converge Lyapunov (E[dL/dt] ≤ 0)"
  status: CONFIRMED
  evidence: spec_boot_1000t (mean_dL=-0.012), 10000t (-0.00122), long_run (-0.00000)
  ref: session 2026-04-12d → 2026-04-14

H4: "el sistema es termodinámicamente estable bajo throttling térmico"
  status: CONFIRMED (extended 2026-04-18)
  evidence: critical_angle (viable_full=true a 67–69°C, stasis_cos≥0.9377)
            thermal_ceiling_v4_bis (viable_full=true a 70°C, min_cos=0.9365, cos recovers at hold)
  ref: session 2026-04-13b + 2026-04-18

H5: "senescencia requiere estrés externo — no emerge en kernel aislado"
  status: PARTIAL (impl constraint identified)
  evidence_partial: H_rest=0.400 FLAT en 60.5M ciclos / 110 min — sin deriva
  cause: h_rest es constante hardcoded (H_REST_RATIO×log2(N_ORGANELLES)) — no puede derivar
  gap: test real requiere h_rest adaptativo O estrés externo (térmico/competidores/ruido)
  experiment_needed: adaptive_h_rest parameter sweep OR long_run_thermal

H6: "existe un umbral de recursión (N_kernels) bajo presión térmica donde viable_all < 1"
  status: OPEN
  evidence_partial: cgroup_multikernel viable_all=100% a N=4
  gap: no se ha probado N > 4 bajo carga térmica real
  experiment_needed: recursive_thermal_ramp

H7: "trust tiene bifurcación dinámica — atractor de bajo-trust estable"
  status: CONFIRMED (análisis)
  evidence: long_run trust=0.000–0.002 en 110 min desde trust_init=0.80
  mechanism: degen penaliza -0.050/ciclo, stasis recupera +0.002×N_stasis << 0.050
  implication: trust en spec_boot no es trust del nucleus — variables distintas

H8: "viable_full=false es estructuralmente inalcanzable bajo perturbación δ≤1.0"
  status: CONFIRMED (nueva, 2026-04-18)
  evidence: theta_psi_stress — δ=1.0 → min_cos=0.79, viable_full=true
  implication: θ_PSI redefinido como umbral precautorio (0.79), no de fallo
  open_q: δ > 1.0 no probado — requiere revisión de diseño

H9: "la curvatura de respuesta térmica es no-lineal (inflection point existe)"
  status: PENDING — thermal_ladder en ejecución (2026-04-18)
  evidence_partial: v1=49°C, v3=63°C, v4_bis=68°C — puntos conocidos
  experiment: thermal_ladder (50→60→70→80°C) — resultados pendientes
```

---

## Próximos experimentos (ciclo 2026-04-18)

Ver `docs/experiments/queue.vsm` — prioridades revisadas con findings de long_run.
