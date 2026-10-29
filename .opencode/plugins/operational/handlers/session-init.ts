// design: docs/design/sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * session-init.ts — handler for context injection on session start.
 *
 * Reads current_focus.json, checks for stale entries, surfaces alert
 * backlog (EP-0/F3), provides context.
 *
 * CC-1: listens on session.created — "session.start" is NOT a bus event
 * (absent from the documented event list; never dispatched by the core).
 */
import { existsSync, readFileSync } from "node:fs"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

export const sessionInitHandler: Handler = {
  id: "session-init",
  priority: 1,
  events: ["session.created"],

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

    // 2. Consume unacked alerts (EP-0/F3): surface summary + ack.
    //    Output contract: machine-readable LAST line of stdout, e.g.
    //    "alerts_consumed=3" / "alerts_unacked=0".
    try {
      const { stdout } = await execFileP(
        "python3",
        ["system/kernel/alert_consume.py", "--boot"],
        { timeout: 15_000, cwd: ctx.repoRoot },
      )
      const line = stdout.trim().split("\n").filter(Boolean).pop() || ""
      if (line) results.push(line)
    } catch { /* alert consumption is best-effort, never block boot */ }

    const duration = Date.now() - start
    return {
      result: results.length > 0 ? "ok" : "skip",
      durationMs: duration,
      detail: results.join(",") || "no active focus",
      summary: results.join(","),
    }
  },
}
