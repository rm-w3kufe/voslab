/**
 * scenario-memory-gap-bridge.ts — Bridge between scenario-memory and gap-resolver.
 * design: docs/spec_revision/design-sources/rsi-observer-v1/scenario-memory-gap-bridge-design.vsm
 * dir_schema: .opencode/plugins/operational/
 * creates: scenario-memory suggestions for gap resolution
 * consumes: gap-resolver events, scenario-memory procedures
 * check: impl-with-design-valid
 *
 * Allows scenario-memory to suggest procedures for resolving gaps.
 * When a gap is detected, scenario-memory can provide:
 * 1. Past procedures that resolved similar gaps
 * 2. Adapted procedures based on confidence
 * 3. New procedure recommendations
 *
 * R10: Engine decides with structural evidence, LLM proposes.
 * R16: Policy declares (tree), instrument interprets (handler).
 */
import { loadProcedures, matchProcedures, getRecommendation } from "../../shared/matching";
import { logActivation } from "../../shared/log-activation";

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

/**
 * Query scenario-memory for gap resolution suggestions.
 * @param gapContext - The gap context to query for
 * @param repoRoot - Repository root path
 * @returns Array of suggestions, sorted by confidence
 */
export function queryScenarioMemoryForGap(
  gapContext: GapContext,
  repoRoot: string,
): GapSuggestion[] {
  const procedures = loadProcedures(repoRoot);
  if (procedures.length === 0) {
    return [];
  }

  // Match gap context against past procedures
  const matches = matchProcedures(
    procedures,
    gapContext.gapType,
    "gap-resolution",
    {
      gapId: gapContext.gapId,
      filePath: gapContext.filePath,
      trigger: gapContext.trigger,
    },
  );

  // Convert matches to suggestions
  const suggestions: GapSuggestion[] = matches.map((match) => ({
    procedureId: match.procedure.id,
    confidence: match.confidence,
    source: match.confidence >= 0.8 ? "reused" : 
            match.confidence >= 0.6 ? "adapted" : "new",
    suggestion: generateGapSuggestion(match, gapContext),
    metadata: {
      matchScore: match.score,
      procedureOutcome: match.procedure.outcome,
    },
  }));

  // Log the query
  logActivation({
    type: "scenario-memory-gap-query",
    gapId: gapContext.gapId,
    gapType: gapContext.gapType,
    suggestionsFound: suggestions.length,
    topConfidence: suggestions.length > 0 ? suggestions[0].confidence : 0,
  });

  return suggestions;
}

/**
 * Generate a human-readable suggestion from a match.
 */
function generateGapSuggestion(match: any, gapContext: GapContext): string {
  const proc = match.procedure;
  const confidence = match.confidence;

  if (confidence >= 0.8) {
    return `High confidence: Use procedure ${proc.id} (past success: ${proc.outcome.success})`;
  } else if (confidence >= 0.6) {
    return `Medium confidence: Adapt procedure ${proc.id} for gap ${gapContext.gapId}`;
  } else {
    return `Low confidence: Create new procedure for gap ${gapContext.gapId}`;
  }
}

/**
 * Check if a gap has been resolved by scenario-memory.
 * @param gapId - The gap ID to check
 * @param repoRoot - Repository root path
 * @returns true if a high-confidence resolution exists
 */
export function isGapResolvedByScenarioMemory(
  gapId: string,
  repoRoot: string,
): boolean {
  const procedures = loadProcedures(repoRoot);
  
  const matches = matchProcedures(
    procedures,
    "gap-resolution",
    "gap-resolution",
    { gapId },
  );

  // Check if any high-confidence match exists
  return matches.some((match) => match.confidence >= 0.8);
}
