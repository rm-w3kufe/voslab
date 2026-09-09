/**
 * services-handler.ts — handler for services scripts.
 *
 * Runs: service_watchdog.py, vsf-compact.py, vsf_cgroup_reallocate.py.
 * Trigger: session.idle (periodic, low frequency).
 */
import { runScript, type ScriptResult } from "../../../shared/run-script"
import type { Handler } from "../vsf-event-router"

export const servicesHandler: Handler = {
  id: "services",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ScriptResult[] = []

    // Run each services script
    for (const script of [
      "scripts/state/services/service_watchdog.py",
      "scripts/state/services/vsf_compact.py",
      "scripts/state/services/vsf_cgroup_reallocate.py",
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
