// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * state-reconcile.ts — handler for drift detection on session.idle.
 *
 * Checks if n02 is reachable, then runs monitor_reconcile.py --check.
 * Only runs if state.db exists (n02 reachable).
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

export const stateReconcileHandler: Handler = {
  id: "state-reconcile",
  priority: 3,
  events: ["session.idle"],

  classify: async () => {
    // Only run if n02 is reachable
    try {
      await execP("ssh root@n02 test -f /var/lib/vsf-state/state.db", { timeout: 5_000 })
      return true
    } catch {
      return false
    }
  },

  execute: async (ctx) => {
    const start = Date.now()
    const reconcileScript = join(ctx.repoRoot, "scripts/state/monitoring/monitor_reconcile.py")

    if (!existsSync(reconcileScript)) {
      return { result: "skip", durationMs: 0, detail: "reconcile script not found" }
    }

    try {
      const { stdout } = await execP(`python3 "${reconcileScript}" --check`, {
        timeout: 30_000,
        cwd: ctx.repoRoot,
      })
      const hasDrift = /drift|DRIFT/i.test(stdout)
      return {
        result: hasDrift ? "ok" : "skip",
        durationMs: Date.now() - start,
        detail: hasDrift ? "drift detected" : "no drift",
        summary: hasDrift ? "drift=yes" : "drift=none",
      }
    } catch {
      return { result: "error", durationMs: Date.now() - start, detail: "reconcile failed" }
    }
  },
}
