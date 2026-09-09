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
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation, type LogReasoning, type LogImpact } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

interface GovernanceResult {
  script: string
  result: string
  detail: string
  durationMs: number
}

async function runScript(
  repoRoot: string,
  scriptPath: string,
  args: string[] = [],
): Promise<GovernanceResult> {
  const start = Date.now()
  const full = join(repoRoot, scriptPath)
  if (!existsSync(full)) {
    return { script: scriptPath, result: "skip", detail: "not found", durationMs: 0 }
  }
  try {
    const { stdout } = await execFileP("python3", [full, ...args], {
      cwd: repoRoot,
      timeout: 30_000,
      env: { ...process.env },
    })
    return {
      script: scriptPath,
      result: "ok",
      detail: stdout.trim().slice(0, 500),
      durationMs: Date.now() - start,
    }
  } catch (err: any) {
    return {
      script: scriptPath,
      result: "fail",
      detail: err.message?.slice(0, 300) || "unknown error",
      durationMs: Date.now() - start,
    }
  }
}

export const governanceHandler: Handler = {
  id: "governance",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: GovernanceResult[] = []

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
