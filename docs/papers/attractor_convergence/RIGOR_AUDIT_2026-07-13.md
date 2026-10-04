# Rigor Audit — Attractor Convergence paper (2026-07-13)

Auditor: Claude (Opus). Trigger: rmw3 — after the Fierro convexity-free
refinement, re-examine the paper for contradictions/fallacies, figure↔text
coherence, jargon, and opportunities for mathematical prose.

**STATUS: IN PROGRESS (incremental).** This pass covered the geometric core
(State Space, Feasible Region, Lyapunov, Basin, TDA, Discussion portrait).
Remaining: Experiments 3–12, Limitations, What-Can-Be-Modeled, Functional,
full figure-by-figure sweep. Findings appended as the sweep continues.

Method order (agreed): **(1) rigor** [this doc] → (2) fix figure + reconcile
text → (3) selective de-jargon → (4) mathematical-prose pass. Do not style
before the rigor grid is clean.

---

## METHOD NOTE — de-jargon must be SELECTIVE, not total (unlike the addendum)

Jargon density (main.tex): `tick` ×122, `kernel` ×139, `EXP-` ×133,
`Rust` ×129, `cgroup` ×13, `operational` ×20.

The addendum could be de-jargoned *completely* because it is pure mathematics.
The paper cannot: its thesis IS that "the mathematics lives in a system that
runs 24/7." Jargon there is constitutive, not incidental. So the de-jargon
must be **selective by section type**:

- **Mathematical sections** (State Space Formalism, Feasible Region, Lyapunov,
  Coordinate-Free Functional): full math register, addendum-style.
  `tick`→`iteration`, `kernel`→`the map/system`, `EXP-LY-01`→`(Benettin's
  algorithm)`. This is where Fierro reads.
- **Experimental sections** (the 12 experiments): `kernel`/`tick`/`EXP-XX` are
  legitimate (they name what was run) — but cut REPETITION (not "kernel" 5× per
  paragraph).
- **System sections** (Physical Substrate, VSL protocol): jargon stays; it is
  the point.

⟦ DECISION NEEDED (rmw3): audience for the de-jargon. If it's Fierro's Q4
review → prioritize the math sections. If it's a journal → AC may not be the
journal paper at all (rmw3's own read: "too dense for a journal"; P2/P3 are the
philosophy/language-facing ones). This changes how far the de-jargon goes. ⟧

---

## IMAGE AUDIT (2026-07-13, visual inspection of rendered figures) — IN PROGRESS

### IMG-1 — CONTRADICTION: figures show D_eff=3.00, tables/text say 6.00
- **Where:** Fig 3(b) "Attractor dimensionality" and Fig 4 "D_eff vs Scale" both
  plot D_eff stabilising at **3.00**. Table 2 and §5.2 text say D_eff stabilises
  at **6.00**. The figures render the PREDECESSOR-law series; the canonical-law
  result is 6.00. Table 2 caption admits it ("figures below are being regenerated
  under the canonical law").
- **Severity:** HIGH visually — a reader sees "6.00" in the caption/table and
  "3.00" in the plot on the same page. Known-but-unresolved.
- **Fix:** regenerate Fig 3(b)/Fig 4 under the canonical law (→ 6.00), OR, until
  then, add a one-line in-figure note "(predecessor law; canonical = 6.00)".

### IMG-2 — D_eff is OVERLOADED: three different numbers all called "D_eff"
- **Where:** PCA correlation dimension ≈ **2–3** (§5.3, my R11 edit); heuristic
  active_dims+trust×2 = **3.00** (predecessor) / **6.00** (canonical). Three
  distinct quantities under one name.
- **Severity:** MEDIUM — compounds R11. A reader cannot tell which D_eff a given
  "3" or "6" refers to.
- **Fix:** distinct names — D_corr (PCA ≈2–3), D_eff (heuristic, 6.00 canonical),
  formal D_KY (=0). State the three once, like the three cones and three views.

### IMG-3 — flat figures with no variation (candidate for cut/consolidation)
- **Where:** Fig 10 (running λmax — a flat horizontal line at −0.01005), Fig 4
  after its initial transient (flat at 3.00). The flatness IS the result
  (stability), but a single number in text may carry it better than a plot.
- **Severity:** LOW — editorial, not a correctness issue. Flagged for rmw3's
  figure-review (matches "graphs that show no variation" concern).

### IMG-4 — two Lipschitz numbers (L≈0.85 vs L_f∈[1.4,24.4]) need global/local framing
- **Where:** Remark 3 (p.10) states L≈0.85 = full-state Jacobian norm ON Ω_A
  (cosine metric); the addendum + Limitations (R9) cite L_f∈[1.4,24.4] = the
  GLOBAL worst-case bound. They are consistent (a tight local norm inside a loose
  global bound), but my R9 Limitations edit says "exceeds 1 on Ω\Ω_A" — the
  global bound actually exceeds 1 EVERYWHERE (it's conservative); the measured
  norm on Ω_A is 0.85. Reword R9 to "the global worst-case bound exceeds 1
  (conservative); the measured Jacobian norm on Ω_A is ≈0.85."
- **Severity:** MEDIUM — Fierro would probe exactly this. One-sentence fix.

### FIG-1 — RESOLVED ✓ (commit 34781d6)
- fig:omega_nested redrawn: Ω non-convex (visible concave entropy-face
  indentation), convex Ω_A wedge, stasis cone, s̄, contraction arrows,
  confined excursion. Honest. Renders correctly (page 10).

### IMG-5 — embedded figure titles carry numbers that disagree with LaTeX
- **Where:** the in-image suptitles (from plot_results.py) say "Figure 7"
  (V_mem, LaTeX caption = Fig 6), "Figure 6" (trust, LaTeX = Fig 7), "Figure 2"
  (basin, LaTeX = Fig 5), etc. The script hard-codes old numbers; LaTeX numbers
  by order. Reader sees "Figure 7" in the image and "Figure 6" in the caption.
- **Severity:** MEDIUM — systematic, confusing. Fix: drop the numbered suptitles
  from the scripts (let LaTeX number), regenerate.

### FIG-5 (basin bowl) — rmw3 DECISION: cut the 3D potential bowl
- The 3D Lyapunov-potential bowl suggests a smooth convex basin (contradicts the
  non-convex Ω story) + carries the D_eff=3.00 stale label. rmw3: cut it; keep
  the 2D panels. **Replaced conceptually by the new honest 3D geometry figure**
  (fig:geometry_3d, commit 63f6844) which shows the real nested-cone geometry.
  Action: regenerate Fig 5 as 2D-only (edit plot_results.py), or drop the 3D
  subplot. Tasked, not yet done (needs script edit).

### FIG-6, FIG-7 (V_mem, trust bifurcation) — OK, show real variation. Keep.

### FIG-1 — FINAL FORM: cross-section (diana) view (commit 7f1b94b)
- Iterated: wedge (unclear) → 3D cones (notch too subtle) → **cross-section
  perpendicular to s̄** (nested discs; Ω non-convexity now OBVIOUS as an
  indentation). rmw3 chose this. The 3D figure was removed (superseded) —
  a cross-section of a cone reads far better than the funnel or the volume.
  The plain-tikz cross-section needs no external script.

## FULL FIGURE AUDIT (2026-07-13, all figures inspected visually)

### CUT — irrelevant / redundant / flat (no variation, no function)
- **F-CUT-1: Fig 5 3D bowl (fig2_basin_3d)** — the Lyapunov-potential bowl.
  Suggests a smooth convex basin (contradicts non-convex Ω); carries stale
  D_eff=3.00. rmw3 already decided: cut, keep the 2D panels.
- **F-CUT-2: fig8_basin_volume panel (b)** — "recovery by strength": 5 bars ALL
  at 1.0. Zero variation. The point (full recovery across all κ) is one text
  sentence. Cut panel (b), keep panel (a) histogram.
- **F-CUT-3: fig10_lyapunov** — running λmax is a flat horizontal line at
  −0.01005. The flatness IS the result but a number carries it. Candidate cut
  (or shrink to an inset).
- **F-CUT-4: fig3_thermal panel (b)** — "viable region in pressure space" plots
  the SAME points as panel (a) with the x-axis rescaled (temp → p=T/T_safety).
  Redundant. Keep (a), cut (b) or merge.

### WRONG DATA / RECALIBRATE
- **F-DATA-1 (D_eff overloaded — the big one):** D_eff is plotted as FOUR
  different numbers under one name — 3.00 (predecessor/baseline: fig2_dky_scale,
  fig2b_basin, fig4_senescence), ~5 (thermal cycling: fig_tc01_composite),
  5.0/3.89 (demon: fig_oe02), while the TEXT/tables say 6.00 (canonical). Every
  D_eff figure shows the predecessor-law value; the canonical measurement is
  "pending". FIX: regenerate under the canonical law (→6.00) AND disambiguate
  the name (D_corr for PCA ≈2–3; D_eff for the heuristic; formal D_KY=0).
- **F-DATA-2: fig3_multikernel_geometry — trust_final axis is NEGATIVE**
  (−0.05 to −0.35). Trust ∈ [0,1] by definition. A plotting bug (sign flip or
  wrong axis mapping). The cosine matrix (left panel) is correct; the right
  panel's trust axis is wrong. FIX the axis.
- **F-DATA-3: fig5_rtr is marked "schematic"** — illustrative, NOT measured, in
  a paper whose thesis is "everything is measured." Either replace with real
  recursive_thermal_ramp data or mark it clearly as schematic in the caption
  (currently the "schematic" watermark is easy to miss).
- **F-DATA-4 (IMG-5): embedded figure numbers disagree with LaTeX** — in-image
  suptitles say "Figure 7/6/2…" from an old hardcoded numbering; LaTeX numbers
  by order. Reader sees two different numbers. Drop the numbered suptitles from
  the scripts.

### TERMINOLOGY (post-refinement drift)
- **F-TERM-1: fig5_rtr title "attractor cone"** → "stasis cone" (renamed in the
  text per R3). Same for any other in-image "attractor cone".

### COSMETIC (minor)
- fig9_topology panel (a): symlog y-axis shows NEGATIVE Betti numbers (β≥0 by
  definition) — an empty negative axis. Use a linear/log axis without the
  negative range.
- fig_oe02_real_demon: the red (B-demon) band is a solid saturated block (50k
  ticks of dense oscillation) — hard to read detail. Downsample or alpha it.

### GOOD — keep as-is (real variation, coherent with text)
- Fig 1 omega (diana ✓), fig7_vmem (2→1 collapse), fig6_trust_bifurcation
  (dual attractor), fig11_sustained_noise (V(σ) curve, matches corrected text),
  fig9_topology (β0=1/β1=0, 79× separation), fig_v_capstone (V=min break table —
  well designed), fig_soplo_landauer (4 panels, honest about the seed's wrong
  sign), fig_tc01_composite (main panels), fig8 panel (a), fig3_thermal (a).

### NOT individually inspected (variants of the above; spot-clean)
- fig1_lyapunov, fig4_theta_psi, fig_tc01_dips, fig_slack_census,
  fig_v_discrimination, fig_trust_two_law, fig1_thermal_response.

### SUMMARY for rmw3
- **Cut 4** (Fig5-3D, fig8-b, fig10, fig3-b) — all flat/redundant.
- **Recalibrate/fix 4** — D_eff overload (many figs), trust-negative axis
  (multikernel), schematic fig5_rtr, embedded numbering. D_eff is the big one.
- **Rename 1** — attractor→stasis cone in fig5_rtr.
- Data figures need script edits + (for D_eff) canonical-law data → DS work,
  gated on the canonical re-measurement existing.

---

## FIX STATUS (updated 2026-07-13, commit b46a6cc)
- ✅ **R2, R6, R7, R8, R9 — FIXED** in the exhaustive propagation pass. All
  text-level; paper compiles 70pp, 0 undefined refs. Residual check clean
  ("twice the state norm", "globally contract", "spherical cap" all gone;
  both "non-expansive" occurrences now consistent).
- ✅ **R3 — FIXED (commit c6b318e):** nesting declared once in §Attractor geometry
  (viable Ω / core Ω_A / stasis cone 18.2°); every ambiguous "attractor cone"
  renamed to "stasis cone"; the real error (cos=0.9365 "within cone" — it's < 0.95
  so outside the stasis cone but inside Ω_A) corrected to "within Ω_A" at both
  sites (L99 intro, table row); "cone apex" → "apex (cos=1)". Exhaustive check
  clean, compiles 70pp.
- ✅ **R4 — FIXED (commit c6b318e):** Discussion portrait now reads "in stasis the
  trajectory occupies an 18.2° cone … the full trajectory, including transient,
  spans cos 0.61–1.00 within Ω."
- ⬜ **R1 — OPEN (design):** redraw fig:omega_nested (four-object nested geometry).
  Held for rmw3's figure-review pass (visual-style / redundant-figure cleanup).

---

## FINDINGS — RIGOR (figure↔text coherence + logical consistency)

### R1 — CONTRADICTION: the Ω figure is drawn convex; the text says Ω is not convex
- **Where:** `fig:omega_nested` (tikzpicture ~L671) draws Ω as a smooth convex
  ellipse and Ω_A as a concentric convex ellipse. The text (L644) states
  plainly "Ω is **not** convex."
- **Why it matters:** a reader who sees "Ω is not convex" then a convex ellipse
  registers an immediate contradiction — and Fierro, who raised the convexity
  objection (Q1), is the reader most primed to catch it. This is the exact
  fallacy-class rmw3 flagged.
- **Severity:** HIGH — it undercuts the paper's strongest response to Q1.
- **Fix direction:** redraw Ω with an irregular (non-convex) boundary; draw Ω_A
  as a convex CONIC WEDGE from the origin (that is what {cos ≥ θ} looks like),
  nested inside Ω. See R3 for the full four-object structure.

### R2 — INTERNAL INCONSISTENCY: "spherical cap" vs "circular cone ∩ bounded set"
- **Where:** L659 still says Ω_A is "a spherical cap, compact and convex" (the
  OLD description, the one we corrected in the addendum as imprecise — a
  spherical cap is not convex in the ambient space). L713 already says the
  correct "intersection of a circular cone (convex for θ_A ≥ 0) with the bounded
  state set."
- **Why it matters:** two different descriptions of the same object Ω_A on
  adjacent pages — a residue of partial editing. The "spherical cap … convex"
  form is the one Fierro would challenge.
- **Severity:** MEDIUM — internal, correctable in one edit.
- **Fix:** replace L659 "spherical cap" with the cone∩bounded-set formulation;
  sweep for other "spherical cap" occurrences.

### R3 — AMBIGUITY: one word "cone" for THREE nested objects of different angle
- **Where:** "cone" appears ~12× (L99, 543, 713, 937, 950, 965, 997, 1093,
  1103, 1114, 2016, 2633). It denotes at least three distinct sets:
  1. the **empirical attractor cone** — 18.2° (cos ≥ 0.95), where stasis
     observations actually sit (fig:basin caption L997, Discussion L3566);
  2. **Ω_A**, the contractive core — cos ≥ 0.88 (θ_A, the "Fierro bound");
  3. **Ω**, the viable region — cos ≥ 0.70.
- **Why it matters:** the reader cannot tell which cone a given sentence means.
  "well inside the attractor cone" (L99) uses #1; "at the cone apex" (L937,950)
  is ambiguous; Theorem 1 uses #2. Three angles, one word.
- **Severity:** MEDIUM-HIGH — geometric clarity is the paper's backbone.
- **Fix:** name them distinctly — e.g. "stasis cone (18.2°)", "contractive core
  Ω_A", "viable region Ω" — and state the nesting explicitly once.

### R4 — POTENTIAL OVERCLAIM: "attractor is an 18.2° cone" vs trajectory spans cos 0.61–1.00
- **Where:** Discussion L3566 "Compact: 18.2° cone"; but TDA method (L~1258)
  reports the full trajectory spans stasis cosine 0.61–1.00 with mean distance
  to centroid 0.786. The 18.2° cone (cos ≥ 0.95) is only the STASIS regime.
- **Why it matters:** during transient/breathing the system LEAVES the 18.2°
  cone. Saying "the attractor is an 18.2° cone" is true for stasis but a reader
  may take it as "the system is always in the cone," which is false. fig:basin
  plots only the 139 STASIS observations (correct), but the prose doesn't guard
  the distinction.
- **Severity:** MEDIUM — true-but-easily-misread; one clause fixes it.
- **Fix:** "the STASIS attractor occupies an 18.2° cone; the full trajectory,
  including transient, spans cos 0.61–1.00 within Ω."

### R6 — NUMERICAL INCONSISTENCY: the noise range is described as "twice" AND "four times" the state norm
- **Where:** the same EXP-NS-01 amplitude is called "**twice** the state norm"
  at L105 (abstract/intro), L1226 (table caption), L3080 (Limitations) — but
  "**four times** / fourfold" at L751 (Remark) and L1243 ("σ=2.0 … fourfold").
- **Ground truth (FIERRO-NS-RANGE, DS):** the parameter σ ranges 0→2.0, and
  σ=2.0 corresponds to noise = 4× the state norm. So "σ=2.0" and "four times the
  norm" are both correct; "twice the state norm" is WRONG — it confuses the
  parameter value (2.0) with a norm multiple (which is 4×).
- **Why it matters:** a probabilist will read the numbers. FIERRO-NS-RANGE fixed
  the ADDENDUM and one paper site (L751) but left L105, L1226, L3080 saying
  "twice." Also fig:sustained_noise (L1235) calls σ≈1.0 the "extreme regime"
  while the sweep runs to σ=2.0 — a second numeric slip.
- **Severity:** MEDIUM-HIGH — Fierro-visible, it's arithmetic.
- **Fix:** every occurrence → "four times the state norm (σ up to 2.0)"; fix the
  "σ≈1.0 extreme" caption.

### R7 — CONTRADICTION: "globally contracting" (L2040) vs the L_f>1 refinement
- **Where:** the emergent-envelope Remark (L2040) says "the kernel's free
  dynamics -- **globally contracting**, λmax = ln 0.99 < 0."
- **Why it matters:** λmax<0 is contraction ON AVERAGE (a Lyapunov-exponent
  statement); "globally contracting" asserts per-step global contraction, which
  is exactly what DS's measured L_f ∈ [1.4, 24.4] REFUTES and what the addendum
  explicitly disclaims. Fierro reading "globally contracting" here, then "L_f>1,
  no per-step contraction off the core" in the addendum, sees a contradiction.
- **Severity:** MEDIUM-HIGH — direct clash with the central refined claim; but
  it's one word in a secondary Remark.
- **Fix:** "contracting on average (λmax = ln 0.99 < 0)" — the Remark's point
  (free dynamics bound the excursion tightly) survives unchanged.

### R8 — INTERNAL CONTRADICTION: figure caption says "non-expansive" off-core; theorem says it does not claim that
- **Where:** fig:omega_nested caption (L701) — "excursions into Ω\Ω_A are
  **non-expansive** and confined." Theorem 1 (L734, edited) — "we do **not**
  claim per-step non-expansiveness … the worst-case Lipschitz [bound exceeds 1]."
- **Why it matters:** the caption and the theorem it illustrates now disagree.
  The L_f correction was applied to the theorem but not propagated to the caption.
- **Severity:** MEDIUM — internal, one-line fix.
- **Fix:** caption → "excursions into Ω\Ω_A are confined (return in finite time),
  though not per-step non-expansive."

### R9 — HONESTY OPPORTUNITY: L_f>1 is disclosed only in the theorem, not in Limitations
- **Where:** L_f∈[1.4,24.4] appears only at L734 (theorem). Limitations does not
  acknowledge it as a residual.
- **Severity:** LOW — not a contradiction; disclosing the ugly bound in
  Limitations too would strengthen credibility with a hostile reader.
- **Fix (optional):** one Limitations sentence: "the global Lipschitz bound
  exceeds 1; confinement off the core is empirical, not a per-step guarantee."

---

### R10 — TERMINOLOGY: "stable fixed point" vs "not a fixed point but a compact region"
- **Where:** L91 "a stable fixed point", L132 "point attractor", L350/869/878/890
  "point sink" — but L978 "The attractor is **not a fixed point** but a compact
  region"; L1016 "point attractor in the stasis subspace."
- **Root:** the paper conflates three distinct objects: the DETERMINISTIC
  attractor of f₀ (a unique fixed point s̄, Banach), the OBSERVED stochastic
  attractor (a compact region — the stasis cone — because noise + breathing give
  it extent), and the TOPOLOGY (a point sink: β₀=1, β₁=0, no cycle). All three
  are consistent, but L978's bare "not a fixed point" clashes with L91's "fixed
  point" for a reader who doesn't supply the deterministic/observed distinction.
- **Severity:** MEDIUM — apparent contradiction; Fierro-visible.
- **Fix:** state the distinction once — "the deterministic map has a unique fixed
  point s̄; under noise the observed attractor is a compact region around it (the
  stasis cone), whose topology is a point sink." Then L978 → "the observed
  (noisy) attractor is not a single point but a compact region around the
  deterministic fixed point."

### R11 — NOTATION: the symbol D_KY is used for BOTH the formal (=0) and the heuristic (≈2–3) dimension
- **Where:** L889 "Kaplan–Yorke dimension of 0 — a point sink" and L227 "KY
  dimension zero" (the FORMAL KY, from the all-negative spectrum) — but L980
  "consistent with $D_\text{KY} \approx 2$–$3$" and L1651 "$D_\text{KY} = 3.00$"
  use the SAME symbol for the D_eff heuristic (active_dims + trust×2). The paper
  itself repeatedly warns they differ (L894, L986, L3063, L3070, L3197: "D_eff
  heuristic, NOT the formal Kaplan–Yorke"), then uses D_KY for the heuristic anyway.
- **Severity:** MEDIUM — a probabilist reads "D_KY ≈ 2–3" against an all-negative
  spectrum (which forces formal D_KY = 0) as an error. Self-inflicted by symbol reuse.
- **Fix:** L980 and L1651: `D_\text{KY}` → `D_\text{eff}` (they denote the
  heuristic). Reserve `D_KY` for the formal =0 value only.

---

## META-FINDING — the paper has the SAME debt class we've been fixing in DS

R1, R2, R7, R8 are all the same shape: the convexity-free + L_f-disclosure
correction was applied to the CENTRAL objects (Theorem 1 L713–734, intro L82,
contributions L335) but NOT propagated exhaustively to the PERIPHERAL ones that
depended on the old claim — the figure (drawn convex; caption "non-expansive"),
the envelope Remark ("globally contracting"), the "spherical cap" residue, the
noise "twice" descriptions. This is a **partial edit** — the exact
"verify/propagate the happy path, not the whole affected set" failure we just
flagged in DS's work (SHA_DRIFT, skipped resize, the 80 untokened nodes).
The lesson recurses: after any central correction, sweep EVERY dependent site.

**Deeper root (R3, R4, R10, R11):** the paper does not consistently distinguish
three views of the same object on the surface, even where it distinguishes them
in principle: the DETERMINISTIC f₀ (fixed point, formal D_KY=0, contraction on
average), the OBSERVED stochastic process (compact stasis cone, D_eff≈2–3,
confinement), and the TOPOLOGY (point sink, β₀=1). The cones (R3), the "18.2°"
claim (R4), fixed-point-vs-region (R10), and D_KY-vs-D_eff (R11) are all this one
imprecision surfacing in different places. A single "name the three views once"
convention (as done for the cones in R3) resolves the whole family.

---

### R5 — RESOLVED: β₀=1,β₁=0 "point sink" vs the two-regime confinement picture
- **Observation:** TDA gives β₀=1, β₁=0 (a contractible blob, point sink). This
  is consistent with Proposition-1 existence. BUT the refined argument now has
  TWO regimes (contraction in Ω_A, confinement-only in Ω\Ω_A). A point-sink
  topology describes the stasis attractor; it says nothing about the off-core
  regime. **RESOLVED:** β₀=1 is NOT used to imply global contraction; the one
  global-contraction claim is the wording at L2040, captured as R7. β₀=1,β₁=0 as
  a stasis-attractor topology is sound. No action beyond R7.

---

## STATUS after pass 3 (AUDIT COMPLETE — functional + full sweep)
- **Functional (§capstone): CLEAN.** It uses `c` as a SIGN gate of λmax, explicitly
  "not a contraction strength — no scale-free notion of how fast a system
  contracts." It already frames itself in Fierro's Q0–Q3. No convexity/global
  assumption. No finding.
- **Two new findings this pass: R10 (fixed-point vs compact-region), R11 (D_KY
  symbol reused).** Both text-level, both instances of the deeper root above.
- **Rigor grid CLOSED.** Eleven findings total. No fabrication, no false theorem,
  no logical fallacy in the argument. All defects are propagation residues +
  surface imprecision between the deterministic / observed / topological views.
  Open items: R1 (figure), R10, R11 (text) — held for the next propagation pass
  alongside rmw3's figure review.

## STATUS after pass 2 (geometric core + noise + Experiments spot-sweep)
- Figures swept: fig:omega_nested (R1,R8), fig:basin (R3,R4),
  fig:multikernel (R3), fig:sustained_noise (R6). Coherent-enough:
  fig9_topology, fig10_lyapunov (not flagged).
- Global-contraction/convex language: swept; one real hit (R7 L2040), plus the
  known residues (R2 L659). Functional (§capstone) does NOT assume convexity
  (grep clean) — but not yet read line-by-line.
- Verdict: the paper's math body is SOUND; the defects are propagation residues
  (meta-finding), not logic errors. No fabrication, no false theorem.

## PENDING (next passes, lower priority)
- Coordinate-Free Functional (§capstone) — line-by-line read (grep clean so far).
- Experiments 1–12 full read for softer residues (only spot-swept).
- Jargon line-map for the math sections (de-jargon targets) — deferred until
  audience decision (Fierro vs journal).

## RECOMMENDED FIX PLAN (once rmw3 approves)
1. **One exhaustive propagation pass** (fixes R2,R6,R7,R8 — all one-line text
   edits + the noise arithmetic). Low risk, high credibility gain.
2. **Redraw fig:omega_nested** (R1) — the four-object nested geometry with
   non-convex Ω, conic Ω_A wedge, stasis cone, two regimes. The one real
   figure job.
3. **Clarify the three cones** (R3) — name them distinctly, state nesting once.
4. **Guard the 18.2° claim** (R4) — one clause.
5. THEN selective de-jargon (audience-dependent).
