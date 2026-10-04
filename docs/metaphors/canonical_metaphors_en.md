# Canonical Metaphors

*Translating a viable system to people who don't read cybernetics — without lying to them.*

---

## Why this repository exists

A viable system is abstract. The five functions, requisite variety, anticipatory projection:
precise ideas, but none walks through the door of anyone who hasn't read Beer. The metaphor is
the bridge.

But a metaphor is a loan against understanding. It buys clarity by hiding detail, and the interest
comes due exactly where the analogy breaks. The farmer who waters before the drought explains
anticipation beautifully — until someone asks "and can he water against *next year's* drought?" and
discovers he can't, that he only sees a day ahead. If that question wasn't answered in advance, the
metaphor didn't teach: it deceived.

Hence the **house rule**, the one non-negotiable of this repository:

> **No metaphor enters without declaring where it breaks.**
> A metaphor without a stated breaking-point is not pedagogy: it is propaganda.

It's the same discipline that governs everything else here. The credit that closed this cycle
(+0.9 of autonomy in S4) was earned by cutting in both directions: refused when it wasn't warranted,
retracted when a test failed, credited only when the evidence held. An honest metaphor does the same:
it says the useful thing and, in the same breath, says exactly how far it's true.

---

## How to add a metaphor

Four fields. All four mandatory; the third is what separates this repository from a brochure.

- **Translates:** *one* concept, not ten. If your metaphor explains five things, it probably explains
  none of them well.
- **The story:** concrete, everyday, no jargon. If it needs a footnote, it isn't a metaphor yet.
- **Where it breaks:** the exact point where it stops being true. Mandatory. This is where the loan
  is repaid.
- **In the system:** the real mechanism it translates, with a pointer, for anyone who wants to go
  from the story down to the iron.

---

## Part I — What the system *is*

### The workshop and its five trades

**Translates:** the five functions of a viable system (S1–S5).

**The story.** Picture a workshop that survives for decades. There are five trades, and not one is
spare. **The hands** (S1) do the work: cut, weld, assemble. **The shared reflexes** (S2) keep two
hands from reaching for the same tool at once — they don't command, they just prevent the collision.
**The floor manager** (S3) allocates what there is: who uses what, how much, when. **The surprise
inspector** (S3\*) shows up unannounced and looks at what the reports don't show. **The lookout on
the roof** (S4) doesn't watch the workshop: it watches the horizon, the street, the weather, what's
coming. And **the constitution** (S5) sets the limits no one — not even the manager — can override.
A living workshop has all five. Take away the lookout and it survives until the first surprise; take
away the constitution and the strongest hand eats the rest.

**Where it breaks.** In a real workshop the trades blend: the same person sometimes cuts and
sometimes allocates. In a body, worse: there's no "floor manager" you can point to. The separation is
a lens for *diagnosis*, not a blueprint of the insides. And there's a difference the workshop doesn't
capture: here each hand can itself be a complete workshop with its own five trades (see *the Russian
dolls*).

**In the system:** S1–S5 in `viability.yaml`; `docs/concepts.md`; the Cybersyn pattern.

---

## Part II — What it *does*

### The farmer who waters before the drought

**Translates:** anticipation — S4's projection that acts *before* the excursion.

**The story.** Two farmers, the same field, the same water. The first waters when the plant is
already wilting: he reacts to the damage. The second reads the sky and the soil and waters the day
*before* the heat arrives. He didn't use more water — he used the same water, moved one day earlier,
guided by a reading of the horizon. His plant never wilts. That's all anticipation is: not more
resources, the same resources moved in time, because someone looked ahead.

**Where it breaks.** Reading the sky only works as far ahead as the weather is legible. Read too far
and the farmer isn't anticipating anymore: he's guessing the season's average — which is our exact
limit. Our "sky" is legible for about a day; beyond that, the projection converges to the base rate
(see *the actuarial table*). And one more honesty: for now our farmer waters in a trial — the
reallocation is validated but *simulated*, not yet actuated on real soil.

**In the system:** S4 Markov projection → anticipatory reallocation; EXP-S4-01 (all four hypotheses
pass in one config; ~14% effect, 1-day lead); `docs/spec_revision/system/s4-intelligence/theory-ap-01/anticipatory_prevention.vsm`.

### The price of staying yourself

**Translates:** epistemic viability — the continuous cost of holding coherence.

**The story.** A body at rest looks like it's doing nothing. But it is paying, every second, to keep
its temperature and chemistry inside the narrow band where life is possible. Staying yourself is not
free: it's a bill paid without pause against the current that pulls toward dissolution. A system that
stops paying doesn't stay still — it comes apart. Existing already costs; *knowing* costs on top.

**Where it breaks.** The "two prices" — of existing and of knowing — are sharper in the metaphor than
in the math, where they tangle. And there's an asymmetry the body doesn't show: a body's band is set
by biology, and it isn't wrong; ours is set by a policy (see *the thermostat*), and it can be. Our
band is a decision, not a law of nature.

**In the system:** the *epistemic_viability* paper; the viable region Ω; `stasis_cos`.

### The hand that pulls back before the brain decides

**Translates:** the algedonic signal — the pain/pleasure channel that bypasses the slow layer.

**The story.** You touch a hot pot and your hand pulls back *before* you've thought the word "hot".
The signal doesn't wait for deliberation: it has its own wire, fast, straight to action. A viable
system needs that wire — an alarm channel that skips the thinking layer when something is urgent,
because thinking takes time and sometimes time is exactly what there isn't.

**Where it breaks.** A reflex is dumb by design — it can pull the hand from a warmth it mistook for
fire. So the reflex can never be the only judge: the slow layer reviews afterward. In our system the
reflex path is *deterministic* and forbidden from using the language model (rule R10), precisely
because a "smart" reflex is a slow reflex, and a slow reflex is no reflex.

**In the system:** the algedonic channel; rules R10/R10.1; `vsf-s5-algedonic`.

### The goalkeeper and requisite variety

**Translates:** Ashby's Law — to regulate something you need at least as much variety as it throws at you.

**The story.** A goalkeeper can only stop as many *kinds* of shot as they have kinds of save. Put them
against a striker with more tricks than the keeper has saves, and they'll be beaten — not by bad luck,
by arithmetic. To control something you need at least as much variety as that something throws at you.
It's not a slogan: it's a law, as hard as the law of the lever.

**Where it breaks.** The metaphor suggests the only way out is to *grow* your variety until it matches
the world's. False, and dangerous: sometimes the honest move is to *reduce* the world's variety —
shrink the goal, add a filter, coordinate so not every shot arrives at once — instead of pretending
you can save everything. The law says you need the variety; it doesn't say you must get it by growing.
That's what S2 and filters do.

**In the system:** Cyberfilter/S3, S2 coordination; Ashby as the foundation of variety.

---

## Part III — What it *doesn't* do

*(The most important part for trust. A system that only advertises what it does is a salesman; one
that advertises, with equal care, what it doesn't do is a partner.)*

### The actuarial table, not the weather forecast

**Translates:** the real scope of the climate model — it gives base rates, it doesn't predict events.

**The story.** An insurance actuary's table tells you a 60-year-old has, say, a 2% chance of
such-and-such this year. It's true, it's useful, and it knows *nothing* about you: not your name, not
your coming Tuesday. It gives historical rates, not predictions of events. Our climate model is
exactly that: it tells you the historical rate at which a zone drifts toward stress. It doesn't know
an atmospheric river is coming next week. Ask it to forecast the storm and it will hand you the
century's average, unbothered.

**Where it breaks.** This metaphor *is* the farmer's breaking-point: here is where "reading the
horizon" ends. And it breaks further if you push it: past one day, our table forgets where you started
and just repeats the base rate (~20% from any state). It's an actuarial table with a one-day memory.
Good for understanding a zone's *regime*, never for whether it'll rain on Thursday — for that, a
weather model, not this one.

**In the system:** the 5-bin percentile Markov chain; the ERA5 climatology (1991–2020); the warning
blocks in `scripts/reportes/reporte_clima_*.py`.

### The map is not the territory

**Translates:** the "model ≡ reality" rule — and why it's a discipline, not omniscience.

**The story.** A map is useful *precisely* because it leaves things out. But a map that believes it's
the territory is dangerous: you'll drive straight into the lake it simplified away. Our "model ≡
reality" rule is a discipline to keep the map honest — every service the map declares must really
exist, and a census verifies it — not a claim that the map *is* the world.

**Where it breaks.** A perfectly reconciled map is still a map: it can be true about what it shows and
silent about what it never surveyed. Reconciliation buys you "no lies", not "no gaps". The
un-instrumented doesn't appear — and not appearing is not the same as not existing.

**In the system:** `model≡reality`; `topology_reconcile`; the anti-orphan census (S3\*).

---

## Part IV — How it's governed

### The thermostat nobody can override

**Translates:** S5, policy — it doesn't do the work, it sets the band the work must respect.

**The story.** A thermostat doesn't heat the room. It decides the *band* the room must stay in, and
nothing in the room gets a vote. S5 is the system's thermostat: it doesn't execute, it sets the limits
execution can't cross. Its power isn't action — it's the last word on the edges.

**Where it breaks.** A badly-set thermostat is a silent tyranny: the room obeys a wrong number without
complaint. So whoever sets the band must, in turn, be bound (see *the rule that binds the rule-maker*).
A band nobody can override is only safe if changing it is hard and visible.

**In the system:** S5 policy; the viable region Ω; the covenant floor.

### The rule that binds the rule-maker too

**Translates:** A5, the autonomy ceiling and the covenant — the system can't vote itself more power.

**The story.** The strongest constitution is the one that binds its own author — where not even the
king can, by decree, exempt himself. In our system the deepest rule is that the big corrections —
changing the band itself, the "double loop" — always require a human to say yes. The system can't vote
itself more autonomy. It can propose it; it can't take it.

**Where it breaks.** A rule is worth only what its enforcement is worth: a covenant the executor can
quietly edit is a suggestion. Ours is deterministic and audited (S3\*) precisely so that the binding
doesn't depend on good intentions. And a nuance the king-metaphor hides: this ceiling is a *choice*,
not a natural law. We set it low on purpose — because a ceiling the system chose could, in principle,
be chosen again, which is why the lock is kept *outside* (see the offline CA).

**In the system:** the A5 autonomy ceiling; D4 single/double loop; the covenant; the offline S5 CA.

### The inspector who arrives unannounced

**Translates:** S3\* — the sporadic audit that sees what S3's reports don't show.

**The story.** The floor manager (S3) sees the reports the units *choose* to send. The surprise
inspector (S3\*) walks in unannounced and looks at what the reports don't show — the drawer nobody
mentioned. Not because the units lie, but because every reporting channel has a blind spot, and the
only cure for a blind spot is a look from the angle that channel doesn't cover.

**Where it breaks.** The inspector is sporadic by design. Make them constant and they become just
another reporting channel, with their own blind spot — and they strangle the work they audit along the
way. Their value is in the surprise and the different angle, not in total coverage. An inspector who
watches everything, all the time, is no longer an inspector: they're the bureaucracy they came to
prevent.

**In the system:** the S3\* audit; anti-orphan reconciliation; `vsf-s3-star`.

---

## Part V — The shape of the whole

### The Russian dolls

**Translates:** recursion — any unit that does work can itself be a complete system.

**The story.** You open a Russian doll and inside is a *whole* doll — not a piece of one, a complete
one. You open that and there's another. Our system is built this way: any unit that does work (an S1)
can, on the inside, be a complete system with its own five trades. It's dolls all the way down, and
each doll is whole.

**Where it breaks.** Real dolls are identical and they run out. Ours differ at each level and have to
*earn* their completeness: a unit counts as recursive only if it passes a certification, not by
declaring it. And the nesting bottoms out — at some floor there's a real hand doing real work, not
another doll. Recursion is a structure, not an excuse never to reach the ground.

**In the system:** `recursive: true` + `vsf_ref`; DSN-EVC-01 (the embedded certifier);
`docs/recursive_vsm_theory.md`.

---

## Coda

The discipline of this repository is the whole system's, in miniature: say the useful thing and, in
the same breath, say exactly where it stops being true. The +0.9 that closed this cycle was earned by
cutting both ways — refused when it wasn't warranted, credited when the evidence held. Every metaphor
here stands the same way: not by what it illuminates, but by how honest it is about its own shadow.

A metaphor that doesn't know its shadow isn't a bridge. It's a trap with a nice view.
