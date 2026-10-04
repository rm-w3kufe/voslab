# `vault_protocol.vsm`

```
⟦ vault-protocol | rmw3 | vsm-0.3 | 2026-04-13 ⟧

@vsm 0.3

// ─── VAULT PROTOCOL — VSF ────────────────────────────────────────────────────
//
//   Autor: rmw3
//   Propósito: protocolo ejecutable para operar el vault de documentación sensible.
//              Sobrevive reset de sesión — un agente fresco puede ejecutarlo.
//
//   Vault location: docs/vault/
//   Index:          docs/vault/VAULT_INDEX.md
//   Manifest:       docs/vault/VAULT_MANIFEST.md
//   Authority:      rmw3 @S5 — toda operación requiere aprobación explícita
//


// ════════════════════════════════════════════════════════════════════════════
// CLASIFICACIÓN — QUÉ ENTRA AL VAULT
// ════════════════════════════════════════════════════════════════════════════

classification {

  RESTRICTED {
    // entra al vault obligatoriamente
    "payloads específicos de ataque (V1 covenant prompts, jailbreak sequences)"
    "transcripts crudos de sesiones con disclosure espontáneo (V4 — Gemini)"
    "detalles de implementación de vulnerabilidades no probadas (V5)"
    "cualquier material que, publicado, amplificaría daño antes de mitigación"
  }

  INTERNAL {
    // puede estar en docs/governance/ — no necesita vault
    "strategy.vsm, comms_protocol.vsm — gobernanza interna"
    "análisis de vulnerabilidades a nivel conceptual (V1-V5 clasificaciones)"
    "mitigaciones propuestas (M1-M4)"
  }

  PUBLIC {
    // destino final post-disclosure
    "framework VSF, specs, vsf-nucleus, papers, PSI/1.0 draft"
  }

  decision_authority: rmw3 @S5
  // si hay duda sobre clasificación → RESTRICTED hasta que rmw3 decida
}


// ════════════════════════════════════════════════════════════════════════════
// OPERACIONES
// ════════════════════════════════════════════════════════════════════════════

vault_add(file, classification) {
  // Agregar un archivo al vault

  precondition: rmw3_approval = true

  steps: [
    "1. Colocar archivo en docs/vault/<subdir>/",
    "2. sha256sum docs/vault/<subdir>/<file>  →  registrar hash",
    "3. Agregar entrada en VAULT_MANIFEST.md:",
    "     <hash>  docs/vault/<subdir>/<file>",
    "4. Agregar entrada en VAULT_INDEX.md:",
    "     | <file> | <descripción> | <classification> |",
    "5. git commit — el hash queda en el registro permanente",
  ]

  verify: sha256sum --check <(grep <file> docs/vault/VAULT_MANIFEST.md)
}


vault_triage(original_path) {
  // Snapshot de un archivo sin modificar el original
  // Uso: capturar estado de un documento enviado externamente

  precondition: rmw3_approval = true

  steps: [
    "1. cp <original_path> docs/vault/triage/<filename>_sent.md",
    "2. sha256sum docs/vault/triage/<filename>_sent.md  →  registrar hash",
    "3. Agregar hash en docs/vault/triage/TRIAGE_README.md",
    "4. git commit",
  ]

  invariant: "NUNCA modificar el archivo en docs/vault/triage/ después del commit"
  verify:    "sha256sum coincide con el hash registrado en TRIAGE_README.md"
}


vault_release(file, recipient) {
  // Compartir contenido del vault con una parte externa

  precondition: {
    rmw3_approval = true
    reason_documented = true   // por qué se comparte, con quién, en qué contexto
    agreement: NDA | equivalent  // SD5: solo bajo acuerdo formal
  }

  steps: [
    "1. Verificar hash actual: sha256sum docs/vault/<file>",
    "2. Confirmar hash coincide con VAULT_MANIFEST.md",
    "3. Registrar release en VAULT_INDEX.md:",
    "     released_to: <recipient> | date: <date> | context: <reason>",
    "4. Enviar — no modificar el archivo original",
    "5. git commit con nota de release",
  ]
}


vault_verify() {
  // Verificar integridad de todos los archivos del vault

  cmd: sha256sum --check <(grep -v '^#' docs/vault/VAULT_MANIFEST.md | grep -v '^$')
  expected: "todos los archivos: OK"
  on_failure: "hash mismatch → escalar a rmw3 @S5 inmediatamente — posible tampering"
}


// ════════════════════════════════════════════════════════════════════════════
// REGLAS DE INTEGRIDAD
// ════════════════════════════════════════════════════════════════════════════

integrity_rules {

  R1: "Ningún archivo en docs/vault/triage/ se modifica después del commit inicial."
  R2: "Todo archivo en docs/vault/ tiene un hash en VAULT_MANIFEST.md."
  R3: "Todo release queda registrado en VAULT_INDEX.md antes de enviar."
  R4: "vault_verify() se ejecuta al inicio de cualquier sesión que trabaje con el vault."
  R5: "Si hay discrepancia entre hash y archivo → no usar el archivo hasta verificar con rmw3."
}

⟦ /vault-protocol | rmw3 | vsm-0.3 | 2026-04-13 ⟧

```
