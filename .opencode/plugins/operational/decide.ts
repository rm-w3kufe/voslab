/**
 * decide.ts — DECIDE class plugin for socratic engine.
 *
 * PURPOSE: Evaluate complex agent decisions before execution.
 * TRIGGER: agent.propose_decision (called by agent when making decisions)
 *
 * This plugin bridges the gap between agent reasoning and socratic evaluation.
 * When the agent proposes a decision, it calls this hook which:
 *   1. Builds context from the proposal
 *   2. Evaluates decide.tree.vsm
 *   3. Returns certified decision or rejection
 *   4. Logs for RSI learning
 *
 * CLASSES (PLUGIN-CLASS-TAXONOMY-v1):
 *   DECIDE — decision-time: "¿esta decisión es válida?" → tree decide.tree.vsm
 */
import { socraticShell } from "../support/vsf-socratic-shell";

export const DecideTree = socraticShell({
  classId: "DECIDE",
  treeRel: ".opencode/plugins/support/trees/decide.tree.vsm",
  hook: "tool.execute.after",
  
  context: (input: any, output: any, repoRoot: string) => {
    // Only trigger on bash commands that call decide
    const tool = input?.tool || "";
    const args = input?.args || {};
    
    if (tool !== "bash") return { skip: true };
    
    const command = args?.command || "";
    
    // Check if this is a decide command
    if (!command.includes("socratic-engine") || !command.includes("eval-tree")) {
      return { skip: true };
    }
    
    // Extract decision context from command
    // Format: socratic-engine eval-tree decide.tree.vsm --decision "..." --alternatives "..." --impact "..."
    const decisionMatch = command.match(/--decision\s+"([^"]+)"/);
    const alternativesMatch = command.match(/--alternatives\s+"([^"]+)"/);
    const impactMatch = command.match(/--impact\s+"([^"]+)"/);
    const reversibleMatch = command.match(/--reversible\s+(true|false)/);
    
    const decision = decisionMatch?.[1] || "unspecified decision";
    const alternatives = alternativesMatch?.[1]?.split(",") || [];
    const impact = impactMatch?.[1] || "unspecified";
    const reversible = reversibleMatch?.[1] || "true";
    
    return {
      type: "DECIDE",
      decision,
      alternatives: alternatives.length > 0 ? alternatives : ["no alternatives provided"],
      impact,
      reversible,
      repoRoot,
    };
  },
  
  act: async (decision: any, input: any, output: any, repoRoot: string) => {
    const truth = decision?.truth || "UNKNOWN";
    const certified = decision?.certified || false;
    const home = decision?.home || "unknown";
    
    // Log the decision evaluation
    console.error(`[DECIDE] Decision evaluated: truth=${truth}, certified=${certified}, home=${home}`);
    
    if (truth === "TRUE" && certified) {
      return { result: "certified", detail: `Decision approved: ${home}` };
    } else if (truth === "FALSE" && certified) {
      return { result: "rejected", detail: `Decision rejected: ${home}` };
    } else {
      return { result: "uncertain", detail: `Decision uncertain: ${home}` };
    }
  },
});

export default DecideTree;
