/**
 * find-plugin-script — resolve a plugin script path relative to repo root.
 *
 * Used by plugins to find their bash/python scripts. The script lives at a
 * known relative path from the repo root; this function walks up from the
 * given directory until it finds the file.
 *
 * Pattern from learning-cycle-scan.ts, extracted as shared utility.
 */
import { resolve, dirname } from "node:path";
import { existsSync } from "node:fs";

/**
 * Find a script by walking up from `directory` until `relPath` is found.
 * @param directory - starting directory (usually process.cwd() or plugin directory)
 * @param relPath - relative path from repo root to the script
 * @returns absolute path to the script, or null if not found
 */
export function findScript(directory: string, relPath: string): string | null {
  let p = resolve(directory || process.cwd());
  for (let i = 0; i < 6; i++) {
    const candidate = resolve(p, relPath);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(p);
    if (parent === p) break;
    p = parent;
  }
  return null;
}
