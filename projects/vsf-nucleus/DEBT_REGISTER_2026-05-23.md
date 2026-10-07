# DEBT REGISTER — Post-Colapso al Núcleo
**Fecha**: 2026-05-23
**Contexto**: Tras consolidar 7 LXC → 1 LXC (n02 LXC 101 con nucleus + ollama colapsados), quedan 10 deudas operacionales que requieren resolución antes de retomar paper/experimentos.

---

## Estado del sistema verificado (evidencia)

| Métrica | Valor | Fuente |
|---|---|---|
| Nucleus PID | 9662 | `systemctl show vsf-nucleus-operational` |
| Memoria nucleus | 968 KB | `MemoryCurrent` systemd |
| Uptime | desde 2026-05-23 04:06:29 UTC | `ActiveEnterTimestamp` |
| BBS embebido | /root/bbs.db, 136KB, growing | `stat` + mtime 05:20 |
| Ollama | active, qwen2.5-coder:7b loaded (4.6GB) | `systemctl is-active` + `/api/tags` |
| LXC 101 RAM total | 12GB (5.3 usado / 6.9 disponible) | `free -m` |
| Binario nucleus | 5.9M, en /root/ y /home/rmw3/vsf/.../target/release/ | `ls -lh` |
| Código fuente | 9,885 LOC en 18 módulos Rust | `wc -l src/*.rs` |

**Conclusión**: el colapso funcionó. RAM liberada se asignó a Ollama (314MB residentes + 4.6GB modelo). El sistema es autónomo: BBS (SQLite embedded) + Ollama (loopback) + Nucleus (Rust) sin dependencias externas.

---

## Deudas activas (10)

### DEBT-31 — LXC fantasma del modelo distribuido (RESUELTO 2026-05-24)
- **Severidad**: Media
- **Estado**: ✅ RESUELTO 2026-05-24
  - LXC 102 (vsf-nucleus deprecated): DESTRUIDO ✓
  - LXC 104 (telemetry): KEEP — S5 Console activo + 63GB datos históricos (RE-CLASIFICADO: NO era deprecated)
  - LXC 105 (bbh-prod): KEEP — entrará a producción en paralelo
  - LXC 106 (bbs): RECICLADO + RENAMED a `vsf-nats-test` — NATS testbed activo
- **Descripción**: LXC 102 (vsf-nucleus), 104 (telemetry), 106 (bbs) corriendo pero sin servicios activos. NO están "vacíos" — contienen datos.

**Hallazgos por LXC (verificados):**

| LXC | Hostname | Disco usado | Contenido crítico |
|---|---|---|---|
| 102 | vsf-nucleus | 3.2G + mount `/data/vsf-nucleus/telemetry` (vacío) | Configs viejas, /var/log 139M — **safe to destroy** |
| 104 | telemetry | **63G** | `aggregator.py` (tiered retention raw/min1/hourly/daily), `algedonic/alerts.jsonl`, 1.7G logs — **datos históricos experimentos** |
| 105 | bbh-prod | 614M | `/root/vsf-bbh/roe.yaml` (4.3KB Rules of Engagement BBH) — **PRESERVAR** |
| 106 | bbs | 1.5G | `bbs.db` (36KB, último write 11-May, pre-colapso), `bbs_server.py` (3KB) — histórico |

**Backup creado en host n02** (`/root/lxc-backups-pre-cleanup-2026-05-23/`):
- `lxc104-aggregator.py` (22K)
- `lxc104-alerts.jsonl` (4.1K)
- `lxc105-vsf-bbh-roe.yaml` (4.3K)
- `lxc106-bbs.db` (36K)
- `lxc106-bbs_server.py` (3K)

**Decisión pendiente del usuario** (sub-deudas):
- **DEBT-31a**: ¿LXC 104 con 63GB de telemetry histórica = preservar? (probable: SÍ, si paper retoma)
- **DEBT-31b**: LXC 105 `roe.yaml` ya respaldado — destruir LXC 105 cuando confirmes
- **DEBT-31c**: LXC 102 mount vacío — safe to destroy cuando confirmes
- **DEBT-31d**: LXC 106 bbs viejo — destruir tras backup confirmado

**Fix (cuando decidas)**:
```bash
ssh root@n02 'pct stop 102 && pct destroy 102'  # safe (mount vacío)
ssh root@n02 'pct stop 105 && pct destroy 105'  # roe.yaml ya respaldado
ssh root@n02 'pct stop 106 && pct destroy 106'  # bbs viejo respaldado
# LXC 104: NO destruir hasta decidir sobre los 63GB
```

### DEBT-32 — LXC 105 (bbh-prod) sin servicio activo
- **Severidad**: Media
- **Descripción**: Container running, solo SSH/cron. Nombre sugiere "BBH production" pero sin proceso.
- **Riesgo**: BBH (Bug Bounty Hunter) puede estar pendiente de deploy o ser código muerto.
- **Fix**: Decisión binaria:
  - **A)** Deploy BBH workflow ahí (alinea con memoria `project_vsf_bbh.md`)
  - **B)** Eliminar si BBH ya corre embebido en nucleus o vive en kali-bbh
- **Pre-requisito**: verificar `project_vsf_bbh.md` y código BBH actual.

### DEBT-33 — sqlite3 CLI faltante en LXC 101 ✅ RESUELTO (2026-05-30)
- **Severidad**: Baja
- **Resolución**: instalado en LXC 101 (`/bin/sqlite3`). Verificado con `pct exec 101 -- which sqlite3`. Permite ahora inspección manual de `bbs.db` desde host n02.

### DEBT-34 — Documentación PHASE_1-4 dice "564KB", real es 968KB ✅ RESUELTO (2026-05-30)
- **Severidad**: Baja
- **Medición real (2026-05-30, post-G-K.2 build)**:
  - Binary on disk: **6.3 MB** stripped (Cargo.toml `strip = true` aplicado, cf. DEBT-38)
  - RSS runtime: **~10 MB**
  - VSZ: ~551 MB
- **Resolución**: rango operacional efectivo actualizado a **RSS 8-12 MB, binary 6-7 MB stripped**. Cifras "564KB" y "968KB" eran de builds tempranos sin SQLite embebido + sin BBH/PSI subscribers.

### DEBT-35 — Sin endpoint HTTP nucleus para query externa de BBS ✅ SUPERSEDED (2026-05-31)
- **Severidad**: Media
- **Resolución**: superseded por **D.1 Motor 2** (`projects/vsf-motor2`, commit `186baab`). Motor 2 es un proceso aparte (no acopla failure modes al nucleus) que expone `http://127.0.0.1:9101` con `/v1/health`, `/v1/topics`, `/v1/messages/recent?limit=N[&topic=X]`. Read-only + WAL + QUERY_ONLY → cero impacto medible en write throughput de Motor 1 (nucleus).

### DEBT-36 — Logs S4 no inmediatamente visibles en journalctl ✅ RESUELTO (2026-05-30)
- **Severidad**: Baja
- **Resolución**: `/root/nucleus-wrapper.sh` (en LXC 101) ahora ejecuta `exec stdbuf -oL -eL /root/vsf-nucleus-operational ...`, forzando line-buffering en stdout/stderr antes de la redirección a journald. Verificado post-restart: cada `println!` de los subscribers aparece en `journalctl --since "10 sec ago"` sin lag. Solución elegida en vez de tocar el código fuente (más portable, sin rebuild).

### DEBT-37 — vsf-arch.html inconsistencia local/remoto ✅ RESUELTO
- **Severidad**: Resuelto (2026-05-23)
- **Descripción**: Documento mostraba "OPERATIONAL" sin distinguir compilación local vs deployment n02.
- **Resolución**: commits b0d1dd1 + actualizaciones 2026-05-23 con topología real.

### DEBT-38 — Binary nucleus no stripped (5.9M) ✅ RESUELTO (commiteado previo, verificado 2026-05-30)
- **Severidad**: Baja
- **Resolución**: `[profile.release] strip = true` presente en `projects/vsf-nucleus/Cargo.toml` (line 44) y `projects/vsf-s3-star/Cargo.toml` (line 38). Build actual produce **6.3 MB** stripped (la cifra "5.9M" en el título de la deuda era pre-strip).

### DEBT-39 — Ollama API solo en 127.0.0.1 (por diseño)
- **Severidad**: Por diseño / verificar
- **Descripción**: Tras colapso, ollama y nucleus comparten LXC 101 → comunicación via loopback. Ningún otro LXC puede invocar Ollama.
- **Riesgo**: Si Stage 2 introduce otra VM/LXC que necesite LLM, requiere abrir puerto en bridge interno.
- **Decisión pendiente**: ¿mantener loopback (mejor seguridad) o exponer interno (flexibilidad)?
- **Fix**: ajustar `OLLAMA_HOST` env var + firewall LXC si decidimos abrir.

### DEBT-40 — vsf-nucleus-control sin plan de deployment
- **Severidad**: Baja
- **Descripción**: Proyecto separado (587K, compilado 2026-04-20) con experimentos EXP-NC-01/02/03 (negative controls del paper attractor_convergence). No incluido en colapso al núcleo.
- **Riesgo**: cuando paper retome, hay que decidir si correr controls localmente (WSL) o desplegarlos.
- **Fix**:
  - Decisión: deploy a LXC 102 (recuperado de DEBT-31) o ejecución batch local
  - Documentar en `docs/experiments/queue.vsm`
- **Bloqueador**: ninguno; depende de cuándo retome paper cycle 1.

---

## Priorización sugerida

### Bloque inmediato (housekeeping, 1-2h total)
1. **DEBT-33** — instalar sqlite3 (1 min)
2. **DEBT-34** — actualizar PHASE_1-4 doc (5 min)
3. **DEBT-38** — strip binary + Cargo profile (5 min + build)
4. **DEBT-31** — backup + destroy LXC 102/104/106 (30-45 min con respaldos)

### Bloque corto (decisiones + observabilidad, 3-4h)
5. **DEBT-32** — decidir destino LXC 105 (15 min decisión + ejecución)
6. **DEBT-36** — logging mejorado S4 (30 min)
7. **DEBT-35** — HTTP API para BBS (2-3h)

### Bloque diferido (cuando aplique)
8. **DEBT-39** — decisión arquitectónica sobre Ollama exposure (cuando Stage 2 lo requiera)
9. **DEBT-40** — plan controls (cuando paper retome)
10. **DEBT-41** — undeclared nats-server on LXC 107 (decommission or declare)
11. **DEBT-42** — TASKS.vsm status drift pattern (reconcile protocol)

---

## Entries added 2026-06-11 (findings — session convergence-waves-1-2)

### DEBT-41 — Undeclared nats-server running on LXC 107 ✅ RESUELTO (2026-06-16)
- **Severity**: Low (no traffic risk) / Medium (model≡reality violation)
- **Resolution**: Verified 2026-06-16 — `nats-server.service` is `disabled` + `inactive`
  on LXC 107. No listening on port 4222. Resolved de facto (disabled at some point
  after DEBT was written). model≡reality gap closed: S3* census no longer sees orphan.

### DEBT-42 — TASKS.vsm status drift is a PATTERN, not an incident ✅ RESUELTO (2026-06-16)
- **Severity**: Medium (planning on stale state wastes sessions)
- **Resolution**: `scripts/state/tasks_reconcile.py` deployed to `/usr/local/bin/tasks_reconcile.py`
  on n02 host; running daily at 02:00 UTC via cron (`0 2 * * * root VSF_ROOT=...
  python3 /usr/local/bin/tasks_reconcile.py --emit`). Writes drift findings to `state.db
  task_drift` table and emits NATS algedonic. Meta-lesson documented in `AGENT.md`.

---

## Entries added 2026-06-19 (implications of EXP-SOPLO-01 + EXP-TRUST-01 Phase A)

### DEBT-PAPER-01 — §sec:trustlaw thermodynamics: soplo is NOT an erasure step
- **Severity**: High (paper correctness / reviewer risk)
- **Type**: Correctiva — paper defensibility
- **Finding**: Current §sec:trustlaw text frames each soplo as "an information write to τ" with cost
  kT·ln2 per firing. **Incorrect** per EXP-SOPLO-01 F1: the soplo is a conditional injective shift
  (τ↦τ+0.18 when τ<0.75; `.min(1.0)` never engages since τ+0.18 < 0.93 always). Per-event ΔH≡0.
  The thermodynamic cost is in the **ensemble Lyapunov contraction** (L<1), not in per-event resets.
  Any reviewer with information-thermodynamics background would flag this.
- **Fix**: Rewrite §sec:trustlaw open question: soplo reversible (injective), cost = ensemble
  contraction tied to L<1 property. Optionally add EXP-SOPLO-01 subsection + fig_soplo_landauer.
- **Task**: T-O1 — Opus session, **gated on S5 sign-off**
- **Blocker for**: paper defensibility; §sec:trustlaw rewrite (T-O1)

### DEBT-PAPER-02 — Lyapunov–Landauer bridge proposition (missing or unverified)
- **Severity**: Medium (contribution completeness)
- **Type**: Contributiva — potential new Corollary/Proposition
- **Finding**: EXP-SOPLO-01 empirically establishes Ω_diss ≈ kT·ln2·|ΔH_ensemble|/tick — a direct
  bridge between the trust law's Lyapunov exponent (L<1) and its thermodynamic dissipation rate.
  Unknown whether §sec:maxwell already captures this formally. If not, it is a novel contribution.
- **Fix**: Audit §sec:maxwell + §sec:trustlaw. If the bridge proposition is absent, add as Corollary:
  "The trust update operator's thermodynamic cost equals kT·ln2 times its Lyapunov contraction rate."
- **Task**: T-O2 — Opus session, **gated on S5 sign-off** (can pair with T-O1)
- **Blocker for**: paper completeness

### DEBT-EXP-01 — H_TRUST1 experimental design: independence only testable under perturbation
- **Severity**: Medium (methodological — affects EXP-TRUST-01 closure)
- **Type**: Metodológica
- **Finding**: H_TRUST1 as written ("axis independence: |corr(trust_i, trust_j)| < 0.3 for N≥100
  epochs") is evaluable only during perturbations, not at baseline. EXP-TRUST-01 Phase A confirmed:
  at steady state all axes peg near 1.0, making correlation a peg artifact (behavioral↔predictive
  corr=0.886 despite no mechanistic coupling). The hypothesis was ill-posed for steady-state measurement.
- **Fix**: Phase B spec reformulates H_TRUST1: "test |corr(trust_i, trust_j)| < 0.3 DURING
  axis-specific perturbation (run_2 structural↓; run_3 behavioral noise)." Documented in spec.vsm.
- **Task**: T-S3 (spec annotation) + T-S5 (Phase B spec) + T-S7 (Phase B runs)
- **Blocker for**: EXP-TRUST-01 final closure (C2 full PASS)

### GAP-COUPLE-01 — λ_i per-axis table undelivered (blocked until Phase B)
- **Severity**: High (downstream dependency)
- **Type**: Bloqueante
- **Finding**: DSN-COUPLE-01 Phase 4 trust gate calibration and covenant M9 depend on empirically
  fitted λ_i values per axis (behavioral~0.2, structural~0.05, predictive~0.1, communicative~0.15).
  EXP-TRUST-01 Phase A cannot deliver them: all axes pegged at ~1.0, variance microscopic, no
  perturbation variability to fit λ_i from. The table is currently uncalibrated.
- **Fix**: Phase B run_2/run_3 on LXC 108 → per-axis recovery curves → fit λ_i per axis → deliver
  to COUPLE-01 P4 and CHECO CH.b. Task T-S7 (implementation) → T-G1 (delivery).
- **Blocker for**: DSN-COUPLE-01 Phase 4; covenant M9 two-axis calibration; CHECO CH.b

### GAP-CHECO-01 — CHECO CH.b calibration deferred (stationary baseline, no drift to project)
- **Severity**: Medium (functional — calibration deferred, not broken)
- **Type**: Funcional
- **Finding**: CHECO-PROJ-1 requires a trust slope for the OLS time-to-breach forward model.
  EXP-TRUST-01 Phase A delivered a stationary series (behavioral slope≈0, ac1=0.984). An OLS
  model on flat data projects no drift — the time-to-breach estimate is undefined at baseline.
  The engine is implementable but not calibratable without degradation data.
- **Fix**: Implement CHECO-PROJ-1 OLS engine now (modular, plug-in ready for Phase B data).
  Defer threshold calibration and model validation to post-Phase-B. Task T-S8 (engine) → T-G2 (calibration).
- **Blocker for**: CHECO-PROJ-1 final calibration; CH.b parameter delivery

---

## Sign-off
- **Author**: rmw3 + Claude (Opus 4.7)
- **Verified**: 2026-05-23 ~01:20 UTC con SSH directo a n02
- **Next review**: tras resolver bloque inmediato (DEBT-31, 33, 34, 38)
