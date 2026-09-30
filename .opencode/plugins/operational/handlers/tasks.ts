/**
 * tasks-handler.ts — handler for task maintenance scripts.
 *
 * Runs (read-only / report modes):
 *   tasks_validate.py      — TASKS.vsm gate (bare)
 *   tasks_reconcile.py     — model≡reality reconcile (bare)
 *   maintain.py --check    — maintenance coherence (needs task_tree → FND)
 *   tasks_archive.py --closed — DRY-RUN report; the APPLY side lives in
 *                               session-hygiene (guard: file exists + --apply)
 * handoff_archive.py is NOT run here (session-hygiene owns it, with an
 * existsSync guard — bare invocation crashed with FileNotFoundError).
 * Trigger: session.idle (periodic).
 * CC-2 (CYCLE-CLOSE-001): bare invocations without required mode flags
 * were usage-errors; contracts now match each script's CLI.
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
    const results: ScriptResult[] = []

    const runs: [string, string[]][] = [
      ["scripts/state/tasks/tasks_validate.py", []],
      ["scripts/state/tasks/tasks_reconcile.py", []],
      ["scripts/state/tasks/maintain.py", ["--check"]],
      ["scripts/state/tasks/tasks_archive.py", ["--closed"]],
    ]
    for (const [script, args] of runs) {
      const r = await runScript(ctx.repoRoot, script, args)
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
