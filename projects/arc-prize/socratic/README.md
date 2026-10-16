<!-- design: projects/arc-prize/arc_prize_design.vsm -->

# ARC-AGI-3 Socratic Agent

Pipeline autónomo para juegos ARC-AGI-3 usando arquitectura VSM.

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                    GAME ENGINE                          │
│  (arc-agi-3: 25 juegos, grid-based)                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  1. PERCEIVE  │ Grid state, actions disponibles        │
├─────────────────────────────────────────────────────────┤
│  2. CANON     │ Predecir vs observar (drift)           │
├─────────────────────────────────────────────────────────┤
│  3. MEMORY    │ Detectar patrones aplicables           │
├─────────────────────────────────────────────────────────┤
│  4. FEEDBACK  │ Señales dolor/placer de historial      │
├─────────────────────────────────────────────────────────┤
│  5. SOCRATIC  │ Sugerencia UCB1 (explotar/explorar)    │
├─────────────────────────────────────────────────────────┤
│  6. LLM       │ Proponer acción con contexto           │
├─────────────────────────────────────────────────────────┤
│  7. ACT       │ Ejecutar en game engine                │
├─────────────────────────────────────────────────────────┤
│  8. LEARN     │ Registrar outcome para próximo paso    │
└─────────────────────────────────────────────────────────┘
```

## Módulos

| Módulo | Rol VSM | Función |
|--------|---------|---------|
| `socratic_agent.py` | S4/S3 | Árbol de decisión + UCB1 para explorar/explotar |
| `arc3_memory.py` | S5 | 59 patrones como contexto para LLM |
| `arc3_feedback.py` | S3 | Señales dolor/placer de resultados |
| `arc3_canon.py` | S4 | Predicción vs observación (drift detection) |
| `my_agent_socratic.py` | Orquestador | Perceive → socratic → LLM → act → learn |

## Resultados

### Comparación en ls20 (10 steps)

| Métrica | Random | Socratic + LLM |
|---------|--------|----------------|
| FPS | 0.10 | 0.55 |
| Acciones únicas | 5/7 | 6/7 |
| Memoria | Ninguna | UCB1 + Patrones |
| Contexto LLM | Ninguno | 59 patrones + feedback |

### Notas

- **CPU-only** (Ollama qwen3:1.7b) — sin GPU
- **Sin entrenamiento** — exploración ciega
- **Próximo paso**: Kaggle GPU (RTX 6000) + modelo grande (Qwen 3.6 27B)

## Instalación

```bash
# En LXC 114
cd /root/arc-agi-3/kaggle-starter
cp src/*.py agent/
.venv/bin/python scripts/play_local.py --game ls20 --max-steps 20
```

## Estructura

```
arc3-socratic/
├── notebooks/
│   └── demo.ipynb           ← Demo visual del pipeline
├── src/
│   ├── socratic_agent.py    ← Decision tree + UCB1 memory
│   ├── arc3_memory.py       ← Pattern detection (59 patterns)
│   ├── arc3_feedback.py     ← Algedonic pain/pleasure signals
│   ├── arc3_canon.py        ← State canon drift detection
│   └── my_agent_socratic.py ← Full integrated agent
├── results/
│   └── (evaluation results)
├── docs/
│   └── (architecture docs)
└── README.md
```

## Próximos Pasos

1. **GPU**: Kaggle RTX 6000 + Qwen 3.6 27B
2. **API Key**: arcprize.org para testing completo
3. **Prompt Engineering**: Optimizar contexto para modelos grandes
4. **Pattern Learning**: Aprender nuevos patrones durante ejecución
5. **Multi-game**: Transferencia de conocimiento entre juegos
