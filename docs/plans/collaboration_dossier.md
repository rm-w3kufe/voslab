# Academic collaboration track — dossier (NOT valid VSL: outreach working doc)

Status: dossier ready. SENDING is rmw3's (identity + email + timing).
Rule: no mass emails (arXiv etiquette) — one tailored contact per group,
with our numbers attached. Goal per group is concrete (endorsement,
joint eval, benchmark slot), never "collaborate generally".

## Group A — Ojewale & Venkatasubramanian (Brown)
- Paper: Designing for Doubt (2606.02965v2, AIES 2026). Contact:
  victor_ojewale@brown.edu, suresh@brown.edu.
- Why us: closest fit on earth. Their taxonomy (specification /
  verification / authority gaps) + Safety/Usability/Informed-Refusal
  rates maps 1:1 onto our H1 battery. Our certified-UNKNOWN doctrine
  (indeterminacy vocab + gate + JURY) is the machine-checkable form
  their framework calls for but doesn't specify.
- Offer: independent replication of their protocol on a non-LLM
  substrate (deterministic engine, 16 adversarial cases, no judge
  noise) + our 3-gap taxonomy extension (proven-indeterminacy kinds).
- Ask: feedback on the mapping + arXiv endorsement in cs.AI (they
  qualify as established authors in-domain).
- Our numbers to attach: H1 precision@certified 1.0, false-cert 0.0,
  baselines 9 unfounded vs 0 (replay 89616a69f91f74aa).

## Group B — Kaptein / Khan / Podstavnychy (TU/e + Kyvvu)
- Paper: Runtime Governance as Policies on Paths (2603.16586).
  Contact: m.c.kaptein@tue.nl (corresponding).
- Why us: independent derivation of their core thesis (our R10:
  audit logs unverifiable under nondeterministic evaluation) +
  running system + cost data. Their open problems (risk calibration,
  limits of enforced compliance) are our H3/H4 territory.
- Offer: risk-calibration measurements (p95/latency/attenuation
  numbers) + a deployed-policy case study (covenant seed on LXC).
- Ask: feedback + arXiv endorsement fallback if Group A is slow.

## Group C — AbstentionBench team (Meta FAIR)
- People: Kirichenko, Ibrahim, Chaudhuri, Bell. Repo:
  facebookresearch/AbstentionBench (20 datasets, 35k questions).
- Why us: architecture-level abstention (control plane deciding FOR
  the model) vs their model-level measurement. Their headline finding
  (reasoning fine-tuning degrades abstention 24%) is exactly what a
  decoupled governor fixes by construction.
- Offer: run our governor over their subsets once we have an LLM
  backend (blocked today) + contribute the control-plane pattern.
- Ask: nothing until backend exists. Track as phase-2 contact.

## Group D — HAL Princeton (sayashk, arvindn@cs.princeton.edu)
- Venue: scaffold-aware leaderboard (21,730 rollouts, costs tracked).
- Why us: HAL measures SCAFFOLDS separately from models — the only
  leaderboard where architecture (not weights) is the variable.
- Offer: our scaffold as a submission (deterministic governance
  layer + measured cost).
- Ask: submission criteria + queue. Needs public repos first (A1).

## Sequencing
1. A first (best fit + endorsement path). Draft below.
2. B in parallel (different people, no conflict).
3. D after A1 (needs public artifacts to point at).
4. C after LLM backend exists.

## Draft — Group A (rmw3 sends, adapt tone freely)

Subject: independent replication of your abstention protocol on a
deterministic substrate (+ endorsement request)

Dear Victor and Suresh,

Your "Designing for Doubt" reframed our work: we had built a trivalent
evaluation engine with certified abstention without knowing your
taxonomy existed. Mapping it was almost 1:1 — our ignorance cases are
your specification gaps, our conflicts are verification gaps, our
policy blocks are authority gaps.

Two things that may interest you:
(a) We run your protocol shape (Safety/Usability-style rates +
falsifiable thresholds) on 16 adversarial cases with fully
deterministic scoring — no LLM judge, no rater variance:
precision@certified 1.0, zero false certifications, and ablations
showing 9 unfounded actions where the system abstains.
(b) We extended the taxonomy with proven-indeterminacy kinds
(undecidable-reduction, hung-jury with quorum, exhaustive-empty…):
cases where UNKNOWN is certified *with proof attached*, enforced by
a runtime gate. Precedent: Scots 'not proven' verdicts.

Everything is replayable (seeds + hashes in the repo; happy to share
a private link before anything is public).

Two asks, either welcome independently:
1. Does the mapping to your taxonomy survive contact with your
   definitions? We'd value 10 minutes of your criticism.
2. We're preparing an arXiv submission in cs.AI and need an
   endorser in-domain — would you consider it on the strength of
   the draft (attached on request)?

Thank you for the paper — it gave our engineering a name.

Best regards,
rmw3
[vOSlab — governed autonomy lab]
