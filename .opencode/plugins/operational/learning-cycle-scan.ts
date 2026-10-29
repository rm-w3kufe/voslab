/**
 * design: docs/design/sources/r16-spec-v1/learning-cycle-instruments-design.vsm
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
 *
 * SANDBOX (NEXT-3 thin slice): all spawns go through sandboxedExecFile
 * (execFile-only, cwd+path confined, env allowlisted, bounded, audited).
 * Activation logging uses logActivation (direct append, no subprocess).
 */
import type { Plugin } from "@opencode-ai/plugin"
import { existsSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { logActivation } from "../../shared/log-activation"
import { sandboxedExecFile } from "../../shared/run-sandbox"
import { algedonicAlert } from "../../shared/algedonic-alert"

// ROOT: repo root. BUG FIX 2026-08-17 (AGENT-PLUGIN-CYCLE-REPAIR): the v1
// used join(process.cwd(),"..","..") assuming cwd=.opencode/plugins/ — but
// opencode runs plugins with cwd=repo root, so the path resolved to /home
// (one level too high), existsSync=false, and the scan NEVER ran (silent
// dead code). Fix: walk UP from the session directory until the scan script
// exists (same pattern as vsf-onboard-reminder.findManifest). Only the
// session directory is probed — never process.cwd(), so a session opened
// outside the repo degrades to "no scan to enforce" instead of a wrong path.
//
// BUG FIX 2026-10-07 (L-OCC root cause): the caller derived the repo root as
// dirname³(scan) — correct only while REL had THREE segments
// (scripts/state/…). When the script moved to scripts/state/core/ (4
// segments) dirname³ resolved to <root>/scripts, logActivation wrote to
// <root>/scripts/logs/agent_plugin.jsonl, and every reader of the canonical
// logs/agent_plugin.jsonl saw the instrument as dead (1,309 records were
// stranded there, 2026-09-12 → 2026-10-07). The walk-up directory that
// MATCHES the relative path IS the repo root — return it directly; no
// dirname counting that silently breaks on the next move.
function findScript(directory: string): { root: string; path: string } | null {
  const REL = "scripts/state/core/session_learning_scan.sh"
  let p = resolve(directory || process.cwd())
  for (let i = 0; i < 6; i++) {
    const candidate = resolve(p, REL)
    if (existsSync(candidate)) return { root: p, path: candidate }
    const parent = dirname(p)
    if (parent === p) break
    p = parent
  }
  return null
}

/** Env knob sanitized to int (argv-safe by construction, numeric anyway). */
function envInt(name: string, fallback: number): number {
  const raw = process.env[name]
  const n = raw === undefined ? NaN : Number.parseInt(raw, 10)
  return Number.isFinite(n) && n > 0 ? n : fallback
}

export default (async ({ project, directory, $ }) => {
  const root = directory || process.cwd()
  const found = findScript(root)
  const scan = found ? found.path : null
  // Repo root = the walk-up directory where REL resolved (findScript).
  // NEVER dirname-counting off the scan path — that off-by-one stranded
  // every activation record in <root>/scripts/logs/ (L-OCC 2026-10-07).
  // null (no scan in this checkout) → degrade to the session directory.
  const repoRootDir = found ? found.root : root

  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return

      // AGENT-CYCLE-OBSERVABILITY-2026-08-17: log every activation — if the
      // scan is dead again, the log goes silent and the next audit sees it
      // (the 2026-08-17 lesson: dead plugin with NO trace).
      try {
        await logActivation(
          repoRootDir, "learning-cycle-scan", "session.idle",
          "event fired", "fired")
      } catch { /* logging must never break the scan */ }

      if (!scan || !existsSync(scan)) {
        // no scan script in this checkout — nothing to enforce (nothing staged)
        return
      }

      const run = await sandboxedExecFile(["bash", scan, "pass"], {
        repoRoot: repoRootDir,
        timeoutMs: 10_000,
        auditSource: "learning-cycle-scan",
      })
      if (run.ok) {
        const stderr = run.stderr
        if (stderr && /BLOCKS|FAIL|pendiente|sin registrar/i.test(stderr)) {
          // The scan reported pending learnings — surface it (block is visual:
          // opencode keeps running, but the agent sees the pending drafts).
          console.error(
            "[learning-cycle-scan] ⚠️ aprendizajes detectados sin registrar:\n" +
              stderr +
              "\n→ Convertir en IR (learning_records/) o eliminar el draft antes de cerrar.",
          )
          algedonicAlert(repoRootDir, "learning_drafts_pending",
            "learning-cycle-scan(S4)", "warn",
            `aprendizajes detectados sin registrar: ${stderr.trim()}`)
        }
        try {
          await logActivation(
            repoRootDir, "learning-cycle-scan", "session.idle",
            "scan executed", "ok", "PASS no pending")
        } catch { /* logging must never break the scan */ }
      } else {
        // scan failed (exit != 0) — treat as pending learnings report
        console.error(
          "[learning-cycle-scan] ⚠️ learning scan detectó drafts pendientes " +
            "(session_learning_scan.sh exit≠0). Revisar learning_records/.pending/.",
        )
        algedonicAlert(repoRootDir, "learning_drafts_pending",
          "learning-cycle-scan(S4)", "warn",
          "learning scan detectó drafts pendientes (session_learning_scan.sh exit≠0). Revisar learning_records/.pending/.")
        try {
          await logActivation(
            repoRootDir, "learning-cycle-scan", "session.idle",
            "scan executed", "error", "drafts pending or scan failed")
        } catch { /* logging must never break the scan */ }
      }

      // S4 statistical mechanism (learning_cycle.vsm §1 trace): POPULATE the
      // window (aggregate IRs) and READ under condition (N novel in W days →
      // S4/S5 decide investment in new structure). Deterministic (R10).
      const stats = join(repoRootDir, "scripts/state/monitoring/learning_stats.py")
      if (existsSync(stats)) {
        const check = await sandboxedExecFile(["python3", stats, "--check",
          "--min-n", String(envInt("LEARNING_MIN_N", 3)),
          "--window-days", String(envInt("LEARNING_WINDOW_DAYS", 30))], {
          repoRoot: repoRootDir,
          timeoutMs: 10_000,
          auditSource: "learning-cycle-scan",
        })
        if (check.ok) {
          if (check.stderr && /TRIGGER/i.test(check.stderr)) {
            console.error(
              "[learning-cycle-scan] 🔔 S4: N patrones novel en ventana → " +
                "decisión de inversión pendiente:\n" + check.stderr,
            )
            algedonicAlert(repoRootDir, "learning_investment_pending",
              "learning-cycle-scan(S4)", "warn",
              `S4: N patrones novel en ventana → decisión de inversión pendiente: ${check.stderr.trim()}`)
          }
        } else {
          console.error(
            "[learning-cycle-scan] 🔔 S4: N patrones novel alcanzaron umbral — " +
              "decisión de inversión pendiente (learning_stats.py --check exit≠0).",
          )
          algedonicAlert(repoRootDir, "learning_investment_pending",
            "learning-cycle-scan(S4)", "warn",
            "S4: N patrones novel alcanzaron umbral — decisión de inversión pendiente (learning_stats.py --check exit≠0).")
        }
      }
    },
  }
}) satisfies Plugin
