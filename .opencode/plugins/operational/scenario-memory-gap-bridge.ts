/**
 * scenario-memory-gap-bridge.ts — Bridge between scenario-memory and gap-resolver.
 *
 * GAP-19 consolidation: removed dependency on matching.ts (duplicate TS logic).
 * This bridge reads procedures directly and provides gap resolution suggestions.
 * All matching logic is canonical in Python (scenario_memory.py).
 *
 * R10: Engine decides with structural evidence, LLM proposes.
 * R16: Policy declares (tree), instrument interprets (handler).
 */
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

/** Gap context for scenario-memory query. */
export interface GapContext {
  gapId: string;
  gapType: string;
  filePath?: string;
  trigger: string;
}

/** Scenario-memory suggestion for gap resolution. */
export interface GapSuggestion {
  procedureId: string;
  confidence: number;
  source: "reused" | "adapted" | "new";
  suggestion: string;
  metadata: Record<string, any>;
}

/** Minimal procedure record for gap matching. */
interface Procedure {
  id: string;
  type: string;
  source: { instrument: string; hook: string };
  outcome: { success: boolean };
  context?: Record<string, any>;
  metadata: { timestamp: string };
}

/**
 * Load procedures from learning_records/procedures/.
 */
function loadProcedures(repoRoot: string): Procedure[] {
  const dir = join(repoRoot, "docs/spec_revision/learning_records/procedures");
  if (!existsSync(dir)) return [];

  try {
    const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
    const procedures: Procedure[] = [];
    for (const file of files) {
      try {
        const proc = JSON.parse(readFileSync(join(dir, file), "utf-8"));
        if (proc.type === "procedure") procedures.push(proc);
      } catch { /* skip malformed */ }
    }
    return procedures;
  } catch { return []; }
}

/**
 * Simple confidence scoring (mirrors Python scenario_memory logic).
 */
function scoreMatch(proc: Procedure, gapType: string): number {
  if (proc.source.instrument !== gapType) return 0;
  let score = 0.4;
  if (proc.source.hook === "gap-resolution") score += 0.3;
  if (proc.outcome?.success) score += 0.2;
  // Recency bonus
  const ts = proc.metadata?.timestamp;
  if (ts) {
    const days = (Date.now() - new Date(ts).getTime()) / 86400000;
    if (days <= 7) score += 0.1;
  }
  return Math.min(score, 1);
}

/**
 * Query scenario-memory for gap resolution suggestions.
 */
export function queryScenarioMemoryForGap(
  gapContext: GapContext,
  repoRoot: string,
): GapSuggestion[] {
  const procedures = loadProcedures(repoRoot);
  if (procedures.length === 0) return [];

  const matches: { proc: Procedure; confidence: number }[] = [];
  for (const proc of procedures) {
    const confidence = scoreMatch(proc, gapContext.gapType);
    if (confidence > 0) matches.push({ proc, confidence });
  }

  matches.sort((a, b) => b.confidence - a.confidence);

  return matches.map((m) => ({
    procedureId: m.proc.id,
    confidence: m.confidence,
    source: m.confidence >= 0.8 ? "reused" : m.confidence >= 0.6 ? "adapted" : "new",
    suggestion: m.confidence >= 0.8
      ? `High confidence: Use procedure ${m.proc.id}`
      : m.confidence >= 0.6
      ? `Medium confidence: Adapt procedure ${m.proc.id} for gap ${gapContext.gapId}`
      : `Low confidence: Create new procedure for gap ${gapContext.gapId}`,
    metadata: { procedureOutcome: m.proc.outcome },
  }));
}

/**
 * Check if a gap has been resolved by scenario-memory.
 */
export function isGapResolvedByScenarioMemory(
  gapId: string,
  repoRoot: string,
): boolean {
  const procedures = loadProcedures(repoRoot);
  return procedures.some((proc) => {
    const confidence = scoreMatch(proc, "gap-resolution");
    return confidence >= 0.8;
  });
}
