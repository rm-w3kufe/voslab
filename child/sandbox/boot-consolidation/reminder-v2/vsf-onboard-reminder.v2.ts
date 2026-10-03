/**
 * vsf-onboard-reminder v2 — R5 boot-order enforcement for OpenCode.
 *
 * SANDBOX COPY (child/sandbox/boot-consolidation/reminder-v2/). Design source:
 * M3_reminder_v2.vsm (proposal approved by parent, D1-D4). This is NOT the
 * production file — the parent promotes it after R4 verification (R13).
 *
 * v2 changes vs v1 (current .opencode/plugins/vsf-onboard-reminder.ts):
 *   D1  msg-count discriminates CLEAN vs RESUMED: msgs.data.length > 0 →
 *       RESUMED (resume/attach/post-compact — a summary is present); else →
 *       CLEAN (fresh start). v1 used the same detection to SKIP silently; v2
 *       inverts the branch and injects the RESUMED advisory instead of silence.
 *   D2  CLEAN shrinks to a reference to the boot manifest
 *       (docs/spec_revision/system/boot/boot_manifest.vsm — the index of
 *       everything the boot loads, P4). Fail-safe: if the manifest file is
 *       absent, fall back to the current full CLEAN text (never silent).
 *   D3  RESUMED is VERBATIM from the bash original's RESUMED branch
 *       (scripts/vsf-onboard-reminder:43-58) — the proven protection, ported
 *       whole: focus → cross-check TASKS.vsm → onboard.sh only if empty/
 *       contradicts → treat summary as RECALL.
 *   D4  advisory-only, never blocks — same authority as v1 (M2 verifier check
 *       (b) enforces: a reminder must not throw).
 *
 * Incident history: 2026-06-22 (post-compact ran on summary alone), 2026-07-27
 * (recurred). OpenCode has no SessionStart source flag, so this fires on
 * "session.created" and injects via client.session.prompt — once per session.
 */
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import type { Plugin } from "@opencode-ai/plugin";

// ── D2 fail-safe: the manifest is the index; if it is missing, fall back ──
const MANIFEST_REL = "docs/spec_revision/system/boot/boot_manifest.vsm";

// The manifest lives at the REPO ROOT (docs/spec_revision/...), which is not
// necessarily the session directory: the child workspace (child/) has its own
// docs/ (deploy/archive/sandbox) with no spec_revision tree, so resolving
// against `directory` wrongly falls back. Walk UP from the session directory
// until a candidate path exists (the repo root is an ancestor of any session
// inside the repo); only the session directory is probed — never the process
// cwd, so a session opened outside the repo gets the fail-safe text.
function findManifest(directory: string): string | null {
  let p = resolve(directory || process.cwd());
  for (let i = 0; i < 6; i++) {
    const candidate = resolve(p, MANIFEST_REL);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(p);
    if (parent === p) break;
    p = parent;
  }
  return null;
}

const CLEAN_REMINDER_MANIFEST = `VSF project — CLEAN session start. Boot order is normative (hard_rules.R5_canon_over_recall). Read the boot manifest — the index of everything the boot loads and why:

${MANIFEST_REL}

It indexes: the six boot docs (dependency order covenant ≻ core_boot_primer ≻ vsl_language_primer ≻ regulation_layer ≻ hard_rules ≻ communication_protocol), RULES.md, the vsl-language reference set, prompts, reminders, gates, measure-checks, MCP servers, commands. Read the manifest, then the docs it points to. Do not improvise the order (P1/P4).`;

// Fail-safe full text (identical to v1) — used only if the manifest is absent.
const CLEAN_REMINDER_FALLBACK = `VSF project — CLEAN session start. Boot order is normative (hard_rules.R5_canon_over_recall). Do not improvise it:

1. docs/spec_revision/system/boot/ — all SIX boot docs (dependency order: covenant ≻ core_boot_primer ≻ vsl_language_primer ≻ regulation_layer ≻ hard_rules ≻ communication_protocol). Dependency base: the notation and axioms every other document is written in. Reference set (14 items): system/s5-policy/vsl-language/, manifest index.vsm — on demand.
2. RULES.md — hard rules, rationale, S5 attribution.
3. bash scripts/state/onboard.sh

Then: read the BOOT MANIFEST (docs/spec_revision/system/boot/boot_manifest.vsm) — which MCP server serves which domain is the instrument map. Asking the wrong one returns [] which reads as absence rather than wrong address:
  state-canon        tasks · focus · journal
  state-canon-infra  services · lxcs · chains · topology   (n02 state.db; domain 'rules' RETRACTED 2026-08-12 — query raises, pointing at docs/spec_revision/system/boot/hard_rules.vsm)

Cross-check any claim from a compact summary against TASKS.vsm before acting (R5: canon over recall).`;

// ── D3: VERBATIM from scripts/vsf-onboard-reminder:43-58 (bash original) ──
const RESUMED_REMINDER = `VSF project — this is a post-compact or post-resume start. Before acting on the conversation summary above, before any other tool call:

1. state_query('focus') via state-canon, or read current_focus.json — cheap, tells you what was in flight. DO NOT trust it blindly: entries go stale (confirmed 2026-07-27 — one stayed "active" after the task was done and superseded). Cross-check each active/paused ref against TASKS.vsm.
2. Only if focus is empty, missing, or contradicts TASKS.vsm:
      bash scripts/state/onboard.sh

Treat every claim in the summary as RECALL, not canon — a lead to verify, never the source of truth. Do not resume the "last task" from the summary until step 1 or 2 has actually run in THIS turn. (Regressed twice already: 2026-06-22 and 2026-07-27.)`;

export const OnboardReminder: Plugin = async ({ client }) => {
  const told: Set<string> = new Set();

  return {
    "session.created": async ({ sessionID, directory }: any) => {
      if (told.has(sessionID)) return;
      told.add(sessionID);

      // D1: msg-count discriminates CLEAN vs RESUMED.
      let resumed = false;
      try {
        const msgs = await client.session.messages({
          path: { id: sessionID },
        });
        resumed = !!(msgs.data && Array.isArray(msgs.data) && msgs.data.length > 0);
      } catch {
        // message list unavailable — assume CLEAN (remind anyway, cheap)
        resumed = false;
      }

      let reminder: string;
      if (resumed) {
        // D3: RESUMED verbatim from the bash original (proven protection).
        reminder = RESUMED_REMINDER;
      } else {
        // D2: CLEAN cites the manifest; fail-safe to full text if missing.
        reminder = findManifest(directory)
          ? CLEAN_REMINDER_MANIFEST
          : CLEAN_REMINDER_FALLBACK;
      }

      try {
        await client.session.prompt({
          path: { id: sessionID },
          query: { directory },
          body: {
            prompt: reminder,
            parts: [],
          },
        });
      } catch (e: any) {
        console.error(`[vsf-onboard-reminder] inject failed: ${e.message}`);
      }
    },
  };
};

export default OnboardReminder;