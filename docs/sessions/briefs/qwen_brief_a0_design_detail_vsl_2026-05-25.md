@vsl 0.1
// brief_id: qwen_a0_design_detail
// purpose: lock A0 design decisions before code commit
// notation: VSL strict (per rmw3 directive)
// counterpart: vsf-s3-star (Cargo workspace member, separate binary)
// supersedes: §3 of qwen_brief_tier_alpha_review_2026-05-25 (architectural;
//             this brief is *implementation contract*)

V(vsf-s3-star, L=1.audit)
  parent      : V(vsf-nucleus, L=1)
  isolation   : process_separate ∧ binary_separate ∧ crash_domain_separate
  capability  : read_only(events.jsonl) ∧ write_only(nats_pub) ∧ no_write(disk_root)
  scope       : audit(V(vsf-nucleus)) ∀ tick ∈ poisson_schedule
  forbidden   : { ∀ direct_call → S3, ∀ mutation → events.jsonl, ∀ ψ → V(bbh) }

// ─────────────────────────────────────────────────────────────────────────
// Q1 — NATS subject hierarchy (semantic, contract-level)
// ─────────────────────────────────────────────────────────────────────────

decide("Q1.subject_hierarchy"):
  options = {
    (a): "vsf.<vsf_id>.s3_star.audit.<event_type>"   // namespaced under vsf
    (b): "s3_star.<vsf_id>.audit.<event_type>"       // peer namespace
    (c): "vsf.<vsf_id>.audit.<finding|sample|drift>" // anonymous emitter
  }
  constraint:
    must_subscribe_by   : { rmw3_console, future_witness_external }
    must_not_collide    : current_subjects { vsf.alpha.>, bbh.>, vsf.alpha.algedonic }
    Beer_principle      : S3* visible_to_S5 ∧ ¬filterable_by_S3
  question:
    ask = "Cuál notation respeta mejor (i) S3* es independent_observer, no_child_of_S3
           y (ii) subscribers externos pueden suscribir audit_class sin tocar
           subjects internos del nucleus operacional?"
  default_if_undecided = (a)

// ─────────────────────────────────────────────────────────────────────────
// Q2 — Alert predicate language (extensibility-load-bearing)
// ─────────────────────────────────────────────────────────────────────────

decide("Q2.predicate_language"):
  context:
    location = s5_policy.s3_star.alert_predicate
    purpose  = "S5 declares qué findings → algedonic, sin recompile s3-star"
  options = {
    (a): { kind: "json_dsl"
           example: { all_of: [ { field: "severity",  op: ">=", value: 7 },
                                { field: "category",  op: "in", value: ["covenant_drift","merkle_break"] } ] }
           pros: "declarative, parseable, no_code_exec"
           cons: "limited expressiveness" }
    (b): { kind: "cel_subset"  // Common Expression Language minimal
           example: "finding.severity >= 7 && finding.category in ['covenant_drift']"
           pros: "well_known, expressive"
           cons: "parser_dependency, eval_safety_concerns" }
    (c): { kind: "rust_const_fn_table"  // compile-time dispatch
           example: "match finding.category { CovenantDrift if f.sev >= 7 => true, _ => false }"
           pros: "max_safety, no_runtime_parse"
           cons: "no_S5_runtime_modify ⇒ violates 'S5_modifies_without_recompile'" }
  constraint:
    A5_corollary       : S5_modify_predicate_runtime ⇒ ¬(c)
    A0_min_complexity  : favor (a) for tier_α
    extensibility_path : (a) → (b) por v1.1 si needed
  question:
    ask = "Predicate language para Tier α — ¿(a) JSON-DSL minimal sufficient,
           o vale la pena (b) CEL desde el principio? Recomienda + justificación."
  default_if_undecided = (a)

// ─────────────────────────────────────────────────────────────────────────
// Q3 — s3_star_sample event schema (contract con canonical chain)
// ─────────────────────────────────────────────────────────────────────────

decide("Q3.sample_event_schema"):
  context:
    inherits  = CanonicalEvent v0.2.1
    system_id = "s3_star"           // distinct from vsf_nucleus, bbh
    chain     = SEPARATE merkle chain (s3-star writes own events.jsonl)
                OR same chain via NATS publish only?
  options = {
    (a): { chain: "separate"
           path:  "/var/lib/vsf/s3_star/events.jsonl"
           pub:   "nats vsf.alpha.s3_star.audit.<type>"
           pros:  "true independence — VSF compromise no afecta audit ledger"
           cons:  "2 chains to verify, S3* witness becomes its own canonical" }
    (b): { chain: "shared via canonical NATS publish only"
           path:  "no_local_events.jsonl, only_publish_through_nats"
           pub:   "nats vsf.alpha.s3_star.audit.<type>"
           pros:  "single source of truth (vsf-nucleus events.jsonl) after γ.9 absorption"
           cons:  "s3-star findings depend on vsf-nucleus NATS up — coupling violates isolation" }
    (c): { chain: "both: local + publish"
           pros:  "defense in depth"
           cons:  "2 ledgers to reconcile" }
  constraint:
    Beer_principle    : S3* sees what S3 misses ⇒ ¬depend_on(S3.transport_alive)
    audit_integrity   : audit_log_compromise ⇒ S3* function lost
  required_fields:
    extends_CanonicalEvent
    + { audit_target: "covenant|merkle|s4_decision|drift"
      , finding_severity: f64 ∈ [0,10]
      , finding_class: "noop|low|medium|high|critical"
      , sample_method: "poisson|periodic|suspicion_driven"
      , predicate_matched: Option<String>  // which alert_predicate matched
      , source_event_hash: Option<String>  // what we audited (chain link)
      }
  question:
    ask = "Schema-level (a/b/c)? Razón principal."
  default_if_undecided = (a)

// ─────────────────────────────────────────────────────────────────────────
// Q4 — Audit cycle workflow (sequence of operations)
// ─────────────────────────────────────────────────────────────────────────

decide("Q4.cycle_workflow"):
  context:
    trigger    = poisson_tick(λ = 1 / mean_interval_secs)
    timeout    = ≤ 60s per cycle  // bounded so missed sample doesn't pile up
  proposed_sequence = [
    step_1: "covenant_check": { local_sha256(covenant.vsm) =?= HTTPS_GET(canonical_hash_source) }
    step_2: "merkle_spot_check": { sample N=10 recent events, verify prev_hash chain locally }
    step_3: "s4_decision_audit": { fetch last K=5 s4-analysis events, check vs covenant constraints }
    step_4: "policy_eval": { eval s5_policy.s3_star.alert_predicate over findings }
    step_5: "emit": { → events.jsonl OR nats per Q3 }
    step_6: "algedonic_maybe": { if predicate matched ∧ severity ≥ threshold → emit algedonic_emit }
  ]
  options = {
    (a): "as_proposed (1→2→3→4→5→6)"
    (b): "parallel: (1 ∥ 2 ∥ 3) → 4 → 5 → 6"  // concurrency, faster
    (c): "covenant_first_blocking: if (1) FAIL → halt, raise algedonic immediately, skip 2-3"
  }
  constraint:
    bounded_time     : ∀ cycle, total_duration < 60s
    fail_isolation   : step_N failure ⇒ ¬propagate, log + continue next cycle
    covenant_special : covenant drift = highest priority (Beer: identity > observation)
  question:
    ask = "Sequence (a/b/c)? Si (c), ¿qué significa 'halt' — process exit, o solo skip resto del cycle?"
  default_if_undecided = (c) con halt = skip_rest_of_cycle ∧ emit_algedonic

// ─────────────────────────────────────────────────────────────────────────
// Q5 — Algedonic emission integration
// ─────────────────────────────────────────────────────────────────────────

decide("Q5.algedonic_integration"):
  context:
    target_channel    = vsf.alpha.algedonic  (current γ.4 binary)
    current_emitters  = { vsf-nucleus.γ.4 (S3 self-fire), bbh.<inst>.algedonic (future S1) }
    s3_star_addition  = third emitter on same channel
  question_a:
    "Does S3* publish to SAME channel vsf.alpha.algedonic, OR own subject
     vsf.alpha.s3_star.algedonic that S5 subscribes separately?"
  options_a = {
    (a): "same channel vsf.alpha.algedonic — single audit path to S5"
    (b): "separate vsf.alpha.s3_star.algedonic — S5 distinguishes source"
  }
  constraint_a:
    Beer_S3_star    : "bypass S3 hierarchy" ⇒ must reach S5 directly
    rate_limit_pool : per s5_policy.algedonic.rate_limit_per_sec = 2.0 — shared o per-origin?
  question_b:
    "Rate limit — per-origin (s3-star tiene su own 2/sec) o global pool (s3-star
     comparte 2/sec con vsf-nucleus self-fire y bbh)?"
  options_b = {
    (a): per_origin (s3-star: 2/sec, vsf-nucleus: 2/sec, bbh: 2/sec — total 6/sec max)
    (b): global_pool (∑ all origins ≤ 2/sec — saturable)
  }
  default_if_undecided: question_a → (a), question_b → (a) per_origin
  rationale_a_default: "single channel = S5 unified audit path, simpler"
  rationale_b_default: "per_origin avoids one component DOSing the channel,
                       matches existing algedonic.rs MAX_PER_SEC=2.0 per origin"

// ─────────────────────────────────────────────────────────────────────────
// Response format (VSL strict)
// ─────────────────────────────────────────────────────────────────────────

format("response"):
  ∀ q ∈ {Q1..Q5}:
    {
      decide.q.choice    = <a|b|c|...>
      decide.q.rationale = <1-3 lines>
      decide.q.refine    = Option<{ modification: <text> }>
    }
  signoff = {
    A0_design_locked = bool
    next_unblocker   = Option<question>  // si quedan dudas
    vsl_iteration_n  = 2
  }

// END BRIEF
@vsl_end
