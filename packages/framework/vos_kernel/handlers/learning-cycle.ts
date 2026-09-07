// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * learning-cycle.ts — handler for learning scan + S4 stats.
 *
 * Migrated from learning-cycle-scan.ts. Runs on session.idle.
 * Calls: session_learning_scan.sh pass + learning_stats.py --check
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

export const learningCycleHandler: Handler = {
  id: "learning-cycle",
  priority: 1,
  events: ["session.idle"],

  classify: async () => true, // always run — scan is idempotent

  execute: async (ctx) => {
    const start = Date.now()
    const scanScript = join(ctx.repoRoot, "scripts/state/session_learning_scan.sh")
    const statsScript = join(ctx.repoRoot, "scripts/state/monitoring/learning_stats.py")

    if (!existsSync(scanScript)) {
      return { result: "skip", durationMs: 0, detail: "scan script not found" }
    }

    try {
      await execP(`bash "${scanScript}" pass`, { timeout: 10_000, cwd: ctx.repoRoot })

      if (existsSync(statsScript)) {
        await execP(
          `python3 "${statsScript}" --check --min-n ${process.env.LEARNING_MIN_N ?? 3} --window-days ${process.env.LEARNING_WINDOW_DAYS ?? 30}`,
          { timeout: 10_000, cwd: ctx.repoRoot },
        ).catch(() => {}) // stats failure is non-blocking
      }

      return { result: "ok", durationMs: Date.now() - start, detail: "scan PASS" }
    } catch {
      return { result: "error", durationMs: Date.now() - start, detail: "scan failed" }
    }
  },
}
