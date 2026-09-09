/**
 * procedure-generator.ts — Scenario Memory Phase 3: procedure generation module.
 *
 * Generates new procedures based on adaptation of existing ones.
 * Creates adapted versions with modified parameters or approach.
 *
 * Design:
 * - generateProcedure(): Create new procedure from adaptation
 * - adaptProcedure(): Modify existing procedure based on outcomes
 * - validateProcedure(): Ensure procedure is well-formed
 * - saveProcedure(): Persist to learning_records/procedures/
 *
 * R10: Generation is deterministic (no LLM inference).
 * R17: SAFEGUARD — max 3 adaptations per original procedure.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

/** A procedure record from learning_records/procedures/. */
export interface Procedure {
  id: string;
  type: "procedure";
  version: string;
  source: {
    instrument: string;
    hook: string;
  };
  action: string;
  decision: {
    result: string;
  };
  outcome: {
    success: boolean;
    detail?: string;
    durationMs?: number;
  };
  context?: Record<string, any>;
  metadata: {
    timestamp: string;
    pid: number;
    adaptations_used?: number;
    parent_id?: string;
    adaptation_reason?: string;
  };
}

/** Generated procedure result. */
export interface GeneratedProcedure {
  procedure: Procedure;
  reason: string;
  adaptation_level: "high" | "medium" | "low";
}

/**
 * Generate a new procedure based on adaptation of an existing one.
 */
export function generateProcedure(
  original: Procedure,
  adaptationLevel: "high" | "medium" | "low",
  reason: string,
  newOutcome?: { success: boolean; detail?: string; durationMs?: number },
): GeneratedProcedure {
  const now = new Date().toISOString();
  const adaptations_used = (original.metadata.adaptations_used || 0) + 1;

  // Create adapted procedure
  const adapted: Procedure = {
    id: `${original.id}-adapted-${adaptations_used}`,
    type: "procedure",
    version: "1.0",
    source: { ...original.source },
    action: adaptAction(original.action, adaptationLevel),
    decision: { result: "pending" },
    outcome: newOutcome || { success: false, detail: "adaptation pending" },
    context: {
      ...original.context,
      adapted_from: original.id,
      adaptation_level: adaptationLevel,
    },
    metadata: {
      timestamp: now,
      pid: process.pid,
      adaptations_used,
      parent_id: original.id,
      adaptation_reason: reason,
    },
  };

  return {
    procedure: adapted,
    reason,
    adaptation_level: adaptationLevel,
  };
}

/**
 * Adapt action based on adaptation level.
 */
function adaptAction(action: string, level: "high" | "medium" | "low"): string {
  // For now, return the original action with adaptation marker
  // Future: implement specific adaptations based on level
  return `[adapted:${level}] ${action}`;
}

/**
 * Validate a procedure is well-formed.
 */
export function validateProcedure(procedure: Procedure): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (!procedure.id) errors.push("missing id");
  if (procedure.type !== "procedure") errors.push("invalid type");
  if (!procedure.source?.instrument) errors.push("missing source.instrument");
  if (!procedure.source?.hook) errors.push("missing source.hook");
  if (!procedure.action) errors.push("missing action");
  if (!procedure.metadata?.timestamp) errors.push("missing metadata.timestamp");

  // R17 safeguard: check adaptations_used
  const adaptations_used = procedure.metadata?.adaptations_used || 0;
  if (adaptations_used > 3) {
    errors.push("max adaptations exceeded (R17 safeguard)");
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

/**
 * Save procedure to learning_records/procedures/.
 */
export function saveProcedure(repoRoot: string, procedure: Procedure): boolean {
  const dir = join(repoRoot, "docs/spec_revision/learning_records/procedures");
  mkdirSync(dir, { recursive: true });

  const filename = `${procedure.id}.json`;
  const filepath = join(dir, filename);

  // Check if file already exists
  if (existsSync(filepath)) {
    console.error(`[PROCEDURE-GENERATOR] procedure already exists: ${filename}`);
    return false;
  }

  try {
    writeFileSync(filepath, JSON.stringify(procedure, null, 2));
    return true;
  } catch (e: any) {
    console.error(`[PROCEDURE-GENERATOR] failed to save: ${e.message}`);
    return false;
  }
}

/**
 * Load a procedure by ID.
 */
export function loadProcedure(repoRoot: string, procedureId: string): Procedure | null {
  const dir = join(repoRoot, "docs/spec_revision/learning_records/procedures");
  const filename = `${procedureId}.json`;
  const filepath = join(dir, filename);

  if (!existsSync(filepath)) return null;

  try {
    const content = readFileSync(filepath, "utf-8");
    return JSON.parse(content);
  } catch {
    return null;
  }
}

/**
 * Get adaptation history for a procedure.
 */
export function getAdaptationHistory(
  repoRoot: string,
  procedureId: string,
): Procedure[] {
  const dir = join(repoRoot, "docs/spec_revision/learning_records/procedures");
  if (!existsSync(dir)) return [];

  try {
    const { readdirSync } = require("node:fs");
    const files = readdirSync(dir).filter((f: string) => f.endsWith(".json"));
    const history: Procedure[] = [];

    for (const file of files) {
      try {
        const content = readFileSync(join(dir, file), "utf-8");
        const proc = JSON.parse(content);
        // Check if this is an adaptation of the original
        if (proc.metadata?.parent_id === procedureId || proc.id === procedureId) {
          history.push(proc);
        }
      } catch {
        // Skip malformed files
      }
    }

    // Sort by timestamp
    return history.sort((a, b) =>
      new Date(a.metadata.timestamp).getTime() - new Date(b.metadata.timestamp).getTime()
    );
  } catch {
    return [];
  }
}
