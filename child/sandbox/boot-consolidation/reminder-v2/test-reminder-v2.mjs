// test-reminder-v2.mjs — child-session TEST HARNESS for vsf-onboard-reminder.v2.ts
//
// WHY A HARNESS (method, per dispatch "documenta el método"):
//   opencode run (non-interactive) does NOT emit `session.created` (verified
//   empirically: a CLEAN-V1-TEST session has only user+assistant messages, no
//   injected reminder). The plugin's branch logic lives in that handler, which
//   the interactive TUI runtime emits. This harness loads the SAME plugin
//   module (child/sandbox/.../vsf-onboard-reminder.v2.ts) with the SAME SDK
//   contract (@opencode-ai/plugin 1.18.16 — the version child node_modules
//   provides, the one opencode uses), supplies a mock client that records the
//   injected prompt, and emits the real `session.created` event with the two
//   message-history states the plugin discriminates on (D1):
//     - msgs.data.length === 0  → CLEAN branch   (manifest citation, D2)
//     - msgs.data.length  >  0  → RESUMED branch (focus→cross-check→RECALL, D3)
//   Evidence = the exact prompt text the plugin injects per branch.
//
// This is a unit-level test of the plugin code against the runtime event
// contract — the same discrimination the TUI would perform. It does NOT
// modify production: the plugin under test is the sandbox copy; the global
// symlink is untouched (verified after).

import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pluginTs = resolve(__dirname, "vsf-onboard-reminder.v2.ts");
const sandboxDir = resolve(__dirname, "..", "..", ".."); // → child/

// ── transpile the sandbox .ts to a temp .mjs so node (this box has no TS
//    transform) can import the EXACT source under test ──
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
const tmpDir = mkdtempSync(join(tmpdir(), "reminder-v2-"));
const tmpTs = join(tmpDir, "vsf-onboard-reminder.v2.ts");
const tmpJs = join(tmpDir, "vsf-onboard-reminder.v2.js");
writeFileSync(tmpTs, readFileSync(pluginTs, "utf-8"));
// tsc may be cached from a prior `npx -p typescript@5`; prefer a cache that
// actually bundles typescript@5 (the deprecated `tsc` package also drops a
// .bin/tsc that cannot compile). Else fall back to npx.
const glob = (await import("node:fs")).readdirSync(
  join(homedir(), ".npm", "_npx"), { withFileTypes: true });
let tscBin = null;
for (const e of glob) {
  if (!e.isDirectory()) continue;
  const pkg = join(homedir(), ".npm", "_npx", e.name,
    "node_modules", "typescript", "package.json");
  if (!existsSync(pkg)) continue;
  const ver = JSON.parse(readFileSync(pkg, "utf-8")).version ?? "";
  if (!ver.startsWith("5.")) continue;
  const cand = join(homedir(), ".npm", "_npx", e.name,
    "node_modules", ".bin", "tsc");
  if (existsSync(cand)) { tscBin = cand; break; }
}
const tscCmd = tscBin ?? "npx";
const tscArgs = tscBin
  ? [tmpTs, "--outDir", tmpDir, "--module", "esnext", "--target", "es2022",
     "--moduleResolution", "bundler", "--skipLibCheck", "--noEmitOnError",
     "false"]
  : ["-y", "-p", "typescript@5", "tsc", tmpTs, "--outDir", tmpDir,
     "--module", "esnext", "--target", "es2022", "--moduleResolution",
     "bundler", "--skipLibCheck", "--noEmitOnError", "false"];
let tscStderr = "";
try {
  execFileSync(tscCmd, tscArgs, { stdio: ["ignore", "ignore", "pipe"],
    timeout: 120000, encoding: "utf-8" });
} catch (e) {
  tscStderr = e?.stderr?.toString?.() ?? String(e);
  if (!existsSync(tmpJs)) {
    console.error("tsc failed to emit " + tmpJs + "\n" + tscStderr.slice(0, 1200));
    process.exit(2);
  }
  // tsc emitted despite type errors (noEmitOnError false) — proceed.
}
const pluginPath = tmpJs;
process.on("exit", () => rmSync(tmpDir, { recursive: true, force: true }));

// ── mock client: records every prompt injection, answers messages() ──
function makeClient(messageCount) {
  const injected = [];
  const client = {
    session: {
      messages: async () => ({
        data: messageCount > 0
          ? Array.from({ length: messageCount }, (_, i) => ({ id: `msg_${i}` }))
          : [],
      }),
      prompt: async ({ path, body }) => {
        injected.push({ sessionID: path?.id, prompt: body?.prompt });
      },
    },
  };
  return { client, injected };
}

async function loadPlugin() {
  // The sandbox plugin is TypeScript with a type-only import of
  // "@opencode-ai/plugin"; node --experimental-strip-types removes it.
  const mod = await import(pluginPath);
  const factory = mod.OnboardReminder || mod.default;
  if (typeof factory !== "function") {
    throw new Error("plugin factory not found in " + pluginPath);
  }
  return factory;
}

const factory = await loadPlugin();

function summarize(prompt) {
  if (!prompt) return "∅";
  // ORDER MATTERS: the corrected fallback also names boot_manifest.vsm, so
  // the citation check would swallow it. The fallback's unique marker is
  // "all SIX boot docs" (v1 full text); check it FIRST.
  if (prompt.includes("all SIX boot docs")) return "CLEAN-fallback (full text)";
  if (prompt.includes("boot_manifest.vsm")) return "CLEAN-v2 (manifest citation)";
  if (prompt.includes("post-compact or post-resume")) return "RESUMED-v2";
  return "UNKNOWN";
}

let failures = 0;

// ═══ SCENARIO 1 — CLEAN: no prior messages → CLEAN advisory cites manifest ═══
{
  const { client, injected } = makeClient(0);
  const h = await factory({
    client,
    project: { id: "test", directory: sandboxDir },
    directory: sandboxDir,
    worktree: sandboxDir,
    experimental_workspace: { register() {} },
    serverUrl: new URL("http://127.0.0.1:0"),
    $: {},
  });
  await h["session.created"]({ sessionID: "ses_clean_test", directory: sandboxDir });
  const inj = injected;
  console.log("SCENARIO 1 — CLEAN (msgs=0)");
  if (inj.length !== 1) {
    console.log("  ✗ expected 1 injection, got " + inj.length);
    failures++;
  } else {
    const kind = summarize(inj[0].prompt);
    console.log("  ✓ injected 1 prompt  kind=" + kind);
    console.log("  prompt excerpt: " + JSON.stringify(inj[0].prompt.slice(0, 160)));
    if (kind !== "CLEAN-v2 (manifest citation)") {
      console.log("  ✗ expected CLEAN-v2 with manifest citation (D2)");
      failures++;
    }
    if (!inj[0].prompt.includes("docs/spec_revision/system/boot/boot_manifest.vsm")) {
      console.log("  ✗ manifest path missing from CLEAN text");
      failures++;
    }
  }
}

// ═══ SCENARIO 2 — RESUMED: prior messages → RESUMED advisory (D3 verbatim) ═══
{
  const { client, injected } = makeClient(3);
  const h = await factory({
    client,
    project: { id: "test", directory: sandboxDir },
    directory: sandboxDir,
    worktree: sandboxDir,
    experimental_workspace: { register() {} },
    serverUrl: new URL("http://127.0.0.1:0"),
    $: {},
  });
  await h["session.created"]({ sessionID: "ses_resumed_test", directory: sandboxDir });
  const inj = injected;
  console.log("SCENARIO 2 — RESUMED (msgs=3)");
  if (inj.length !== 1) {
    console.log("  ✗ expected 1 injection, got " + inj.length);
    failures++;
  } else {
    const kind = summarize(inj[0].prompt);
    console.log("  ✓ injected 1 prompt  kind=" + kind);
    console.log("  prompt excerpt: " + JSON.stringify(inj[0].prompt.slice(0, 160)));
    if (kind !== "RESUMED-v2") {
      console.log("  ✗ expected RESUMED-v2 (D3)");
      failures++;
    }
    // D3 verbatim markers from the bash original (scripts/vsf-onboard-reminder:43-58)
    for (const marker of ["state_query('focus')", "TASKS.vsm", "RECALL",
                          "Regressed twice already"]) {
      if (!inj[0].prompt.includes(marker)) {
        console.log("  ✗ RESUMED text missing marker: " + marker);
        failures++;
      }
    }
  }
}

// ═══ SCENARIO 3 — fail-safe: manifest MISSING on disk → CLEAN falls back to
//   full text (D2 fail-safe; never silent) ═══
{
  const emptyDir = resolve("/tmp/opencode/reminder-v2-test-empty-" + Date.now());
  const { mkdirSync } = await import("node:fs");
  mkdirSync(emptyDir, { recursive: true });
  const { client, injected } = makeClient(0);
  const h = await factory({
    client,
    project: { id: "test", directory: emptyDir },
    directory: emptyDir,
    worktree: emptyDir,
    experimental_workspace: { register() {} },
    serverUrl: new URL("http://127.0.0.1:0"),
    $: {},
  });
  await h["session.created"]({ sessionID: "ses_clean_fallback", directory: emptyDir });
  const inj = injected;
  console.log("SCENARIO 3 — CLEAN fail-safe (manifest missing)");
  if (inj.length !== 1) {
    console.log("  ✗ expected 1 injection, got " + inj.length);
    failures++;
  } else {
    const kind = summarize(inj[0].prompt);
    console.log("  ✓ injected 1 prompt  kind=" + kind);
    if (kind !== "CLEAN-fallback (full text)") {
      console.log("  ✗ expected full-text fallback when manifest absent (D2 fail-safe)");
      failures++;
    }
  }
}

// ═══ SCENARIO 4 — D4: no throw in the module body (advisory-only) ═══
{
  const src = readFileSync(pluginPath, "utf-8");
  const body = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
  const throws = (body.match(/\bthrow\b/g) || []).length;
  console.log("SCENARIO 4 — advisory-only (D4)");
  console.log("  ✓ throw statements in code body: " + throws);
  if (throws > 0) failures++;
}

console.log("");
console.log(failures === 0
  ? "HARNESS: PASS — v2 plugin discriminates CLEAN (manifest citation) / RESUMED (focus→RECALL) per D1-D4"
  : `HARNESS: FAIL — ${failures} assertion(s)`);
process.exit(failures === 0 ? 0 : 1);