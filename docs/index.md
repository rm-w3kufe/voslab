# VSF / vOS — Documentation Index

> **Viable System Framework** — framework para diseñar y operar sistemas viables.
> Basado en el VSM de Beer (1972) + patrones de Cybersyn (1971).

---

## ¿Por dónde empezar?

| Si eres... | Lee primero |
|---|---|
| Nuevo en el proyecto | [Conceptos VSM](guides/concepts.md) → [Guía VSL](guides/human_guide.md) |
| Continuando una sesión | `HANDOFF.vsm.md` (raíz del repo) → [queue.vsm](experiments/queue.vsm) |
| Reanudando tras compactación | [ecosystem_refs](reference/ecosystem_refs.vsm) — 16 refs S5 (memoria/capas/ecosistema) |
| Implementando un experimento | [queue.vsm](experiments/queue.vsm) → spec del experimento |
| Escribiendo un paper | [paper_data.vsm del paper](papers/) → [skeleton main.tex](papers/) |
| Buscando un término | [glossary.vsm](glossary.vsm) |

---

## Estructura

```
docs/
├── index.md              ← este archivo
├── glossary.vsm          ← todos los términos formales del proyecto
│
├── guides/               ← documentación pública y de incorporación
│   ├── concepts.md       ← S1-S5, patrones Cybersyn
│   ├── human_guide.md    ← cómo leer y escribir VSL
│   ├── vsm_notation_spec.md ← spec formal de la notación
│   ├── infrastructure.md ← perfiles de infra + instalación
│   └── vsl_primer.md     ← introducción rápida a VSL
│
├── archive/lifecycle-2026-10-04/theory/ ← teoría formal (movida al archivo 2026-10-04;
│                   ver DOCS.md para los enlaces vivos de theory/*)
│
├── experiments/          ← specs de experimentos + queue de ejecución
│   ├── queue.vsm               ← índice ordenado + status (LEER PRIMERO)
│   ├── theta_psi_stress/       ← encontrar θ_PSI exacto (bloquea task O)
│   ├── long_run_senescence/    ← envejecimiento real (horas)
│   ├── thermal_ceiling_v4_bis/ ← re-run con cooldown previo
│   └── block_b_full/           ← sensores reales mem/io en Block B
│
├── spec/                 ← diseños formales de protocolos y arquitectura
│   ├── psi_protocol/     ← [PENDIENTE] protocolo de intervención S4
│   ├── s4_integration/   ← [PENDIENTE] LLM como organelo vivo
│   └── sci01_progression/ ← [PENDIENTE] criterios de avance por stage
│
├── papers/               ← papers LaTeX
│   ├── attractor_convergence/  ← Paper 1: convergencia geométrica (publicable)
│   └── basin_geometry/         ← Paper 2: geometría de cuenca + A_auto (viernes)
│
├── operations/           ← runbooks operacionales
│   └── n02_runbook.vsm   ← [PENDIENTE] deploy, tunnels, experimentos en n02
│
├── plans/                 ← planes estratégicos (plan_registry.vsm = índice)
│   ├── refs_optimization_proposal.vsm ← REFS-OPT-001: cache+memoria desde 16 refs (proponed)
│   └── r4_lote2_proposal.vsm ← R-4 lote-2: 5 refs (X1..X5) + sanitización F5 (proposed)
│
├── reference/            ← auditorías + referencias externas destiladas
│   ├── capabilities_audit.vsm / technical_debt_registry.vsm / vsflab_packages.vsm
│   └── ecosystem_refs.vsm   ← 16 refs web S5 (memoria / capas / ecosistema)
│
└── governance/           ← documentos constitucionales
    ├── covenant.vsm      ← contrato A0/A0.1 — firmado por rmw3, Claude, Gemini
    └── covenant_amendment.vsm ← [PENDIENTE] protocolo de enmienda
```

---

## Estado del proyecto

| Componente | Estado |
|---|---|
| vsf-nucleus binario | ✅ activo en n02 |
| spec_boot experiment | ✅ PASS — viable_full=true, governed=true |
| Attractor theory | ✅ confirmado empíricamente — D_KY≈2, cono 18.2° |
| cgroup_multikernel (S3↔S1) | ✅ viable_all=100% |
| Basin geometry | ✅ SAME BASIN — mean pairwise cos=0.9854 |
| A_auto | ✅ confirmado — viable sin S3 |
| Paper 1 (attractor convergence) | ✅ listo para compilar |
| Paper 2 (basin geometry) | 🔧 skeleton listo — prosa pendiente (viernes) |
| θ_PSI exacto | 🔧 upper bound < 0.9377 — theta_psi_stress pendiente |
| PSI protocol spec | ⬜ task(O) — pendiente θ_PSI exacto |
| S4 integration | ⬜ task pendiente |
| Senescencia long-run | ⬜ requiere --minutes flag (viernes) |

---

## Metodología

El ciclo de desarrollo está formalizado en [theory/vos_dev_cycle.vsm](archive/lifecycle-2026-10-04/theory/vos_dev_cycle.vsm).

Tres patrones clave:
- **experiment_spec** — escribir `spec.vsm` antes de implementar cualquier experimento
- **paper_skeleton** — `main.tex` + `paper_data.vsm` antes de una sesión de escritura
- **queue_vsm** — índice ordenado con status para continuidad entre sesiones

**Principio central:** *lo que no está en `.vsm` commitado no sobrevive el reset de sesión.*

---

## Referencias principales

- Beer, S. (1972). *Brain of the Firm*. Allen Lane.
- Beer, S. (1979). *The Heart of Enterprise*. Wiley.
- Medina, E. (2011). *Cybernetic Revolutionaries*. MIT Press. (Cybersyn)
- Ashby, W.R. (1956). *Introduction to Cybernetics*. Chapman & Hall.
- Ott, Grebogi, Yorke (1990). *Controlling Chaos*. PRL 64(11). (OGY — soplo)
