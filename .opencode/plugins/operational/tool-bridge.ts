/**
 * tool-bridge.ts — Shared bridge caller for tool integration plugins.
 *
 * Extracts the bridge calling logic so it can be shared between
 * tool-pipeline.ts and session-lifecycle.ts.
 */
import { spawn } from "node:child_process"
import { existsSync, statSync } from "node:fs"
import { join } from "node:path"
import { findScript } from "../../shared/find-plugin-script"
import { homedir } from "node:os"
import { logActivation } from "../../shared/log-activation"
import { algedonicAlert } from "../../shared/algedonic-alert"

// Use findScript for reliable path resolution (no hardcoded fallback)
const BRIDGE_PATH = findScript(process.cwd(), ".opencode/plugins/operational/tool_integration_bridge.py") || ""
const SAFE_MODE_FLAG = join(homedir(), ".opencode", ".safe_mode")

// Budget 30000 (TRIGGER-AUDIT-2026-10-13, aligned scenario-memory-gap-bridge).
// log-distill post-rotation recompute measured 40–90s (signature changes when
// a fresh archive lands → cache miss) > 30000 → SIGTERM → bridge_call_failed
// (T3-F1 root cause, 2026-10-20). Cache-hit steady state is ~1.5s; the bump
// covers the once-per-rotation miss only. grows with session count)
const BRIDGE_TIMEOUT_DEFAULT = 30000
const BRIDGE_TIMEOUTS: Record<string, number> = { "log-distill": 130000 }

/**
 * Call the tool integration bridge with a command and arguments.
 * Returns parsed JSON response or null on error.
 *
 * Transport (E2BIG-BRIDGE-STDIN-2026-10-16, adopted 2026-10-16): args ride
 * stdin as a JSON array behind the --args-stdin flag; argv carries only
 * command + flag. Linux E2BIG caps argv (MAX_ARG_STRLEN 128KiB per string),
 * which killed MB-class payloads (gap-resolver socratic-tree-file, 81
 * alerts 2026-10-14→20). spawn (not execFile) because async execFile has
 * no stdin-input option.
 */
export async function callBridge(
  command: string,
  args: string[] = []
): Promise<any | null> {
  if (!existsSync(BRIDGE_PATH)) return null
  const timeoutMs = BRIDGE_TIMEOUTS[command] ?? BRIDGE_TIMEOUT_DEFAULT
  try {
    const stdout = await new Promise<string>((resolve, reject) => {
      const child = spawn(
        "python3",
        ["-W", "ignore", BRIDGE_PATH, command, "--args-stdin"],
        { stdio: ["pipe", "pipe", "pipe"] }
      )
      let out = ""
      let errBuf = ""
      let settled = false
      const timer = setTimeout(() => {
        if (settled) return
        settled = true
        // killed=true on purpose: logActivation renders [TIMEOUT] from it
        // (TRIGGER-AUDIT-2026-10-13 semantics, carried from execFile).
        const e: any = new Error(
          `Command failed: python3 -W ignore ${BRIDGE_PATH} ${command}: killed after ${timeoutMs}ms`
        )
        e.killed = true
        try { child.kill("SIGTERM") } catch { /* already dead */ }
        reject(e)
      }, timeoutMs)
      child.stdout.setEncoding("utf-8")
      child.stderr.setEncoding("utf-8")
      child.stdout.on("data", (d) => { out += d })
      child.stderr.on("data", (d) => { errBuf += d })
      child.on("error", (e) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        reject(e)
      })
      child.on("close", (code) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        if (code === 0) resolve(out)
        else reject(new Error(
          `Command failed: python3 -W ignore ${BRIDGE_PATH} ${command} --args-stdin` +
          (errBuf ? `: ${errBuf.slice(0, 300)}` : "")
        ))
      })
      // EPIPE guard: python may exit (bad JSON → sys.exit(1)) before we
      // finish writing — stdin errors must surface via close(code≠0), never
      // as an unhandled rejection.
      child.stdin.on("error", () => { /* surfaced via close */ })
      child.stdin.write(JSON.stringify(args), "utf8", () => { child.stdin.end() })
    })
    const raw = stdout.trim()
    // TUI-stderr hygiene 2026-09-10: raw dumps only with VOS_DEBUG_BRIDGE=1
    if (process.env.VOS_DEBUG_BRIDGE === "1") {
      console.error(`[bridge-debug] raw(${raw.length}): ${raw.slice(0, 500)}`)
    }
    const j = raw.indexOf("{"); const ja = raw.indexOf("["); const s = j === -1 ? ja : ja === -1 ? j : Math.min(j, ja)
      return JSON.parse(s === -1 ? raw : raw.slice(s))
  } catch (e: any) {
    console.error(`[tool-bridge] callBridge(${command}) error: ${e?.message || e}`)
    // Layer A: a bridge failure is a pain signal — route it to the algedonic
    // channel so it surfaces at session.created and cannot rot unnoticed
    // (console.error + logActivation alone left it invisible to S5 in-cycle).
    algedonicAlert(process.cwd(), "bridge_call_failed", "tool-bridge(S2)",
      "error", `callBridge(${command}) error: ${String(e?.message || e).slice(0, 300)}`)
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
        // TRIGGER-AUDIT-2026-10-13: killed=true ⇒ timeout (SIGTERM before
        // any stderr) — distinguishable now from a real python crash.
        `bridge call failed${e?.killed ? "[TIMEOUT]" : ""}: ${String(e?.message || e).slice(0, 200)}`,
        { timeout_ms: timeoutMs, args_count: args.length }
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
