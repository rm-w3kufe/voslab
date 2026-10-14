/**
 * gap-registry.ts — Gate registry integration for gap resolution.
 *
 * Loads gap definitions from the unified gate registry, which combines:
 * - Static gate trees (.opencode/plugins/support/trees/*.tree.vsm)
 * - Gap-definition gates (.opencode/plugins/operational/gap-definitions/*.gap.json)
 * - RSI-generated gates (from rsi_pipeline.py)
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { algedonicAlert } from "../../shared/algedonic-alert"

const execFileP = promisify(execFile)

// ─── Types ───────────────────────────────────────────────────────────────────

export interface GapDefinition {
  id: string
  name: string
  description: string
  trigger: {
    type: string
    patterns?: string[]
    directories?: string[]
    events?: string[]
  }
  context: {
    gatherers: Array<{
      type: string
      [key: string]: any
    }>
  }
  evaluation: {
    type: string
    tree?: string
    inputs?: string[]
  }
  actions: Array<{
    condition: string
    action: string
    params?: Record<string, any>
  }>
  logging: {
    destination: string
    format: string
  }
}

interface GateRegistryGate {
  id: string
  name: string
  description: string
  gate_type: string
  source: string
  trigger: {
    type: string
    patterns?: string[]
    directories?: string[]
    events?: string[]
  }
  evaluation: {
    type: string
    tree?: any
  }
  actions: Array<{
    type: string
    severity?: string
    message?: string
  }>
  severity: string
  enabled: boolean
  metadata: Record<string, any>
}

// ─── Gate Registry Integration ───────────────────────────────────────────────

/**
 * Load gap definitions from the unified gate registry.
 * This combines static gates, gap-definition gates, and RSI-generated gates.
 */
export async function loadGapDefinitionsFromRegistry(repoRoot: string): Promise<GapDefinition[]> {
  const GATE_REGISTRY_ENABLED = process.env.GATE_REGISTRY_ENABLED !== "false"
  
  if (!GATE_REGISTRY_ENABLED) {
    return []
  }

  try {
    // Call gate_registry.py to get all gates
    const registryScript = join(repoRoot, "packages/public/vsf-rsi/vsf_rsi/gate_registry.py")
    if (!existsSync(registryScript)) {
      return []
    }

    const { stdout } = await execFileP(
      "python3",
      [registryScript, "--json"],
      { cwd: repoRoot, timeout: 10000 }
    )

    const registry = JSON.parse(stdout)
    const gates: GapDefinition[] = []

    // Convert registry gates to GapDefinition format
    for (const [gateId, gateData] of Object.entries(registry.gates || {})) {
      const gate = gateData as GateRegistryGate
      if (!gate.enabled) continue

      // Convert gate_type to trigger type
      let triggerType = "always"
      if (gate.trigger?.type) {
        triggerType = gate.trigger.type
      }

      // Convert evaluation to gap format
      let evaluation = { type: "rule-based" }
      if (gate.evaluation?.type === "socratic" && gate.evaluation?.tree) {
        evaluation = {
          type: "socratic-tree",
          tree: typeof gate.evaluation.tree === "string" 
            ? gate.evaluation.tree 
            : JSON.stringify(gate.evaluation.tree)
        }
      }

      // Convert actions to gap format
      const actions = (gate.actions || []).map(action => ({
        condition: "true",
        action: action.type === "report" ? "log-success" : "alert-conflict",
        params: {
          message: action.message || `Gate ${gateId} triggered`,
          severity: action.severity || gate.severity
        }
      }))

      // Add severity-based action
      if (gate.severity === "CRITICAL" || gate.severity === "HIGH") {
        actions.push({
          condition: "decision === 'BLOCK'",
          action: "block-commit",
          params: { reason: `Gate ${gateId} blocked action` }
        })
      }

      const gapDef: GapDefinition = {
        id: gateId,
        name: gate.name,
        description: gate.description,
        trigger: {
          type: triggerType,
          ...gate.trigger
        },
        context: {
          gatherers: [{ type: "read-content" }]
        },
        evaluation,
        actions,
        logging: {
          destination: "logs/gap-resolution.jsonl",
          format: "jsonl"
        }
      }

      gates.push(gapDef)
    }

    return gates
  } catch (err: any) {
    console.error(`[gap-registry] Failed to load from registry: ${err.message}`)
    // Layer A: a registry load failure is a pain signal — route to the channel.
    algedonicAlert(repoRoot, "gap_registry_load_failed", "gap-registry(S4)",
      "error", `Failed to load gap definitions from registry: ${err.message}`)
    return []
  }
}
