/**
 * vsf-agent-vsl-gate — R15 enforcement for inter-agent communication.
 * design: docs/spec_revision/design-sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
 * CLASS-GATE instance (PLUGIN-CLASS-TAXONOMY-v1).
 *
 * MIGRATED TO SOCRATIC SHELL (2026-08-23): this plugin now uses the
 * centralized socratic shell factory. The decision logic is in gate.tree.vsm.
 *
 * Systemic correspondence (VSM):
 *   organ    S3 — control with veto: the ONLY mechanism in the boot that
 *            can block an action (the others are S3* advisory).
 *   capacity VARIETY REGULATION of the inter-agent channel (Ashby):
 *            the tmux parent↔child channel is high variety (free prose);
 *            the gate ATTENUATES it by demanding VSL — it reduces the
 *            variety of unverifiable messages to the variety of
 *            verifiable envelopes.
 *   channel  φ↓/φ↑ (blocks on send; veto).
 *   authority S5 (rmw3) delegates R15 enforcement to this S3; the gate
 *            does not decide policy, it executes the one declared in
 *            core_boot_primer.comms (PROTOCOL_VERSION 3).
 *
 * Behavior (RELOCATE-GATE-SPEC B1-B5):
 *   B1 block bash sending ≥120 chars to an agent tmux session WITHOUT a
 *      VSL marker (.vsm path, phi(), @vsm, directive, envelope, dispatch,
 *      guardrail_critico, φ).
 *   B2 allow short acks (<120) and control sequences.
 *   B3 allow ANY tmux use that is not a message to an agent session.
 *   B4 block with an actionable message naming the correct envelope path
 *      pattern.
 *   B5 NEVER block outside tool.execute.before of bash.
 */
import type { Plugin } from "@opencode-ai/plugin";
import { socraticShell } from "../support/vsf-socratic-shell";
import { logActivation } from "../../shared/log-activation";

/** Envelope / VSL markers that legitimize a message body. (B1) */
const VSL_MARKER =
  /\.vsm\b|phi\s*\(|@vsm|directive|envelope|dispatch|guardrail_critico|\bφ\b|φ(↑|↓)/i;

/** Control keys / short acks that must never be blocked. (B2) */
const CONTROL_ONLY =
  /^Enter$|^C-c$|^C-d$|^Escape$|^\^C$|^\^D$|^ok$|^done$|^ack$/i;

/** A tmux send-keys carrying a message body to a named session. */
const SEND_KEYS =
  /tmux\s+send-keys\s+-t\s+([A-Za-z0-9_.-]+)\s+(['"])(.*?)\2/;

/** Prose threshold — below this we assume ack/telegraphic. (B1) */
const PROSE_THRESHOLD = 120;

/**
 * Decide whether a bash command is a blocked R15 violation.
 * Pure function — no I/O — so the acceptance tests (checks/vsl-gate-valid)
 * can run it directly against fixtures (RELOCATE-GATE-SPEC A1-A4).
 *
 * NOT exported (M7 fix 2026-08-15): opencode 1.18.18 calls every exported
 * function of a plugin module as a factory candidate, passing the
 * PluginInput (object). An exported evaluateCommand is invoked spuriously
 * at load time, throws on cmd.match, and leaves the plugin unregistered
 * (gate R15 silently off — see RECTIF-PLUGIN-SANDBOX-AUDIT). The decision
 * logic lives here; checks/vsl-gate-valid validates it via mirror JS.
 *
 * @returns {string | null} block message when the command violates R15,
 *          null when it is allowed.
 */
function evaluateCommand(cmd: string): string | null {
  const m = cmd.match(SEND_KEYS);
  if (!m) return null; // B3: not a tmux message to an agent session

  const body = m[3].trim();
  if (body.length < PROSE_THRESHOLD) return null; // B2: short ack
  if (CONTROL_ONLY.test(body)) return null; // B2: control sequence
  if (VSL_MARKER.test(body)) return null; // B1: VSL-formatted

  // B4: actionable block naming the correct envelope pattern.
  return (
    `R15 BLOCK: inter-agent message is prose, not VSL. ` +
    `Message to session "${m[1]}" (${body.length} chars) has no VSL ` +
    `marker (.vsm envelope path, phi() block, @vsm, directive, ` +
    `guardrail_critico). Create the dispatch envelope first, e.g. ` +
    `child/docs/deploy/YYYY-MM-DD_parent_dispatch_<topic>.vsm (parent->` +
    `child) or docs/deploy/YYYY-MM-DD_ds_dispatch_<topic>.vsm (S3->S1), ` +
    `then send only: "phi([O]@S3 -> [S]@S1, directive): read <envelope path>".`
  );
}

/**
 * CLASS-GATE instance using the socratic shell.
 * The tree gate.tree.vsm defines the decision logic.
 */
export const AgentVSLGate: Plugin = socraticShell({
  classId: "GATE",
  treeRel: ".opencode/plugins/support/trees/gate.tree.vsm",
  hook: "tool.execute.before",
  context: (input: any, output: any) => {
    // B5: only evaluate bash commands
    if (input.tool !== "bash") return { skip: true };
    
    const cmd: string = String(output.args?.command ?? "");
    const block = evaluateCommand(cmd);
    
    // Build context for the socratic tree
    return {
      command: cmd,
      is_tmux_send: SEND_KEYS.test(cmd),
      has_vsl_marker: VSL_MARKER.test(cmd),
      is_short_ack: cmd.length < PROSE_THRESHOLD || CONTROL_ONLY.test(cmd),
      r15_violation: block !== null,
      block_message: block,
    };
  },
  act: async (decision, input, output, repoRoot) => {
    // If the tree says FAIL (r15_violation), block the command
    if (decision.truth === "FALSE" && decision.home === "fail") {
      const block = evaluateCommand(String(output.args?.command ?? ""));
      if (block) {
        // Log the activation
        await logActivation(
          repoRoot, "vsf-agent-vsl-gate", "tool.execute.before",
          "R15 block", "error", `blocked ${block.length} chars prose`
        ).catch(() => {});
        
        // Block the command
        throw new Error(block);
      }
    }
    
    return { result: "pass", detail: "R15 check passed" };
  },
});

export default AgentVSLGate;
