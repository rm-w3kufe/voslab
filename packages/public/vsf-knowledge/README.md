# vsf-knowledge

Knowledge base del sistema VSF.

## Instalación

```bash
pip install vsf-knowledge
```

## Uso

```python
from vsf_knowledge.knowledge_base import KnowledgeBase

# Inicializar knowledge base
kb = KnowledgeBase()

# Cargar knowledge específica
architecture = kb.get_architecture()
rsi_identity = kb.get_rsi_identity()
vsl_basics = kb.get_vsl_basics()

# Listar todos los archivos
files = kb.list_knowledge()

# Buscar en la knowledge base
results = kb.search("keyword")
```

## Estructura

```
vsf_knowledge/
├── __init__.py
└── knowledge_base.py
```

## Archivos Incluidos

- architecture.vsm - Arquitectura del sistema
- rsi_identity.vsm - Identidad RSI
- self_maintaining_patterns.vsm - Patrones de auto-mantenimiento
- vsl_basics.vsm - Fundamentos de VSL
