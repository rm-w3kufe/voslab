# PLAN DE COMPLETACIÓN AL 100%

## OBJETIVO
Alcanzar 100% de conformidad en vOSlab completando:
1. Copia de 63 checks shell del padre
2. Tests para 3 paquetes nuevos
3. Integración de vsf-checks con scripts shell

## FASE 1: CHECKS SHELL (63 scripts)

### 1.1 Copiar checks a vsf-checks
```bash
# Copiar todos los checks shell
cp ~/vsf/checks/* packages/public/vsf-checks/checks/
```

### 1.2 Categorizar checks por dominio
| Categoría | Cantidad | Ejemplos |
|-----------|----------|----------|
| boot | 4 | boot-load-test, boot-manifest-valid, boot-ontology-clean, boot-task-load-clean |
| vsl | 4 | vsl-encoding-valid, vsl-gate-valid, vsl-timestamp-required, vslline-manifest-valid |
| plugin | 3 | plugin-behavior-valid, plugin-location-valid, plugin-s2-coherent |
| ontology | 3 | ontology-master-coherent, ontology-master-frame, ontology-master-trace |
| agent | 3 | agent-map-valid, agent-plugin-log-valid, agent-plugin-path-valid |
| tasks | 2 | tasks-census-converge, tasks-structure-guard |
| task | 2 | task-format-valid, task-maintenance-valid |
| socratic | 2 | socratic-engine-selftest, socratic-gate-valid |
| classification | 2 | classification-tree-valid, classification-valid |
| child | 2 | child-boot-state-archive-gates, child-refs-notify-valid |
| Otros | 36 | compression-drift-valid, crl-expiry-proximity, dir-schema-valid, etc. |

### 1.3 Crear manifiesto de checks
Crear `packages/public/vsf-checks/vsf_checks/checks_manifest.json` con:
- Nombre del check
- Categoría
- Descripción
- dependencias

### 1.4 Actualizar check_runner.py
Agregar functions para:
- `list_checks()` - Listar checks disponibles
- `run_checks_by_category(category)` - Ejecutar por categoría
- `validate_check_manifest()` - Validar manifiesto

## FASE 2: TESTS PARA PAQUETES NUEVOS

### 2.1 vsf-algedonic (9 scripts)
Crear `tests/test_algedonic.py` con tests básicos:
- `test_ac_algedonic_import()` - Verificar import
- `test_ac_classifier_import()` - Verificar import
- `test_beacon_attestation_import()` - Verificar import
- `test_vsf_beacon_main_import()` - Verificar import
- `test_vsf_decision_auth_import()` - Verificar import

### 2.2 vsf-analysis (12 scripts)
Crear `tests/test_analysis.py` con tests básicos:
- `test_analyze_s401_import()` - Verificar import
- `test_checo_env_snapshot_import()` - Verificar import
- `test_checo_projection_import()` - Verificar import
- `test_markov_analysis_import()` - Verificar import
- `test_viability_forecaster_import()` - Verificar import

### 2.3 vsf-state (30 scripts)
Crear `tests/test_state.py` con tests básicos:
- `test_hook_analytics_import()` - Verificar import
- `test_monitor_reconcile_import()` - Verificar import
- `test_s5_ca_import()` - Verificar import
- `test_service_watchdog_import()` - Verificar import
- `test_tasks_validate_import()` - Verificar import

## FASE 3: INTEGRACIÓN VSF-CHECKS

### 3.1 Crear bridge para checks shell
Crear `packages/public/vsf-checks/vsf_checks/shell_check_bridge.py`:
```python
class ShellCheckBridge:
    """Bridge para ejecutar checks shell del padre."""
    
    def __init__(self, checks_dir: str):
        self.checks_dir = checks_dir
    
    def list_checks(self) -> List[str]:
        """Listar checks disponibles."""
        
    def run_check(self, check_name: str) -> Tuple[bool, str]:
        """Ejecutar un check específico."""
        
    def run_all_checks(self) -> Dict[str, Tuple[bool, str]]:
        """Ejecutar todos los checks."""
        
    def get_check_categories(self) -> Dict[str, List[str]]:
        """Obtener checks por categoría."""
```

### 3.2 Actualizar __init__.py
Agregar exports del bridge:
```python
from .check_runner import run_check, run_all_checks
from .shell_check_bridge import ShellCheckBridge
```

### 3.3 Agregar tests del bridge
Crear `tests/test_shell_check_bridge.py`:
- `test_shell_check_bridge_init()` - Verificar inicialización
- `test_list_checks()` - Verificar listado
- `test_run_check_success()` - Verificar ejecución exitosa
- `test_run_check_failure()` - Verificar fallo
- `test_run_all_checks()` - Verificar ejecución masiva
- `test_get_check_categories()` - Verificar categorías

## FASE 4: VERIFICACIÓN FINAL

### 4.1 Ejecutar todos los tests
```bash
# Ejecutar tests de todos los paquetes
for pkg in packages/public/*/ packages/framework/*/; do
  if [ -d "$pkg/tests" ]; then
    cd ~/vOSlab/$pkg
    python3 -m pytest tests/ -v
    cd ~/vOSlab
  fi
done
```

### 4.2 Verificar cobertura
```bash
# Verificar cobertura de tests
pytest --cov=packages --cov-report=term-missing
```

### 4.3 Actualizar reporte de conformidad
Actualizar `CONFORMITY_REPORT.md` con:
- 100% checks shell copiados
- 100% tests en paquetes nuevos
- 100% integración vsf-checks

## CRONOGRAMA

| Fase | Duración | Entregable |
|------|----------|------------|
| Fase 1 | 30 min | 63 checks copiados + manifiesto |
| Fase 2 | 20 min | Tests para 3 paquetes |
| Fase 3 | 15 min | Shell check bridge |
| Fase 4 | 10 min | Verificación final |
| **Total** | **75 min** | **100% conformidad** |

## RECURSOS NECESARIOS

1. Acceso a `~/vsf/checks/` (63 scripts shell)
2. Python 3.8+ con pytest
3. ~75 minutos de tiempo

## RIESGOS

1. **Checks shell con dependencias**: Algunos checks pueden requerir herramientas específicas
2. **Tests incompletos**: Los tests básicos verifican imports, no funcionalidad completa
3. **Integración**: El bridge puede necesitar ajustes para checks específicos

## ÉXITO

- 63/63 checks shell copiados
- 15+ tests nuevos agregados
- Shell check bridge funcionando
- 100% conformidad alcanzada
