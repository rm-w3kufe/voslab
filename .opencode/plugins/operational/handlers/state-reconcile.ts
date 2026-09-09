// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * state-reconcile.ts — handler for drift detection on session.idle.
 *
 * REASONING: State reconciliation compares the declared state (what the system
 * thinks is true) against the observed state (what's actually happening on n02).
 * Drift detection identifies discrepancies that need attention.
 *
 * PREREQUISITES:
 * - n02 is reachable via SSH
 * - state.db exists on n02
 * - Reconcile script exists
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation, type LogReasoning, type LogImpact } from "../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

export const stateReconcileHandler: Handler = {
  id: "state-reconcile",
  priority: 3,
  events: ["session.idle"],

  classify: async () => {
    // Only run if n02 is reachable
    try {
      await execFileP("ssh", ["root@n02", "test", "-f", "/var/lib/vsf-state/state.db"], { timeout: 5_000 })
      return true
    } catch {
      return false
    }
  },

  execute: async (ctx) => {
    const start = Date.now()
    const reconcileScript = join(ctx.repoRoot, "scripts/state/monitoring/monitor_reconcile.py")

    // REASONING: Why are we running state reconciliation?
    const reasoning: LogReasoning = {
      why: "Detectar drift entre estado declarado y observado en n02",
      prerequisites: [
        "n02 reachable via SSH",
        "state.db existe en n02",
        "Script de reconciliación existe",
      ],
      alternatives: [
        "skip - si n02 no reachable",
        "force - ejecutar reconciliación independientemente de connectividad",
      ],
      chosen: "full - ejecutar reconciliación y detectar drift",
    }

    // IMPACT: What does this affect?
    const impact: LogImpact = {
      scope: "estado del sistema y consistencia",
      reversible: false,
      side_effects: [
        "Drift detectado puede requerir acción correctiva",
        "Estado declarado puede ser actualizado",
      ],
    }

    if (!existsSync(reconcileScript)) {
      await logActivation(ctx.repoRoot, "state-reconcile", "session.idle", "skip", "not_found", "reconcile script not found", {
        reasoning: { ...reasoning, chosen: "skip - script no encontrado" },
        impact,
      })
      return { result: "skip", durationMs: 0, detail: "reconcile script not found" }
    }

    try {
      // Log start with reasoning
      await logActivation(ctx.repoRoot, "state-reconcile", "session.idle", "start", "running", undefined, {
        reasoning,
        impact,
        trigger: { event: "session.idle", source: "event-router" },
      })

      const { stdout } = await execFileP("python3", [reconcileScript, "--check"], {
        timeout: 30_000,
        cwd: ctx.repoRoot,
      })
      const hasDrift = /drift|DRIFT/i.test(stdout)
      const detail = hasDrift ? "drift detected" : "no drift"
      const durationMs = Date.now() - start

      // Log completion with reasoning
      await logActivation(ctx.repoRoot, "state-reconcile", "session.idle", "execute", hasDrift ? "warn" : "ok", detail, {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: hasDrift
            ? "Drift detectado - se requiere investigación"
            : "Sin drift - estado consistente",
        },
        impact: hasDrift ? {
          ...impact,
          side_effects: ["Drift detectado - puede requerir acción correctiva"],
        } : impact,
        metrics: {
          duration_ms: durationMs,
          items_processed: 1,
          success_rate: 1.0,
        },
      })

      return {
        result: hasDrift ? "ok" : "skip",
        durationMs,
        detail,
        summary: hasDrift ? "drift=yes" : "drift=none",
      }
    } catch {
      const durationMs = Date.now() - start

      // Log failure with reasoning
      await logActivation(ctx.repoRoot, "state-reconcile", "session.idle", "execute", "error", "reconcile failed", {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: "Reconciliación falló - revisar logs para detalles",
        },
        impact,
        metrics: {
          duration_ms: durationMs,
          items_processed: 0,
          success_rate: 0,
        },
      })
      return { result: "error", durationMs, detail: "reconcile failed" }
    }
  },
}
