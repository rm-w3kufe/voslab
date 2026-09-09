// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * learning-cycle.ts — handler for learning scan + S4 stats.
 *
 * REASONING: The learning cycle analyzes session history to extract patterns
 * and insights. It runs on session.idle to process data collected during
 * active sessions, feeding into S4 intelligence for future decisions.
 *
 * PREREQUISITES:
 * - Session learning scan script exists
 * - Sufficient session data (min-n items)
 * - Time window for analysis (default 30 days)
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation, type LogReasoning, type LogImpact } from "../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

export const learningCycleHandler: Handler = {
  id: "learning-cycle",
  priority: 1,
  events: ["session.idle"],

  classify: async () => true, // always run — scan is idempotent

  execute: async (ctx) => {
    const start = Date.now()
    const scanScript = join(ctx.repoRoot, "scripts/state/session_learning_scan.sh")
    const statsScript = join(ctx.repoRoot, "scripts/state/monitoring/learning_stats.py")

    // REASONING: Why are we running the learning cycle?
    const reasoning: LogReasoning = {
      why: "Analizar historial de sesiones para extraer patrones e insights",
      prerequisites: [
        "Script de scan existe",
        "Datos de sesión suficientes (min-n items)",
        "Ventana de tiempo para análisis (default 30 días)",
      ],
      alternatives: [
        "skip - si no hay datos nuevos desde último scan",
        "force - ejecutar scan independientemente de datos",
      ],
      chosen: "full - ejecutar scan y verificar estadísticas",
    }

    // IMPACT: What does this affect?
    const impact: LogImpact = {
      scope: "datos de aprendizaje y estadísticas S4",
      reversible: true,
      side_effects: [
        "Patrones extraídos del historial",
        "Estadísticas de aprendizaje actualizadas",
        "Insights para decisiones futuras",
      ],
    }

    if (!existsSync(scanScript)) {
      await logActivation(ctx.repoRoot, "learning-cycle", "session.idle", "skip", "not_found", "scan script not found", {
        reasoning: { ...reasoning, chosen: "skip - script no encontrado" },
        impact,
      })
      return { result: "skip", durationMs: 0, detail: "scan script not found" }
    }

    try {
      // Log start with reasoning
      await logActivation(ctx.repoRoot, "learning-cycle", "session.idle", "start", "running", undefined, {
        reasoning,
        impact,
        trigger: { event: "session.idle", source: "event-router" },
      })

      await execFileP("bash", [scanScript, "pass"], { timeout: 10_000, cwd: ctx.repoRoot })

      if (existsSync(statsScript)) {
        await execFileP(
          "python3", [statsScript, "--check", "--min-n", String(process.env.LEARNING_MIN_N ?? 3), "--window-days", String(process.env.LEARNING_WINDOW_DAYS ?? 30)],
          { timeout: 10_000, cwd: ctx.repoRoot },
        ).catch(() => {}) // stats failure is non-blocking
      }

      const durationMs = Date.now() - start

      // Log completion with reasoning
      await logActivation(ctx.repoRoot, "learning-cycle", "session.idle", "execute", "ok", "scan PASS", {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: "Scan completado exitosamente - patrones extraídos",
        },
        impact,
        metrics: {
          duration_ms: durationMs,
          items_processed: 1,
          success_rate: 1.0,
        },
      })
      return { result: "ok", durationMs, detail: "scan PASS" }
    } catch {
      const durationMs = Date.now() - start

      // Log failure with reasoning
      await logActivation(ctx.repoRoot, "learning-cycle", "session.idle", "execute", "error", "scan failed", {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: "Scan falló - revisar logs para detalles",
        },
        impact,
        metrics: {
          duration_ms: durationMs,
          items_processed: 0,
          success_rate: 0,
        },
      })
      return { result: "error", durationMs, detail: "scan failed" }
    }
  },
}
