# vsf-nucleus — Live Telemetry Guide
> **STATUS: historical_record** — OBSOLETE (:8080 opsroom era) — reemplazado por view host LXC 109 (:8088 formaid studio /live module dashboard). Telemetría canonical en kernel_map.vsm telemetry_canonical + vos_core_theory. Comandos apuntan a opsroom retirado.

## 1. Prerequisitos

```bash
# Tunnel activo (verificar primero)
curl -s http://127.0.0.1:8080/nav   # → JSON si está OK
# Si no responde: ssh -N -f n02-opsroom
```

---

## 2. Arrancar un experimento en n02

```bash
# Experimentos disponibles:
# spec_boot | thermal_stress_v3 | cgroup_multikernel | thermal_ceiling_v4
# critical_angle | multikernel_geometry | s3_failure_resilience

# Corto (foreground):
ssh n02-tunnel "/usr/local/bin/vsf-nucleus --experiment spec_boot --ticks 1000 --quiet"

# Largo (background, 2h):
ssh n02-tunnel "nohup /usr/local/bin/vsf-nucleus --experiment spec_boot --minutes 120 --quiet > /tmp/exp.log 2>&1 &"

# Ver checkpoints del run largo:
ssh n02-tunnel "tail -f /tmp/exp.log"
```

---

## 3. Stream SSE — opsroom

```bash
# Stream crudo desde terminal:
curl -N http://127.0.0.1:8080/stream

# Filtrado por experimento:
curl -N "http://127.0.0.1:8080/stream?experiment=spec_boot"

# En el browser:
# http://127.0.0.1:8080  → panel "live stream" → ▸ connect
```

---

## 4. Métricas clave en el stream

Cada evento tiene esta estructura:

```json
{
  "ts": "2026-04-13T19:14:21Z",
  "event_type": "init_step",
  "status": "stasis_vector",
  "metrics": {
    "step": "spec_boot",
    "tick": 544235377,
    "entropy_phase": "stasis",
    "stasis_cos": 0.9995,
    "l_x": 0.1926,
    "obs_n": 7665288
  }
}
```

**Qué mirar:**

| Métrica | Rango sano | Señal de alerta |
|---|---|---|
| `stasis_cos` | ≥ 0.70 | < 0.70 → nonviable |
| `entropy_phase` | `stasis` | `degen` prolongado |
| `l_x` | bajando | subiendo → divergencia |
| `trust` | 0.40–1.0 | < 0.40 → gobernanza débil |

**Glosario rápido:**

| Campo | Significado |
|---|---|
| `stasis_cos` | coseno entre state_vector actual y atractor — cercanía al estado estable |
| `l_x` | función de Lyapunov — bajando = convergiendo al atractor |
| `entropy_phase` | fase del ciclo: `stasis` → `inhale` → `degen` → `exhale` → `stasis` |
| `obs_n` | observaciones acumuladas en fase stasis — base del atractor |
| `trust` | nivel de confianza del kernel — acumula con runs limpios |
| `mean_dL` | tasa media de cambio de L(x) — negativo = convergencia confirmada |
| `D_KY` | dimensión de Kaplan-Yorke — dimensionalidad efectiva del atractor |

---

## 5. Checkpoints de senescencia (long_run)

```bash
# Ver progreso en tiempo real:
ssh n02-tunnel "tail -f /tmp/senescence.log"

# Ver solo checkpoints:
ssh n02-tunnel "grep checkpoint /tmp/senescence.log"

# Formato de checkpoint:
# [checkpoint] t=660s ticks=452M cycles=6.4M trust=0.000 H_rest=0.400 cos=0.9731 mean_dL=-0.00000 V_mem=1
```

**Señales de senescencia a observar con el tiempo:**

| Señal | Qué observar |
|---|---|
| H_rest drift | `H_rest` sube sobre 0.400 → entropía de reposo aumenta |
| V_mem saturation | `V_mem` entries sube hacia 10k → memoria vectorial llena |
| Rigidez (τ_meta) | cycles/minuto baja → soplos menos frecuentes |
| Trust plateau | trust llega a 1.0 y se estabiliza → fase production |

---

## 6. API directa

```bash
curl http://127.0.0.1:8080/nav                    # sistemas disponibles
curl http://127.0.0.1:8080/system/vsf-nucleus     # estado actual
curl http://127.0.0.1:8080/state/vsf-nucleus      # telemetría parseada
```

---

## 7. Reiniciar servicios si caen

```bash
# Opsroom caído en n02:
ssh n02-tunnel "fuser -k 8080/tcp"   # limpiar puerto si está ocupado
ssh n02-tunnel "PYTHONPATH=/home/rmw3/vsf nohup python3 -m uvicorn opsroom.api:app --host 127.0.0.1 --port 8080 > /tmp/opsroom.log 2>&1 &"

# Tunnel local caído:
pkill -f n02-opsroom
ssh -N -f n02-opsroom

# Verificar todo OK:
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080   # → 200
```
