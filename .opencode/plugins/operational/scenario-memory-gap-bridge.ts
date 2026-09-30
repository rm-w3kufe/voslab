/**
 * scenario-memory-gap-bridge.ts — Bridge between scenario-memory and gap-resolver.
 *
 * CC-4 (CYCLE-CLOSE-001): the old loader read docs/spec_revision/learning_records/
 * procedures/ — EMPTY since the TS writer was removed 2026-09-24 (dead store;
 * FND-GAP-BRIDGE-STALE-01) → every query early-returned [] and gap suggestions
 * were never evaluated. Now both consumers (this bridge and the idle handler)
 * delegate to the canonical matcher scripts/vsl/tools/match_procedure.py,
 * which reads the LIVE vsf_rsi scenario store. Single scoring source (GAP-19),
 * deterministic (R10): same payload → byte-identical suggestions.
 */
import { execFileSync } from "node:child_process";
import { findScript } from "../../shared/find-plugin-script";

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

const MATCHER_REL = "scripts/vsl/tools/match_procedure.py";

/**
 * Query scenario-memory (canonical matcher) for gap resolution suggestions.
 * Fail-soft: matcher missing or failing ⇒ [] (same outward behavior as the
 * old empty-store path — never breaks the gap handler).
 */
export function queryScenarioMemoryForGap(
  gapContext: GapContext,
  repoRoot: string,
): GapSuggestion[] {
  const matcher = findScript(repoRoot || process.cwd(), MATCHER_REL);
  if (!matcher) return [];

  const input = JSON.stringify({
    instrument: gapContext.gapType || "unknown",
    hook: gapContext.trigger || "gap-resolution",
    context: { file_path: gapContext.filePath || "" },
    repoRoot,
  });

  try {
    const stdout = execFileSync(
      "python3",
      [matcher, "match-procedure", "--input", input],
      { encoding: "utf-8", maxBuffer: 4 * 1024 * 1024, timeout: 30000 },
    );
    const result = JSON.parse(stdout);
    const matches: GapSuggestion[] = Array.isArray(result?.matches)
      ? result.matches.filter(
          (m: any) =>
            m &&
            typeof m.procedureId === "string" &&
            typeof m.confidence === "number" &&
            typeof m.suggestion === "string",
        )
      : [];
    // Old contract: return every scored candidate (old scorer's floor was
    // 0.4); the gap handler only acts on suggestions[0] with confidence
    // ≥ 0.8, so outward behavior is identical. Top-5 by confidence.
    return matches.sort((a, b) => b.confidence - a.confidence);
  } catch {
    return [];
  }
}

/**
 * Check if a gap has been resolved by scenario-memory.
 */
export function isGapResolvedByScenarioMemory(
  gapId: string,
  repoRoot: string,
): boolean {
  const suggestions = queryScenarioMemoryForGap(
    { gapId, gapType: "gap-resolution", trigger: "gap-resolution" },
    repoRoot,
  );
  return suggestions.some((s) => s.confidence >= 0.8);
}
