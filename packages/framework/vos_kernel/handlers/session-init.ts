// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * session-init.ts — handler for context injection on session.start.
 *
 * Reads current_focus.json, checks for stale entries, provides context.
 */
import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { exec } from "node:child_process"
import { promisify } from "node:util"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

export const sessionInitHandler: Handler = {
  id: "session-init",
  priority: 1,
  events: ["session.start"],

  classify: async () => true, // always run

  execute: async (ctx) => {
    const start = Date.now()
    const results: string[] = []

    // 1. Read current focus
    const focusFile = join(ctx.repoRoot, "current_focus.json")
    if (existsSync(focusFile)) {
      try {
        const content = readFileSync(focusFile, "utf-8")
        const focus = JSON.parse(content)
        const active = Object.entries(focus).filter(
          ([, v]: [string, any]) => v.status === "active",
        )
        if (active.length > 0) {
          results.push(`focus_active=${active.length}`)
        }
      } catch { /* non-critical */ }
    }

    // 2. Check for stale focus entries
    // Note: focus_close_check.py not yet implemented
    // const focusClose = join(ctx.repoRoot, "scripts/state/focus_close_check.py")
    // if (existsSync(focusClose)) {
    //   try {
    //     await execP(`python3 "${focusClose}" --check`, { timeout: 5_000, cwd: ctx.repoRoot })
    //   } catch { /* non-critical */ }
    // }

    const duration = Date.now() - start
    return {
      result: results.length > 0 ? "ok" : "skip",
      durationMs: duration,
      detail: results.join(",") || "no active focus",
      summary: results.join(","),
    }
  },
}
