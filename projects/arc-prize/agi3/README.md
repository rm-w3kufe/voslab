# ViArc-3 — AGI-3 track lab (interactive homeostat)

Plan: `../knowledge/viarc3_master_plan.vsm` · Study: `../knowledge/arc_agi3_study.vsm`
Identity (S5 ratified): **ViArc-3 = interactive homeostat** — perceive →
model → goal-infer → plan → act, retrodiction-certified, algedonic pressure.

## Layout (tracked here; heavy env is rebuildable in /tmp/opencode/arc3-lab)
```
agi3/
├── README.md              ← this index
├── agent/viarc3_agent.py  ← homeostat skeleton (edit this; sync to lab)
└── lab/                   ← pointer: /tmp/opencode/arc3-lab (untracked)
```

## Dev loop (M0 done 2026-10-17)
```bash
# rebuild lab if missing:
#   git clone --depth1 https://github.com/arcprize/ARC-AGI-3-Kaggle-Starter.git /tmp/opencode/arc3-lab
#   cd /tmp/opencode/arc3-lab && make setup PYTHON=$(uv python find 3.12)
cd /tmp/opencode/arc3-lab
cp ~/vOSlab/projects/arc-prize/agi3/agent/viarc3_agent.py agent/my_agent.py
make play-local GAME=ls20 STEPS=200
make list-games
```
Python 3.12 via uv (WSL). LXC 114 stays AGI-2-only (3.11 < 3.12).

## M0 status (2026-10-17)
- setup complete: arc-agi + arcengine + slim framework + 25 public games cached
- play-local smoke: ls20 end-to-end, 61 actions, scorecard flow OK (169 fps)
- next: M1 homeostat loop on ls20/ft09/vc33 (Duke-proven set)

## Submissions & versioning (convención S5 2026-10-20)

**Convención de numeración (plataforma-alineada):** el número de versión
del *mensaje* de submission == `current_version_number` del kernel de
Kaggle. El "design version" del agente (f5/v8/v9…) vive en el código y
los commits; NO va en el mensaje (histórico: kernel v9 fue enviado como
"v8" → ambigüedad en leaderboard/browser; reconciliado 2026-10-20).

**Mecánica (dos superficies, no confundir):**
- `kaggle kernels push` = nueva versión del kernel + corrida *commit*
  (modo normal, sin juegos: escribe parquet dummy de 1 fila, ~32s,
  **cero evaluación**). El H1/markdown del notebook es metadata
  visible — actualizarlo en `build_notebook.py` de arc3-lab al evolucionar
  el diseño (el de la era v6 decía "homeostat + certified LLM brain").
- `competition_submit_code(kernel, kernel_version, file, message)` =
  el ÚNICO camino a score: clava esa versión del kernel y la corre el
  juez con `KAGGLE_IS_COMPETITION_RERUN=true` + gateway + juegos
  ocultos. **Cuota real API-verified: 1 envío/día/competición**
  (FAILED_PRECONDITION "daily Submission allowance (1)" — el supuesto
  de 8/día era incorrecto). Score legible vía `list_submissions` →
  `publicScore` cuando `status=COMPLETE`; la UI no es necesaria.

**Flujo por build:** sync `viarc3_agent.py` → `agent/my_agent.py` →
`make notebook` → `make submit` (push) → sleeper/guard (slot del día,
expect_ver) → `competition_submit_code` → poll `publicScore`.
