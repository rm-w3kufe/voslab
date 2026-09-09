/**
 * matching.ts — Scenario Memory Phase 2: procedure matching module.
 *
 * Provides functions to match current context against past procedures
 * stored in learning_records/procedures/. Uses the procedure-match.tree.vsm
 * for deterministic evaluation (R10: engine decides, LLM proposes).
 *
 * Design:
 * - loadProcedures(): Read all procedure records from procedures/
 * - matchProcedures(): Find similar procedures by instrument/context
 * - calculateConfidence(): Score match quality (0-1)
 * - getRecommendation(): Suggest action based on match results
 *
 * R9: UNKNOWN = no procedures exist, not "can't decide".
 * R10: All matching is deterministic, no LLM inference.
 */
import { readFileSync, existsSync, readdirSync } from "node:fs";
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
  };
}

/** Match result with confidence score. */
export interface MatchResult {
  procedure: Procedure;
  confidence: number;
  reason: string;
}

/** Recommendation based on match results. */
export interface Recommendation {
  action: "reuse" | "adapt" | "skip";
  confidence: number;
  reason: string;
  suggestedProcedure?: Procedure;
}

/**
 * Load all procedure records from the procedures directory.
 * Returns empty array if directory doesn't exist.
 */
export function loadProcedures(repoRoot: string): Procedure[] {
  const proceduresDir = join(repoRoot, "docs/spec_revision/learning_records/procedures");
  if (!existsSync(proceduresDir)) return [];

  try {
    const files = readdirSync(proceduresDir).filter((f: string) => f.endsWith(".json"));
    const procedures: Procedure[] = [];

    for (const file of files) {
      try {
        const content = readFileSync(join(proceduresDir, file), "utf-8");
        const proc = JSON.parse(content);
        if (proc.type === "procedure") {
          procedures.push(proc);
        }
      } catch {
        // Skip malformed files
      }
    }

    return procedures;
  } catch {
    return [];
  }
}

/**
 * Match current context against past procedures.
 * Returns matches sorted by confidence (highest first).
 */
export function matchProcedures(
  procedures: Procedure[],
  currentInstrument: string,
  currentHook: string,
  currentContext?: Record<string, any>,
): MatchResult[] {
  const matches: MatchResult[] = [];

  for (const proc of procedures) {
    const confidence = calculateConfidence(
      proc, currentInstrument, currentHook, currentContext
    );

    if (confidence > 0) {
      matches.push({
        procedure: proc,
        confidence,
        reason: getMatchReason(proc, currentInstrument, currentHook),
      });
    }
  }

  // Sort by confidence (highest first)
  return matches.sort((a, b) => b.confidence - a.confidence);
}

/**
 * Calculate confidence score for a procedure match (0-1).
 * 
 * Scoring:
 * - Same instrument: +0.4
 * - Same hook: +0.3
 * - Success: +0.2
 * - Recent (within 7 days): +0.1
 */
function calculateConfidence(
  proc: Procedure,
  currentInstrument: string,
  currentHook: string,
  currentContext?: Record<string, any>,
): number {
  let confidence = 0;

  // Instrument match (required)
  if (proc.source.instrument !== currentInstrument) {
    return 0;
  }
  confidence += 0.4;

  // Hook match
  if (proc.source.hook === currentHook) {
    confidence += 0.3;
  }

  // Success bonus
  if (proc.outcome.success) {
    confidence += 0.2;
  }

  // Recency bonus (within 7 days)
  if (proc.metadata.timestamp) {
    const procDate = new Date(proc.metadata.timestamp);
    const now = new Date();
    const daysSince = (now.getTime() - procDate.getTime()) / (1000 * 60 * 60 * 24);
    if (daysSince <= 7) {
      confidence += 0.1;
    }
  }

  return Math.min(confidence, 1);
}

/**
 * Get human-readable reason for the match.
 */
function getMatchReason(
  proc: Procedure,
  currentInstrument: string,
  currentHook: string,
): string {
  const reasons: string[] = [];

  if (proc.source.instrument === currentInstrument) {
    reasons.push("same instrument");
  }
  if (proc.source.hook === currentHook) {
    reasons.push("same hook");
  }
  if (proc.outcome.success) {
    reasons.push("past success");
  }

  return reasons.join(", ") || "context match";
}

/**
 * Get recommendation based on match results.
 * 
 * Rules:
 * - confidence >= 0.8: reuse (high confidence)
 * - confidence >= 0.6: adapt (medium confidence, may need adjustment)
 * - confidence < 0.6: skip (low confidence, don't reuse)
 */
export function getRecommendation(
  matches: MatchResult[],
): Recommendation {
  if (matches.length === 0) {
    return {
      action: "skip",
      confidence: 0,
      reason: "no matching procedures found",
    };
  }

  const best = matches[0];

  if (best.confidence >= 0.8) {
    return {
      action: "reuse",
      confidence: best.confidence,
      reason: `high confidence match: ${best.reason}`,
      suggestedProcedure: best.procedure,
    };
  }

  if (best.confidence >= 0.6) {
    return {
      action: "adapt",
      confidence: best.confidence,
      reason: `medium confidence match: ${best.reason}`,
      suggestedProcedure: best.procedure,
    };
  }

  return {
    action: "skip",
    confidence: best.confidence,
    reason: `low confidence match: ${best.reason}`,
  };
}
