/**
 * test-patch.ts — TEST FILE for patch detection.
 * This is a test file to verify patch detection works.
 */
import type { Plugin } from "@opencode-ai/plugin"

export const TestPatch: Plugin = () => {
  return {
    "tool.execute.after": async (input: any) => {
      if (input.tool !== "write") return
      console.log("Patch detection test")
    },
  }
}

export default TestPatch
// Added line 1
// Added line 2
