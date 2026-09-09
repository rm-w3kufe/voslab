// hook-analytics.ts — handler for hook activation analytics.
//
// DESIGN: ABSORCIÓN DE VARIEDAD (rmw3 S5): the activation log contains raw
// variety. This handler ABSORBS it and REDUCES it to patterns that can
// inform the learning cycle.
//
// Runs on session.idle (after learning-cycle). Calls hook_analytics.py --json
// and surfaces insights for S4/S5.
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

export const hookAnalyticsHandler: Handler = {
  id: "hook-analytics",
  priority: 2,  // runs after learning-cycle (priority 1)
  events: ["session.idle"],

  classify: async () => {
    // Only run if analytics script exists
    const scriptPath = join(process.cwd(), "scripts/state/monitoring/hook_analytics.py")
    return existsSync(scriptPath)
  },

  execute: async (ctx) => {
    const start = Date.now()
    const script = join(ctx.repoRoot, "scripts/state/monitoring/hook_analytics.py")

    if (!existsSync(script)) {
      return { result: "skip", durationMs: 0, detail: "analytics script not found" }
    }

    try {
      // Run analytics in JSON mode
      const { stdout } = await execFileP(
        "python3", [script, "--json", "--window-hours", "168"],  // last 7 days
        { timeout: 15_000, cwd: ctx.repoRoot }
      )

      const report = JSON.parse(stdout)

      // Surface key insights (absorb variety → reduce to actionable info)
      const insights: string[] = []

      // High error rate
      if (report.errors.error_rate > 5) {
        insights.push(`HIGH ERROR RATE: ${report.errors.error_rate}% (${report.errors.total_errors} errors)`)
      }

      // Instruments with high failure rates
      for (const [inst, rate] of Object.entries(report.errors.failure_rates)) {
        if ((rate as number) > 10) {
          insights.push(`${inst}: ${rate}% failure rate`)
        }
      }

      // Anomalies
      for (const anomaly of report.anomalies) {
        if (anomaly.severity === "warning") {
          insights.push(`ANOMALY: ${anomaly.type} — ${anomaly.instrument}`)
        }
      }

      // Inactive instruments (potential dead plugins)
      const inactive = report.anomalies.filter((a: any) => a.type === "inactive")
      if (inactive.length > 0) {
        insights.push(`${inactive.length} instruments inactive > 7 days`)
      }

      const detail = insights.length > 0
        ? insights.join("; ")
        : `OK — ${report.summary.total_records} activations, ${report.summary.error_rate}% errors`

      return {
        result: report.errors.error_rate > 10 ? "warning" : "ok",
        durationMs: Date.now() - start,
        detail,
      }
    } catch (e: any) {
      return {
        result: "error",
        durationMs: Date.now() - start,
        detail: e.message?.slice(0, 200) || "analytics failed",
      }
    }
  },
}
