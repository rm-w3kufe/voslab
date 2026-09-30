/**
 * lifecycle-handler.ts — handler for lifecycle scripts.
 *
 * Runs: lifecycle-status.sh, lifecycle-report.sh, lifecycle-dashboard.sh,
 *       lifecycle-init.sh, lifecycle-promote.sh.
 * Trigger: session.idle (periodic reporting)
 *
 * Provides unified lifecycle visibility across all projects.
 */
import { runScript, type ScriptResult } from "../../../shared/run-script"
import type { Handler } from "../vsf-event-router"

export const lifecycleHandler: Handler = {
  id: "lifecycle-reporting",
  priority: 2,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ScriptResult[] = []

    // Run lifecycle scripts
    // CC-2: lifecycle-init.sh / lifecycle-promote.sh removed from idle —
    // both are MANUAL ops requiring args (and promote WRITES state);
    // bare invocations were usage-errors.
    for (const script of [
      "scripts/state/lifecycle/lifecycle-status.sh",
      "scripts/state/lifecycle/lifecycle-status.sh --extended",
    ]) {
      const args = script.includes("--extended") ? ["--extended"] : []
      const scriptPath = script.replace(" --extended", "")
      const r = await runScript(ctx.repoRoot, scriptPath, args)
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
