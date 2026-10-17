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
