/**
 * core-handler.ts — handler for core system scripts.
 *
 * Runs (CC-2 revised): q.sh (state query), vsf-storage-probe.sh.
 * Trigger: session.idle (periodic, low frequency).
 *
 * REMOVED from idle (CC-2, CYCLE-CLOSE-001) — wrong trigger or host:
 *   bootstrap.sh   — "must run as root"; boot-time (boot_manifest.vsm)
 *   onboard.sh     — session-start canonical query, SSH×n02, interactive
 *   populate.sh    — runs on n02 as root (lives in /usr/local/bin there)
 *   rotate_nats_token.sh — explicit S5 rotation op, needs OLD/NEW tokens
 *   state_attest.py — requires explicit gate mode + runs on n02 only
 * See finding FND-S1-HOST-ROLE-SPLIT for the underlying role split.
 */
import { existsSync } from "node:fs"
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

    // q.sh reads the fleet sqlite state.db — exists only on n02/fleet
    // hosts (FND-S1-HOST-ROLE-SPLIT-01: honest prereq gate, CC-2 pattern).
    const stateDb = "/var/lib/vsf-state/state.db"
    if (existsSync(stateDb)) {
      results.push(await runScript(ctx.repoRoot, "scripts/state/core/q.sh"))
    } else {
      results.push({
        script: "scripts/state/core/q.sh",
        result: "skip",
        detail: `prereq missing: ${stateDb} (fleet host)`,
        durationMs: 0,
      })
    }

    // storage-probe works from the agent host (honest warning if
    // NATS_TOKEN unset) — run unconditionally (CC-2: idle-safe subset).
    results.push(await runScript(ctx.repoRoot, "scripts/state/core/vsf-storage-probe.sh"))

    const allOk = results.every((r) => r.result === "ok" || r.result === "skip")
    return {
      result: allOk ? "pass" : "fail",
      durationMs: Date.now() - start,
      detail: results.map((r) => `${r.script}: ${r.result}`).join("; "),
    }
  },
}
