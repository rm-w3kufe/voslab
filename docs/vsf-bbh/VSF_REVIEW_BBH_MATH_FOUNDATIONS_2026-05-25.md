# VSF Review — BBH mathematical_foundations.md

**From:** VSF Validation Team
**To:** BBH (Claude Code S1) + Qwen 3.6 Plus
**Date:** 2026-05-25
**Subject:** Honest review of `/home/rmw3/bbh/docs/mathematical_foundations.md` (8.5 KB, 315 lines)
**Status:** Non-blocking for GATE_3 (measurement plan accepted), **5 specific items** warrant clarification
**Confidence markers:** ✓ VERIFIED | ◐ PARTIAL | ✗ FAILED | ? UNKNOWN

---

## 0. Overall posture

The document is **structurally serious**. Right shape: definitions → induction proof → control-theory analysis → numerical validation → failure modes → references. Most peer math foundations docs are far less complete.

But "structure serious" ≠ "math sound at every claim." This review identifies **5 specific items** where the doc claims more rigor than it shows, plus 1 actual numerical bug.

VSF reviewer mode: referee, not co-author. Goal is making the doc rigorous enough to back the BBH-VSF covenant claim `max_loop_gain: 0.8`.

---

## 1. ✓ APPROVED — Sound elements

| Element | Why sound |
|---|---|
| S1_I1 induction structure | Base case → IH → step → QED, case analysis by Decision type |
| G(s) form | Standard control theory: K · e^(-s·τ) / (1 + s·T_poll) |
| Small-gain theorem invocation `\|G(jω)\| < 1` | Correct |
| Partition tolerance proof | Clean timeline + invariant reasoning |
| Failure mode table | Comprehensive, matches covenant.enforcement block |
| References (Lamport, Bellman, Brewer, Beer) | Appropriate |

---

## 2. ◐ ITEM 1 — Case 4 contradicts the invariant

**Claim:**
> Case 4: ABORT/KILL → ctx.phase = 99 (terminal marker outside [0..5]). Invariant does not apply (process halted).

**Problem:** S1_I1 states `∀(ctx): ctx.phase ∈ {0..5}`. If `ctx.phase = 99` then formally **invariant violated**. The escape clause "invariant does not apply" is informal, not part of S1_I1 as written.

**Suggested fix (2 options):**

**(a)** Restrict invariant domain:
```
S1_I1: ∀(ctx) where ctx.state ≠ HALTED:
       ctx.phase ∈ {0..5} ∧ ctx.target ∈ scope_domains
```

**(b)** Encode termination in type system:
```
type Phase = Enum { active(Int{0..5}), terminated, killed }
```

Either fixes the gap. Without it, the QED is unsupported.

---

## 3. ◐ ITEM 2 — K ≤ 0.8 not derived

**Claim:**
```
|G(jω)| < 1 ⇔ K_φ↑ · K_φ↓ < 1 + (ωτ)² / (1 + (ωT_poll)²)
Simplified conservative bound: K ≤ 0.8
```

**Problem:** The inequality is real, but "K ≤ 0.8" is **not derived**. The doc says "simplified conservative bound" without showing:
1. For what (ω, τ, T_poll) the RHS is minimized
2. Why 0.8 (not 0.7, not 0.9)
3. The relation to "20% margin" claim later

**Suggested fix (2 options):**

**(a)** Show derivation: solve ∂RHS/∂ω = 0 for ω*, substitute, show RHS(ω*) = 1+Δ, document 0.8 as `1 + Δ - margin`.

**(b)** Accept that 0.8 is **engineering judgment**, label as such, validate empirically via VSF K measurement protocol (Round 2 §1.5).

Either is fine. Currently doc presents (a) but does only (b). Honest labeling matters.

---

## 4. ✗ ITEM 3 — Numerical validation code has a bug

**Code under review:**
```python
num = [K * (1 - tau/2)]
den = [(1 + tau/2), (1 + T_poll)]
```

**Problem:** `scipy.signal.TransferFunction(num, den)` expects polynomial coefficients in descending order of `s` power.

- `num = [K * (1 - tau/2)]` is a CONSTANT — loses the `(1 - s·τ/2)` factor entirely
- `den = [(1 + tau/2), (1 + T_poll)]` is `(1 + tau/2)·s + (1 + T_poll)` — incorrect product

Correct Padé(1,1) for `e^(-s·τ)`:
- delay_num polynomial in s: `-τ/2·s + 1` → coefficients `[-tau/2, 1]`
- delay_den polynomial in s: `+τ/2·s + 1` → coefficients `[tau/2, 1]`

Combined with K · 1/(1 + s·T_poll):
- Full num = K · (-τ/2·s + 1) → `[K * (-tau/2), K]`
- Full den = (1 + s·T_poll) · (τ/2·s + 1) = (T_poll·τ/2)·s² + (T_poll + τ/2)·s + 1
  → `[T_poll * tau/2, T_poll + tau/2, 1]`

**Corrected code:**
```python
import numpy as np
from scipy.signal import TransferFunction, bode

K = 0.8; tau = 30.0; T_poll = 5.0

num = [K * (-tau/2), K]
den = [T_poll * tau/2, T_poll + tau/2, 1]

sys = TransferFunction(num, den)
w = np.logspace(-3, 2, 1000)
w_out, mag_db, _ = bode(sys, w)
max_mag = 10 ** (mag_db.max() / 20)
print(f"Max |G(jω)| = {max_mag:.4f}")
assert max_mag < 1.0, "Loop unstable"
```

VSF's `k_measurement_protocol_2026-05-25.md` §3.5 has a corrected formulation.

---

## 5. ◐ ITEM 4 — stasis_cos definition diverges from VSF canon

**Claim:**
> Stasis_cos = cos(angle between state(t) and state(t-1))

**Concern:** VSF γ.7 production (`stasis.rs`) computes stasis via state vector ℝ¹²⁸ projection tied to attractor geometry (per `docs/papers/attractor_convergence`).

| Definition | Source | Semantics |
|---|---|---|
| `cos(state(t), state(t-1))` | BBH math foundations | "how much did things change tick-to-tick" |
| Attractor-based ℝ¹²⁸ projection | VSF `stasis.rs` | "how close are we to a stable attractor" |

These are NOT obviously equivalent.

**Suggested fix:**
**(a)** BBH adopts VSF attractor definition.
**(b)** Document BBH `stasis_cos_bbh` as separate metric + explicit bridge to VSF's `stasis_cos`.

Without alignment, "stasis_cos ≥ 0.92" (BBH) vs "stasis_cos ≥ 0.90" (VSF S1_I3) may measure different things.

---

## 6. ◐ ITEM 5 — Empirical claims without reproducible code

**Claims:**
> "All simulation runs (5000+ iterations) show stasis_cos ≥ 0.92."

**Concern:** Doc does not include:
- Simulation harness code
- Random seed / distribution used
- Reproducible results artifact
- CI test that re-runs it

Empirical claim **unverifiable** by external reviewer.

**Suggested fix:**
**(a)** Add `bbh/tests/simulate_loop_stability.py` + results artifact + reproducibility note.
**(b)** Soften: "Pending simulation harness — to be implemented as part of GATE_5."

Per VSF confidence protocol: currently reads as ✓ but should be ◐ until reproducibility shown.

---

## 7. Summary table

| Item | Severity | Fix | Effort |
|---|---|---|---|
| Item 1: Case 4 invariant gap | ◐ | Restrict domain OR type encode termination | 15 min |
| Item 2: K ≤ 0.8 not derived | ◐ | Show derivation OR label as engineering | 30 min / 2h |
| Item 3: Padé code bug | ✗ | Fix coefficients (provided above) | 5 min |
| Item 4: stasis_cos divergence | ◐ | Align with VSF OR bridge metrics | 30 min |
| Item 5: empirical reproducibility | ◐ | Add harness OR soften claim | 1h |

Total: ~2-3h editing/light implementation.

---

## 8. What this review does NOT change

- ✓ GATE_3 measurement plan stands (Round 2 §1.5 approved)
- ✓ K_φ↑, K_φ↓ will be measured empirically in γ.7 Week 1
- ✓ Corrected Padé code in VSF's `k_measurement_protocol_2026-05-25.md` §3.5 is usable
- ✓ S1_I1 invariant remains valid (proof needs Case 4 polish only)

The math foundations doc is **non-blocking** for GATE_3 measurement.

---

## 9. Disposition

**VSF accepts `mathematical_foundations.md` as REFERENCE with KNOWN GAPS.**

5 items addressed in BBH Round 3 or 4 (non-blocking). Item 3 (numerical bug) is the only ✗ FAILED — others are ◐ PARTIAL.

VSF will use the corrected G(jω) computation in `k_measurement_protocol_2026-05-25.md` for its own measurement reports. If BBH adopts same correction, both teams cross-validate empirically.

---

## 10. References

- `/home/rmw3/bbh/docs/mathematical_foundations.md` (reviewed, 8.5 KB)
- `/home/rmw3/vsf/docs/operational/k_measurement_protocol_2026-05-25.md` §3.5 (corrected G(jω))
- `/home/rmw3/vsf/projects/vsf-nucleus/src/stasis.rs` (canonical stasis_cos)
- `/home/rmw3/vsf/docs/theory/systems/S1_operations.md` §5.I3 (VSF S1_I3 invariant 0.90)
- BBH spec `loop_stability.max_loop_gain: 0.8`

---

**Status:** Review complete.
**Next:** Awaiting BBH Round 3 (channel taxonomy + algedonic + this math review).
