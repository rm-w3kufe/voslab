// doc-tracking.ts — handler for doc-manifest consistency verify.
//
// P2 W3 (2026-10-12): doc_tracking/verify_docs.py ran only manually —
// drift, orphans and the S5 review queue stayed invisible. This handler
// runs it on session.idle, throttled to 1/hour via marker file, with a
// 120s timeout (probe runs exceeded 60s). REPORT-ONLY: verify rc0 is a
// report, not a gate — results never block, only surface.
import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"
import { sandboxedExecFile } from "../../../shared/run-sandbox"

const MARKER_REL = "state/doc_tracking/.idle_last"
const THROTTLE_MS = 3600_000

export const docTrackingHandler: Handler = {
  id: "doc-tracking",
  priority: 3,
  events: ["session.idle"],

  classify: async (ctx) => {
    const script = join(ctx.repoRoot, "scripts/doc_tracking/verify_docs.py")
    if (!existsSync(script)) return false
    try {
      const marker = join(ctx.repoRoot, MARKER_REL)
      if (!existsSync(marker)) return true
      const last = Number(readFileSync(marker, "utf-8").trim())
      if (!Number.isFinite(last)) return true
      return Date.now() - last > THROTTLE_MS
    } catch {
      return true // marker unreadable — run rather than stall forever
    }
  },

  execute: async (ctx) => {
    const start = Date.now()
    const script = join(ctx.repoRoot, "scripts/doc_tracking/verify_docs.py")
    try {
      const run = await sandboxedExecFile(
        ["python3", script],
        { repoRoot: ctx.repoRoot, timeoutMs: 120_000, auditSource: "doc-tracking" }
      )
      try {
        writeFileSync(join(ctx.repoRoot, MARKER_REL), String(Date.now()))
      } catch {
        // marker best-effort — throttle degrades to every idle, still safe
      }
      if (!run.ok) throw new Error(run.detail)
      const interesting = (run.stdout || "")
        .split("\n")
        .filter((l) => /orphan|drift|missing|queue|huerfano|faltante/i.test(l))
        .slice(0, 5)
      return {
        result: "ok",
        durationMs: Date.now() - start,
        detail: interesting.length > 0 ? interesting.join("; ") : "doc-manifest clean",
        summary: `doc-tracking: ${interesting.length > 0 ? interesting.length + " findings" : "clean"}`,
      }
    } catch (e: any) {
      return {
        result: "error",
        durationMs: Date.now() - start,
        detail: (e.message || "verify_docs failed").slice(0, 200),
      }
    }
  },
}
