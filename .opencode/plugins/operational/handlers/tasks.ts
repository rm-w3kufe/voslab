/**
 * tasks-handler.ts — handler for task maintenance scripts.
 *
 * Runs: tasks_archive.py, tasks_reconcile.py, tasks_validate.py,
 *       maintain.py, handoff_archive.py.
 * Trigger: session.idle (periodic).
 */
import { runScript, type ScriptResult } from "../../../shared/run-script"
import type { Handler } from "../vsf-event-router"

export const tasksHandler: Handler = {
  id: "tasks-maintenance",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results = []

    for (const script of [
      "scripts/state/tasks/tasks_validate.py",
      "scripts/state/tasks/tasks_reconcile.py",
      "scripts/state/tasks/maintain.py",
      "scripts/state/tasks/tasks_archive.py",
      "scripts/state/tasks/handoff_archive.py",
    ]) {
      const r = await runScript(ctx.repoRoot, script)
      results.push(r)
    }

    const allOk = results.every((r) => r.result === "ok" || r.result === "skip")
    return {
      result: allOk ? "pass" : "fail",
      durationMs: Date.now() - start,
      detail: results.map((r) => `${r.script}: ${r.result}`).join("; "),
    }
  },
}
