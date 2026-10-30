# D-OMEGA-GUARD — Ratification of the Ω-guard for learned modes

**Decision:** The Ω-guard protocol lock is ratified, with **experiment-only
scope**: the learned-modes mechanism (dynamic prototypes μₛ) is authorized to
run on the **LXC 108 sandbox only**, for the duration of EXP-MODES-01
(7 days). Production adoption is **explicitly NOT authorized** by this
decision — it requires a second S5 signature after the experiment's data is
reviewed.

**Ratified by:** rmw3 (S5), 2026-07-11.
**Recommended by:** Claude (Fable 5), same session.
**A5 classification:** This is the boundary case of D4 — the kernel modifying
its own structure (what the prototypes mean) rather than its state. First
self-modifying element authorized in the kernel's history; hence the
scoped, twice-gated form.

---

## What the Ω-guard is

Today the mode prototypes μₛ (the ℝ¹²⁸ representatives of "being S1 … S5")
are compile-time constants. The learned-modes mechanism makes them dynamic:

```
μₛ(t+1) = μₛ(t) + ε · wₛ(t) · (x(t) − μₛ(t)),   ε = 0.001
```

— online EM on the kernel's own state stream. The Ω-guard is the structural
containment: **before any prototype update is committed, the kernel simulates
one tick with the candidate μₛ and checks Ω; if the trajectory would exit Ω,
the update is rejected and logged.** A protocol lock in code, not a policy in
a document. Cost ≈ 16K flops per update.

## The organisation/structure contract (Maturana)

The conceptual basis is the same distinction used in the Fierro response and
the AC paper: the **organisation** stays invariant — Ω, the S1-S5 topology,
the λ-sign monitoring, the covenant (compiled in, SHA-verified at boot) —
while the **structure** (the prototypes) adapts with experience. The Ω-guard
is what enforces that split in code: learning may move the prototypes, but
never to a place that violates Ω. The system cannot learn its way out of its
own constitution.

## What this ratification authorizes

1. EXP-MODES-01 on LXC 108 (sandbox), 7 days, per its spec
   (`docs/experiments/EXP-MODES-01/spec.vsm`).
2. The guard as covenant-level lock: removing or weakening it later is a
   covenant change (S5 signature required).
3. The specified mitigations: lr decay (Robbins–Monro), mode-collapse
   repulsion, freeze-on-λ>0, designed-modes checkpoint for revert.

## What it does NOT authorize

- Any learned-modes code on LXC 101 (production nucleus).
- Any change to Ω, the covenant, or A5 itself.
- Production adoption — second decision, after EXP-MODES-01 review.

## Linked artifacts

- Experiment spec: `docs/experiments/EXP-MODES-01/spec.vsm`
- Paper seed (NP, ratified same session): `docs/papers/learned_modes/seed.vsm`
- Theory source: `docs/spec_revision/plan/theory-sid-01/seven_ideas_deep.vsm` §7 + Claude review §4
