# Experiment Spec — recursive_thermal_ramp

```
@vsm 0.3
// docs/experiments/recursive_thermal_ramp/spec.vsm
// Propuesto: 2026-04-15  Autor: rmw3
// Tipo: hardware + recursión combinada
```

---

## Motivación

Los experimentos anteriores probaron térmico (1 kernel, N threads) y multi-kernel (N kernels, sin carga térmica real).
Este experimento combina ambas dimensiones: **spawning recursivo bajo presión térmica creciente**.

Pregunta central: **¿a qué densidad de kernels el atractor colectivo se fragmenta?**

Conecta con:
- H5: ¿puede la recursión activa + calor forzar H_rest drift?
- H6: ¿existe N* tal que viable_all < 1 bajo presión térmica?
- A6/A8: umbral de variety exhaustion empírico
- Paper §5: relación entre geometría del atractor y número de actores bajo estrés compartido

---

## Diseño del experimento

```
experiment("recursive_thermal_ramp") = {
  id:       "EXP-RTR-01",
  hardware: "n02 (Proxmox, cgroup v2, Skylake 4c)",
  goal:     "spawn S1 kernels uno por uno hasta límite térmico o límite de cgroup",

  // Condiciones de parada (OR)
  stop_conditions: [
    "temp_cpu >= 80°C",          // límite duro térmico
    "viable_all < 1.0",          // primer kernel no viable
    "N_kernels >= MAX_KERNELS",  // límite de recursos (default: 32)
    "cgroup_write_error",        // kernel de SO deniega cgroup
  ],

  // Fases
  phase_1_ramp: {
    tick_interval:  50,          // cada 50 ticks: spawn nuevo S1 kernel
    kernel_config:  "spec_boot con trust_init=0.80",
    cgroup_path:    "/sys/fs/cgroup/vsf/rtr-{N}/",
    thermal_monitor: "read_cpu_temp_c() cada tick",
    log_per_spawn:  [N_kernels, temp, viable_all, mean_pairwise_cos],
  },

  phase_2_at_limit: {
    trigger:   "stop_condition reached",
    duration:  100,              // 100 ticks de observación en el límite
    log:       [viable_all, per_kernel_cos, H(t), trust per kernel],
    question:  "¿qué pasa en el atractor exactamente en el umbral?",
  },

  phase_3_cooldown: {
    trigger:   "after phase_2",
    action:    "no new spawns — mantener todos los kernels activos",
    duration:  "hasta temp < 50°C O 10 minutos",
    log:       [viable_all, mean_pairwise_cos, temp, recovery trajectory],
    question:  "¿se recupera el atractor colectivo? ¿converge de vuelta al cono 18.2°?",
  },
}
```

---

## Métricas clave a registrar

| Métrica | Significance |
|---------|-------------|
| N* | número de kernels donde stop_condition dispara |
| temp(N*) | temperatura en el momento límite |
| viable_all(N*) | ¿todos viables en el límite? |
| mean_pairwise_cos(N*) | geometría del atractor en el límite (vs baseline 0.9854) |
| max_angle(N*) | ¿el cono se expande más allá de 18.2°? |
| trust_mean(N*) | trust promedio de todos los kernels |
| recovery_time | ticks hasta viable_all=1.0 post-cooldown |
| H_rest_drift | ¿drift del punto de reposo bajo estrés extremo? (H5) |

---

## Hipótesis que prueba

| Hipótesis | Predicción | Qué confirmaría |
|-----------|-----------|-----------------|
| H6 | ∃ N* donde viable_all drops | Si viable_all < 1 en algún momento |
| H1 | atractor sigue siendo único | mean_pairwise_cos ≥ 0.95 en el límite |
| H4 | viable bajo throttle térmico | viable_all = 1 hasta stop_condition = 80°C |
| H5 | estrés externo puede causar drift | Si H_rest de algún kernel sube durante ramp |
| A6 | variety exhaustion observable | S3 no puede absorber si N demasiado grande |
| A_auto | kernels viables sin S3 activo | viable post-cooldown sin intervención |

---

## Relación con el cono de 18.2°

El ángulo del atractor (arccos(0.95) = 18.2°) fue medido con N=4 kernels, sin carga térmica real.

Este experimento pregunta: **¿el cono se expande conforme N crece y la temperatura sube?**

```
hipótesis geométrica:
  cone_angle(N, T) = f(N, T)
  baseline: cone_angle(4, 46°C) ≈ 9.8° (observado)
  predicción: cone_angle(N*, T*) > 18.2° si el sistema está al límite
  falsificación: cone_angle constante ≈ 9.8° → atractor robusto a N y T
```

---

## Implementación

**Función:** `run_recursive_thermal_ramp()` en `src/main.rs`

Pasos de impl:
1. Adaptar `run_cgroup_multikernel()` — quitar N fijo, hacer spawn loop
2. Spawn loop: cada SPAWN_INTERVAL ticks → nuevo S1 kernel en cgroup propio
3. Thermal monitor: `read_cpu_temp_c()` integrado en S3 loop principal
4. Geometry tracker: stasis_dims por kernel → pairwise cos en tiempo real
5. Stop + cooldown phases con logging diferenciado
6. Export: JSONL per-kernel stasis_dims para plot_geometry.py

**Estimación:** ~100–150 líneas, ~1h impl, ~15 min run en n02

---

## Conexión con el paper

Este experimento cierra el gap entre:
- §3 (atractor individual — spec_boot) y
- §4 (atractor colectivo — multikernel_geometry)

añadiendo la dimensión de **stress dinámico progresivo**.

Resultado esperado en paper §5:
```
"El sistema mantiene su cuenca de atracción (θ < 18.2°) hasta N = N*
kernels bajo presión térmica T*, donde N* y T* definen el límite
operacional del S3 coordinator bajo A6."
```

---

## Status

```
status:   PENDING_IMPL
priority: high
date_proposed: 2026-04-15
target_run:    2026-04-17 (antes de publicación 2026-04-18)
impl_in:       projects/vsf-nucleus/src/main.rs
experiment_id: recursive_thermal_ramp
blocks:        [paper §5, H5, H6 resolution]
```
