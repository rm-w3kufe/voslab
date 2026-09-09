/**
 * design: docs/spec_revision/design-sources/r16-spec-v1/LEARNING-CYCLE-INSTRUMENTS-DESIGN.vsm
 * learning-cycle-scan — opencode plugin (auto-discovered in .opencode/plugins/).
 *
 * Recursivity (rmw3 2026-08-16): "todo lo automatizable tiene que ir con hook,
 * eso mismo tiene que ser un hook" — the instrument that forces the learning
 * cycle (learning_cycle.vsm) is itself a hook of the cycle.
 *
 * Trigger: on `session.idle` (session goes to rest — end of turn / waiting
 * for input), run scripts/state/session_learning_scan.sh. If the session
 * detected learnings that were NOT persisted as IRs (drafts left in
 * learning_records/.pending/), report loudly so they are not forgotten.
 *
 * The script is deterministic (R10 — LLM tactics, not enforcement): the
 * plugin only executes it and surfaces its output; the decision lives in
 * the scan (draft present → block/report; absent → pass).
 */
import type { Plugin } from "@opencode-ai/plugin"
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { dirname, join, resolve } from "node:path"

const execP = promisify(exec)

// ROOT: repo root. BUG FIX 2026-08-17 (AGENT-PLUGIN-CYCLE-REPAIR): the v1
// used join(process.cwd(),"..","..") assuming cwd=.opencode/plugins/ — but
// opencode runs plugins with cwd=repo root, so the path resolved to /home
// (one level too high), existsSync=false, and the scan NEVER ran (silent
// dead code). Fix: walk UP from the session directory until the scan script
// exists (same pattern as vsf-onboard-reminder.findManifest). Only the
// session directory is probed — never process.cwd(), so a session opened
// outside the repo degrades to "no scan to enforce" instead of a wrong path.
function findScript(directory: string): string | null {
  const REL = "scripts/state/core/session_learning_scan.sh"
  let p = resolve(directory || process.cwd())
  for (let i = 0; i < 6; i++) {
    const candidate = resolve(p, REL)
    if (existsSync(candidate)) return candidate
    const parent = dirname(p)
    if (parent === p) break
    p = parent
  }
  return null
}

export default (async ({ project, directory, $ }) => {
  const root = directory || process.cwd()
  const scan = findScript(root)
  // Derive the repo root from the FOUND scan path: scan sits at
  // <root>/scripts/state/session_learning_scan.sh, so the repo root is THREE
  // dirname levels up (file → state → scripts → root). v1 of this fix used
  // two levels and resolved to <root>/scripts — caught by R4 verification
  // (join(root, "scripts/state/learning_stats.py") missed the file).
  const repoRootDir = scan
    ? dirname(dirname(dirname(scan)))
    : root

  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return

      // AGENT-CYCLE-OBSERVABILITY-2026-08-17: log every activation — if the
      // scan is dead again, the log goes silent and the next audit sees it
      // (the 2026-08-17 lesson: dead plugin with NO trace).
      const logger = join(repoRootDir, "scripts/state/agent-plugin-log")
      try {
        if (existsSync(logger)) {
          await execP(
            `"${logger}" learning-cycle-scan session.idle "event fired" fired`,
            { timeout: 3_000, cwd: root },
          )
        }
      } catch { /* logging must never break the scan */ }

      if (!scan || !existsSync(scan)) {
        // no scan script in this checkout — nothing to enforce (nothing staged)
        return
      }

      try {
        const { stdout, stderr } = await execP(`bash "${scan}" pass`, {
          timeout: 10_000,
          cwd: root,
        })
        if (stderr && /BLOCKS|FAIL|pendiente|sin registrar/i.test(stderr)) {
          // The scan reported pending learnings — surface it (block is visual:
          // opencode keeps running, but the agent sees the pending drafts).
          console.error(
            "[learning-cycle-scan] ⚠️ aprendizajes detectados sin registrar:\n" +
              stderr +
              "\n→ Convertir en IR (learning_records/) o eliminar el draft antes de cerrar.",
          )
        }
        if (existsSync(logger)) {
          await execP(
            `"${logger}" learning-cycle-scan session.idle "scan executed" ok "PASS no pending"`,
            { timeout: 3_000, cwd: root },
          ).catch(() => {})
        }
      } catch {
        // scan failed (exit != 0) — treat as pending learnings report
        console.error(
          "[learning-cycle-scan] ⚠️ learning scan detectó drafts pendientes " +
            "(session_learning_scan.sh exit≠0). Revisar learning_records/.pending/.",
        )
        if (existsSync(logger)) {
          await execP(
            `"${logger}" learning-cycle-scan session.idle "scan executed" error "drafts pending or scan failed"`,
            { timeout: 3_000, cwd: root },
          ).catch(() => {})
        }
      }

      // S4 statistical mechanism (learning_cycle.vsm §1 trace): POPULATE the
      // window (aggregate IRs) and READ under condition (N novel in W days →
      // S4/S5 decide investment in new structure). Deterministic (R10).
      const stats = join(repoRootDir, "scripts/state/monitoring/learning_stats.py")
      if (existsSync(stats)) {
        try {
          const { stdout, stderr } = await execP(
            `python3 "${stats}" --check --min-n ${process.env.LEARNING_MIN_N ?? 3} --window-days ${process.env.LEARNING_WINDOW_DAYS ?? 30}`,
            { timeout: 10_000, cwd: root },
          )
          if (stderr && /TRIGGER/i.test(stderr)) {
            console.error(
              "[learning-cycle-scan] 🔔 S4: N patrones novel en ventana → " +
                "decisión de inversión pendiente:\n" + stderr,
            )
          }
        } catch {
          console.error(
            "[learning-cycle-scan] 🔔 S4: N patrones novel alcanzaron umbral — " +
              "decisión de inversión pendiente (learning_stats.py --check exit≠0).",
          )
        }
      }
    },
  }
}) satisfies Plugin