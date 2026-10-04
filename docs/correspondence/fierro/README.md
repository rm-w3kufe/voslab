# Correspondence — Prof. Raúl Fierro (Universidad de Valparaíso)

Formal record of the mathematical review exchange around the
`attractor_convergence` paper. This folder holds outgoing correspondence
under version control; the historical working archive stays in
`docs/papers/attractor_convergence/Revisiones/` (referenced, not duplicated).

## Participants

- **Prof. Raúl Fierro** — external mathematical reviewer (probability /
  stochastic processes). First contact via the Beer-community outreach arc.
- **rmw3** — author of record; owns send decisions (S5).
- **VSF Research Group** — Claude (theory/architecture) + DS (measurements).

## Exchange timeline

| # | Date | Direction | Item | Where |
|---|------|-----------|------|-------|
| 1 | 2026-05 | ← received | Original review: Q1 (convexity of Ω), Q2 (contractivity L<1), Q3 (spectral bound σ_max) | `../../papers/attractor_convergence/Revisiones/Rev_Prof_Raul_Fierro.pdf` |
| 2 | 2026-05/06 | → sent | First response iteration | `../../papers/attractor_convergence/Revisiones/Resp1_Prof_Fierro.txt` + analysis docs |
| 3 | 2026-06-29 | prepared | **Mathematical Addendum** — consolidated resolution of Q1–Q3 | `addendum_omega/` (this repo, canonical) |
| 4 | 2026-07-02 | prepared | **Q4 full-body package** — paper v0.8 + exec summary + Annex B + draft letter; gate CLEARED, send held (rmw3) | `../../papers/attractor_convergence/fierro_q4_package.vsm` |
| 5 | 2026-07-11 | internal | Pre-send review of the addendum — 6 findings, amendments proposed | `addendum_omega/REVIEW_2026-07-11.md` |

## Current status

**Held pre-send — amendments ratified and applied (rmw3, 2026-07-11).**
F1/F2/F4a/F4c are applied to `addendum.tex` (rev. 2, July 2026): the existence
argument is now convexity-free (Krylov–Bogolyubov + Banach + Foster–Lyapunov),
and the paper's Theorem 1 + all five Krasnosel'skiĭ mentions + the cover
letter were aligned with the same formulation. Remaining before rmw3 sends:

1. `FIERRO-L-BOUND` (DS, tasked) — Lipschitz number from deployed constants;
   fills the §2 non-expansiveness discharge.
2. `FIERRO-NS-RANGE` (DS, tasked) — reconcile 2.0 vs 4.0 ‖x‖ and fill the
   `[*]` placeholders (N, σ range) in `addendum.tex` §3.
3. Paper version: freeze v0.9 (2026-07-11 material: structural form, D_eff
   ceiling, Santiago lineage, convexity-free Thm 1) — recommended over v0.8.
4. OMEGA-MARGIN disclosure: honesty note in the letter, or wait for the
   diagnostic (repair plan, `OMEGA-MARGIN-BINDING-DIAG`).

## Lasting impact of the exchange

Fierro's Q1–Q3 became the **domain validation protocol** (Q1 = Ω convex,
Q2 = L < 1, Q3 = σ_max) now live in `calibration.rs` and required for every
new VSF domain — applied to s1-clima (certified 2026-06-26) and s1-econ.
The planned non-convex Ω (Raworth doughnut, EXP-LL-01-P1) is framed in the
draft letter as an open question for him.

## Conventions

- Everything sent to or received from Prof. Fierro gets a row in the timeline.
- Outgoing documents: canonical `.tex`/`.md` source lives here; compiled PDFs
  are reproducible artifacts.
- Received documents: archived as-is, named `*_received_<date>.pdf`.
- Send decisions are rmw3's alone (outward action, ITEM_11-class hold).
