/**
 * design: docs/design/sandbox/plugin-s2-coordination-v1/plugin_s2_coordination.vsm
 * vsf-scripts-manifest-updater.ts — Plugin that updates the scripts manifest automatically
 *
 * When a file under scripts/ (ANY family — A2 2026-10-13 widened the scope from
 * scripts/state/ only; the updater regenerates BOTH the state manifest and the
 * full corpus census in one invocation, so a single trigger covers all dirs).
 *
 * Uses tool.execute.after to detect write/edit operations on scripts/** files.
 */
import type { Plugin } from "@opencode-ai/plugin"
import { join } from "node:path"
import { existsSync } from "node:fs"
import { sandboxedExecFile } from "../../shared/run-sandbox"

// Configuration
const SCRIPTS_DIR = "scripts"
const MANIFEST_UPDATE_SCRIPT = "scripts/shared/update_scripts_manifest.py"

// Extensions that trigger an update
const TRIGGER_EXTENSIONS = [".py", ".sh", ".service", ".timer", ".sql", ".json", ".db"]

// File patterns to ignore
const IGNORE_PATTERNS = [
  "__pycache__",
  ".pyc",
  ".git",
  "node_modules",
]

/**
 * Checks whether the file is under scripts/ (any family, A2)
 */
function isInScriptsDir(filePath: string): boolean {
  return filePath.startsWith(SCRIPTS_DIR + "/") || filePath.includes(`/${SCRIPTS_DIR}/`)
}

/**
 * Checks whether the file should trigger the update
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
