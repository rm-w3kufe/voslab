# VSL for BBH — Spec mínimo para C2 (bbh-wsl)
# Versión: 1.0 | Base: VSL v0.3 (docs/spec/vsm_notation_spec.md)

## Gramática esencial (todo lo que necesitas)

```
@vsm 0.3                              // ← REQUIRED en todo .vsm
// comentario                         // ← // para notas

// ─── System (opcional, para declarar identidad) ───
V("c2-bbh", L=2) = {
  role:     "C2 orchestrator",
  parent:   V("vsf", L=3),
  status:   production,
}

// ─── Blocks (tu estado) ───
ecosystem: {
  topology:    "S5→C2→n01→n02→LXC111",
  principle:   "subordinado en comando, autonomo en ejecucion",
}

// ─── Arrays ───
hypotheses: [
  H1: "VSL reduce tokens en ≥70%",
  H2: "implementación funcionalmente idéntica",
]

// ─── Anidación ───
targets_processed: {
  affirm_v9: { findings: 11, status: "completo", environment: "production" },
  stripe:    { findings: 4,  status: "externo completo", pending: "auth layer" },
}

// ─── Referencias ───
// @ref docs/spec/vsm_notation_spec.md

// ─── Session block ───
session("2026-07-22") = {
  summary:   "lo que se hizo",
  result:    pass | partial | fail,
  resolved:  ["task-id — evidence"],
  next:      "what to do next",
}
```

## B_schema (modo comprimido — 72-79%)

Reglas:
1. `domain_context: {target=bbh, env=WSL/opencode, layer=C2}` — REQUIRED al inicio
2. Sin redundancia: valores por defecto no se escriben
3. IDs cortos pero legibles: `affirm_v9` en vez de `target_affirm_v9_status`
4. Strings sin comillas si son identifiers: `status: production` en vez de `status: "production"`
5. `@ref` para docs externos en vez de copiar contenido

Ejemplo comparativo:

```json
// JSON (312 lines → ~1000 tokens)
{"ecosystem": {"topology": "S5(rmw3) -> C2(WSL/bbh-wsl) -> n01 -> n02(Proxmox) -> LXC111(bbh-lab) -> Kali(headed browser, Playwright, mitmproxy)"}}
```

```vsm
// VSL B_schema (~250 tokens, -75%)
@vsm 0.3
domain_context: {target=bbh, env=WSL/opencode, layer=C2}

ecosystem: {
  topology:  "S5→C2→n01→n02→LXC111→Kali",
  principle: "subordinado en comando, autonomo en ejecucion",
}
```

## Reglas para BBH

1. **Archivo**: `bbh-wsl/bbh-session.vsm` (al lado de `bbh-session.json`)
2. **Header**: `@vsm 0.3` + `domain_context` obligatorio
3. **Migración**: empieza con los 5 bloques principales (ecosystem, database, metrics, pending, mcp)
4. **Coexistencia**: JSON sigue siendo fuente de verdad; .vsm es la vista comprimida
5. **Validación**: `python3 ~/vsf/scripts/vsl/vsl_parser.py bbh-session.vsm` — yo corro esto

## Validación

```bash
python3 ~/vsf/scripts/vsl/vsl_parser.py bbh-session.vsm          # validate
python3 ~/vsf/scripts/vsl/vsl_parser.py bbh-session.vsm --json   # ver AST
python3 ~/vsf/scripts/vsl/vsl_parser.py bbh-session.vsm --strict # errors as warnings
```

Exit codes: 0=valid ✅ | 1=invalid ❌ | 2=parse_error 💥
