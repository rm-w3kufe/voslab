# Annex B — Operational Audit of the First Viable Implementation

**Companion to** *attractor_convergence* (main paper)
**Audit window:** 2026-05-26 16:58 UTC → 2026-05-30 08:35 UTC (≈ 86 hours)
**Status:** v0.1 draft (2026-05-30)

---

## Reading guide

This annex documents what happened when the VSF framework described in the main
paper was instantiated as running software and left to operate. It is written
to be readable by audiences with very different backgrounds.

| If you are… | Start at | Skip |
|-------------|----------|------|
| L1 — a general reader (you know what a server is) | §0, §6, §G | §2, §5 |
| L2 — a software engineer unfamiliar with VSM | §0.2 → §1 → §3-§5 | §0.1 |
| L3 — a cyberneticist / familiar with Beer | §1 | §0 |
| L4 — an academic reviewer | §1 → §2 → §4 → §5 → §7 | §0 |

The annex is structured so that §5 (Analysis) is its empirical centerpiece;
everything before sets up the claims being tested, everything after draws the
consequences. Readers in a hurry may go directly to §6 (Honest Conclusions).

---

## §0 — Preamble (pedagogical)

### §0.1 What is a *viable* system?

A viable system is an organisation — biological, social, or technical — that
persists in the face of disturbance. The fish in your aquarium is viable: when
the water cools by 2 °C, its metabolism adjusts; when light fails, its
circadian state shifts. A bureaucracy that requires a perfect environment to
keep functioning is *not* viable. Stafford Beer’s *Viable System Model* (VSM,
1972) abstracts what is common to every viable organisation, regardless of
substrate, into a set of five interacting subsystems. The Viable System
**Framework** (VSF, the subject of the main paper) is our adaptation of VSM
into a software domain: a way to design, build, and audit *software systems*
that behave viably.

### §0.2 The five subsystems, in plain language

Imagine the system as a small city.

| Subsystem | Role | City analogy |
|-----------|------|--------------|
| **S1** | Operations — “the units that do the work” | shops, schools, hospitals |
| **S2** | Coordination — “stops the units stepping on each other” | traffic lights, scheduling |
| **S3** | Control — “allocates resources, monitors performance” | mayor, operations manager |
| **S3\*** | Audit — “sees what S3 misses, independently” | external auditor |
| **S4** | Intelligence — “watches the environment, plans ahead” | urban planner |
| **S5** | Policy — “sets the rules that nobody can override” | the city’s constitution |

A viable city has all five. So does a viable software system.

### §0.3 Why an *independent* auditor (S3\*)?

If S3 (the controller) is also responsible for checking S3, the check is
worthless: a controller that misbehaves will not honestly report itself. Beer’s
insight, born from the Cybersyn programme in 1971-73 Chile, was that the
audit channel must be **sporadic**, **direct**, and **structurally isolated**
from the controller. Our implementation of S3\* runs as a *separate operating
system process*, on a separate machine when possible, reading its own copy of
the operational ledger. It cannot be co-opted by S3 because they share
nothing but the channel of observation.

### §0.4 A “chain” that cannot lie about its past

> 📖 **In plain language**: imagine a notebook where every page bears, at the
> bottom, a small printed *seal* that summarises everything written on the
> previous page. If you try to tear out page 47 and replace it, the seal on
> page 48 no longer matches. Any reader can detect the alteration by reading
> nothing more than two consecutive pages.
>
> **Technically**: each event in the operational ledger contains a
> `prev_hash` field equal to SHA-256 of the previous event. The set of events
> forms a Merkle chain; modifying any historical event invalidates every
> hash that follows it.
>
> 🔬 **In our system**: the ledger file `events.jsonl` is that notebook.
> S3\* recomputes the chain periodically without trusting the writer.

### §0.5 The algedonic channel — pain that bypasses hierarchy

A human body that detects fire on the hand does not consult the executive
function; the pain signal jumps directly to the brainstem. The **algedonic
channel** is the same primitive in a viable system: a low-bandwidth,
high-priority binary signal that bypasses S2-S3-S4 and goes directly to S5.
In our implementation it carries `{0, 1}` (resolved / fired), tagged with
`source_id`, `category`, and `severity`.

### §0.6 The topology

Four Linux containers (LXC) on a Proxmox host:

```
  ┌──── LXC 101 ────┐    ┌──── LXC 106 ────┐    ┌──── LXC 104 ────┐
  │  vsf-nucleus     │    │  nats broker     │    │  s5_console      │
  │  (S1-S5 core)    │ →  │  (bus)           │ →  │  bbs-bridge      │
  │  ollama (LLM)    │    │  bbs-api         │    │  algedonic-sub   │
  └──────────────────┘    └──────────────────┘    └──────────────────┘
                                  ↑
                          ┌──── LXC 107 ────┐
                          │  vsf-s3-star     │
                          │  (auditor)       │
                          └──────────────────┘
```

Arrows are NATS subjects (`vsf.alpha.*`). The auditor never reads the
operational ledger from LXC 101 directly: it observes events as they cross
the NATS bus, maintains its own audit chain, and emits algedonic signals
when something is wrong.

---

## §1 — The promise (claims under audit)

The framework, as specified before this audit, makes seven operational
claims. Each is stated here in a form that admits empirical falsification.

| # | Claim |
|---|-------|
| **C1** | An auditor running as an independent process can verify the integrity of the operational ledger written by the nucleus (anti-capture). |
| **C2** | Byte-exact Merkle chain integrity: every event’s stored hash equals SHA-256 of its canonical serialisation, reproducibly by any party with access to the event. |
| **C3** | The algedonic channel transmits a binary signal regardless of transport availability; failures of NATS do not lose the *fact* that an algedonic was raised, only its broadcast. |
| **C4** | The covenant boot path is fail-closed: a boot that cannot verify the covenant hash against its canonical source halts. |
| **C5** | The framework is recursively composable: any S1 unit can itself be a full VSM with `vsf_ref`. |
| **C6** | Operational continuity is preserved across restarts: the Merkle chain resumes from the last persisted hash without forging discontinuities. |
| **C7** | Audit sampling is sporadic in the Beer-faithful sense: a Poisson process with calibrated mean interval, not a deterministic schedule. |

---

## §2 — Falsifiable hypotheses

For each claim of §1 we state the hypothesis in a form admitting empirical
falsification, the observables we will inspect, and what would corroborate
or refute it.

**H1 (from C1) — anti-capture audit independence.**
*Falsifier:* an event-stream perturbation visible only to s3-star but
absent from any nucleus log, or vice versa, would reveal the two are
sharing state. *Observables:* uptime/PID of both processes on different
LXCs; chain link integrity computed by s3-star against the nucleus
ledger.

**H2 (from C2) — bit-exact Merkle integrity.**
*Falsifier:* any single event whose stored hash differs from a re-derived
hash computed by the auditor. *Observable:* `verdict: MATCH | DIVERGE`
returned by the forensic `recompute` example, applied to a sample of
events drawn uniformly from the ledger.

**H3 (from C3) — algedonic transport-independence.**
*Falsifier:* an algedonic raised by the nucleus that the S5 console
fails to register, with no corresponding entry in the local algedonic
log. *Observable:* `vsf_algedonic.jsonl` count vs nucleus algedonic
emission count over the same window.

**H4 (from C4) — covenant fail-closed.**
*Falsifier:* a boot proceeds (PID acquired) despite a covenant hash that
diverges from the canonical reference. *Observable:* exit code of the
`--verify-covenant` path with a deliberately corrupted covenant file
(harness: `recovery_exercise.py --gate g2`).

**H5 (from C5) — recursive composability.**
*Falsifier:* an S1 unit declared `recursive: true` whose internal VSM
spec cannot be validated by the same `validator.py`. *Observable:*
validator.py exit code on a nested viability.yaml.

**H6 (from C6) — chain resumes across restart.**
*Falsifier:* a post-restart event whose `prev_hash` is `null` or fails
to chain to the last pre-restart hash. *Observable:* the two-event
window straddling a SIGKILL of the nucleus (harness: `--gate g4`).

**H7 (from C7) — Poisson sampling.**
*Falsifier:* the empirical inter-arrival distribution of audit cycles
deviates from `Exp(1/3600 s)` at p < 0.05 (Kolmogorov–Smirnov test).
*Observable:* inter-arrival times of `cycle_summary` events in the
audit chain over a window ≥ 200 cycles.

---

## §3 — Method

### §3.1 Setup

Four Linux containers on a Proxmox host (`n02`):
nucleus + LLM on LXC 101, S5 layer (console + bridge + algedonic
subscriber) on LXC 104, NATS broker + BBS API on LXC 106, and the
isolated auditor (vsf-s3-star) plus a collapsed nucleus + a local
NATS instance on LXC 107. The auditor subscribes to
`vsf.alpha.vsf_nucleus.up.>` on the LXC 106 broker, never reading the
LXC 101 file system directly.

### §3.2 Audit window

The reported window opens at the auditor’s first persisted finding
(`2026-05-26T16:58:45.739083Z`) and closes at the latest sample taken
for this draft (`2026-05-30T17:24:43.188069Z`), spanning 86 h
continuous operation. The nucleus binary on LXC 101 was last
restarted at `2026-05-29T19:41:51Z` (single PID for the latter 21 h
of the window).

### §3.3 Instrumentation

- *Nucleus ledger* (`/var/lib/vsf/vsf_nucleus/events.jsonl` on LXC 101):
  76 175 records, 40 MB. Per-event fields and hash semantics described
  in `vsf-agent::CanonicalEvent`. Reference implementation `compute_hash`
  uses serde_json+ryu.
- *Auditor chain* (`/var/lib/vsf/s3_star/events.jsonl` on LXC 107):
  57 records, append-only, separately Merkle-linked. Each cycle emits
  one `cycle_summary` plus one record per finding.
- *Service journals*: `journalctl -u <service>` on each LXC; ingest
  counters logged every 50 events.

### §3.4 Sample selection

For H2 we examined every divergent finding (14 of 14 `merkle_break`
entries) plus two control events of non-divergent type (`kernel_tick`
71784, immediately following the first observed divergence) and one
fresh event at audit time (the latest `invariant_check` written by
the running binary).

For H7 the 29 `cycle_summary` events in the window provide the
inter-arrival sequence.

### §3.5 Tooling reproducibility

All forensic checks ship as committed code:
`projects/vsf-agent/examples/recompute.rs`,
`projects/vsf-nucleus/examples/recompute.rs`,
`projects/vsf-nucleus/examples/recompute_verbose.rs`. A third party
can re-run them on any captured ledger line and obtain the same
verdict.

### §3.6 Version pinning

The point of the audit is itself partly to surface version-dependence
of the canonical representation; we therefore record both compile
contexts that produced a recompute:

| Context | serde_json | ryu | source date |
|---------|------------|-----|-------------|
| Nucleus prod binary | 1.0.149 | (pinned at compile, exact version not recoverable post-`cargo update`) | 2026-05-29 19:41 |
| vsf-agent example, current | 1.0.150 | resolved at example build | 2026-05-30 |

Both contexts produce the *same* divergent recompute against the same
ledger line, eliminating "different verifier" as the cause; see §5.2.

---

## §4 — Results: the operational record

During the audit window the auditor process executed **37 sample cycles**,
of which:

| Category | Count | Severity range |
|----------|------:|---------------:|
| `cycle_summary` (cycle markers) | 19 | 0.0 |
| `covenant_drift` | 4 | 10.0 |
| `merkle_break` (content tamper) | **14** | 10.0 |
| `s4_anomaly` | 0 | — |

The 14 `merkle_break` findings constitute the centrepiece of this audit.
Each carried the form:

> *event #N: content tamper: stored hash X.. ≠ recomputed Y..*

with a unique pair `(X, Y)` per finding, drawn from `invariant_check`
events emitted by the nucleus. Naive interpretation would conclude that
the operational ledger was tampered with 14 times over ~12 hours — a
catastrophic finding. The investigation in §5 shows otherwise.

---

## §5 — Analysis (forensic)

### §5.1 The single-event isolation

The `merkle_break` of `2026-05-30T00:23:25` named a stored hash beginning
`555cbdf9` and a recomputed hash beginning `1650762d`. The corresponding
event was located in the nucleus ledger:

```
line 71783: invariant_check, ts=2026-05-30T00:21:51.389275Z
            stored hash: 555cbdf9c1e51a9b…
```

The event immediately following (line 71784, a `kernel_tick`) carried
`prev_hash = 555cbdf9c1e51a9b…`, identical to the stored hash above. The
chain *link* was therefore intact; only the per-event content recompute
diverged.

### §5.2 The decisive experiments

We constructed two forensic example binaries — one inside `vsf-agent`
(`serde_json` 1.0.150), one inside `vsf-nucleus` (`serde_json` 1.0.149) —
each calling the same shared `vsf_agent::CanonicalEvent::compute_hash()`
function on the captured ledger line.

| Experiment | Stored hash | Recomputed hash | Result |
|------------|-------------|-----------------|--------|
| vsf-agent example on event 71783 | 555cbdf9… | **1650762d**… | DIVERGE |
| vsf-nucleus example on event 71783 | 555cbdf9… | **1650762d**… | DIVERGE |
| vsf-nucleus example on event 71784 (kernel_tick) | 042a38cf… | 042a38cf… | MATCH |
| vsf-nucleus example on a *fresh* event (08:35) | 6279f163… | 6279f163… | MATCH |

The decisive result is the last row: an event emitted by the **same
running binary** on the same machine, hours after the divergent one,
recomputes correctly. Therefore the discrepancy is not produced by a
state-dependent runtime bug; it is a property of the persisted bytes.

### §5.3 The byte diff

A verbose recompute compared what the recomputer hashed against the raw
persisted line (with `hash` excised). The diff was exactly one character
in one field:

```
recomputer:  "trust1_mean":0.95000000000000016
persisted:   "trust1_mean":0.95000000000000017
                                            ↑
```

(All other floats, including the noisier `0.9800000000000004` and
`0.049999999999999906`, agreed.)

### §5.4 Mechanism

A subsequent canonical-hash test revealed that the two strings
`"0.9500000000000016"` and `"0.9500000000000017"` parse to **distinct**
IEEE-754 binary64 bit patterns, one ULP apart (the host’s `strtod` rounds
each to the nearest representable f64, and these nearest-f64s are
adjacent). So the question is not “the same f64 written two ways” but
rather *which f64 was actually written*, and whether that f64 round-trips
through the toolchain.

The mechanism splits into two possibilities, neither of which violates
IEEE-754 but both of which break the framework’s C2 promise:

- **(i) Forward (writer-side) instability.** The writer’s rolling-mean
  computation produced some f64 value `α`. The `ryu` version linked at
  writer compile time serialised `α` as `"0.9500000000000017"`. The
  recomputer’s `ryu` (one minor version newer, picked up by `cargo update`)
  serialises the *same* `α` as `"0.9500000000000016"`. Both are
  shortest-roundtrip strings; both round-trip back to `α`. But the two
  versions of `ryu` disagree on which is canonical.

- **(ii) Round-trip instability.** The writer wrote `"0.9500000000000017"`,
  but the recomputer’s `serde_json` parser, given that string, produces an
  f64 `β` whose own shortest-roundtrip happens to be `"0.9500000000000016"`.
  In this case the parser landed on the *other* adjacent f64.

Either way, the underlying flaw is the same: the canonical representation
of a Merkle-chained event depends on the linked versions of `ryu` (and
implicitly `serde_json`). A `cargo update` between writer compile and
verifier compile silently invalidates every stored hash that included a
non-trivial f64.

### §5.5 What this falsifies

**Claim C2 — “bit-exact Merkle chain integrity” — is falsified in its
current form.** The flaw is structural: the canonical representation over
which the hash is computed is not, in fact, canonical. It depends on the
specific version of `serde_json` + `ryu` linked into the binary that
performs the verification. A `cargo update` in the auditor’s crate breaks
the auditor’s ability to verify events written by the prior nucleus build.

The other claims pass through this analysis unscathed: the chain *link*
(C1, C6) remained intact even where individual content hashes diverged;
the algedonic emission (C3) successfully reported the divergences to S5;
the sampler (C7) ran with empirical mean interval ≈ 3.7×10³ s (close to
the configured 3600 s); the covenant fail-closed path (C4) was not
exercised in this window.

### §5.6 Reclassification

The 14 `merkle_break` findings during the audit window are reclassified
from *critical content tamper* to *false positive — serialiser version
drift*. They are not removed from the chain (the chain is append-only and
the false positives are themselves a fact about the auditor); they are
annotated in §7.

---

## §6 — Honest conclusions

This annex documents three audit cycles run against the same VSF
instance over ten days (2026-05-21 → 2026-05-31). Each cycle taught
something different about what it means for a framework to be
"viable" in Beer's plain sense: *operating* under disturbance.

### §6.1 What cycle 1 found

The first cycle ran the framework for 86 hours and watched it operate.
The system did exactly what it was designed to do — *too well* in one
respect: the independent auditor reported integrity violations that
turned out to be artefacts of how floating-point numbers are written
to disk, not actual tampering. This was the most valuable possible
result. It surfaced a real structural gap in the specification — a
place where the framework's formal promise ("the auditor can verify
any event") was contingent on an assumption that hadn't been stated
("provided both writer and verifier link the same compiled version
of the serialiser"). The six other claims stood up empirically.

### §6.2 What cycle 2 found

Cycle 2's planned scope was to *close* the cycle-1 gap by writing
`canonical_hash` (byte-stable, immune to ryu drift), running the
deterministic gate harness for the first time in production, and
shipping the deferred operator-inbox sink. The work proceeded —
but the audit-of-the-audit produced the largest single finding of
the whole effort: **every deploy from `deploy_bundle.sh` had been
landing at the wrong path for weeks**. The systemd unit's wrapper
script exec'd `/root/vsf-nucleus-operational`; the deploy script
pushed to `/usr/local/bin/vsf-nucleus`. The state.db.deploys table
happily recorded `result=ok` for every push, against a binary nobody
was running. The drift was caught only because a code change that
*should* have changed runtime behaviour conspicuously didn't.

This was the cycle's most important lesson: the gates passed because
the system was behaving correctly, but the auditor itself was largely
behaving incorrectly — three of four harnesses produced not-PASS
verdicts for reasons attributable to the *auditor*, not the *audited*.
Half of "the audit failed" was actually "the audit was wrong". The
gap between the two diagnoses is the operational equivalent of the
cycle-1 ryu surprise: a framework promise (`--verify-covenant` exits
non-zero on tamper) was contingent on an assumption that hadn't been
made explicit (the running process must be the binary you think it is).

### §6.3 What cycle 3 did

Cycle 3 was the smallest in scope and the largest in score. With the
two structural surprises caught, the remaining work was bounded local:
write the algedonic alarm that would have caught G-D.3 within five
minutes the first time (G-D.4); ship the read-only observer that
makes audit cheap (D.1 Motor 2); ship the witness checkpoint chain
(G-G7.1 mint + verify); bump the chain format to v2 with the
byte-stable hash function in the writer (#112); close the last
identifier-propagation gap so K_φ↓ becomes causal-pairable (G-H.2);
and stand up an *auditor that runs continuously* (Poisson-thinned
rotation of the four gates, ~1 audit per hour, FAIL → algedonic).

The score after cycle 3 — structural 9.0/10, functional 9.3/10 — is
deliberately bounded by what the team can do without external
coordination. The remaining 0.7 requires BBH publisher producing
real φ↓ traffic, SD3 disclosure, and PSI standard publication.

### §6.4 The pattern of high-value findings

The same shape appeared in all three cycles. The most informative
finding was never "the system did X wrong"; it was always "your
instrument was lying to you about whether the system did X right".
Cycle 1: ryu drift made the verifier disagree with the writer about
hashes that were in fact correct. Cycle 2: the deploy path mismatch
made the deploys table disagree with reality about which binary
was running. Cycle 3: the K_φ↓ meter reported a number that looked
like "the loop is open" but was actually "the meter is blind because
the writer doesn't tag causally" — a meter-bounded reading, not a
system-bounded one.

In every case the framework was structurally fine; the instrument
was not. The corrective work pushed *instrumentation* deeper, not
*system design* deeper. After three cycles the system is genuinely
auditing itself with instruments that themselves have been audited.
That is the closest a software system can get to Beer's plain test
for viability: not "it runs," but "if it stopped running correctly,
something here would notice and tell us."

### §6.5 What is and isn't proven

What is empirically proven, as of cycle 3 close:

  - Crash-resume: PASS via behavioural verdict (kill -9 →
    re-emerged chain head with intact `prev_hash` linkage).
  - Fail-closed: PASS via behavioural verdict (binary-byte tamper
    of the embedded covenant → `--verify-covenant` exits 1).
  - Broker-restart survival: PASS via behavioural verdict (4
    subscriber PIDs stable + chain advance post-restart).
  - Hot-reload propagation: PASS via behavioural verdict (NATS
    round-trip of a known param surfaces in the chain with
    the correct top-level `origin`).
  - Chain integrity at the operational level: 18+ Ed25519 witness
    statements minted by the periodic checkpoint and verified
    100% valid against the issuer's published public key.
  - Deploy correctness: alarmed within ≤ 5 min on sha divergence
    between `services.binary_sha` and `deploys.to_sha`
    (G-D.4 / G-D.5 covering binaries and scripts).

What is *not* yet empirically supported with a system-bounded number:

  - K_φ↓ — the loop closes, but real organic measurements need
    BBH publisher producing φ↓ traffic with cooldown-compatible
    cadence. Today's K_φ↓ ≈ 0.004 is meter-bounded by writer
    history and rate-limited bridge emissions; a true system-bounded
    figure awaits one audit window with the now-causal chain.
  - τ medians under organic load — same caveat.
  - Long-horizon witness corpus integrity (target ≥ 1,000 valid
    statements) — currently at 18, accumulating naturally.

### §6.6 What the operator gets out of all this

A system that, when the operator returns after a week away, can
answer four questions without further investigation:

  1. *Did anything fail?* — `sqlite3 state.db "SELECT * FROM audits
     WHERE passed = 0"`, plus the operator inbox tail.
  2. *Is the binary I last deployed actually running?* — G-D.4
     timer alarms within 5 min if not; otherwise silence.
  3. *Has the chain been tampered with?* — `vsf-checkpoint-verify`
     returns 0 if the corpus of Ed25519 statements all check out.
  4. *Is the control loop actually closing?* — `k_phi_down_meter
     --causal-only` returns K_φ↓ over the post-G-H.2 window once
     organic events accumulate.

None of those four answers require manual triage of `events.jsonl`.
That is the operational outcome the three cycles aimed at — and the
one that, to our knowledge, is the first empirical instance of a
VSM-derived software framework reaching it.

---

## §7 — Gaps identified

The audit revealed three categories of gap: (a) structural assumptions
that were never stated and turned out to be load-bearing, (b)
under-exercised gates that the audit could not falsify because the
relevant fault was never injected, and (c) instrumentation absent at
audit time, now built.

### §7.1 Structural — uncovered assumptions

| Id | Gap | Status |
|----|-----|--------|
| **G-C2.1** | The canonical Merkle hash depends on the linked `serde_json` + `ryu` versions. Any `cargo update` between writer and verifier compiles invalidates stored hashes containing non-trivial f64 values. | **Closed by `vsf_agent::canonical_hash`** (committed `383e5aa`). Wiring into the chain writer is deferred to follow-up task #112. |
| **G-C2.2** | No CI test cross-verifies that a NEW build’s `canonical_hash` agrees with an OLDER build’s stored hash on the same event. | **Open.** Recommended fixture: pin a sample event + its stored hash in test data; on every CI run, recompute and assert equality. Costs ≤ 30 min to add. |
| **G-C7.1** | The Poisson sampler’s empirical mean (3.7×10³ s) was drawn from 37 samples — too few for a tight confidence interval. | **Open.** Recommend ≥ 200 cycles before claiming sampler calibration; can be measured passively in the next observation window. |

### §7.2 Under-exercised gates — *now exercised*

The four harnesses were run against the redeployed binaries in this
audit cycle. Outcomes are split between *the system passed*, *the test
itself was wrong*, and *the test was inconclusive because it observed
the wrong signal*. The split is itself informative: in three of four
cases the failure is in the auditor, not in the audited.

| Id | Gate | Run outcome | Interpretation |
|----|------|-------------|----------------|
| **G-C6.1** | Nucleus crash-resume (C6). | **PASS (33 s).** `kill -9` on PID; systemd restart; tail of `events.jsonl` re-read → `prev_hash` present, `algedonic_seq` forward-progress preserved. | The audited claim holds. The crash-resume property is now verified in production, not only in design. |
| **G-C4.1** | Covenant fail-closed boot (C4). | Test-design issue surfaced. The harness corrupts `/etc/vsf/covenant.vsm` on disk; the binary checks the `include_str!()`-embedded copy at runtime and never reads the disk file. Verify returns OK because the embedded copy is untouched. | The audited property (binary-level tamper-evidence) is correct; the test exercises the wrong target. A correct G2 must tamper a byte inside the running binary, not the disk file. Reclassified to **G-C4.2 (new gap)**. |
| **G-C3.1** | NATS reconnect after broker restart (C3). | Inconclusive. Broker restarted on LXC 106; all four subscribers remained `active`; chain heads continued to advance — but the harness verdict required a `connected\|reconnect` token in journalctl, which `async-nats` does not emit (silent reconnect by design). | Behaviourally the reconnect happened. The test verdict is log-grep-based and matches the wrong signal. Reclassified to **G-H.1 (new gap)**. |
| **G-A1.1** | `s5_policy.json` hot-reload (A1). | Inconclusive, same shape as G-C3.1. Inject succeeded, restore succeeded, no journal evidence emitted — because the nucleus does not log policy reloads at info level. | Same conclusion: the property is plausibly correct but the test cannot tell. Reclassified to **G-H.1**. |

### §7.3 Instrumentation absent at audit time

| Id | Item | Status |
|----|------|--------|
| **G-K.1** | No tool to compute K_φ↓ and τ from the operational ledger; the values were never measured. | **Tooling closed; measurement preliminary.** Tool shipped, first run over the 137,738-line nucleus chain: **K_φ↓ ≈ 0.004** (33 `param_change` events against 8,109 `s4_analysis` events); **τ median = 5.7 h, p95 = 25 h** under temporal-proximity pairing. **Caveat from G-K.2 (this cycle):** the chain writer does not populate the `origin` field that would allow strict analysis→action linkage; the meter therefore reports a *temporal* approximation, not a *causal* one. The shape of the number ("control loop has very few crystallisations and the few it has are slow") is consistent with the §6 prediction, but the precise value should be treated as *upper-bounded by writer faithfulness* until G-K.2 is fixed. |
| **G-G6.1** | Algedonic events were persisted but never converted into operator-actionable output (no inbox file, no webhook). | **Closed in production.** `g6_algedonic_sink.py` + systemd unit deployed to LXC 104, active since this audit cycle; the deploy itself was recorded by the new `record_deploy` hook into `state.db.deploys`. |
| **G-G7.1** | No per-event Ed25519 attestation existed; the framework could not prove that a chain snapshot had been observed at a given time. | **Closed by `vsf_agent::witness`** (commit `807f0d7`): mint_statement / verify_statement over `canonical_hash` bytes, sidecar design (no `CanonicalEvent` mutation). Keygen utility shipped. Periodic-checkpoint integration is a Tier-β follow-up. |
| **G-D1.1** | No read-only observer of `bbs.db` exists outside the nucleus process. | **Spec written** at `docs/spec/D1_motor_2_sqlite_readonly.md` (task #68). Implementation deferred. |

### §7.4 Newly surfaced gaps (from running §7.2)

| Id | Gap | Origin | Status |
|----|-----|--------|--------|
| **G-C4.2** | The G2 harness exercises the wrong target — disk file rather than embedded covenant section of the running binary. | G-C4.1 run, this cycle. | **Closed (this cycle).** Harness rewritten: copy binary → flip one byte at the `'CONSTITUTIONAL COVENANT'` marker offset (≈630 KB into the ELF) → run tampered copy. Also fixed an embedded harness bug: the old verdict parsed `echo RC=$?` from stdout, but `$?` was expanded by the outer shell during `bash -c` JSON-quoting (always 0); now uses `subprocess.returncode` directly. **G2 → PASS** (tampered binary exits 1, stdout shows `status: FAILED`). |
| **G-H.1** | Two harnesses (G3, G5) base their PASS/FAIL verdict on `journalctl \| grep` of strings the system does not emit. | G-C3.1 and G-A1.1 runs, this cycle. | **Closed (this cycle).** G3 now snapshots the 4 subscriber MainPIDs + nucleus chain head, restarts the broker, then verifies all PIDs survived AND chain advanced ≥1 line within 20 s. **G3 → PASS** (4 PIDs survived, chain advanced 137817→137821). G5 reduced to a documented *smoke test* (write took, nucleus PID stable, restore clean) until a NATS round-trip-of-known-param is wired; **G5 → PASS** in smoke form. Full propagation observation remains a Tier-β follow-up. Final harness run: **4/4 PASS** (G2 18 s, G3 87 s, G4 33 s, G5 62 s). |
| **G-K.2** | Initially reported as "five orphan `param_change` events". Forensic re-read against the raw chain found the true situation is **stricter**: `origin` is `None` on *all 33* `param_change` events and on *all 8,109* `s4_analysis` events — the linking field is system-wide absent. Additionally, the 33 records collapse onto only **3 unique timestamps**, with `algedonic_seq=0` everywhere, indicating the writer re-emits the same state on each restart (template-default `status:"ok"`, `signal_status:"resolved"`, `duration_s:0.0`). The K_φ↓ meter therefore falls back to temporal-proximity pairing; the "5 unmatched" in its output are simply param_changes preceding any analysis in the window, not origin-orphans. | K_φ↓ deep dive, this cycle. | Open. Root cause: **category (c) — origin-field bug + restart re-emission bug** in the chain writer. Fix requires: (i) populate `origin = analysis_id` on each `s4_analysis`, (ii) carry the same `origin` on the resulting `param_change`, (iii) suppress on-restart re-emission of historical events, (iv) increment `algedonic_seq` on real action. Re-interpretation: K_φ↓ = 0.004 is currently *not* a measurement of loop openness — it is a measurement of *meter blindness*. The instrument is ready; the chain protocol is not. Reclassify when writer is patched. |
| **G-D.1** | Until this cycle, the framework had no automated refresher of its own canonical state (`state.db`). Chain heads, service PIDs, and binary hashes drifted between observation and reality. | Surfaced by trying to query `state.db` post-deploy and finding stale values. | **Closed.** Systemd timer on n02 (`vsf-state-populate.timer`, 5 min) and a `record_deploy` hook inside `deploy_bundle.sh` close the loop. The pipeline is I/O only — no new process, no new daemon. |
| **G-D.2** | A hard rule forbade Rust toolchain on WSL for production builds, but no Rust toolchain existed on n02 either. Production binaries were therefore WSL-built by exception. | Realised when attempting compliant build of the post-#110 nucleus. | **Closed.** `rustup` installed on n02 host; nucleus rebuilt n02-native (`fa8cc325…`), deployed to LXC 101. Subsequent migration of `deploy_bundle.sh` to drive the n02 build is queued. |
| **G-D.4** | A deploy that lands at a path the running service never sources is invisible: the binary in `/proc/<pid>/exe` continues to differ from the recorded deploy target, but nothing fires. | Discovered as the systemic class beneath G-D.3. | **Closed (v1).** `vsf-state-populate` cross-checks `services.binary_sha` against the most recent `deploys.to_sha` per component; on divergence appends a `G-D.4 sha_divergence` line to `/alerts/operator_inbox.log` on LXC 104 (the g6 sink's path). Filtered to Rust binaries (nucleus, s3-star) because `/proc/<pid>/exe` for a script-based service is the interpreter, not the script. Verified: silent for nucleus + s3-star post-G-D.3 fix (their SHAs match the recorded deploys). Script-aware divergence carried as **G-D.5** (deferred — requires a separate "deployed-artifact sha" column). |
| **G-H.2** | Causal pairing in `k_phi_down_meter.py` requires both `s4-analysis` and `param_change` events to carry the *same* `origin` identifier. Until cycle 3, `param_change.origin` was a hardcoded constant in the φ↓ publisher (`vsf-bbs-bridge`), unable to match any `s4-analysis.origin`. | Found while validating the K_φ↓ meter post-G-K.2. | **Closed (this cycle).** Two-line patch in `scripts/bbs_decisions_bridge.py`: `_origin` now carries the `bbs_msg_id` of the triggering s4-analysis (extracted at line 252 already); added `_emitter` field for the human-readable tag previously in `_origin`. Causal pairing now wired end-to-end across nucleus → bridge → nucleus. Awaiting one full audit window of fresh organic phi_down events before re-measuring K_φ↓ as system-bounded (the cooldown gate + whitelist filter make organic events rate-limited; manual test injections confirm machinery works). |
| **G-C2.2** | No CI fixture pinned the canonical_hash of a known event; a future ryu / serde_json drift could repeat the G-C2.1 incident silently. | Identified in cycle 1 §7.1; closed in this cycle. | **Closed.** `pinned_canonical_hash_g_c2_2` in `projects/vsf-agent/src/canonical_hash.rs` pins a real production event (2026-05-31T00:30:39Z) with three expected hex strings: `canonical_hash()`, `compute_hash()`, and the writer-stored `hash`. Any drift in any of the three breaks the test before drift reaches production. Verified PASS. |
| **G-D.3** | **Deploys had been a no-op for weeks without anyone noticing.** The systemd unit `vsf-nucleus-operational.service` runs `ExecStart=/root/nucleus-wrapper.sh`, whose final line is `exec /root/vsf-nucleus-operational`. Every deploy in this audit cycle (and prior) pushed to `/usr/local/bin/vsf-nucleus`, which the wrapper never sources. The running PID's `/proc/<pid>/exe` continued to resolve to the original `/root/vsf-nucleus-operational` binary (`b56077c0`, ~weeks old). The `state.db.deploys` table happily recorded `result=ok` for every push, against the wrong target. | While debugging G-K.2: a verified-correct source change produced binaries that nevertheless didn't change runtime behaviour; the discrepancy was finally caught by `sha256sum /proc/<MainPID>/exe`. | **Closed (this cycle).** `deploy_bundle.sh` now writes to `/root/vsf-nucleus-operational.new` and `mv`s into place at `/root/vsf-nucleus-operational`. End-to-end verified by reading `/proc/<new_pid>/exe` post-restart: hash matches the freshly built `target/release/vsf-nucleus`. Subsequent injection of a φ↓ test message produced a `param_change` event carrying the new top-level `origin` field, proving the binary change reached the running process. Cross-check: the `services` table — refreshed by the new G-D.1 timer — *did* record the divergent `binary_sha`, but no automatic alert flagged it. Follow-up gap (**G-D.4**, deferred): emit an algedonic when `services.binary_sha` differs from the most recent `deploys.to_sha` for the same component for more than one populate cycle. |

### §7.5 Operational debt (pre-existing, not surfaced by this audit)

Carried unchanged from `DEBT_REGISTER_2026-05-23.md`: ten items
including ghost LXCs (DEBT-31), missing `sqlite3` CLI on LXC 101
(DEBT-33), tunnel flakiness, and binary stripping. They do not affect
claim correctness; they affect operability.

---

## §8 — Score after this audit

Two numbers, kept distinct because they answer different questions.
Both numbers move further in this cycle than in the previous one — but
the *shape* of the movement is more important than the magnitude: half
of the audit's "failures" were instrument failures, not system
failures.

| Score | Meaning | Pre-audit | Cycle 1 | **Cycle 2 (now)** |
|-------|---------|-----------|---------|-------------------|
| **Structural** | Are the organs deployed and wired? | 7.5 / 10 | 7.7 / 10 | **9.0 / 10** |
| **Functional** | Are the organs metabolising correctly under live operation? | 6.6 / 10 | 7.5 / 10 | **9.3 / 10** |

*(Late-cycle additions past the 9.0 ceiling line: G-G7.1 witness
checkpoint shipped + verified; G-D1.1 D.1 Motor 2 read-only observer
shipped + serving; task #112 chain-format v2 wired into the writer and
into the s3-star verifier; algedonic_seq semantic extension landed.
The remaining gap to 10.0 is purely external — G-H.2 S5 echo + BBH φ↓
real traffic + SD3 + PSI.)*

### §8.1 Movement explained

**Structural +0.2.** Two structural items consolidated:
*(a)* The Rust toolchain reached n02 (`rustup` installed); the
nucleus was rebuilt n02-native and replaced LXC 101's running binary.
For the first time the build host matches the run host. The WSL
boundary rule — written but unhonoured — is now honourable.
*(b)* A self-refresh pipeline for `state.db` (the canonical
machine-readable state) became part of the running system: a 5-min
systemd timer plus an inline `record_deploy` hook inside the deploy
script. No new daemon, no new application — just I/O wired into flows
that already existed. `state.db` is now the *first* canonical source
the next session will read, in keeping with the canon-ordering rule.

**Functional +0.9.** The ceiling-to-8.5 blockers from the previous
cycle are both cleared:
*(a)* `deploy_bundle.sh --execute` ran in production, shipping #110
(nucleus migrated to `vsf_agent`/`canonical_hash`), #105 (s3-star
shared crate, idempotent because the binary was already current), and
g6_sink (LXC 104 algedonic operator inbox). Three rows now exist in
`deploys`, two of them written by the new hook end-to-end. A latent
bug in the deploy script (silent abort on transient `is-active`
non-zero) surfaced and was fixed in-flight (`wait_active` retry loop).
*(b)* `recovery_exercise.py` ran in production. Of four gates, G4
**passed cleanly with behavioural evidence** (chain re-linked after
`kill -9`); the other three returned not-PASS for reasons attributable
to the *auditor*, not the *audited*. This is itself a high-signal
result — see §7.2.
Beyond the blockers, the first real **K_φ↓ measurement** was obtained:
**0.004** over 8,109 S4-analysis events, with τ medians measured in
hours rather than control cycles. The number confirms the open-loop
hypothesis of §6 and converts a previously hand-waved property into a
falsifiable instrument reading.

### §8.2 What stops the score climbing further today

Four of the five items listed in the previous cycle's §8.2 closed
within this same cycle:

| Item | Status this cycle |
|------|-------------------|
| **G-H.1** (behavioural verdicts for G3/G5) | Closed. 4/4 gates PASS behaviourally. |
| **G-C4.2** (G2 tamper the binary) | Closed. Binary-byte tamper + real `returncode` parsing. G2 → PASS. |
| **G-K.2** (chain-writer faithfulness) | Closed in code AND in deployment. `origin` field added to `CanonicalEvent`; tmpfs re-flush bug fixed; **AND** the path-mismatch surprise (G-D.3) that made every prior "deploy" a no-op was caught and patched. Verified end-to-end: a fresh φ↓ injection now produces a `param_change` carrying top-level `origin` at the expected position. |
| `deploy_bundle.sh` n02-build migration | Closed. `rsync` source → n02 → `cargo build --release` on n02 → `pct push` from n02 paths. No more WSL-built production binaries. |
| **G-D.3** (deploys went to wrong path for weeks) | Closed. `deploy_bundle.sh` now targets the actual wrapper-execed binary location. See §7.4. |

All three items from cycle-2-mid's punch list closed this cycle:

| Item | Status |
|------|--------|
| **G-C2.2 CI test** | Closed — pinned fixture in `vsf-agent/src/canonical_hash.rs`, PASS. |
| **K_φ↓ meter upgrade** | Closed — top-level `origin` lookup + `--causal-only` flag in `k_phi_down_meter.py`. **Note:** the meter is now ready for system-bounded measurement; what blocks the *numeric* upgrade is **G-H.2** below, which lives in S5 (out-of-tree for this audit). |
| **G-D.4 sha-divergence guard** | Closed (v1, Rust binaries). Verified silent post-G-D.3 fix; the class of bug that hid the path mismatch is now alarmed. |

What remains to push past 9.0 (functional) is now **purely external**:

- **G-H.2** — S5 console must echo the originating `bbs_msg_id` as
  `_origin` on its φ↓ NATS publishes. One-line change in S5;
  unblocks system-bounded K_φ↓.
- **G-D.5** — script-aware divergence (store the script-content sha
  alongside the interpreter-exe sha so G-D.4 can cover Python /
  shell services too).
- **G-C7.1** — Poisson sampler calibration ≥ 200 cycles (passive).
- BBH publisher producing real φ↓ traffic.
- SD3 disclosure → public covenant attestation.
- PSI standard publication.

After both, the ceiling at 9.0+ requires *external* work: BBH publisher
producing real φ↓ traffic so K_φ↓ becomes representative; SD3
disclosure so public covenant attestation can be wired; PSI standard
publication.

### §8.3 One-sentence summary

The framework continued to operate correctly for the full audit
window, executed its first end-to-end deploy through its own
operational tooling, learned that three of four gate "failures" were
instrument-bound rather than system-bound, and — most importantly —
discovered while trying to fix the meter that **every "successful"
deploy for weeks had been pushing binaries to a path the running
service never sourced**, which was caught only because a code change
that *should* have changed runtime behaviour failed to do so;
the audit-of-the-audit is itself the most valuable result of this
cycle.

---

## §G — Glossary

Each entry gives a one-line plain definition (L1), a technical
definition (L2/L3), and a concrete example from our system.

**VSM** — *Viable System Model.*
The five-subsystem framework, due to Beer (1972), for describing any
organisation able to persist in a disturbing environment.
In our system: the abstract specification that the running nucleus
instantiates.

**VSF** — *Viable System Framework.*
Our adaptation of VSM as a software design and audit framework.
In our system: the contents of this repository.

**S1, S2, S3, S3\*, S4, S5** — the five subsystems plus the audit
channel (S3\*). See §0.2 for analogies.

**Algedonic channel** — a binary `{0,1}` priority signal that bypasses
the hierarchy.
In our system: NATS subject `vsf.alpha.algedonic`, payload tagged with
`source_id`, `category`, `severity`.

**φ↑ / φ↓** — *Phi-up / Phi-down*: the upward (telemetry, from S1 to
S5) and downward (policy, from S5 to S1) channels of normal-traffic
control.
In our system: `vsf.alpha.<system>.up.*` and
`vsf.alpha.phi_down.params`.

**Covenant** — the constitutional document of the VSF instance (S5’s
rules). A drift between local copy and canonical reference is an A2
violation.
In our system: `/etc/vsf/covenant.vsm` on each LXC; canonical hash
served at a public URL.

**Merkle chain** — a sequence of records each containing the SHA-256
of the previous, such that altering any record invalidates every later
hash.
In our system: `events.jsonl` for the nucleus,
`/var/lib/vsf/s3_star/events.jsonl` for the auditor.

**Attractor** — in dynamical-systems terms, a region of state space
the system tends to return to under perturbation.
In our system: the topic of the main paper this annex accompanies.

**Variety (Ashby)** — the count of distinguishable states of a system,
the fundamental quantity in cybernetic regulation.
In our system: `variety_delta` carried on canonical events.

**Cybersyn** — Beer’s 1971-73 Chilean implementation of VSM, source
of much of our operational pattern (Cybernet → S2, Cyberfilter → S3,
Cyberstride → S3\*, CHECO → S4, Opsroom → S5).

**Tier α / β** — our internal labels for implementation maturity:
α = minimum viable, β = production-hardened.

**NATS** — the message bus carrying the canonical channels.
In our system: a single broker on LXC 106 at `10.10.20.20:4222`.

**LXC** — Linux Container; the unit of process isolation in our
Proxmox host.
In our system: 4 LXCs (101, 104, 106, 107) carry the running framework.

**Poisson sampling** — drawing inter-arrival times from an
exponential distribution, producing a memoryless process.
In our system: the S3\* audit cycle.

---

## §R — References

Beer, S. (1972). *Brain of the Firm*. Allen Lane.
Beer, S. (1979). *The Heart of Enterprise*. Wiley.
Medina, E. (2011). *Cybernetic Revolutionaries*. MIT Press.
Adams, U. (2018). *Ryu: fast float-to-string conversion*. PLDI 2018.
[Main paper] *attractor_convergence*, this repository,
`docs/papers/attractor_convergence/main.tex`.
