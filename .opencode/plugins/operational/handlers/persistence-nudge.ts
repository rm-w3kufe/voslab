// persistence-nudge.ts — §6.1 close-checklist advisory nudge (REFS-OPT-001 F4.1).
//
// DESIGN: session-close hygiene as an advisory variety-absorber. On
// session.idle, run persistence_nudge.py (three deterministic checks:
// focus freshness, commit session block, learn freshness). When the
// checklist fails and the emission throttle allows, ONE reminder goes
// to the unified log and to the active focus detail file, then the
// marker is written (6h default). Advisory by design — never blocks;
// an error here must not poison the handler batch.
import { appendFileSync, existsSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"
import { sandboxedExecFile } from "../../../shared/run-sandbox"
import { logActivation } from "../../../shared/log-activation"

export const persistenceNudgeHandler: Handler = {
  id: "persistence-nudge",
  priority: 65, // late advisory: checklist after learning (1), audit (60)
  events: ["session.idle"],

  classify: async () =>
    existsSync(join(process.cwd(), "scripts/state/monitoring/persistence_nudge.py")),

  execute: async (ctx) => {
    const start = Date.now()
    const script = join(ctx.repoRoot, "scripts/state/monitoring/persistence_nudge.py")
    if (!existsSync(script)) {
      return { result: "skip", durationMs: 0, detail: "nudge script not found" }
    }

    try {
      const run = await sandboxedExecFile(
        ["python3", script, "--json"],
        { repoRoot: ctx.repoRoot, timeoutMs: 15_000, auditSource: "persistence-nudge" },
      )
      if (!run.ok) throw new Error(run.detail)
      const report = JSON.parse(run.stdout)
      const throttled = report.throttled === true

      if (report.ok === true) {
        return {
          result: "ok",
          durationMs: Date.now() - start,
          detail: throttled ? "checklist ok (throttled)" : "checklist green: focus/session/learn",
        }
      }

      const failed: string = Array.isArray(report.failed) ? report.failed.join(",") : "unknown"
      if (throttled) {
        return {
          result: "ok",
          durationMs: Date.now() - start,
          detail: `checklist stale (${failed}) — emission throttled`,
        }
      }

      const staleLines: string[] = (Array.isArray(report.checks) ? report.checks : [])
        .filter((c: any) => c && c.ok === false)
        .map((c: any) => `${c.id}: ${c.detail}`)
      const refs: string[] = Array.isArray(report.focus_refs) ? report.focus_refs : []

      // 1) reminder to the unified log (S5 reads it via view_log --live)
      await logActivation(
        ctx.repoRoot,
        "persistence-nudge",
        "session.idle",
        `close checklist pending — ${failed}`,
        "warn",
        staleLines.join("; ").slice(0, 500),
        { focus_refs: refs, marker: "state/rsi/.persistence_nudge_last" },
      )

      // 2) reminder anchored to the active focus detail (newest active ref)
      if (typeof report.newest_ref === "string" && report.newest_ref) {
        const detailPath = join(
          ctx.repoRoot, "state", "focus_details", `${report.newest_ref}.md`,
        )
        if (existsSync(detailPath)) {
          appendFileSync(
            detailPath,
            `\n> nudge ${new Date().toISOString()}: close checklist pending — ${failed}\n`,
          )
        }
      }

      // 3) throttle marker — only emission writes it (script stays read-only)
      if (typeof report.marker === "string" && report.marker) {
        try {
          writeFileSync(report.marker, `${new Date().toISOString()}\n`)
        } catch {
          // marker is a nicety — a read-only checkout must not break the nudge
        }
      }

      return {
        result: "warning",
        durationMs: Date.now() - start,
        detail: `nudged: ${failed} (refs: ${refs.join(",") || "none"})`,
      }
    } catch (e: any) {
      return {
        result: "error",
        durationMs: Date.now() - start,
        detail: e.message?.slice(0, 200) || "persistence nudge failed",
      }
    }
  },
}
