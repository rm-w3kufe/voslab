/**
 * tool-bridge.ts — Shared bridge caller for tool integration plugins.
 *
 * Extracts the bridge calling logic so it can be shared between
 * tool-pipeline.ts and session-lifecycle.ts.
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { findScript } from "../../shared/find-plugin-script"
import { homedir } from "node:os"

const execFileP = promisify(execFile)

// Use findScript for reliable path resolution (no hardcoded fallback)
const BRIDGE_PATH = findScript(process.cwd(), ".opencode/plugins/operational/tool_integration_bridge.py") || ""
const SAFE_MODE_FLAG = join(homedir(), ".opencode", ".safe_mode")

/**
 * Call the tool integration bridge with a command and arguments.
 * Returns parsed JSON response or null on error.
 */
export async function callBridge(
  command: string,
  args: string[] = []
): Promise<any | null> {
  if (!existsSync(BRIDGE_PATH)) return null
  try {
    const { stdout } = await execFileP(
      "python3",
      ["-W", "ignore", BRIDGE_PATH, command, ...args],
      { encoding: "utf-8", timeout: 15000 }
    )
    const raw = stdout.trim()
    console.error(`[bridge-debug] raw(${raw.length}): ${raw.slice(0, 500)}`)
    const j = raw.indexOf("{"); const ja = raw.indexOf("["); const s = j === -1 ? ja : ja === -1 ? j : Math.min(j, ja)
      return JSON.parse(s === -1 ? raw : raw.slice(s))
  } catch (e: any) {
    console.error(`[tool-bridge] callBridge(${command}) error: ${e?.message || e}`)
    return null
  }
}

/**
 * Check if safe mode is enabled.
 */
export function isSafeMode(): boolean {
  return existsSync(SAFE_MODE_FLAG)
}

// ─── Tool classification ──────────────────────────────────────────────────────

/** Tools that MUST go through the pipeline */
export const MANDATORY_TOOLS = new Set([
  "write", "edit", "bash", "task", "read", "glob", "grep",
])

/** Tools that are read-only (no state change) */
export const READ_ONLY_TOOLS = new Set(["read", "glob", "grep", "list_mcp_resources"])

/** Tools that modify state (require full pipeline) */
export const STATE_CHANGING_TOOLS = new Set(["write", "edit", "bash", "task"])
