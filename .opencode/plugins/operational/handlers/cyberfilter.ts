/**
 * cyberfilter-handler.ts — handler for cyberfilter scripts.
 *
 * REASONING: The cyberfilter processes raw system data through multiple
 * stages (variety analysis, L2 projection, L3-L2 aggregation) to produce
 * filtered, actionable intelligence. This is the system's "immune response"
 * for processing environmental signals.
 *
 * PREREQUISITES:
 * - Cyberfilter scripts exist
 * - Raw data available for processing
 * - Processing pipelines configured
 */
import { existsSync } from "node:fs"
import { join } from "node:path"
import { runScript, type ScriptResult } from "../../../shared/run-script"
import { logActivation, type LogReasoning, type LogImpact } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

export const cyberfilterHandler: Handler = {
  id: "cyberfilter",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ScriptResult[] = []

    // REASONING: Why are we running cyberfilter scripts?
    const reasoning: LogReasoning = {
      why: "Procesar datos crudos del sistema a través de múltiples etapas para producir inteligencia filtrada",
      prerequisites: [
        "Scripts de cyberfilter existen",
        "Datos crudos disponibles para procesamiento",
        "Pipelines de procesamiento configurados",
      ],
      alternatives: [
        "skip - si no hay datos nuevos desde último procesamiento",
        "force - procesar independientemente de datos",
      ],
      chosen: "full - ejecutar pipeline completo de cyberfilter",
    }

    // IMPACT: What does this affect?
    const impact: LogImpact = {
      scope: "datos procesados y:",
      reversible: false,
      side_effects: [
        "Variety analysis completada",
        "L2 projection history logged",
        "L3-L2 aggregation realizada",
      ],
    }

    // Log start with reasoning
    await logActivation(ctx.repoRoot, "cyberfilter", "session.idle", "start", "running", undefined, {
      reasoning,
      impact,
      trigger: { event: "session.idle", source: "event-router" },
    })

    // Run each cyberfilter script
    // CC-2: all three stages shell out to `pct` (Proxmox LXC CLI) — only
    // exists on the hypervisor, never on the agent host. Synthetic skip
    // instead of a guaranteed FileNotFoundError fail (FND-S1-HOST-ROLE-SPLIT).
    const hasPct = (process.env.PATH || "").split(":").some((dir) => {
      try { return existsSync(join(dir, "pct")) } catch { return false }
    })
    if (!hasPct) {
      for (const script of [
        "scripts/state/cyberfilter/cyberfilter_variety.py",
        "scripts/state/cyberfilter/vsf_l2_projection_history_logger.py",
        "scripts/state/cyberfilter/vsf_l3_l2_aggregator.py",
      ]) {
        results.push({ script, result: "skip", detail: "prereq missing: pct (hypervisor-only)", durationMs: 0 })
      }
    } else {
      for (const script of [
        "scripts/state/cyberfilter/cyberfilter_variety.py",
        "scripts/state/cyberfilter/vsf_l2_projection_history_logger.py",
        "scripts/state/cyberfilter/vsf_l3_l2_aggregator.py",
      ]) {
        const r = await runScript(ctx.repoRoot, script)
        results.push(r)
      }
    }

    const allOk = results.every((r) => r.result === "ok" || r.result === "skip")
    const detail = results.map((r) => `${r.script}: ${r.result}`).join("; ")
    const durationMs = Date.now() - start

    // Log completion with reasoning
    await logActivation(ctx.repoRoot, "cyberfilter", "session.idle", "execute", allOk ? "ok" : "error", detail, {
      durationMs,
      reasoning: {
        ...reasoning,
        chosen: allOk
          ? "Pipeline de cyberfilter completado exitosamente"
          : `Algunos scripts fallaron: ${results.filter(r => r.result === "fail").map(r => r.script).join(", ")}`,
      },
      impact,
      metrics: {
        duration_ms: durationMs,
        items_processed: results.length,
        success_rate: results.filter(r => r.result === "ok" || r.result === "skip").length / results.length,
      },
    })

    return {
      result: allOk ? "pass" : "fail",
      durationMs,
      detail,
    }
  },
}
