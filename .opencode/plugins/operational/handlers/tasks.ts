/**
 * tasks-handler.ts — handler for task maintenance scripts.
 *
 * Runs (read-only / report modes) over vOSlab's task registry
 * (current_focus.json) — rewired by S5 order 2026-10-03:
 *   focus_maintain.py --validate    — focus-format policy (delegates to
 *                                     gate_suite validate_focus, single
 *                                     source of rules; rc!=0 on violations)
 *   focus_maintain.py --reconcile   — model≡reality findings (advisory, rc=0)
 *   focus_maintain.py --check       — counts + stale-active report (rc=0)
 *   focus_maintain.py --closed      — dry-run archive candidates (rc=0,
 *                                     never writes)
 * The upstream TASKS.vsm scripts in the same dir (validate/reconcile/
 * maintain/archive → ~/vsf/TASKS.vsm, boundary AUTHORITY G-05) are parked
 * here: they follow task_tracking_architecture phase_1 (task() hierarchy),
 * which is not implemented in vOSlab yet.
 * handoff_archive.py is NOT run here (session-hygiene owns it with an
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
      ["scripts/state/tasks/focus_maintain.py", ["--validate"]],
      ["scripts/state/tasks/focus_maintain.py", ["--reconcile"]],
      ["scripts/state/tasks/focus_maintain.py", ["--check"]],
      ["scripts/state/tasks/focus_maintain.py", ["--closed"]],
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
