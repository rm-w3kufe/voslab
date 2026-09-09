/**
 * scripts-automation.ts — handler for automated script execution.
 *
 * REASONING: Many validation/analysis scripts were manual-only.
 * This handler runs them automatically on session.idle, providing
 * continuous monitoring without manual intervention.
 *
 * PREREQUISITES:
 * - Scripts exist in scripts/vsl/tools/
 * - Python3 available
 * - Read-only scripts only (no modifications)
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

interface ScriptConfig {
  id: string
  script: string
  args: string[]
  description: string
  timeout?: number
}

const SCRIPTS: ScriptConfig[] = [
  {
    id: "version-scan",
    script: "scripts/vsl/tools/version_scan.py",
    args: [],
    description: "Scan corpus for @vsm version coherence",
    timeout: 15_000,
  },
  {
    id: "debt-register",
    script: "scripts/vsl/tools/debt_register.py",
    args: ["--json"],
    description: "Scan corpus for debt markers",
    timeout: 10_000,
  },
  {
    id: "dep-graph",
    script: "scripts/vsl/tools/dep_graph.py",
    args: ["--cycles"],
    description: "Check for dependency cycles",
    timeout: 10_000,
  },
  {
    id: "vsm-logic",
    script: "scripts/vsl/tools/vsm_logic.py",
    args: [],
    description: "Verify VSM structural logic",
    timeout: 10_000,
  },
  {
    id: "manifest-canon",
    script: "scripts/vsl/tools/manifest_canon.py",
    args: ["check"],
    description: "Verify boot manifest canon",
    timeout: 10_000,
  },
]

export const scriptsAutomationHandler: Handler = {
  id: "scripts-automation",
  priority: 2,
  events: ["session.idle"],

  classify: async () => true, // always run — scripts are idempotent

  execute: async (ctx) => {
    const start = Date.now()
    const results: string[] = []
    let successCount = 0
    let errorCount = 0

    for (const config of SCRIPTS) {
      const scriptPath = join(ctx.repoRoot, config.script)

      if (!existsSync(scriptPath)) {
        results.push(`${config.id}: script not found`)
        continue
      }

      try {
        await execFileP(
          "python3",
          [scriptPath, ...config.args],
          {
            timeout: config.timeout || 10_000,
            cwd: ctx.repoRoot,
          },
        )
        results.push(`${config.id}: OK`)
        successCount++
      } catch (e: any) {
        // Non-blocking: log but don't fail the handler
        const detail = e?.stdout?.slice(0, 200) || e?.message?.slice(0, 200) || "unknown error"
        results.push(`${config.id}: ${detail}`)
        errorCount++
      }
    }

    const durationMs = Date.now() - start
    const detail = results.join("; ")

    await logActivation(
      ctx.repoRoot,
      "scripts-automation",
      "session.idle",
      "execute",
      errorCount === 0 ? "ok" : "warn",
      detail,
      {
        durationMs,
        metrics: {
          duration_ms: durationMs,
          items_processed: SCRIPTS.length,
          success_rate: successCount / SCRIPTS.length,
        },
      },
    )

    return {
      result: errorCount === 0 ? "ok" : "warn",
      durationMs,
      detail,
    }
  },
}
