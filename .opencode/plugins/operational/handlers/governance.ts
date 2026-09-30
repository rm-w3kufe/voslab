/**
 * governance-handler.ts — handler for governance scripts.
 *
 * Runs (CC-2 revised, contract-correct + host-guarded):
 *   s5_ca.py expiring --ca-dir …   — CA renewal proximity check (read-only)
 *   apply_bbs_whitelist.py …       — idempotent, only if policy+fragment exist
 *   s5_caution.py check            — caution-mode check (read-only)
 * Removed from idle (CC-2):
 *   s5_inbox.py           — SSH dashboard (watch-mode, N probes × 6s ProxyJump
 *                           blows the 30s per-script budget; run on demand)
 *   read_crl_next_update.py — argv helper needing an s5_crl.json path; no CRL
 *                           material exists on the agent host (FND-S1-HOST-ROLE-SPLIT)
 * Trigger: session.idle (periodic, low frequency).
 *
 * REASONING: These scripts verify the health of the trust infrastructure
 * (certificates, CRLs, whitelists). They are run periodically to ensure
 * the system's security posture is maintained.
 */
import { existsSync } from "node:fs"
import { join } from "node:path"
import { runScript, type ScriptResult } from "../../../shared/run-script"
import { logActivation, type LogReasoning, type LogImpact } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

export const governanceHandler: Handler = {
  id: "governance",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ScriptResult[] = []

    // REASONING: Why are we running governance scripts?
    const reasoning: LogReasoning = {
      why: "Verificar salud de infraestructura de confianza después de sesión inactiva",
      prerequisites: [
        "CA certificate no expirado",
        "CRL lista para renovación",
        "BBS whitelist actualizada",
      ],
      alternatives: [
        "skip - si no hay cambios desde última verificación",
        "full - ejecutar todos los scripts de gobernanza",
      ],
      chosen: "full - porque la sesión estuvo inactiva y podría haber cambios",
    }

    // IMPACT: What does this affect?
    const impact: LogImpact = {
      scope: "infraestructura de confianza (CA, CRL, BBS)",
      reversible: false,
      side_effects: [
        "CA renewal check puede renovar certificados",
        "CRL puede ser actualizada",
        "BBS whitelist puede ser modificada",
      ],
    }

    // Log handler activation with reasoning
    await logActivation(ctx.repoRoot, "governance", "session.idle", "start", "running", undefined, {
      reasoning,
      impact,
      trigger: { event: "session.idle", source: "event-router" },
    })

    // Run each governance script — CC-2: correct CLI modes + host prereq
    // guards (absent CA material / policy / state.db on the agent host →
    // synthetic skip instead of guaranteed usage-error noise).
    const runs: { script: string; args: string[]; prereq?: string[] }[] = [
      {
        script: "scripts/state/governance/s5_ca.py",
        args: ["expiring", "--ca-dir", "/var/lib/vsf-state/ca"],
        prereq: ["/var/lib/vsf-state/ca/s5_root.pub.json"],
      },
      {
        script: "scripts/state/governance/apply_bbs_whitelist.py",
        args: ["/etc/vsf/s5_policy.json", "bbs_whitelist.ratified.json"],
        prereq: ["/etc/vsf/s5_policy.json", "bbs_whitelist.ratified.json"],
      },
      {
        script: "scripts/state/governance/s5_caution.py",
        args: ["check"],
        prereq: ["/var/lib/vsf-state/state.db"],
      },
    ]
    for (const run of runs) {
      const absent = (run.prereq || []).filter((p) =>
        !(p.startsWith("/") ? existsSync(p) : existsSync(join(ctx.repoRoot, p))))
      if (absent.length) {
        results.push({
          script: run.script,
          result: "skip",
          detail: `prereq missing: ${absent.join(", ")}`,
          durationMs: 0,
        })
        continue
      }
      const r = await runScript(ctx.repoRoot, run.script, run.args)
      results.push(r)
    }

    const allOk = results.every((r) => r.result === "ok" || r.result === "skip")
    const detail = results.map((r) => `${r.script}: ${r.result}`).join("; ")
    const durationMs = Date.now() - start

    // Log completion with outcome and reasoning
    await logActivation(
      ctx.repoRoot,
      "governance",
      "session.idle",
      "execute",
      allOk ? "ok" : "error",
      detail,
      {
        durationMs,
        reasoning: {
          ...reasoning,
          chosen: allOk
            ? "Todos los scripts completados exitosamente"
            : `Algunos scripts fallaron: ${results.filter(r => r.result === "fail").map(r => r.script).join(", ")}`,
        },
        impact,
        metrics: {
          duration_ms: durationMs,
          items_processed: results.length,
          success_rate: results.filter(r => r.result === "ok" || r.result === "skip").length / results.length,
        },
      },
    )

    return {
      result: allOk ? "pass" : "fail",
      durationMs,
      detail,
    }
  },
}
