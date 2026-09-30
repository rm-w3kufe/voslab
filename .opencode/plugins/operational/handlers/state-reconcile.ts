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
 *
 * HOST (FND-MONITORING-GAP-01, 2026-09-30): the probe is n02-native by
 * design (state.db + pct + systemd live THERE). classify already gates on
 * ssh+state.db; execute now runs the probe THROUGH ssh on n02 — the old
 * local execution probed agent-local /var/lib/vsf-state + pct (absent on
 * this host) and reported 8 stale instruments, 5 of them false. The
 * remote command pins PATH with /usr/sbin (pct): non-interactive ssh and
 * cron default PATHs lack it — the same root cause that crashes the n02
 * cron producers (see the finding's triage table).
 * Deployed copy on n02 = md5-identical to scripts/state/monitoring/
 * monitor_reconcile.py (verified 2026-09-30, a889688173579b9e).
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation, type LogReasoning, type LogImpact } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

export const stateReconcileHandler: Handler = {
  id: "state-reconcile",
  priority: 3,
  events: ["session.idle"],

  classify: async () => {
    // Only run if n02 is reachable
    try {
      const n02 = process.env.VSF_N02 || "n02"
      // CC-2: n02 is behind ProxyJump via n01 (~6s cold); the old 5s
      // timeout always lost the race → classify returned false and the
      // handler NEVER executed despite n02 being reachable.
      await execFileP("ssh", [`root@${n02}`, "test", "-f", "/var/lib/vsf-state/state.db"], { timeout: 10_000 })
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
        "n02 reachable via SSH (classify)",
        "state.db existe en n02",
        "monitor_reconcile.py desplegado en n02 (md5 idéntico al repo)",
        "PATH con /usr/sbin para pct",
      ],
      alternatives: [
        "skip - si n02 no reachable",
        "local - ejecutar el probe en el host agente (ROTO: sin state.db/pct → dolor falso)",
      ],
      chosen: "remote - ejecutar monitor_reconcile en n02 vía ssh",
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

      // Probe on ITS design host (n02) — see header. rc≠0 with an
      // ALGEDONIC line is the DESIGNED pain signal (gaps found), not a
      // crash: keep it loud (result=error) but carry the real detail.
      const remoteCmd = "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin python3 /usr/local/bin/monitor_reconcile.py --check"
      const { stdout } = await execFileP("ssh", ["root@" + n02, remoteCmd], {
        timeout: 70_000,
      })
      const durationMs = Date.now() - start
      const allCurrent = /all \d+ instruments current/.test(stdout)
      const detail = allCurrent ? "all instruments current on n02" : "probe ok"

      await logActivation(ctx.repoRoot, "state-reconcile", "session.idle", "execute", "ok", detail, {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: "Roll-up n02: instrumentos al día",
        },
        impact,
        metrics: { duration_ms: durationMs, items_processed: 1, success_rate: 1.0 },
      })

      return { result: "ok", durationMs, detail, summary: "instruments=current" }
    } catch (e) {
      const durationMs = Date.now() - start
      const out = `${(e as { stdout?: string })?.stdout ?? ""}${(e as { stderr?: string })?.stderr ?? ""}`
      const algedonic = /ALGEDONIC: monitoring_gap/.test(out)

      if (algedonic) {
        // Designed gate semantics: nonzero = pain. NOT silenced — the row
        // stays result=error with the real stale set in the detail.
        const m = out.match(/monitoring_gap — (.+)/)
        const detail = `monitoring_gap: ${m ? m[1].trim() : "instrument(s) stale"}`
        await logActivation(ctx.repoRoot, "state-reconcile", "session.idle", "execute", "warn", detail, {
          durationMs,
          reasoning: {
            ...reasoning,
            chosen: "Algedonic diseñado: instrumentos stale en n02 — dolor real, no crash",
          },
          impact: { ...impact, side_effects: ["Señal de dolor algedonic publicada en el bus"] },
          metrics: { duration_ms: durationMs, items_processed: 1, success_rate: 1.0 },
        })
        return { result: "error", durationMs, detail, summary: "monitoring_gap" }
      }

      const msg = ((e as Error)?.message ?? "reconcile failed").slice(0, 200)
      const detail = `reconcile failed: ${msg}`
      await logActivation(ctx.repoRoot, "state-reconcile", "session.idle", "execute", "error", detail, {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: "Fallo real (ssh/timeout/sin ALGEDONIC) - revisar conectividad a n02",
        },
        impact,
        metrics: { duration_ms: durationMs, items_processed: 0, success_rate: 0 },
      })
      return { result: "error", durationMs, detail }
    }
  },
}
