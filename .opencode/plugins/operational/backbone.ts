/**
 * design: child/docs/integration_backbone_design.vsm
 * backbone.ts — Integration backbone plugin for opencode
 *
 * Manages the lifecycle of code flowing through the system:
 *   tool.execute.after:
 *     1. Detect new files (route → register → verify)
 *     2. Log events to state canon
 *     3. Feed metrics to RSI
 *
 *   session.idle:
 *     1. Reconcile backbone state
 *     2. Detect gaps
 *     3. Report summary
 *
 * Integration:
 *   - backbone.py: core orchestrator
 *   - socratic_bridge.py: socratic engine integration
 *   - canon_bridge.py: state canon integration
 *   - rsi_bridge.py: RSI integration
 */
import type { Plugin } from "@opencode-ai/plugin"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"

const execFileP = promisify(execFile)

const BACKBONE_DIR = join(
  process.env.VOS_ROOT || process.cwd(),
  "..", "vsf", "child", "scripts", "backbone"
)

const BACKBONE_PATH = join(BACKBONE_DIR, "backbone.py")
const CANON_BRIDGE_PATH = join(BACKBONE_DIR, "canon_bridge.py")
const RSI_BRIDGE_PATH = join(BACKBONE_DIR, "rsi_bridge.py")

// ─── Bridge caller ─────────────────────────────────────────────────────────────

async function callBackbone(
  script: string,
  args: string[] = []
): Promise<any> {
  const scriptPath = join(BACKBONE_DIR, script)
  if (!existsSync(scriptPath)) return null
  try {
    const { stdout } = await execFileP(
      "python3",
      [scriptPath, ...args],
      { encoding: "utf-8", timeout: 15000 }
    )
    return JSON.parse(stdout.trim())
  } catch {
    return null
  }
}

// ─── File detection ────────────────────────────────────────────────────────────

/** Extensions that indicate code files */
const CODE_EXTENSIONS = new Set([".py", ".ts", ".js", ".vsm"])

/** Directories to ignore */
const IGNORE_DIRS = new Set([
  "node_modules", ".git", "__pycache__", ".pytest_cache",
  "archive", "legacy", "generated", "tests",
])

function isCodeFile(filePath: string): boolean {
  const ext = filePath.split(".").pop()?.toLowerCase()
  if (!ext || !CODE_EXTENSIONS.has(`.${ext}`)) return false

  const parts = filePath.split("/")
  for (const part of parts) {
    if (IGNORE_DIRS.has(part)) return false
  }

  return true
}

// ─── Plugin ───────────────────────────────────────────────────────────────────

const BackbonePlugin: Plugin = async ({ directory }) => {
  // ═══════════════════════════════════════════════════════════════════════════
  // IDLE: Reconcile and report
  // FIX 2026-10-07 (L-OCC round): moved from a top-level "session.idle" key —
  // the core dispatcher never invokes session.* keys (CC-1 router finding);
  // they arrive ONLY via the generic event hook. The named key was dead.
  // ═══════════════════════════════════════════════════════════════════════════
  async function idleHandler(): Promise<void> {
    // Get summary
    const summary = await callBackbone("canon_bridge.py", ["summary", "--json"])
    if (!summary) return

    // Detect gaps
    const gaps = await callBackbone("rsi_bridge.py", ["detect-gaps", "--json"])
    if (!gaps) return

    const gapCount = gaps.evidence?.gap_count ?? 0
    if (gapCount > 0) {
      console.error(
        `[backbone] ${gapCount} gaps detected — run rsi_bridge.py detect-gaps for details`
      )
    }

    return
  }

  return {
    // ═══════════════════════════════════════════════════════════════════════════
    // AFTER: Process new files through backbone cycle
    // (tool.execute.* = real named hooks, dispatched by the core)
    // ═══════════════════════════════════════════════════════════════════════════
    "tool.execute.after": async (input: any, output: any) => {
      const tool = input.tool || "unknown"

      // Only process write/edit tool calls
      if (tool !== "write" && tool !== "edit") return

      const filePath =
        input.args?.file_path ?? input.args?.filePath ?? ""
      if (!filePath || !isCodeFile(filePath)) return

      // Run backbone cycle (dry-run for now)
      const result = await callBackbone("backbone.py", [filePath, "--json"])
      if (!result) return

      // Log to state canon
      if (result.success) {
        await callBackbone("canon_bridge.py", [
          "record-status",
          "--component", result.component,
          "--status", "ok",
          "--step", "backbone_cycle",
        ])
      }

      return output
    },

    // ═══════════════════════════════════════════════════════════════════════════
    // EVENT HOOK: session.* only (tool.execute.* excluded — they stay named
    // hooks above to prevent double routing, same as vsf-event-router)
    // ═══════════════════════════════════════════════════════════════════════════
    event: async (input: any) => {
      const ev = input?.event ?? input
      if (ev?.type !== "session.idle") return
      await idleHandler()
    },
  }
}

export default BackbonePlugin
