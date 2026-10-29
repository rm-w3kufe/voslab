// design: docs/design/sources/second-order-loop-v1/second_order_loop.vsm
// handoff.ts — S4→S5 consent-rail trigger (second-order-loop F0).
//
// Runs the Python consent-rail (vos_kernel/handoff.py) on session.idle so the
// candidate queues (epistemic discovery_queue + rsi predicate queue) are no
// longer mute: candidates get collected, consent-classified (deterministic,
// R10), and routed (read-only auto / advisory rastro / needs-nod → S5 alert).
// The module is idempotent (ledger) + safe (needs-nod never auto-executes,
// R17). This handler is a thin trigger — all logic lives in handoff.py.
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { resolve } from "node:path"
import { logActivation } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

export const handoffHandler: Handler = {
  id: "handoff",
  priority: 4,
  events: ["session.idle"],

  // Cheap check (R10): always run on idle — the rail is idempotent + cheap.
  classify: async (ctx) => ctx.event === "session.idle",

  execute: async (ctx) => {
    const start = Date.now()
    const script = resolve(ctx.repoRoot, "packages/framework/vos_kernel/handoff.py")
    try {
      const { stdout } = await execFileP("python3", [script], {
        timeout: 20000,
        cwd: ctx.repoRoot,
      })
      let summary = {}
      try {
        summary = JSON.parse(stdout)
      } catch {
        summary = { raw: stdout.slice(0, 200) }
      }
      const s = summary as Record<string, unknown>
      const detail =
        `collected=${s.collected} processed=${s.processed} ` +
        `advisory=${(s.routed_by_rail as any)?.advisory ?? 0} ` +
        `needs-nod=${(s.routed_by_rail as any)?.["needs-nod"] ?? 0}`
      const durationMs = Date.now() - start
      await logActivation(ctx.repoRoot, "handoff", ctx.event, "execute", "ok", detail, {
        durationMs,
        ...s,
      })
      return { result: "ok", durationMs, detail }
    } catch (e: any) {
      const durationMs = Date.now() - start
      const detail = e?.message?.slice(0, 200) || "handoff failed"
      await logActivation(ctx.repoRoot, "handoff", ctx.event, "execute", "error", detail, {
        durationMs,
      })
      return { result: "error", durationMs, detail }
    }
  },
}
