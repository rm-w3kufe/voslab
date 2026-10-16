<!-- design: projects/arc-prize/arc_prize_design.vsm -->

# ARC Prize 2026 — hub unificado (decisión S5 2026-10-16)

Los 3 concursos, la plataforma y los avances en **un solo lugar** dentro de
la plataforma (`projects/` — scope de gates R16). El archive original
`~/vOSlab-scratch` queda **intacto** (git history incluida).

## Estructura

| dir | qué es |
|---|---|
| `agi2/` | pipeline AGI-2: `solve.py` (API pura, attempt_1/2) + recognizer + agent + rsi_bridge + tests + `build_notebook.py` + pipeline Kaggle (`kaggle/{push,daily}.sh`) + `last_kernel_output/` (evidencia última corrida) |
| `agi3/` | agente AGI-3 (hunter, llm_proposer, probe, algedonic) + `state/` (25M de sondas) |
| `socratic/` | `arc3-socratic` — evaluate del agente AGI-3 |
| `paper/` | `arc_paper_v1` (draft ≤1500w, EN, track AGI-3) + outline (rubrica 6 cats) + hybrid |
| `knowledge/` | arc_taxonomy / routing table portables |
| `data/` | training puzzles ARC (1001 archivos, 6.5M) |

## Estado real verificado hoy (2026-10-16)

- **Credenciales**: `~/.kaggle/kaggle.json` (600) con token API (KGAT_…,
  Sep 2026) +
  venv durable `~/.local/share/kaggle/venv` (CLI 2.2.4). **API verificada**
  (kernels status ⇒ COMPLETE). Nada en `/tmp` — sobrevive reboot.
- **AGI-2 Kaggle**: kernel `rmw3kufe/arc-agi-2-solver-v1-symbolic`
  COMPLETE; **1 sola submission** (ref 56186885, 2026-09-12, score público
  vacío); el push "era-93" (v4) quedó **sin submit** → la diaria murió
  ~2026-09-13 (era cron en `/tmp`, no durable).
- **AGI-3**: solo sondas locales; **0 submissions**.
- **Paper**: v1 casi listo; falta P-1 (repo open-source CC0/MIT-0 ANTES del
  eval privado) + notebook público + writeup export.

## LXC 114 — hub local (jupyter-lab)

`/root/arc-agi-2` (LXC 114, `ssh n02-jupyter-cmd`, 10.10.40.120): esqueleto
Sep-13 poblado 2026-10-16 con M1 completo (src/ 10 módulos, data/training
1000 puzzles, notebooks/AGI2_Explore + kaggle build, submissions/smoke_v7).
Python 3.11 + numpy; sin GPU (el Qwen vive staged en Kaggle Dataset).
Baseline simbólico 8.9% local también medible allí con `src/bench_local.py`.

## Pipeline (AGI-2)

```bash
projects/arc-prize/agi2/kaggle/push.sh     # rebuild + push (NO gasta diaria)
projects/arc-prize/agi2/kaggle/daily.sh "msg"  # push + espera + submit (GASTA 1/día)
```

## Deadlines (canon: `docs/publishing/arc_2026_brief.vsm`)

- **2026-11-02 23:59Z** — submissions ARC-AGI-2 + ARC-AGI-3
- **2026-11-08** — papers (usar conservador; kaggle dice 11-09)
- 2026-12-04 — resultados

## Reglas del hub

- Todo artefacto nuevo bajo `projects/arc-prize/` declara
  `design: projects/arc-prize/arc_prize_design.vsm` (gate
  `impl-with-design-valid` lo exige) — el inyector masivo lo ya aplicó a
  la importación.
- Solver **sin GPU / sin internet** (eval Kaggle sandbox) — compat con el
  kernel público ya desplegado.
- Credenciales solo en `~/.kaggle/` (fuera del repo, 600).
