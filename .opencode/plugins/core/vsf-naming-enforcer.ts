/**
 * vsf-naming-enforcer — BLOCKING plugin
 *
 * CLAIM: enforces naming conventions and policy compliance for .vsm files:
 *   - lowercase filenames (no uppercase)
 *   - no double hyphens
 *   - no spaces in filenames
 *   - valid @status (active/ratified/proposed/template/conjecture/archived)
 *   - valid @vsm version format
 *   - header/footer match
 *   - no literal paths in system/ bodies (migration compliance)
 *
 * design: docs/spec_revision/design-sources/structural-integrity-checks-v1/structural_integrity_checks.vsm
 *
 * R16: this plugin implements structural naming rules and policy compliance.
 * R17: BLOCKING — throws on violation.
 *
 * Uses tool.execute.after to detect write/edit operations on .vsm files.
 */
import type { Plugin } from "@opencode-ai/plugin";
import * as path from "node:path";
import { execFileSync } from "node:child_process";

const BLOCKED_EXTENSIONS = [".vsm"];

const VALID_STATUSES = [
  "active",
  "ratified",
  "proposed",
  "template",
  "conjecture",
  "archived",
];

const NamingEnforcer: Plugin = async ({ directory }) => {
  return {
    "tool.execute.after": async (input: any, output: any) => {
      if (input.tool !== "write" && input.tool !== "edit") return;
      const filePath = input.args?.file_path ?? input.args?.filePath ?? "";
      if (!filePath) return;

      const ext = path.extname(filePath);
      const basename = path.basename(filePath);

      // Only check .vsm files
      if (!BLOCKED_EXTENSIONS.includes(ext)) return;

      // Skip special files (covenant has its own seal)
      if (basename === "covenant.vsm") return;

      // Skip standard uppercase files (VSF convention)
      const UPPERCASE_EXCEPTIONS = ["TASKS.vsm", "HANDOFF.vsm.md", "RULES.md"];
      if (UPPERCASE_EXCEPTIONS.includes(basename)) return;

      // Check 1: no uppercase letters
      if (/[A-Z]/.test(basename)) {
        throw new Error(
          `BLOCKED: filename must be lowercase: ${basename}\n` +
            `Rename to: ${basename.toLowerCase()}`
        );
      }

      // Check 2: no double hyphens
      if (basename.includes("--")) {
        throw new Error(
          `BLOCKED: filename contains double hyphens: ${basename}\n` +
            `Use single hyphens instead`
        );
      }

      // Check 3: no spaces
      if (basename.includes(" ")) {
        throw new Error(
          `BLOCKED: filename contains spaces: ${basename}\n` +
            `Use hyphens instead`
        );
      }

      // Check 4: valid @status (if file has content)
      const content = output?.content ?? "";
      if (content && typeof content === "string") {
        const statusMatch = content.match(/@status\s+([a-z_]+)/);
        if (statusMatch) {
          const status = statusMatch[1];
          if (!VALID_STATUSES.includes(status)) {
            throw new Error(
              `BLOCKED: invalid @status '${status}' in ${basename}\n` +
                `Valid statuses: ${VALID_STATUSES.join(", ")}`
            );
          }
        }

        // Check 5: valid @vsm version format
        const versionMatch = content.match(/@vsm\s+([\d.]+)/);
        if (versionMatch) {
          const version = versionMatch[1];
          if (!/^\d+\.\d+$/.test(version)) {
            throw new Error(
              `BLOCKED: invalid @vsm format '${version}' in ${basename}\n` +
                `Valid format: MAJOR.MINOR (e.g., 1.2)`
            );
          }
        }

        // Check 6: header/footer match
        const lines = content.trim().split("\n");
        if (lines.length >= 2) {
          const header = lines[0].trim();
          const footer = lines[lines.length - 1].trim();
          
          const headerMatch = header.match(/⟦\s*(\w+)\s*\|/);
          const footerMatch = footer.match(/⟦\s*\/(\w+)\s*\|/);
          
          if (headerMatch && footerMatch) {
            if (headerMatch[1] !== footerMatch[1]) {
              throw new Error(
                `BLOCKED: header/footer mismatch in ${basename}\n` +
                  `Header: ${headerMatch[1]}, Footer: ${footerMatch[1]}`
              );
            }
          }
        }

        // Check 7: no literal paths in bodies (migration compliance)
        const literalPathMatch = content.match(/docs\/spec_revision\/\S+\.vsm/);
        if (literalPathMatch) {
          // Check if it's in a comment or description
          const lineNum = content.substring(0, content.indexOf(literalPathMatch[0])).split("\n").length;
          const line = lines[lineNum - 1] || "";
          
          if (!line.trim().startsWith("//") && !line.includes("desc=") && !line.includes("result:") && !line.includes("location:")) {
            throw new Error(
              `BLOCKED: literal path in body in ${basename}\n` +
                `Found: ${literalPathMatch[0]}\n` +
                `Use @var instead (see migration_policy.vsm)`
            );
          }
        }
      }

      // Check 8: run verification scripts
      try {
        const root = execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf-8" }).trim();
        const script = `${root}/scripts/vsl/validator/check.py`;
        
        // Run check.py on the file (use execFileSync to prevent shell injection)
        execFileSync("python3", [script, filePath], { 
          encoding: "utf-8",
          timeout: 30000 
        });
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

export default NamingEnforcer;
