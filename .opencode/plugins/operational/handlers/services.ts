/**
 * services-handler.ts — handler for services scripts.
 *
 * Runs: service_watchdog.py, vsf-compact.py, vsf_cgroup_reallocate.py.
 * Trigger: session.idle (periodic, low frequency).
 *
 * HOST ROLE (FND-S1-HOST-ROLE-SPLIT-01 / FND-SVC-WATCHDOG-ROOT-DRIFT-01):
 * all three probe the fleet (pct services, /var/lib/vsf events, the n02
 * anticipation orders dir) — none of those exist on the agent host.
 * FND-S1 decision: fleet runs live ON n02 (watchdog cron every 5 min,
 * systemd timers); the idle handler gates each script on its real prereq
 * and reports an honest skip instead of a guaranteed fail/false alert.
 */
import { existsSync } from "node:fs"
import { join } from "node:path"
import { runScript, type ScriptResult } from "../../../shared/run-script"
import type { Handler } from "../vsf-event-router"

export const servicesHandler: Handler = {
  id: "services",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ScriptResult[] = []

    // pct (Proxmox LXC CLI) only exists on the hypervisor — the watchdog
    // shells out to it for every service/disk/ollama probe.
    const hasPct = (process.env.PATH || "").split(":").some((dir) => {
      try { return existsSync(join(dir, "pct")) } catch { return false }
    })
    if (hasPct) {
      results.push(await runScript(ctx.repoRoot, "scripts/state/services/service_watchdog.py"))
    } else {
      results.push({
        script: "scripts/state/services/service_watchdog.py",
        result: "skip",
        detail: "prereq missing: pct (fleet probe — runs on n02 cron */5)",
        durationMs: 0,
      })
    }

    // vsf-compact compacts the nucleus events log under /var/lib/vsf
    // (fleet path). Filename note: real script is vsf-compact.py (hyphen);
    // the old underscore reference was a guaranteed ENOENT.
    const eventsLog = "/var/lib/vsf/vsf_nucleus/events.jsonl"
    if (existsSync(eventsLog)) {
      results.push(await runScript(ctx.repoRoot, "scripts/state/services/vsf-compact.py"))
    } else {
      results.push({
        script: "scripts/state/services/vsf-compact.py",
        result: "skip",
        detail: `prereq missing: ${eventsLog} (fleet path)`,
        durationMs: 0,
      })
    }

    // cgroup reallocator reads Component A orders from the n02
    // anticipation runtime (status: built — no live wiring yet) and
    // actuates via systemctl set-property on the hypervisor.
    const ordersDir = "/var/lib/vsf-anticipation/orders"
    if (existsSync(ordersDir)) {
      results.push(await runScript(
        ctx.repoRoot,
        "scripts/state/services/vsf_cgroup_reallocate.py",
        ["--orders-dir", ordersDir],
      ))
    } else {
      results.push({
        script: "scripts/state/services/vsf_cgroup_reallocate.py",
        result: "skip",
        detail: `prereq missing: ${ordersDir} (n02 anticipation runtime)`,
        durationMs: 0,
      })
    }

    const allOk = results.every((r) => r.result === "ok" || r.result === "skip")
    return {
      result: allOk ? "pass" : "fail",
      durationMs: Date.now() - start,
      detail: results.map((r) => `${r.script}: ${r.result}`).join("; "),
    }
  },
}
