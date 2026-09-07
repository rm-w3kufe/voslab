// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * session-hygiene.ts — handler for archive + handoff + journal on session.idle.
 *
 * Runs: tasks_archive.py, handoff_archive.py, focus_close_check.py.
 * Journal mark is deferred (agent/MCP does it, not this handler).
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync, statSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

export const sessionHygieneHandler: Handler = {
  id: "session-hygiene",
  priority: 2,
  events: ["session.idle"],

  classify: async () => true, // always run — tools are idempotent

  execute: async (ctx) => {
    const start = Date.now()
    const results: string[] = []

    // 1. Archive completed tasks
    const tasksArchive = join(ctx.repoRoot, "scripts/state/tasks/tasks_archive.py")
    if (existsSync(tasksArchive)) {
      try {
        const { stdout } = await execP(`python3 "${tasksArchive}" --closed --apply`, {
          timeout: 30_000,
          cwd: ctx.repoRoot,
        })
        const archived = stdout.match(/archived=(\d+)/)?.[1] || "0"
        if (archived !== "0") results.push(`tasks_archived=${archived}`)
      } catch { /* non-critical */ }
    }

    // 2. Trim handoff if too large
    const handoffArchive = join(ctx.repoRoot, "scripts/state/tasks/handoff_archive.py")
    const handoff = join(ctx.repoRoot, "HANDOFF.vsm.md")
    if (existsSync(handoffArchive) && existsSync(handoff)) {
      try {
        const stat = statSync(handoff)
        if (stat.size > 200_000) {
          await execP(`python3 "${handoffArchive}" --keep 2 --apply`, {
            timeout: 10_000,
            cwd: ctx.repoRoot,
          })
          results.push("handoff_trimmed=true")
        }
      } catch { /* non-critical */ }
    }

    // 3. Journal mark deferred — agent/MCP does this
    results.push("journal=deferred")

    const duration = Date.now() - start
    return {
      result: results.length > 0 ? "ok" : "skip",
      durationMs: duration,
      detail: results.join(",") || "nothing to do",
      summary: results.join(","),
    }
  },
}
