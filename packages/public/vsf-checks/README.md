# vsf-checks

Validación de checks del sistema VSF.

## Instalación

```bash
pip install vsf-checks
```

## Uso

```python
from vsf_checks.check_runner import run_check, run_all_checks

# Ejecutar un check individual
success, output = run_check("/path/to/check")

# Ejecutar todos los checks en un directorio
results = run_all_checks("/path/to/checks/")

# Filtrar por patrón
results = run_all_checks("/path/to/checks/", pattern="boot")
```

## Estructura

```
vsf_checks/
├── __init__.py
└── check_runner.py
```

## Checks Incluidos

- agent-map-valid
- agent-plugin-path-valid
- boot-load-test
- classification-valid
- dir-schema-valid
- impl-with-design-valid
- learning-record-valid
- plugin-location-valid
- relocate-vsm-valid
- vsl-gate-valid
- write-gates-valid
- ... (60 total)
