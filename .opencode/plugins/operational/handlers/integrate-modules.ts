// integrate-modules.ts — push framework modules through the backbone canal.
//
// P2 W6 (2026-10-12): vos_kernel.backbone.integrate_modules ran only via
// manual CLI + its own test — canal state went stale after framework
// work. This handler runs it on tool.execute.after when the write lands
// under packages/framework/, throttled to 10min via marker file.
// REPORT-ONLY: per-module outcomes continue on error; nothing blocks.
import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { join, resolve, sep, isAbsolute } from "node:path"
import type { Handler } from "../vsf-event-router"
import { sandboxedExecFile } from "../../../shared/run-sandbox"

const MARKER_REL = "state/rsi/.integrate_modules_last"
const THROTTLE_MS = 600_000
const FRAMEWORK_REL = ["packages", "framework"].join(sep)

export const integrateModulesHandler: Handler = {
  id: "integrate-modules",
  priority: 4,
  events: ["tool.execute.after"],

  classify: async (ctx) => {
    const payload: any = (ctx as any).payload ?? {}
    const tool: string = payload.tool || ""
    if (tool !== "write" && tool !== "edit") return false
    const args: any = payload.args ?? {}
    const fp: string = args.file_path ?? args.filePath ?? ""
    if (!fp) return false
    const abs = isAbsolute(fp) ? fp : resolve(ctx.repoRoot, fp)
    if (!abs.startsWith(join(ctx.repoRoot, FRAMEWORK_REL) + sep)) return false
    try {
      const marker = join(ctx.repoRoot, MARKER_REL)
      if (existsSync(marker)) {
        const last = Number(readFileSync(marker, "utf-8").trim())
        if (Number.isFinite(last) && Date.now() - last < THROTTLE_MS) return false
      }
    } catch {
      // marker unreadable — run rather than stall forever
    }
    return true
  },

  execute: async (ctx) => {
    const start = Date.now()
    try {
      const run = await sandboxedExecFile(
        ["python3", "-m", "vos_kernel.backbone.integrate_modules",
         "--state-dir", "state"],
        { repoRoot: ctx.repoRoot, timeoutMs: 120_000, auditSource: "integrate-modules",
          extraEnv: { PYTHONPATH: join(ctx.repoRoot, "packages", "framework") } }
      )
      try {
        writeFileSync(join(ctx.repoRoot, MARKER_REL), String(Date.now()))
      } catch {
        // marker best-effort
      }
      if (!run.ok) throw new Error(run.detail)
      const firstLine = (run.stdout || "").split("\n").filter(Boolean)[0] || "ok"
      return {
        result: "ok",
        durationMs: Date.now() - start,
        detail: firstLine.slice(0, 200),
        summary: `integrate-modules: ${firstLine.slice(0, 120)}`,
      }
    } catch (e: any) {
      return {
        result: "error",
        durationMs: Date.now() - start,
        detail: (e.message || "integrate_modules failed").slice(0, 200),
      }
    }
  },
}
