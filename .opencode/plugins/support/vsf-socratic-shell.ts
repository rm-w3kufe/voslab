/**
 * vsf-socratic-shell — the SINGLE plugin shell (PLUGIN-CLASS-TAXONOMY-v1).
 * design: docs/design/sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
 *
 * WHY (2026-08-18, fase a — rmw3 S5 "ordenar todo lo que es plugins y scripts"):
 * every plugin was an implicit decision tree duplicated in TS. This shell
 * makes the tree DECLARED policy (VSL in .opencode/plugins/support/trees/) and the
 * TS a thin interpreter: resolve the tree of its class, evaluate it with
 * socratic_engine.py (eval-tree CLI), act on the certified answer.
 *
 * R10: the engine decides with structural evidence (certified=True); the
 * LLM may propose, never certify. R9: UNKNOWN → '?' visible, never silent
 * else_home. R16: policy declares, instrument interprets.
 *
 * SCENARIO-MEMORY-FASE-1 (2026-08-27): outcome post-evaluation.
 * After act() completes, the shell emits an outcome record with success,
 * duration, and context for procedural memory (learning_records/procedures/).
 *
 * CLASSES (PLUGIN-CLASS-TAXONOMY-v1):
 *   CLASSIFY — write-time: "¿este documento va aquí?" → tree classify.tree.vsm
 *   GATE     — commit-time (veto): tree gate.tree.vsm (future)
 *   CYCLE    — session.idle: tree cycle.tree.vsm (future)
 *   REMIND   — session.start: tree remind.tree.vsm (future)
 *   OBSERVE  — log-activation helper (not a registered plugin)
 *
 * A plugin becomes: {class, trigger, tree, action}. Register instances in
 * opencode.json; the shell reads the tree for the class and evaluates.
 */
import type { Plugin } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname } from "node:path";
import { findScript } from "../../shared/find-plugin-script";
import { logActivation, type ActivationOutcome } from "../../shared/log-activation";

const execFileP = promisify(execFile);
// VSF wrapper: loads VSF predicates then evaluates (socratic-engine stays agnostic)
const ENGINE_REL = "scripts/vsl/classifier/eval_tree_vsf.py";

/** A registered instance: class + trigger + tree file + action on result. */
export interface SocraticInstance {
  classId: string;          // CLASSIFY | GATE | CYCLE | REMIND
  treeRel: string;          // repo-relative tree file (VSL)
  hook: string;             // e.g. "tool.execute.after"
  /** Build the evaluation context from the hook payload. */
  context: (input: any, output: any, repoRoot: string) => Record<string, any>;
  /** Act on the decision; return {result, detail} for the activation log. */
  act: (decision: any, input: any, output: any, repoRoot: string) => Promise<{result: string, detail?: string}>;
}

/**
 * Create a plugin instance from a class declaration. One shell, N instances.
 * Resolves the tree, evaluates with the engine, logs activation (S5 directiva:
 * observa y mejora — sin registro no hay trazabilidad).
 */
export function socraticShell(inst: SocraticInstance): Plugin {
  return async ({ directory }) => {
    // resolve engine script by walking up from the session directory
    const ENGINE = findScript(directory || process.cwd(), ENGINE_REL);
    const TREE = ENGINE ? dirname(dirname(dirname(dirname(ENGINE)))) + "/" + inst.treeRel : null;
    const repoRootDir = ENGINE
      ? dirname(dirname(dirname(dirname(ENGINE))))   // <root>/scripts/vsl/classifier/engine → 4 up
      : null;
    // resolve tree via repo root (tree lives in .opencode/plugins/support/trees/)
    const TREE_ABS = repoRootDir ? `${repoRootDir}/${inst.treeRel}` : null;

    return {
      [inst.hook]: async (input: any, output: any) => {
        if (!ENGINE || !TREE_ABS) return; // no checkout — nothing to decide
        let ctx: Record<string, any> = {};
        try { ctx = inst.context(input, output, repoRootDir!); } catch { ctx = {}; }
        // skip: the instance declared this hook payload out of scope (e.g.
        // tool.execute.after fires for EVERY tool — write, edit, read, bash,
        // grep… the CLASSIFY instance must only act on .vsm writes, not on
        // reads of .vsm files). Skip BEFORE evaluating: no noise, no false
        // "uncertified" reports (CLASSIFY-READ-TOOL-NOISE, 2026-08-19).
        if (ctx.skip) return;
        const docType = String(ctx.type || "");
        // evaluate the class tree with the engine (deterministic, certified)
        const evalStart = Date.now();
        try {
          const { stdout } = await execFileP(
            "python3", [ENGINE, TREE_ABS, "--doc-type", docType],
            { env: { ...process.env }, maxBuffer: 10 * 1024 * 1024 });
          const decision = JSON.parse(stdout);
          const actStart = Date.now();
          const { result, detail } = await inst.act(decision, input, output, repoRootDir!);
          const durationMs = Date.now() - actStart;
          // Scenario Memory: emit outcome post-evaluation
          const outcome: ActivationOutcome = {
            success: result === "ok" || result === "certified",
            detail: detail,
            durationMs,
            context: {
              treeRel: inst.treeRel,
              docType,
              home: decision.home,
              truth: decision.truth,
              certified: decision.certified,
              unknown: decision.unknown,
            },
          };
          await logActivation(
            repoRootDir!, inst.classId, inst.hook,
            `${docType} → ${decision.home}`, result, detail || "", outcome);
        } catch (e: any) {
          const msg = String(e?.stderr || e?.message || e).trimEnd();
          const durationMs = Date.now() - evalStart;
          console.error(`[SOCRATIC ${inst.classId}] ${msg}`);
          // Scenario Memory: emit outcome on failure too
          const outcome: ActivationOutcome = {
            success: false,
            detail: msg.slice(0, 500),
            durationMs,
            context: {
              treeRel: inst.treeRel,
              docType,
              error: true,
            },
          };
          await logActivation(
            repoRootDir!, inst.classId, inst.hook,
            `eval-tree ${docType}`, "fail", msg.slice(0, 500), outcome);
        }
      },
    };
  };
}

export default socraticShell;
