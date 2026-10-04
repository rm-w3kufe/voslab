# VSF Interface Brief — Opsroom + Public Site

> **Audience:** a UX/UI specialist (human or agent). **Purpose:** dimension the interface work —
> inventory what exists, what's missing, and *every data source + connection point* — so the designer
> can focus on FORM. This brief deliberately does **not** prescribe visual design (colors, type, layout);
> that is the specialist's craft. Authors: rmw3 (S5) + Fable, 2026-07-04.

## 0. Design north star (references, not prescriptions)

VSF's live views have *independently converged* on the visual language of **Project Cybersyn (Chile,
1972)** because they share its theory (Beer's VSM). Use Cybersyn as the fidelity reference:

- **Opsroom** (dense, live, for operating) → the Cybersyn opsroom panels: dark ground, colored subsystem
  boxes, dotted variety flows, the RED/YELLOW/GREEN algedonic panel. Refs in `~/Documents/Graficas/`:
  `cybersyn-screen.jpg`, `Cybersyn-detalle1.jpg`, `pict_opsroom_16_Staffy-*.jpg`.
- **Public site** (clean, narrative, for communicating) → the flat sectoral-flow infographic style.
  Ref: `cybersin-diagram-600x398.jpg` ("LA INDUSTRIA EN LA ECONOMÍA").
- The **algedonic panel** (Cybersyn) and our **algedonic triage table** are the *same conceptual object* —
  R/Y/G severity by subsystem. This mapping is the emotional core of the aesthetic.

Two products, related but distinct aesthetics. Do not force one skin on both.

## 1. Current state — what the opsroom already IS

- **Host:** LXC 109 (`s5-opsroom`), `vsf-view-host.service`, **stdlib only** (Python HTTP + SSE, no
  frameworks), port **:8088**. Reached via `vsf-tunnels`.
- **`/`** = the **formaid studio** — a mermaid editor/preview/export (templates + live generators + saved).
- **`/live`** = the **module dashboard**. Current tabs: `cybernetic-rag`, `system-topology`, `s3-viz`,
  `qwen-mermaid`. Header shows a `CERTIFIED` badge + source + timestamp.
- **What a module renders today** (see screenshot `Captura … 2026-07-04 134707.png`):
  - a row of **stat tiles** (viability/`stasis_cos`, `in Ω`, `Lyapunov L`, `dL`);
  - a **mermaid flow** of the homeostatic loop (solid = flow, dotted = feedback), colored nodes.
- **Live update mechanism:** SSE stream from the host; modules re-render on new φ↑ events.
- **Data access pattern:** modules read **read-only** — nucleus φ↑ (`events.jsonl`, RO bind-mount) +
  `state.db` (RO). Never write. (Security: the opsroom is a *viewer*, not an actuator.)

## 2. What's MISSING (the modules to build / redesign)

### Opsroom (internal, for rmw3)
1. **Algedonic panel (LIVE)** — today the R/Y/G triage table (screenshot `… 2026-07-02 174701.png`) is a
   *one-off generated artifact*, not a live module. Make it a live view of the algedonic ledger. **This is
   the single highest-fidelity-to-Cybersyn module.**
2. **Supervision surface** — the "human-governs" views just specified (`supervision_layer.spec.vsm`):
   (a) the **review surface** (volume/trend/distribution/anomaly of autonomous regulation), and (b) the
   **escalation → decision** panel (pending decisions; APPROVE/DENY/ADJUST; **signed** verdicts).
3. **Autonomous-loops view** — the two Axis-2 loops (amplifier + attenuator) acting live: what the machine
   regulated, when, why (the S3\* audit stream).
4. **Fleet / multi-S1 view** — clima (80 stations, of which 13 Ω-calibrated) + econ, each with its
   `stasis_cos` / regime. A recursion-aware map (the VSM "A–E units" panel, generalized).
5. **Visual redesign** — the current default mermaid (green-on-dark) → the Cybersyn-grade aesthetic.

### Public site (`vsf.u2738.org`, external)
6. A **designed public face** — today it fronts the bastion/beacon only. Needs a narrative site: what VSF
   is, the covenant, the handshake, the papers, the live "shape of viability" (a tasteful, read-only,
   public-safe subset of the opsroom — no operational internals).

## 3. THE DATA MAP — sources + connection points (the important part)

Everything a module needs is one of these. All read-only.

| Signal / view needs | Source | Where / how to read |
|---|---|---|
| `stasis_cos`, `in_omega`, `margin_free`, `margin_binding`, `lyapunov`, `trust×4`, `entropy/phase`, `vr b0/b1` | nucleus **φ↑** | `events.jsonl` (`kernel_tick` records), RO bind-mount on LXC 109 |
| services, components, chains, topology, `coupling_registry`, `peripheral_health` | **state.db** | RO SQLite on n02 (`vsf-q` schema) |
| autonomous regulation (grants/attenuate/escalate) | **NATS** | subject `vsf.alpha.s3star.audit` |
| algedonic alerts (the R/Y/G panel) | **algedonic ledger** | LXC 104 `/root/algedonic/ledger.db` (mirror) / `state.db` |
| supervision decisions (pending + signed verdicts) | **state.db + NATS** | `supervision_decision` rows + subject `vsf.alpha.s5.decision` (per `supervision_layer.spec.vsm`) |
| S1-clima per-station | clima **φ↑** | `/var/log/vsf-clima/<node>.phi_up.jsonl` (LXC 112) |
| S1-econ | econ **φ↑** | `/var/log/s1-econ/phi_up.jsonl` (LXC 113) |
| live push to the browser | **view-host SSE** | the existing `/live` SSE stream (`host.py`) |

**Module contract (existing pattern to follow):** a view-module is a manifest + a Python generator that
reads the sources above and emits HTML/mermaid; the host serves it and pushes SSE updates. See
`opsroom/view_host/` (`host.py`, `formaid.py`, the `cybernetic_rag_view.py` / `system_topology_view.py`
generators) and `opsroom/modules/` manifests. A new module = a new generator + manifest, same shape.

## 4. Constraints (hard)

- **Read-only viewer.** Modules never write to state or actuate. The one exception is the supervision
  escalation panel, whose *only* write is a **signed** `supervision_decision` (verified against the pinned
  S5 root) — treat it as a special, audited path, not a generic control.
- **Stdlib host.** No heavy frontend framework on the host; keep it self-contained (SSE + generated HTML/JS).
  A richer frontend is fine as long as it's bundled and the host stays stdlib.
- **Public site is a different trust zone.** It must expose only a public-safe subset — no operational
  internals, no actuation, no raw ledger. (See `docs/security/security_assessment.md`.)
- **Recursion-aware.** The same module, pointed at a different node's φ↑, should render that node — the
  design should not hard-code "the nucleus."

## 5. Boundary — what WE provide vs what the specialist owns

- **We (VSF) provide:** this brief, the data map, the module contract, live endpoints/samples, and review
  of whether a design faithfully represents the underlying cybernetics.
- **The specialist owns:** the visual system (palette, type, grid, motion), the information hierarchy, the
  component library, and the two distinct skins (opsroom vs public). We do not prescribe these.

## 6. First deliverable to ask the specialist for

A **clickable concept** for one module end-to-end — recommend the **algedonic panel**, because (a) it is
the clearest Cybersyn correspondence, (b) its data source is simple and already exists, and (c) it sets the
visual system the rest inherits. From there, the supervision surface (the objective-closer) is the natural second.
