/**
 * shared-handler.ts — handler for shared scripts.
 *
 * Runs: sync_covenant_hash.sh, vsf_nats.py.
 * Trigger: session.idle (periodic, low frequency).
 */
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"
import { runScript, type ScriptResult } from "../../../shared/run-script"

export const sharedHandler: Handler = {
  id: "shared",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: SharedResult[] = []

    // Run each shared script
    for (const script of [
      "scripts/state/shared/sync_covenant_hash.sh",
      "scripts/state/shared/vsf_nats.py",
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
