# VSF — Human Guide
# How to read, write, and think in VSM notation
# Version: 0.1 | Audience: humans first, machines second

---

## What is this?

VSM notation is a compact formal language for describing systems that need to
**stay alive under pressure** — managing resources, routing information, and
making decisions at multiple levels simultaneously.

It is based on Stafford Beer's Viable System Model (1972), which was originally
designed to model organizations as nervous systems. We extend it to software,
AI agents, and any complex system that needs to self-regulate.

**One sentence:** VSM notation lets you write down *how a system governs itself*
in a form that both humans and machines can read, verify, and execute.

---

## The five building blocks

Every viable system has exactly five subsystems. Always. If one is missing,
the system is not viable — it will eventually fail to adapt.

```
S1 — Operations      "the units that do the work"
S2 — Coordination    "prevents the units from stepping on each other"
S3 — Control         "allocates resources, monitors performance"
S4 — Intelligence    "watches the environment, plans ahead"
S5 — Policy          "sets the rules that nobody can override"
```

Think of it like a living organism:
- S1 = muscles and organs (do the work)
- S2 = nervous reflexes (coordinate without thinking)
- S3 = metabolism (allocates energy, monitors vitals)
- S4 = brain (perceives environment, models the future)
- S5 = DNA (the constraints that define what the organism is)

---

## The recursion principle

**The most important idea:** any S1 unit can itself be a complete viable system.

```
V("company", L=0)
  S1: [ V("division-A", L=1), V("division-B", L=1) ]
                                    ↓
              V("division-A", L=1)
                S1: [ V("team-1", L=2), V("team-2", L=2) ]
```

A team is a viable system. A division made of teams is a viable system.
A company made of divisions is a viable system. Same structure, different scale.

This is what makes VSF scale-invariant — the same five subsystems appear
at every level, each managing its own environment at its own resolution.

---

## How information flows

Information moves in two directions, through named channels:

```
UPWARD  (child → parent):   events.jsonl   ← "here is what happened"
DOWNWARD (parent → child):  params.json    ← "here are your parameters"
```

**Critical rule:** siblings never talk directly. If unit A needs to influence
unit B, it reports upward to the parent S3, which then sends instructions downward.

```
✗  unit-A ——————————————→ unit-B          (prohibited)
✓  unit-A → events.jsonl → S3 → params.json → unit-B   (correct)
```

Why? Because any connection that bypasses S3 is a connection the system
cannot observe, regulate, or correct. Hidden connections kill viable systems.

---

## Resources are physical quantities

Three resources are always tracked:

```
B(L) = min( B_tokens, B_compute, B_time )
```

The effective budget at any level is the **most constrained** dimension.
If you have infinite compute but 10 tokens left, you have 10 tokens.
If you have infinite tokens but the CPU is at 95°C, you have almost nothing.

**Child systems never have more budget than their parent.**
This is a mathematical guarantee — not a policy choice.

---

## The autonomy ceiling

S5 declares what the system can decide on its own, and what requires a human.

```
Single-loop  →  fix within existing rules  →  can be automated
Double-loop  →  change the rules           →  ALWAYS requires human approval
```

A system that changes its own rules without supervision is not viable —
it is unpredictable. The autonomy ceiling is the boundary between
"the machine handles it" and "a human must decide."

---

## Reading VSM notation

Here is a complete system written in VSM notation, with English annotations:

```
@vsm 0.1                                    ← spec version (always first)

V("bbh-platform", L=0) = {                 ← name + level

  E: { kali: "~/claude",                   ← environment: where things live
       parrot: "ssh parrot-ai" },

  S1: { pipeline:                          ← operations: the units doing work
          profile(0) → passive(1) →
          active(2) → enum(3) →
          vuln(4) → report(5) },

  S2: { anti_loop: "5 retries → escalate", ← coordination: prevents oscillation
        log: [kali:"~/claude/logs"] },

  S3: { scheduler: thermal_scheduler,      ← control: allocates resources
        guard: temp<59°C },                ←   hard constraint on compute

  S4: { opsroom: bbh_briefing },           ← intelligence: monitors environment

  S5: { ceiling: {                         ← policy: what requires human
          double_loop: requires_human },
        priorities: [BBH, pentest,
                     tools, OSCP, CTF] }   ←   what matters most, in order
}
```

Reading strategy (left to right, top to bottom):
1. Check `@vsm` version
2. Read `V(id, L=N)` — what is this system, at what level?
3. Read `E:` — what environment does it operate in?
4. Read `S1:` — what does it actually do?
5. Read `S3:` — what constraints govern resource use?
6. Read `S5:` — what can it never do without asking a human?

---

## Writing VSM notation

### Rules

```
rule(S3["my-system"], guard=temp<80°C):
  ∀ op ∈ S1.remote: launch(op) ∘ scheduler
  violation: SIGTERM
```

Read as: "S3 rule for my-system: when temp<80°C, every remote operation
must go through the scheduler. Violation means SIGTERM."

### Escalation

```
signal s ⟹ φ↑    iff  resolve(s, V(L)) = ∅  ∧  urgency(s) > τ
```

Read as: "signal s escalates to the parent when this level cannot resolve it
and the urgency exceeds the threshold."

### Memory entries (compressed)

```
episodic("affirm-v6-p1"):
  ts      = 2026-04-07T23:15
  phase   = 1
  status  = done
  output  = { subdomains: 4, duration_s: 847 }
```

```
procedural("bbh-scheduler-rule"):
  ∀ op ∈ S1.parrot: launch(op) ∘ thermal_scheduler
  guard  = temp < 59°C
  @ref   = "why: feedback_bbh_scheduler.prose.md"
```

---

## The opsroom — VSM made visible

The opsroom is not a separate tool. It is the VSM rendered as a dashboard.
Each view maps directly to a subsystem:

```
┌─────────────────────────────────────────────────────────────────┐
│  VIEW               │  SUBSYSTEM  │  QUESTION IT ANSWERS        │
├─────────────────────┼─────────────┼─────────────────────────────┤
│  System Health      │  S3 audit   │  Do we have resources?      │
│  Pipeline Status    │  S1 ops     │  Are units working?         │
│  Signal Queue       │  S2 coord   │  What couldn't resolve?     │
│  Priority Ranking   │  S4 intel   │  What matters most now?     │
│  Coverage Gaps      │  S3 → S4   │  What are we missing?       │
└─────────────────────────────────────────────────────────────────┘
```

Any system described in VSM notation can generate an opsroom automatically —
because the five views are already defined in the spec. Only the environment
data changes between domains.

---

## What does NOT belong in VSM notation

Not everything compresses well. These stay in prose:

- **Why** something was decided (incident history, tradeoffs)
- **Onboarding narratives** (what the system is for, in plain language)
- **Ambiguous situations** (where human judgment is the whole point)

These are referenced in VSM files with `@ref prose_doc`, not inlined.
The notation is for rules, structure, and constraints — not for stories.

---

## Quick reference card

```
V(id, L)          — viable system at level L
S1 / S2 / S3 / S4 / S5  — subsystems
E                 — environment
B(L)              — budget at level L
φ↑ / φ↓          — upward / downward channel
θ                 — parameter set (from parent)
τ                 — resolution threshold
r                 — local resolution rate
∅                 — unresolvable (triggers escalation)
∘                 — composition ("must go through")
∀                 — for every
∃                 — there exists at least one
⟹                — escalates to parent
@vsm N.N          — version declaration (always first)
@ref filename     — pointer to prose document
// comment        — human annotation (ignored by machines)
```

---

## The eight axioms (plain language)

These are the rules that cannot be broken. If your system violates one,
it is not a viable system — regardless of how well everything else works.

1. **Recursion** — every operational unit can be its own viable system
2. **Budget monotonicity** — children never have more budget than parents
3. **Physical resources** — tokens, compute, and time are the same type of thing
4. **No direct coupling** — siblings communicate only through the parent
5. **Autonomy ceiling** — double-loop changes always need a human
6. **Ashby's law** — the regulator must match the environment's variety
7. **Escalation** — unresolvable signals propagate upward
8. **Absorption** — signal volume decreases exponentially up the hierarchy

---

*This guide is part of the VSF project. See `docs/reference/vsm_notation_spec.md` for
the full formal specification with grammar, axioms, and machine interface.*
