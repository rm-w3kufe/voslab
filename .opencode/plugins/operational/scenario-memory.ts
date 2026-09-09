/**
 * scenario-memory.ts — Scenario Memory Phase 3: handler with adaptation.
 *
 * Runs on session.idle to:
 * 1. Match current context against past procedures (Phase 2)
 * 2. Evaluate if adaptation is needed (Phase 3)
 * 3. Generate adapted procedures when needed (Phase 3)
 * 4. Track confidence over time (Phase 3)
 *
 * Design:
 * - Loads procedures from learning_records/procedures/
 * - Matches current context using matching.ts
 * - Evaluates adaptation using adaptation.tree.vsm (deterministic, R10)
 * - Generates new procedures via procedure-generator.ts
 * - Tracks confidence via confidence-tracker.ts
 * - Logs all actions for observability
 *
 * R10: Engine decides with structural evidence, LLM proposes.
 * R9: UNKNOWN = no procedures exist, not "can't decide".
 * R16: Policy declares (tree), instrument interprets (handler).
 * R17: SAFEGUARD — max 3 adaptations per procedure (prevent infinite loops).
 */
import { logActivation } from "../../shared/log-activation";
import { loadProcedures, matchProcedures, getRecommendation } from "../../shared/matching";
import { shouldAdapt } from "../../shared/confidence-tracker";
import { generateProcedure, validateProcedure, saveProcedure, loadProcedure } from "../../shared/procedure-generator";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname, join } from "node:path";
import { findScript } from "../../shared/find-plugin-script";

const execFileP = promisify(execFile);
const ENGINE_REL = "scripts/vsl/classifier/socratic_engine.py";
const MATCH_TREE_REL = ".opencode/plugins/support/trees/procedure-match.tree.vsm";
const ADAPT_TREE_REL = ".opencode/plugins/support/trees/adaptation.tree.vsm";

/** Handler interface for event-router registration. */
export interface Handler {
  name: string;
  priority: number;
  events: string[];
  classify: (ctx: any) => Promise<boolean>;
  execute: (ctx: any) => Promise<{ result: string; detail?: string }>;
}

/**
 * Create the scenario-memory handler.
 * Matches and adapts procedures on session.idle.
 */
export function createScenarioMemoryHandler(): Handler {
  return {
    name: "scenario-memory",
    priority: 4, // After learning-cycle (1), before gap-resolution (5)
    events: ["session.idle"],

    classify: async (ctx) => {
      // Always run — matching/adaptation is idempotent and low-cost
      return true;
    },

    execute: async (ctx) => {
      const start = Date.now();
      const { repoRoot, directory } = ctx;

      // Load past procedures
      const procedures = loadProcedures(repoRoot);
      if (procedures.length === 0) {
        return {
          result: "skip",
          detail: "no procedures recorded yet",
        };
      }

      // Get current context (instrument, hook from session)
      const currentInstrument = ctx.instrument || "unknown";
      const currentHook = ctx.hook || "session.idle";
      const currentContext = ctx.context || {};

      // Match against past procedures (Phase 2)
      const matches = matchProcedures(
        procedures,
        currentInstrument,
        currentHook,
        currentContext,
      );

      // Get recommendation
      const recommendation = getRecommendation(matches);

      // Evaluate adaptation (Phase 3)
      let adaptationResult = null;
      let generatedProcedure = null;

      if (matches.length > 0 && recommendation.suggestedProcedure) {
        const bestMatch = matches[0];
        const outcomes = procedures
          .filter(p => p.source.instrument === currentInstrument)
          .map(p => ({ success: p.outcome.success, timestamp: p.metadata.timestamp }));

        // Check if adaptation is needed
        const adaptationRecommendation = shouldAdapt(
          bestMatch.procedure,
          outcomes,
        );

        if (adaptationRecommendation.should_adapt) {
          // Evaluate with adaptation tree (deterministic, R10)
          try {
            const ENGINE = findScript(directory || process.cwd(), ENGINE_REL);
            const TREE_ABS = ENGINE
              ? join(dirname(dirname(dirname(dirname(ENGINE)))), ADAPT_TREE_REL)
              : null;

            if (ENGINE && TREE_ABS) {
              const treeCtx = {
                procedure: bestMatch.procedure,
                outcomes,
                context_changed: currentContext !== bestMatch.procedure.context,
              };

              const { stdout } = await execFileP(
                "python3", [ENGINE, "eval-tree", TREE_ABS, "--context", JSON.stringify(treeCtx)],
                { env: { ...process.env }, maxBuffer: 10 * 1024 * 1024 }
              );
              adaptationResult = JSON.parse(stdout);

              // Generate adapted procedure if tree recommends adaptation
              if (adaptationResult.truth === "TRUE") {
                const adaptationLevel = adaptationResult.home?.includes("high")
                  ? "high"
                  : adaptationResult.home?.includes("medium")
                  ? "medium"
                  : "low";

                const generated = generateProcedure(
                  bestMatch.procedure,
                  adaptationLevel,
                  adaptationRecommendation.reason,
                );

                // Validate and save
                const validation = validateProcedure(generated.procedure);
                if (validation.valid) {
                  const saved = saveProcedure(repoRoot, generated.procedure);
                  if (saved) {
                    generatedProcedure = generated;
                  }
                } else {
                  console.error(`[SCENARIO-MEMORY] invalid procedure: ${validation.errors.join(", ")}`);
                }
              }
            }
          } catch (e: any) {
            console.error(`[SCENARIO-MEMORY] adaptation evaluation failed: ${e.message}`);
          }
        }
      }

      const durationMs = Date.now() - start;

      // Log the result
      const resultDetail = generatedProcedure
        ? `adapted: ${generatedProcedure.reason} (level: ${generatedProcedure.adaptation_level})`
        : `${recommendation.action}: ${recommendation.reason}`;

      await logActivation(
        repoRoot,
        "scenario-memory",
        "session.idle",
        `match ${matches.length} procedures → ${recommendation.action}`,
        generatedProcedure ? "adapted" : recommendation.action === "skip" ? "ok" : "recommendation",
        resultDetail,
        {
          success: recommendation.action !== "skip" || !!generatedProcedure,
          detail: resultDetail,
          durationMs,
          context: {
            procedures_count: procedures.length,
            matches_count: matches.length,
            recommendation: recommendation.action,
            confidence: recommendation.confidence,
            adaptation: adaptationResult?.truth,
            generated: !!generatedProcedure,
          },
        },
      );

      return {
        result: generatedProcedure ? "adapted" : recommendation.action === "skip" ? "ok" : "recommendation",
        detail: resultDetail,
      };
    },
  };
}

export default createScenarioMemoryHandler;
