/**
 * scenario-memory.ts — Scenario Memory handler.
 *
 * GAP-19 consolidation: TS is a thin dispatcher. All matching/adaptation
 * logic lives in Python (scenario_memory.py). TS shells out to the
 * socratic engine CLI for evaluation. No duplicate logic.
 *
 * R10: Engine decides with structural evidence, LLM proposes.
 * R16: Policy declares (tree), instrument interprets (handler).
 */
import { logActivation } from "../../shared/log-activation";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname, join } from "node:path";
import { findScript } from "../../shared/find-plugin-script";
import type { Handler, HandlerResult } from "./vsf-event-router";

const execFileP = promisify(execFile);
// CC-4 (CYCLE-CLOSE-001): the old scripts/vsl/classifier/socratic_engine.py
// never existed in-repo → every idle hit the "engine not found" early-return
// and suggestions were NEVER evaluated (FND-SCENARIO-ENGINE-DEAD-01).
// Canonical matcher: same contract (match-procedure --input <json>), reads
// the LIVE vsf_rsi scenario store (single scoring source, R10 deterministic).
const ENGINE_REL = "scripts/vsl/tools/match_procedure.py";

/**
 * Create the scenario-memory handler.
 * Matches and adapts procedures on session.idle.
 *
 * GAP-19 consolidation: TS is a thin dispatcher. All matching/adaptation
 * logic lives in Python (scenario_memory.py). TS shells out to Python
 * for evaluation. No duplicate logic.
 */
export function createScenarioMemoryHandler(): Handler {
  return {
    id: "scenario-memory",
    priority: 4, // After learning-cycle (1), before gap-resolution (5)
    events: ["session.idle"],

    classify: async (ctx) => {
      // Always run — matching/adaptation is idempotent and low-cost
      return true;
    },

    execute: async (ctx): Promise<HandlerResult> => {
      const start = Date.now();
      const { repoRoot, directory } = ctx;

      // Delegate to Python: scenario_memory.py match + socratic evaluation
      // Python is the canonical source for matching/adaptation logic.
      try {
        const ENGINE = findScript(directory || process.cwd(), ENGINE_REL);
        if (!ENGINE) {
          return { result: "skip", durationMs: Date.now() - start, detail: "engine not found" };
        }

        const currentInstrument = ctx.instrument || "unknown";
        const currentHook = ctx.hook || "session.idle";
        const payload = JSON.stringify({
          instrument: currentInstrument,
          hook: currentHook,
          context: ctx.context || {},
          repoRoot,
        });

        const { stdout } = await execFileP(
          "python3", [ENGINE, "match-procedure", "--input", payload],
          { env: { ...process.env }, maxBuffer: 10 * 1024 * 1024 }
        );

        const result = JSON.parse(stdout);
        const durationMs = Date.now() - start;

        await logActivation(
          repoRoot,
          "scenario-memory",
          "session.idle",
          `match ${result.matches_count || 0} procedures → ${result.action || "skip"}`,
          result.action === "skip" ? "ok" : "recommendation",
          result.detail || `${result.action}: ${result.reason || "no detail"}`,
          {
            success: result.action !== "skip",
            detail: result.detail || result.reason,
            durationMs,
            context: {
              instrument: currentInstrument,
              hook: currentHook,
              matches_count: result.matches_count || 0,
              recommendation: result.action,
              confidence: result.confidence || 0,
            },
          },
        );

        return {
          result: result.action === "skip" ? "ok" : "ok",
          durationMs,
          detail: result.detail || result.reason,
        };
      } catch (e: any) {
        const durationMs = Date.now() - start;
        await logActivation(
          repoRoot, "scenario-memory", "session.idle",
          "error", "evaluation_failed", e?.message?.slice(0, 200) || "unknown error",
        );
        return { result: "error", durationMs, detail: e?.message?.slice(0, 200) };
      }
    },
  };
}

export default createScenarioMemoryHandler;
