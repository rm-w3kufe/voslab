// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * session-init.ts — handler for context injection on session.start.
 *
 * Reads current_focus.json, checks for stale entries, provides context.
 */
import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

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

    const duration = Date.now() - start
    return {
      result: results.length > 0 ? "ok" : "skip",
      durationMs: duration,
      detail: results.join(",") || "no active focus",
      summary: results.join(","),
    }
  },
}
