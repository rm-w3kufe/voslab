/**
 * confidence-tracker.ts — Scenario Memory Phase 3: confidence tracking module.
 *
 * Tracks confidence scores for procedures over time. Adjusts confidence
 * based on outcomes (success increases, failure decreases).
 *
 * Design:
 * - calculateConfidence(): Compute confidence from outcomes
 * - adjustConfidence(): Adjust based on new outcome
 * - getConfidenceLevel(): Classify confidence (high/medium/low)
 * - shouldAdapt(): Determine if adaptation is needed
 *
 * R10: All calculations are deterministic.
 * R17: SAFEGUARD — max 3 adaptations per procedure.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

/** Confidence record for a procedure. */
export interface ConfidenceRecord {
  procedureId: string;
  confidence: number;
  outcomes: {
    success: boolean;
    timestamp: string;
    context?: Record<string, any>;
  }[];
  adaptations_used: number;
  last_updated: string;
}

/** Confidence level classification. */
export type ConfidenceLevel = "high" | "medium" | "low" | "none";

/** Adaptation recommendation. */
export interface AdaptationRecommendation {
  should_adapt: boolean;
  level: ConfidenceLevel;
  reason: string;
  confidence: number;
  adaptations_remaining: number;
}

/**
 * Calculate confidence from outcomes.
 * 
 * Scoring:
 * - Base: 0.5
 * - Each success: +0.1 (max 1.0)
 * - Each failure: -0.15 (min 0.0)
 * - Recency bonus: +0.05 if last outcome within 7 days
 */
export function calculateConfidence(outcomes: { success: boolean; timestamp: string }[]): number {
  if (outcomes.length === 0) return 0.5;

  let confidence = 0.5;
  const now = new Date();

  for (const outcome of outcomes) {
    if (outcome.success) {
      confidence += 0.1;
    } else {
      confidence -= 0.15;
    }

    // Recency bonus
    const outcomeDate = new Date(outcome.timestamp);
    const daysSince = (now.getTime() - outcomeDate.getTime()) / (1000 * 60 * 60 * 24);
    if (daysSince <= 7) {
      confidence += 0.05;
    }
  }

  return Math.max(0, Math.min(1, confidence));
}

/**
 * Adjust confidence based on new outcome.
 */
export function adjustConfidence(
  currentConfidence: number,
  newOutcome: { success: boolean; timestamp: string },
): number {
  let adjustment = 0;

  if (newOutcome.success) {
    adjustment = 0.1;
  } else {
    adjustment = -0.15;
  }

  // Recency bonus
  const outcomeDate = new Date(newOutcome.timestamp);
  const now = new Date();
  const daysSince = (now.getTime() - outcomeDate.getTime()) / (1000 * 60 * 60 * 24);
  if (daysSince <= 7) {
    adjustment += 0.05;
  }

  return Math.max(0, Math.min(1, currentConfidence + adjustment));
}

/**
 * Get confidence level classification.
 */
export function getConfidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.8) return "high";
  if (confidence >= 0.6) return "medium";
  if (confidence >= 0.3) return "low";
  return "none";
}

/**
 * Determine if adaptation is needed based on confidence and outcomes.
 */
export function shouldAdapt(
  procedure: { metadata?: { adaptations_used?: number } },
  outcomes: { success: boolean; timestamp: string }[],
): AdaptationRecommendation {
  const adaptations_used = procedure.metadata?.adaptations_used || 0;
  const max_adaptations = 3; // R17 safeguard
  const adaptations_remaining = max_adaptations - adaptations_used;

  if (adaptations_remaining <= 0) {
    return {
      should_adapt: false,
      level: "none",
      reason: "max adaptations reached (R17 safeguard)",
      confidence: 0,
      adaptations_remaining: 0,
    };
  }

  const confidence = calculateConfidence(outcomes);
  const level = getConfidenceLevel(confidence);

  // Calculate failure rate
  const total = outcomes.length;
  const failures = outcomes.filter(o => !o.success).length;
  const failure_rate = total > 0 ? failures / total : 0;

  // Determine if adaptation is needed
  let should_adapt = false;
  let reason = "";

  if (failure_rate >= 0.5 && total >= 3) {
    should_adapt = true;
    reason = `high adaptation: ${(failure_rate * 100).toFixed(0)}% failure rate`;
  } else if (failure_rate >= 0.2 && total >= 2) {
    should_adapt = true;
    reason = `medium adaptation: ${(failure_rate * 100).toFixed(0)}% failure rate`;
  } else if (confidence >= 0.8 && total >= 2) {
    // High confidence but may need minor adjustment
    should_adapt = true;
    reason = `low adaptation: high confidence (${(confidence * 100).toFixed(0)}%) with context change`;
  }

  return {
    should_adapt,
    level,
    reason,
    confidence,
    adaptations_remaining,
  };
}

/**
 * Load confidence records from disk.
 */
export function loadConfidenceRecords(repoRoot: string): ConfidenceRecord[] {
  const dir = join(repoRoot, "docs/spec_revision/learning_records/confidence");
  if (!existsSync(dir)) return [];

  try {
    const { readdirSync } = require("node:fs");
    const files = readdirSync(dir).filter((f: string) => f.endsWith(".json"));
    const records: ConfidenceRecord[] = [];

    for (const file of files) {
      try {
        const content = readFileSync(join(dir, file), "utf-8");
        records.push(JSON.parse(content));
      } catch {
        // Skip malformed files
      }
    }

    return records;
  } catch {
    return [];
  }
}

/**
 * Save confidence record to disk.
 */
export function saveConfidenceRecord(repoRoot: string, record: ConfidenceRecord): void {
  const dir = join(repoRoot, "docs/spec_revision/learning_records/confidence");
  mkdirSync(dir, { recursive: true });
  
  const filename = `${record.procedureId}.json`;
  writeFileSync(join(dir, filename), JSON.stringify(record, null, 2));
}
