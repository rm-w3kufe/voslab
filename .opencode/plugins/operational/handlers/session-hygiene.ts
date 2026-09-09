// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * session-hygiene.ts — handler for archive + handoff + journal on session.idle.
 *
 * REASONING: Session hygiene maintains the health of the session lifecycle
 * by archiving completed tasks, trimming oversized handoffs, and preparing
 * for journal marking. This prevents unbounded growth and ensures clean
 * session transitions.
 *
 * PREREQUISITES:
 * - Archive scripts exist
 * - Handoff file exists and may need trimming
 * - Journal marking is deferred to agent/MCP
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync, statSync } from "node:fs"
import { join } from "node:path"
import { logActivation, type LogReasoning, type LogImpact } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

export const sessionHygieneHandler: Handler = {
  id: "session-hygiene",
  priority: 2,
  events: ["session.idle"],

  classify: async () => true, // always run — tools are idempotent

  execute: async (ctx) => {
    const start = Date.now()
    const results: string[] = []

    // REASONING: Why are we running session hygiene?
    const reasoning: LogReasoning = {
      why: "Mantener salud del ciclo de vida de sesión: archivar tareas completas, limpiar handoffs",
      prerequisites: [
        "Scripts de archivo existen",
        "Archivo handoff existe y puede necesitar limpieza",
        "Marcado de journal diferido a agent/MCP",
      ],
      alternatives: [
        "skip - si no hay tareas completadas",
        "force - archivar independientemente de estado",
      ],
      chosen: "full - ejecutar archivado y verificación de handoff",
    }

    // IMPACT: What does this affect?
    const impact: LogImpact = {
      scope: "archivos de sesión y handoffs",
      reversible: true,
      side_effects: [
        "Tareas completadas archivadas",
        "Handoff trimmed si es muy grande",
        "Journal preparado para marcado",
      ],
    }

    // Log start with reasoning
    await logActivation(ctx.repoRoot, "session-hygiene", "session.idle", "start", "running", undefined, {
      reasoning,
      impact,
      trigger: { event: "session.idle", source: "event-router" },
    })

    // 1. Archive completed tasks
    const tasksArchive = join(ctx.repoRoot, "scripts/state/tasks/tasks_archive.py")
    if (existsSync(tasksArchive)) {
      try {
        const { stdout } = await execFileP("python3", [tasksArchive, "--closed", "--apply"], {
          timeout: 30_000,
          cwd: ctx.repoRoot,
        })
        const archived = stdout.match(/archived=(\d+)/)?.[1] || "0"
        if (archived !== "0") results.push(`tasks_archived=${archived}`)
      } catch { /* non-critical */ }
    }

    // 2. Trim handoff if too large
    const handoffArchive = join(ctx.repoRoot, "scripts/state/tasks/handoff_archive.py")
    const handoff = join(ctx.repoRoot, "HANDOFF.vsm.md")
    if (existsSync(handoffArchive) && existsSync(handoff)) {
      try {
        const stat = statSync(handoff)
        if (stat.size > 200_000) {
          await execFileP("python3", [handoffArchive, "--keep", "2", "--apply"], {
            timeout: 10_000,
            cwd: ctx.repoRoot,
          })
          results.push("handoff_trimmed=true")
        }
      } catch { /* non-critical */ }
    }

    // 3. Journal mark deferred — agent/MCP does this
    results.push("journal=deferred")

    const durationMs = Date.now() - start
    const detail = results.join(",") || "nothing to do"

    // Log completion with reasoning
    await logActivation(ctx.repoRoot, "session-hygiene", "session.idle", "execute", results.length > 0 ? "ok" : "skip", detail, {
      durationMs,
      reasoning: {
        ...reasoning,
        chosen: results.length > 0
          ? `Completado: ${results.join(", ")}`
          : "Nada que hacer - sesión ya limpia",
      },
      impact,
      metrics: {
        duration_ms: durationMs,
        items_processed: results.length,
        success_rate: 1.0,
      },
    })

    return {
      result: results.length > 0 ? "ok" : "skip",
      durationMs,
      detail,
      summary: results.join(","),
    }
  },
}
