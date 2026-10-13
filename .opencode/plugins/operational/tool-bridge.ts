/**
 * tool-bridge.ts — Shared bridge caller for tool integration plugins.
 *
 * Extracts the bridge calling logic so it can be shared between
 * tool-pipeline.ts and session-lifecycle.ts.
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync, statSync } from "node:fs"
import { join } from "node:path"
import { findScript } from "../../shared/find-plugin-script"
import { homedir } from "node:os"
import { logActivation } from "../../shared/log-activation"

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
      { encoding: "utf-8", timeout: 30000 }
    )
    const raw = stdout.trim()
    // TUI-stderr hygiene 2026-09-10: raw dumps only with VOS_DEBUG_BRIDGE=1
    if (process.env.VOS_DEBUG_BRIDGE === "1") {
      console.error(`[bridge-debug] raw(${raw.length}): ${raw.slice(0, 500)}`)
    }
    const j = raw.indexOf("{"); const ja = raw.indexOf("["); const s = j === -1 ? ja : ja === -1 ? j : Math.min(j, ja)
      return JSON.parse(s === -1 ? raw : raw.slice(s))
  } catch (e: any) {
    console.error(`[tool-bridge] callBridge(${command}) error: ${e?.message || e}`)
    // PERSIST-S5-2026-10-03 (directiva: "el ciclo debe estar
    // permanentemente revisando y observando errores que muestran los
    // logs"): console.error dies with the TUI — a bridge failure left NO
    // trace in agent_plugin.jsonl (observed: pipeline-after error visible
    // to the user only, log showed all-ok around it). Now it does.
    // logActivation never throws; belt-and-suspenders anyway.
    try {
      await logActivation(
        process.cwd(),
        "tool-bridge",
        "bridge.error",
        `callBridge(${command})`,
        "error",
        // TRIGGER-AUDIT-2026-10-13: killed=true ⇒ execFile timeout (SIGTERM
        // before any stderr) — distinguishable now from a real python crash.
        // Budget 15000→30000: session-report measured 7.3s at current state
        // (grows with session count) and today 15 phase-calls died pre-stderr
        // under parallel load; aligned with scenario-memory-gap-bridge (30s).
        `bridge call failed${e?.killed ? "[TIMEOUT]" : ""}: ${String(e?.message || e).slice(0, 200)}`,
        { timeout_ms: 30000, args_count: args.length }
      )
    } catch {
      // logging must never break the caller
    }
    return null
  }
}

/**
 * Check if safe mode is enabled.
 *
 * Hardening 2026-09-10 (S5-auth family): the flag must be owned by the
 * current uid — a foreign-planted flag (another local user, stray copy)
 * must NOT silently disable the fail-safe. Owner mismatch = disabled.
 */
export function isSafeMode(): boolean {
  if (!SAFE_MODE_FLAG || !existsSync(SAFE_MODE_FLAG)) return false
  try {
    const st = statSync(SAFE_MODE_FLAG)
    if (typeof (process as any).getuid === "function" && st.uid !== (process as any).getuid()) {
      console.error(`[tool-bridge] safe mode flag owned by uid ${st.uid}, expected ${(process as any).getuid()} — ignored`)
      return false
    }
    return true
  } catch {
    return false
  }
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
