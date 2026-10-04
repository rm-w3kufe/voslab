# Legacy → clean viable-module migration protocol
> **STATUS: historical_record** — consumido por fuse S5-POLICY-CORE → s5_policy_core.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

> **Status:** `feat/cybernetic-rag`, v0.1. Sibling of DSN-COUPLE-01 (onboarding) and R9 (no concessions).
> **Origin (rmw3, 2026-06-05):** while building the Cybernetic RAG view-host we realised the right move
> for *every* legacy LXC/service is the same — rebuild it as a clean viable module, never graft onto the
> legacy base. "Lo importante es el protocolo." The S5-opsroom view-host (LXC 109) is the reference impl.

## 0. The principle (why a protocol, not a patch)

A legacy component (old `api.py`, the SCADA dashboard, the mis-named containers) is **not migrated by
bolting new behaviour onto it** — that is the concession R9 forbids. It is migrated by **rebuilding it
as a declared, certified, decommissionable viable module** and retiring the legacy once the clean
replacement is live. The replacement consumes the canonical channel (φ↑, `core/connection_schema.json`),
not the legacy interface.

## 1. The naming convention — `Sn-function`

Containers/VMs are named for their VSM role + function (hostnames lowercase). Ratified 2026-06-05.

| LXC | legacy name | canonical `Sn-function` | VSM role | rename status |
|---|---|---|---|---|
| 101 | nucleus | `s3s4-nucleus` | S3 control + S4 intel (collapsed) + ollama | scheduled |
| 104 | s5-layer | `s5-policy` | S5 console / governance / algedonic | scheduled |
| 106 | vsf-nats-test | `s2-broker` | S2 coordination (NATS + BBS) | scheduled (was task #5) |
| 107 | vsf-collapsed-poc | `s3star-audit` | S3* sporadic audit | scheduled (was task #5) |
| 108 | vsf-sandbox | `dev-sandbox` *(outside Sn)* | not a VSM subsystem — test harness | scheduled |
| **109** | — (new) | **`s5-opsroom`** | S5 opsroom / view-host | **DONE (ref impl)** |

Renaming a *live* container touches hostname + `state.db.lxcs.role` + tunnels (`reference_vsf_tunnels`)
+ services — so the existing-container renames are a **scheduled migration window**, not bundled with a
build. New containers are born under the convention (109 was).

## 2. The migration steps (per legacy component)

Logical gates (no time estimates):
1. **Rebuild clean** — a NEW minimal module (new code, new container if warranted), with **no legacy
   interface as a base**. It consumes the canonical φ↑ channel (`connection_schema`), not the old API.
2. **Declare** — a `lxcs` row (Sn-function name) + a `coupling_registry` row (`kind=phi_channel` /
   appropriate kind). `status=planned` until it has a verifying feed (an `active` declaration with no
   feed = ORPHAN under the S3* reconcile — model≡reality).
3. **Certify the coupling** — the φ↑ feed is AX-STATE-attested; the module **verifies** it
   (`state_verify`, G-V3) before acting. Run the view-contract gates **G-V1..G-V4** (version /
   conformance / attestation / declaration).
4. **Cut over + decommission** — once the clean module is live and certified, retire the legacy: stop
   the old service, remove its repo source, set the old `coupling_registry`/`lxcs` rows to `deprecated`
   or delete. Never decommission the legacy *before* the replacement is verified live.

## 3. Reference implementation — `s5-opsroom` (LXC 109)

- **What it is:** a clean, minimal **view-host** — NOT the legacy `opsroom/api.py`. It (a) subscribes to
  NATS φ↑ (`vsf.alpha.view.*`, `vsf.alpha.attest.*`), (b) verifies the upstream source attestation
  (`state_verify`), (c) serves the panel scaffold + the module registry to the browser over a minimal
  WS/SSE. Hosts **view-module #1 = `cybernetic-rag`** (`opsroom/modules/cybernetic-rag.module.json`).
- **Declared:** `lxcs` 109 `s5-opsroom` + `coupling_registry` `view-cybernetic-rag` (`phi_channel`,
  **`active`** since §7.3b). Component `vsf-view-host` (deploy 109).
- **φ↑ wiring (§7.3b, option 3 — structural):** the canonical φ↑ is the nucleus `events.jsonl` (FILE,
  Merkle-chained, per `connection_schema` — NOT NATS). To put it on the shared channel: the nucleus
  telemetry dir `/var/lib/vsf/vsf_nucleus` is bind-mounted from the host `/var/lib/vsf-telemetry/vsf_nucleus`
  (chown `100000:100000` for the unprivileged map) — **RW into 101** (mp1, at the nucleus's own path, no
  code change) and **RO into 109** (mp0, at `/mnt/telemetry`). Applied via a clean stop→copy→mount→reboot
  of 101 (nucleus recovered, chain intact, `certified=True`). The view-host reads the tail (seek, not a
  119MB scan; UTF-8-tolerant; window > the 60s sampler), verifies the chain, and projects. *These mounts
  are `pct` config (not in the repo) — this doc is their traceability record.*
- **Replaced SCADA (cutover §7.4, DONE 2026-06-06):** the SCADA deploy on LXC 101 (`vsf-opsroom.service`,
  :8080) was decommissioned once 109 served BOTH modules certified — service stopped+disabled+removed,
  `/opt/vsf/opsroom` deleted, the SCADA + legacy pre-SCADA opsroom repo files removed (`opsroom/` is now
  just `view_host/` + `modules/`), the :8080 tunnel retired (the opsroom is :8088). The nucleus on 101 was
  unaffected (separate process). This is migration step 4 executed: kill the legacy only after the clean
  replacement is live + certified.

## 4. What this protocol is NOT

- Not a rewrite-everything-now mandate. It is **incremental**: one module at a time, legacy kept alive
  until its clean replacement is certified.
- Not coupled to a framework choice. The view-host is vanilla (no React); the discipline is the
  certified φ↑ contract + declaration, not the rendering tech.

## 5. Next

(1) Build the `s5-opsroom` minimal host on 109 (NATS φ↑ subscriber + `state_verify` + static module
host); (2) §7.2 the attested view builder feeding it; (3) schedule the existing-container rename window
(101/104/106/107/108) as the next application of this protocol.
