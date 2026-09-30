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
import { logActivation, type LogReasoning, type LogImpact } from "../../../shared/log-activation"
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

      // FND-LEARNING-STATS-DEAD-STORE-01: no more swallowed output.
      // stats --check reads the LIVE scenario store; rc=1 is a TRIGGER
      // (novel failure signatures ≥ N → S4/S5 decision signal), rc=2 is
      // a broken store. Both are surfaced in `detail` instead of a
      // fixed "scan PASS"; stats stays non-blocking (scan is the gate).
      let statsDetail = "stats not run"
      if (existsSync(statsScript)) {
        try {
          const { stdout } = await execFileP(
            "python3", [statsScript, "--check", "--min-n", String(process.env.LEARNING_MIN_N ?? 3), "--window-days", String(process.env.LEARNING_WINDOW_DAYS ?? 30)],
            { timeout: 10_000, cwd: ctx.repoRoot },
          )
          statsDetail = stdout.trim().split("\n")[0] || "stats ok"
        } catch (e) {
          const err = e as { code?: number; stdout?: string; stderr?: string }
          const summary =
            (err.stdout || "").trim().split("\n")[0] ||
            (err.stderr || "").trim().split("\n")[0] ||
            "no output"
          if (err.code === 1) {
            statsDetail = `stats TRIGGER — ${summary}`
          } else {
            statsDetail = `stats error (rc=${err.code}) — ${summary}`
          }
        }
      }

      const durationMs = Date.now() - start
      const detail = `scan PASS; ${statsDetail}`

      // Log completion with reasoning
      await logActivation(ctx.repoRoot, "learning-cycle", "session.idle", "execute", "ok", detail, {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: "Scan completado exitosamente - stats sobre el store vivo",
        },
        impact,
        metrics: {
          duration_ms: durationMs,
          items_processed: 1,
          success_rate: 1.0,
        },
      })
      return { result: "ok", durationMs, detail }
    } catch (e) {
      const durationMs = Date.now() - start
      const message = e instanceof Error ? e.message.split("\n")[0] : String(e)

      // Log failure with reasoning
      await logActivation(ctx.repoRoot, "learning-cycle", "session.idle", "execute", "error", `scan failed: ${message}`, {
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
      return { result: "error", durationMs, detail: `scan failed: ${message}` }
    }
  },
}
