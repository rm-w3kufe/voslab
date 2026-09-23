# Certified UNKNOWN: Proof-Carrying Abstention for Governed Autonomy

> NOT valid VSL — arXiv working draft (Markdown, destined for LaTeX).
> Exempt from .vsm policy by destination format (cf. docs/archive/*.md
> precedent). Content is normative for the publishing track.

**Working draft** — vOSlabai / rmw3 — 2026-09-23 — status: outline + measurementsbrief, sections in progress.

> Target: arXiv cs.AI (systems paper with code + measurements, NOT a
> survey). Requires endorsement (path 2: personal, domain authors).
> Related: arXiv:2603.16586 (deterministic policies), arXiv:2604.19818
> (proof-of-guardrail), arXiv:2606.02965 (informed abstention).

## Abstract (draft)

Agentic benchmarks saturate on task success while ignoring whether the
agent *should have acted at all*. We present a control plane for
governed autonomy built on three mechanisms: (1) **trivalent evaluation
with certified abstention** — UNKNOWN outputs carry machine-checkable
proof of indeterminacy (`indeterminacy` evidence block) or are degraded
to uncertified by a runtime gate; (2) **jury operators** that certify
disagreement itself (hung verdicts with tallies, quorum rules); and
(3) **evolutionary strategy search** with shadow-mode validation and
cross-cycle retention. Measured on a 6-suite battery (H1–H5 + ARC
harness, all replayable): precision@certified = 1.0 with zero false
certifications across 16 adversarial cases; ablations without abstention
take 9 unfounded actions where the system abstains; generational search
beats equal-budget random search 3/3 with non-negative slopes and no
holdout regression; governance overhead p95 229ms per tool call with
130B/action audit volume; 16/16 chaos scenarios degrade gracefully with
zero escaped exceptions. Head-to-head on honesty scenarios vs LangGraph
defaults (3/3 vs 0/3 correct abstentions at policy-LOC parity) and vs
NVIDIA NeMo Guardrails' deterministic layer (5/5 rail verdicts; NeMo's
`unclear` is a dialog act with no truth value, no certification
vocabulary, and no propagation algebra). All artifacts, seeds, and
replay hashes are published with the paper.

## 1. Introduction

- Task benchmarks (SWE-bench ~95%, τ²-bench ~99%) saturate; they measure
  the underlying model, not the governance architecture. Category error
  to compete there with a control plane.
- The open question (2606.02965, 2604.19818, 2603.16586): who decides
  whether to act, with what evidence, at what cost — and can we verify
  the guardrail ran?
- Thesis: separate *truth* (trivalent) from *certification*
  (evidence-backed), make abstention proof-carrying, evolve strategies
  under shadow validation, account governance cost honestly.

## 2. Related work

- Runtime Governance as deterministic policies over paths (2603.16586):
  independent derivation of our R10 (audit logs unverifiable under
  nondeterministic policy evaluation).
- Proof-of-Guardrail + trace contracts + fault injection (2604.19818):
  our JSONL logs, negative controls, H4 chaos, replay hashes.
- Informed Abstention framework (2606.02965): 144 scenarios × 7 model
  families; penalization of pausing in current benchmarks; need for
  runtime enforcement + calibrated guards + auditable traces. Our H1
  is a running instantiation with falsifiable thresholds.
- NeMo Guardrails (Colang, 5 rail types): programmable, interpretable,
  model-independent — closest existing system; differs in LLM-centric
  runtime (dialog progression requires model calls) and absence of
  uncertainty propagation semantics.
- Kasirzadeh & Gabriel (Nature 2026): agentic profiles
  (autonomy/efficacy/goal-complexity/generality) — our system targets
  high-autonomy + high-efficacy with proportional safeguards (WEF/IMDA
  progressive governance).

## 3. Architecture

- 3.1 Trivalent engine + certification algebra (AND/OR/NOT/XOR/IMPLIES/
  DIALECTICAL_AND/JURY, computation nodes).
- 3.2 Indeterminacy vocabulary + validation gate (R10-corolario).
- 3.3 Jury operator (supermajority, quorum, tally evidence).
- 3.4 RSI loop (generational GA, shadow mode, retention, registries).
- 3.5 Cost accounting (per-eval audit persistence design, sampling).

## 4. Measurements (baseline_v2, replay 89616a69f91f74aa)

| Suite | Result |
|---|---|
| H5 determinism | 270 evals × 3 hash seeds, 0 divergences |
| H1 honesty | precision@certified 1.0, false-cert 0; baselines 9 unfounded vs 0 |
| H2 evolution | slopes ≥ 0 (3 faults), holdout 1.0, ablation 3/3 |
| H3 cost | p95 229ms < 500ms; 130B/action; fixes documented (5s→36ms record path) |
| H4 chaos | 16/16 graceful, 0 escaped |
| ARC lane | 12/12 valid, floor 0.0% (no solver — honest) |
| vs LangGraph | 3/3 vs 0/3 abstain, LOC parity |
| vs NeMo rails | 5/5 rail verdicts; deltas documented |

## 5. Discussion

- What the red H3 taught (honest failure → profile → fix → green).
- What H2 taught (retention gap found by measurement, not review).
- What H4 taught (observer-effect heal: introspection mutating health).
- Limits: no LLM-judge external baseline (no API budget); no hardened
  adversary yet (NeMo full-stack needs LLM backend); ARC solver future.

## 6. Future work

- ARC program-synthesis solver over grid DSL (harness ready).
- Round-2 comparison vs hardened stacks.
- Codabench publication of H1–H5 as runnable benchmark.
- Async audit persistence (durability-preserving design).

## Reproducibility

- Repos: socratic-engine v0.2.12, vsf-rsi v0.2.16 (tags, PyPI).
- Battery: `python3 benchmarks/run_all.py` (seed 20260922).
- Results: `benchmarks/results/baseline_v2.json`,
  `compare_lg_v1.json`, `compare_nemo_v1.json` (replay hashes inside).
