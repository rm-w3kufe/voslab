/**
 * core-handler.ts — handler for core system scripts.
 *
 * Runs: bootstrap.sh, onboard.sh, populate.sh, q.sh,
 *       rotate_nats_token.sh, state_attest.py, vsf-storage-probe.sh.
 * Trigger: session.idle (periodic, low frequency).
 */
import { runScript, type ScriptResult } from "../../../shared/run-script"
import type { Handler } from "../vsf-event-router"

export const coreHandler: Handler = {
  id: "core-scripts",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ScriptResult[] = []

    // Run each core script
    for (const script of [
      "scripts/state/core/bootstrap.sh",
      "scripts/state/core/onboard.sh",
      "scripts/state/core/populate.sh",
      "scripts/state/core/q.sh",
      "scripts/state/core/rotate_nats_token.sh",
      "scripts/state/core/state_attest.py",
      "scripts/state/core/vsf-storage-probe.sh",
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
