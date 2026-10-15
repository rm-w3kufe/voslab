/**
 * design: docs/plans/system_projection_2026_10_14.vsm
 * (EV-R2/W1 — auto-resync de derived blocks; el gate queda como
 *  verificador post-hoc.)
 * derived-resync — opencode plugin (auto-discovered in .opencode/plugins/).
 *
 * CLASS: operational (advisory). Trigger: `session.idle`.
 * Runs scripts/vsl/tools/derived_resync.py --apply:
 *   - re-pins sha256[:16] stale hash entries in system/boot/boot_manifest.vsm
 *     (the treadmill this kills: every kernel edit left boot-manifest-valid
 *     RED until a human re-pinned — live demo 2026-10-15, rsi_cycle.py
 *     stale hours after the P-B re-pin because P-EV-R4 edited it)
 *   - regenerates scripts manifests when the scripts/ fingerprint changed
 *   - reports tasks drift (judgment — NEVER auto-written, R9)
 *
 * The resync is mechanical (R10 deterministic): the plugin only executes
 * the tool and surfaces the report; no decisions live here.
 *
 * SANDBOX: spawn via sandboxedExecFile (execFile-only, cwd+path confined,
 * env allowlisted, bounded, audited). Activation logging via logActivation
 * (direct append, no subprocess).
 */
import type { Plugin } from "@opencode-ai/plugin"
import { existsSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { logActivation } from "../../shared/log-activation"
import { sandboxedExecFile } from "../../shared/run-sandbox"

// Walk-up to the repo root (same pattern as learning-cycle-scan — the
// directory that MATCHES the relative path IS the repo root; never
// dirname-counting, which silently breaks on the next move, L-OCC).
function findTool(directory: string): { root: string; path: string } | null {
  const REL = "scripts/vsl/tools/derived_resync.py"
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

export default (async ({ directory }: { directory?: string }) => {
  const found = findTool(directory || process.cwd())
  const repoRootDir = found ? found.root : (directory || process.cwd())

  return {
    event: async ({ event }: { event: { type: string } }) => {
      if (event.type !== "session.idle") return

      try {
        await logActivation(
          repoRootDir, "derived-resync", "session.idle",
          "event fired", "fired")
      } catch { /* logging must never break the resync */ }

      if (!found) {
        // no tool in this checkout — nothing to resync
        return
      }

      const run = await sandboxedExecFile(
        ["python3", found.path, "--apply", "--json"],
        {
          repoRoot: repoRootDir,
          timeoutMs: 120_000,
          auditSource: "derived-resync",
        })
      if (!run.ok) {
        console.error(
          "[derived-resync] ⚠️ resync reportó drift que no pudo resolver " +
          `(exit≠0). Ver: python3 ${found.path} --json`)
        try {
          await logActivation(
            repoRootDir, "derived-resync", "session.idle",
            "resync executed", "error", run.stderr?.slice(0, 300) || "exit!=0")
        } catch { /* logging must never break */ }
        return
      }

      // Surface only when something was actually rewritten (quiet no-op
      // on the common idle where nothing drifted).
      let report: {
        drift_total?: number
        boot_pins_applied?: number
        scripts?: { regenerated?: boolean }
        tasks_drift?: { summary?: string }
      } = {}
      try {
        const out = run.stdout?.trim() || "{}"
        report = JSON.parse(out.slice(out.indexOf("{")))
      } catch { /* unparseable output = log-only */ }

      const applied = (report.boot_pins_applied || 0) > 0 ||
        report.scripts?.regenerated === true
      if (applied) {
        console.error(
          `[derived-resync] derived blocks re-sincronizados: ` +
          `boot_pins=${report.boot_pins_applied || 0} ` +
          `scripts_regenerated=${report.scripts?.regenerated ? "yes" : "no"} ` +
          `— gate boot-manifest-valid queda como verificador post-hoc.`)
      }
      const td = report.tasks_drift?.summary
      if (td && /finding/i.test(td)) {
        // judgment drift: report only, never auto-write (R9)
        console.error(`[derived-resync] tasks_drift (report-only): ${td}`)
      }
      try {
        await logActivation(
          repoRootDir, "derived-resync", "session.idle",
          "resync executed", "ok",
          `drift_total=${report.drift_total ?? "?"} ` +
          `boot_pins_applied=${report.boot_pins_applied ?? 0}`)
      } catch { /* logging must never break */ }
    },
  }
})
