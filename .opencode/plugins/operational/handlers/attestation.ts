/**
 * attestation-handler.ts — handler for attestation checks.
 *
 * Runs: check_agent_log.py (agent log validation),
 *       check_binary_integrity.py (binary integrity).
 * Trigger: session.idle (periodic).
 */
import { runScript, type ScriptResult } from "../../../shared/run-script"
import type { Handler } from "../vsf-event-router"

export const attestationHandler: Handler = {
  id: "attestation",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results = []

    for (const script of [
      "scripts/state/attestation/check_agent_log.py",
      "scripts/state/attestation/check_binary_integrity.py",
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
