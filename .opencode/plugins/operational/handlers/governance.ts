/**
 * governance-handler.ts — handler for governance scripts.
 *
 * Runs: s5_ca.py (CA renewal check), s5_inbox.py (S5 inbox),
 *       read_crl_next_update.py (CRL expiry),
 *       apply_bbs_whitelist.py (BBS whitelist),
 *       s5_caution.py (caution mode).
 * Trigger: session.idle (periodic, low frequency).
 *
 * REASONING: These scripts verify the health of the trust infrastructure
 * (certificates, CRLs, whitelists). They are run periodically to ensure
 * the system's security posture is maintained.
 */
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

    // Run each governance script (sequential — each may SSH to n02)
    for (const script of [
      "scripts/state/governance/s5_ca.py",
      "scripts/state/governance/s5_inbox.py",
      "scripts/state/governance/read_crl_next_update.py",
      "scripts/state/governance/apply_bbs_whitelist.py",
      "scripts/state/governance/s5_caution.py",
    ]) {
      const r = await runScript(ctx.repoRoot, script)
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
