# D-A0-MODEL-DOWNGRADE — A0 ethical classifier on 1.5b: accepted risk + reactivation gate

**Decision:** The A0 classifier (the ethical/semantic scan, A0/A0.1 axioms) runs
on `qwen2.5-coder:1.5b` instead of `7b` for its recurring scans. The 7b is
reserved on-demand (KEEP_ALIVE=5m unloads it).

**Accepted by:** rmw3 (S5), 2026-07-13, following Claude's security analysis.
**Class:** accepted security debt with a mandatory reactivation gate — NOT a
permanent design choice.

---

## Why the downgrade

The host (n02, i7-7600U, 2 physical cores) cannot sustain recurring 7b inference:
a single 7b pass is ~200s on one core, and with A0 + nucleus-S4 both on the
1-core ollama budget the models starved the host (load 7.76 → nucleus watchdog
SIGKILL, incident 2026-07-13). 1.5b fits the budget; 7b does not, recurringly.

## The risk being accepted

A0 is the ONLY defence layer that performs **semantic** ethical judgement —
detecting patterns that "feel wrong" without breaking any structural rule. The
other layers are different in kind: the covenant (hash verification,
deterministic, fail-closed), the diverse verifier / s3-star (structural,
cryptographic), the Merkle chain (integrity). On 1.5b, A0 reasons less subtly
than on 7b and may miss (false negative) a subtle semantic violation the 7b would
have flagged, or emit more noise (false positives) for a human to filter.

## Why it is acceptable NOW (not why it is fine forever)

1. **A0 is advisory (R11)** — it flags for human review (S5); it neither decides
   nor executes. A miss produces no action, only an absent flag. The hard safety
   floor is the deterministic covenant, which does not depend on A0.
2. **No real adversaries yet** — the system is pre-R6 (not integrated with
   external S1 / BBH). Inputs are internal and controlled; A0 is observing a
   system that observes itself, not defending against an attacker.
3. **Empirical history** — A0 has produced ~2,634 CAPTURE_SUSPECT events, ~all
   noise, zero real ethical-violation captures (there have been none). In
   practice A0 generates flags a human filters, not threat detections.
4. **Redundancy** — TRIAGE-EVIDENCE-RULE (R12), s3-star, the diverse verifier are
   independent detection layers covering what A0 might miss.

Summary: this does not weaken the safety floor; it postpones a semantic
ethical-reasoning capacity that currently has nothing to reason against.

## REACTIVATION GATE — mandatory, rmw3-committed

When ANY of the following becomes true, A0's semantic capacity must be restored
via a **structural** solution (not merely "switch back to 7b on the same host"):

- **Adversarial inputs** — the system integrates an external S1 (BBH) or any
  input path that is not internally controlled (post-R6).
- **Agency growth** — autonomous actions requiring ethical judgement increase
  beyond the current advisory-only posture.
- **Hardware change** — the substrate gains the CPU/GPU headroom to sustain a
  more capable model (vOS bare-metal / Proxmox roadmap).

## Structural solutions to evaluate at the gate (not now — would be over-eng.)

1. **Hybrid escalation** — A0 runs 1.5b for the normal stream, escalates only
   ambiguous/borderline cases to 7b on-demand (tolerates latency where it
   matters). Best capability/cost balance; more code.
2. **Better substrate** — GPU or multi-core host makes recurring 7b viable.
3. **Domain-specialised model** — a small model fine-tuned for the ethical
   axioms may beat a general 7b at the specific task, at 1.5b cost.
4. **Expand the deterministic floor** — move more of the ethical checks from the
   LLM into the deterministic covenant layer, reducing reliance on A0's semantics.

## Tracking

- Task `A0-MODEL-REACTIVATE` (seeded, gated) in TASKS.vsm.
- This debt is surfaced in the risk register, not buried in a session block.
- Related: [[project_crag]] (A0/S4 layer), covenant decisions, R6 gate.
