/**
 * vsf-scripts-manifest-updater.ts — Plugin para actualizar manifiesto de scripts automáticamente
 *
 * Cuando se crea o modifica un archivo en scripts/state/, actualiza el manifiesto.
 *
 * Uses tool.execute.after to detect write/edit operations on scripts/state/ files.
 */
import type { Plugin } from "@opencode-ai/plugin"
import { join } from "node:path"
import { existsSync } from "node:fs"
import { sandboxedExecFile } from "../../shared/run-sandbox"

// Configuración
const SCRIPTS_DIR = "scripts/state"
const MANIFEST_UPDATE_SCRIPT = "scripts/shared/update_scripts_manifest.py"

// Extensiones que triggers actualización
const TRIGGER_EXTENSIONS = [".py", ".sh", ".service", ".timer", ".sql", ".json", ".db"]

// Patrones de archivos a ignorar
const IGNORE_PATTERNS = [
  "__pycache__",
  ".pyc",
  ".git",
  "node_modules",
]

/**
 * Verifica si el archivo está en scripts/state/
 */
function isInScriptsDir(filePath: string): boolean {
  return filePath.startsWith(SCRIPTS_DIR) || filePath.includes(`/${SCRIPTS_DIR}/`)
}

/**
 * Verifica si el archivo debe triggers la actualización
 */
function shouldTrigger(filePath: string): boolean {
  if (!TRIGGER_EXTENSIONS.some(ext => filePath.endsWith(ext))) {
    return false
  }
  if (IGNORE_PATTERNS.some(pattern => filePath.includes(pattern))) {
    return false
  }
  return true
}

/**
 * Actualiza el manifiesto (SANDBOX: execFile confinado, sin shell).
 */
async function updateManifest(cwd: string): Promise<boolean> {
  try {
    const scriptPath = join(cwd, MANIFEST_UPDATE_SCRIPT)
    if (!existsSync(scriptPath)) {
      return false
    }
    const run = await sandboxedExecFile(["python3", scriptPath], {
      repoRoot: cwd,
      timeoutMs: 10_000,
      auditSource: "vsf-scripts-manifest-updater",
    })
    return run.ok
  } catch {
    return false
  }
}

const ScriptsManifestUpdater: Plugin = async ({ directory }) => {
  return {
    "tool.execute.after": async (input: any, output: any) => {
      if (input.tool !== "write" && input.tool !== "edit") return
      const filePath = input.args?.file_path ?? input.args?.filePath ?? ""
      if (!filePath) return
      if (!isInScriptsDir(filePath)) return
      if (!shouldTrigger(filePath)) return

      const cwd = directory || process.cwd()
      const start = Date.now()
      const success = await updateManifest(cwd)
      const durationMs = Date.now() - start

      if (success) {
        console.error(`[vsf-scripts-manifest-updater] manifest updated for ${filePath}`)
      }
    },
  }
}

export default ScriptsManifestUpdater
