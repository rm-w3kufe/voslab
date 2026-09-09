/**
 * vsf-policy-enforcer — BLOCKING plugin
 *
 * CLAIM: enforces policy compliance for .vsm documents:
 *   - Binding completeness (all @var have bindings)
 *   - Status transitions (valid state changes)
 *   - Migration compliance (no literal paths)
 *   - Version increment (breaking changes have bump)
 *
 * design: docs/vos_system_layer/specifications/binding_policy.vsm
 *         docs/vos_system_layer/specifications/status_policy.vsm
 *         docs/vos_system_layer/specifications/migration_policy.vsm
 *         docs/vos_system_layer/specifications/versioning_policy.vsm
 *
 * R16: this plugin implements policy compliance rules.
 * R17: BLOCKING — throws on violation.
 *
 * SCOPE EXPANDED (PROPAGATION-2026-08-31): enforces on ALL .vsm files,
 * not just system/ docs.
 *
 * Uses tool.execute.after to detect write/edit operations on .vsm files.
 */
import type { Plugin } from "@opencode-ai/plugin";
import * as path from "node:path";
import { execFileSync } from "node:child_process";

const PolicyEnforcer: Plugin = async ({ directory }) => {
  return {
    "tool.execute.after": async (input: any, output: any) => {
      if (input.tool !== "write" && input.tool !== "edit") return;
      const filePath = input.args?.file_path ?? input.args?.filePath ?? "";
      if (!filePath) return;

      const basename = path.basename(filePath);
      const content = output?.content ?? "";

      if (!content || typeof content !== "string") return;

      // Run all verification scripts
      try {
        const root = execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf-8" }).trim();
        
        // Run check.py which includes all verification scripts (use execFileSync to prevent shell injection)
        const script = `${root}/scripts/vsl/validator/check.py`;
        execFileSync("python3", [script, filePath], { 
          encoding: "utf-8",
          timeout: 30000 
        });
        
        console.error(`✓ Policy compliance: ${basename}`);
      } catch (error: any) {
        // check.py throws on errors, so we catch and re-throw
        if (error.status !== 0) {
          throw new Error(
            `BLOCKED: policy compliance check failed for ${basename}\n` +
              `Run: python3 scripts/vsl/validator/check.py ${filePath}\n` +
              `Error: ${error.message}`
          );
        }
      }
    },
  };
};

export default PolicyEnforcer;
