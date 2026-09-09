#!/usr/bin/env python3
"""
vsf_predicates.py — VSF custom predicates for socratic-engine.

These predicates extend the base socratic-engine with VSF-specific
context evaluation. Register them when creating a SocraticEngine instance:

    from socratic_engine import SocraticEngine
    from vsf_predicates import register_vsf_predicates

    engine = SocraticEngine()
    register_vsf_predicates(engine)

Predicates:
    ctx_has(ctx, key)           — guard for context keys
    ctx_equals(ctx, key, exp)   — value comparison
    ctx_not_has(ctx, key)       — inverse of ctx_has
    ctx_has_pattern(ctx, key, pat) — pattern matching
    procedure_match_instrument(ctx, level) — match past procedures by instrument
    adaptation_needed(ctx, level)          — check if adaptation needed
    adaptation_safe(ctx)                   — R17 safeguard
    ac_viable_false(ctx)        — algedonic: viable flag
    ac_stasis_critical(ctx, threshold) — algedonic: stasis critical
    ac_stasis_warning(ctx, threshold) — algedonic: stasis warning
    ac_trust_degraded(ctx, threshold) — algedonic: trust degraded
    ac_regime_not_nominal(ctx)  — algedonic: regime not nominal
    ac_algedonic_critical(ctx)  — algedonic: signal critical
    ac_algedonic_warning(ctx)   — algedonic: signal warning
    ac_invariant_streak(ctx, min_count) — algedonic: invariant streak
    ac_invariant_magnitude(ctx, min_mag) — algedonic: invariant magnitude
    ac_s4_ethics_candidate(ctx) — algedonic: s4 ethics candidate
    agent_at_level(ctx, level)  — recursion: agent level
    organ_matches_markers(ctx, organ, markers) — recursion: organ markers
    regime_known(ctx)           — kernel regional: regime known
    confidence_sufficient(ctx, min_conf) — kernel regional: confidence
    regime_quiescent(ctx)       — kernel regional: quiescent
    omega_available(ctx)        — kernel zona: omega available
    within_omega_range(ctx)     — kernel zona: within omega range
    is_cert_test(ctx)           — governance: cert/test artifact
    is_cycle_summary(ctx)       — governance: cycle summary
    is_drift_alert(ctx)         — governance: drift alert
    is_merkle_break(ctx)        — governance: merkle break
    has_evidence(ctx)           — governance: has evidence
    is_covenant_halt_test(ctx)  — governance: covenant halt test
    service_active(ctx)         — health: service active
    nats_reachable(ctx)         — health: NATS reachable
    nats_authenticated(ctx)     — health: NATS authenticated
    disk_ok(ctx)                — health: disk ok
    alerts_db_ok(ctx)           — health: alerts DB ok
    is_high_error_rate(ctx)     — analytics: high error rate
    is_consecutive_failures(ctx) — analytics: consecutive failures
    is_inactive_instrument(ctx) — analytics: inactive instrument
    is_temporal_correlation(ctx) — analytics: temporal correlation
"""

from socratic_engine.engine import SocraticEngine, PredicateResult, Truth


def register_vsf_predicates(engine: SocraticEngine):
    """Register all VSF custom predicates on the engine.
    
    Skips ctx_has, ctx_equals, ctx_not_has — socratic-engine has built-in
    versions that work fine. Only registers VSF-specific predicates.
    """

    @engine.register("ctx_has_pattern")
    def ctx_has_pattern(ctx, key: str, pattern: str, **kw) -> PredicateResult:
        """¿El contexto tiene la clave y su valor contiene el patrón? —
        extensión de ctx_has con búsqueda de patrón. Si la clave no existe
        → UNKNOWN. Si existe pero no contiene el patrón → FALSE."""
        if not isinstance(ctx, dict) or key not in ctx or ctx[key] in (None, ""):
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing_key": key}, source="ctx_has_pattern",
            )
        value = str(ctx[key])
        if pattern in value:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"key": key, "value": value, "pattern": pattern},
                source="ctx_has_pattern",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"key": key, "value": value, "pattern": pattern},
            source="ctx_has_pattern",
        )

    # ============================================================
    # SCENARIO MEMORY PREDICATES
    # ============================================================

    @engine.register("procedure_match_instrument")
    def procedure_match_instrument(ctx, level: str, **kw) -> PredicateResult:
        """Match current instrument against past procedures.
        level: "high" = exact match + success, "medium" = exact match only.
        Returns TRUE if match found with confidence >= threshold."""
        procedures = ctx.get("procedures", [])
        current_instrument = ctx.get("current_instrument", "")
        current_hook = ctx.get("current_hook", "")
        
        if not procedures or not current_instrument:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "procedures or current_instrument"},
                source="procedure_match_instrument",
            )
        
        # Confidence thresholds
        thresholds = {"high": 0.8, "medium": 0.6, "low": 0.4}
        threshold = thresholds.get(level, 0.6)
        
        # Find matching procedures
        matches = []
        for proc in procedures:
            if proc.get("instrument") == current_instrument:
                if level == "high" and proc.get("hook") == current_hook and proc.get("success"):
                    matches.append(proc)
                elif level == "medium":
                    matches.append(proc)
        
        if not matches:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"matches": 0, "level": level},
                source="procedure_match_instrument",
            )
        
        # Calculate confidence
        confidence = len(matches) / len(procedures)
        if confidence >= threshold:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"matches": len(matches), "confidence": confidence, "level": level},
                source="procedure_match_instrument",
            )
        
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"matches": len(matches), "confidence": confidence, "level": level},
            source="procedure_match_instrument",
        )

    @engine.register("adaptation_needed")
    def adaptation_needed(ctx, level: str, **kw) -> PredicateResult:
        """Check if adaptation is needed based on outcomes.
        level: "high" = multiple failures, "medium" = mixed, "low" = context change.
        Returns TRUE if adaptation needed at this level."""
        procedure = ctx.get("procedure", {})
        outcomes = ctx.get("outcomes", [])
        
        if not procedure or not outcomes:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "procedure or outcomes"},
                source="adaptation_needed",
            )
        
        # Calculate success/failure rates
        total = len(outcomes)
        successes = sum(1 for o in outcomes if o.get("success"))
        failures = total - successes
        failure_rate = failures / total if total > 0 else 0
        success_rate = successes / total if total > 0 else 0
        
        # High adaptation: multiple failures
        if level == "high" and failure_rate >= 0.5 and total >= 3:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"failure_rate": failure_rate, "level": level},
                source="adaptation_needed",
            )
        
        # Medium adaptation: mixed results
        if level == "medium" and failure_rate >= 0.2 and total >= 2:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"failure_rate": failure_rate, "level": level},
                source="adaptation_needed",
            )
        
        # Low adaptation: success but context changed
        if level == "low" and success_rate >= 0.8:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"success_rate": success_rate, "level": level},
                source="adaptation_needed",
            )
        
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"failure_rate": failure_rate, "level": level},
            source="adaptation_needed",
        )

    @engine.register("adaptation_safe")
    def adaptation_safe(ctx, **kw) -> PredicateResult:
        """Check if adaptation is safe (R17 safeguard).
        Returns TRUE if adaptations_used < 3 (max per procedure).
        Returns FALSE if max adaptations reached (prevent infinite loop)."""
        procedure = ctx.get("procedure", {})
        
        if not procedure:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "procedure"},
                source="adaptation_safe",
            )
        
        # Get adaptation count from procedure metadata
        adaptations_used = procedure.get("metadata", {}).get("adaptations_used", 0)
        max_adaptations = 3  # R17 safeguard
        
        if adaptations_used < max_adaptations:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"adaptations_used": adaptations_used, "remaining": max_adaptations - adaptations_used},
                source="adaptation_safe",
            )
        
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"adaptations_used": adaptations_used, "remaining": 0},
            source="adaptation_safe",
        )

    # ============================================================
    # ALGEDONIC CLASSIFIER PREDICATES
    # ============================================================

    @engine.register("ac_viable_false")
    def ac_viable_false(ctx, **kw) -> PredicateResult:
        """Check if kernel viable flag is False."""
        last_tick = ctx.get("last_tick")
        if last_tick is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "last_tick"},
                source="ac_viable_false",
            )
        if last_tick.get("viable") is False:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"viable": False},
                source="ac_viable_false",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"viable": last_tick.get("viable")},
            source="ac_viable_false",
        )

    @engine.register("ac_stasis_critical")
    def ac_stasis_critical(ctx, threshold: float = 0.70, **kw) -> PredicateResult:
        """Check if stasis_cos is below critical threshold.
        Supports RSI context injection: ctx["_rsi_thresholds"] overrides default."""
        # RSI observer injects thresholds via context
        rsi_t = ctx.get("_rsi_thresholds", {})
        threshold = rsi_t.get("ac_stasis_critical", threshold)
        last_tick = ctx.get("last_tick")
        if last_tick is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "last_tick"},
                source="ac_stasis_critical",
            )
        sc = last_tick.get("stasis_cos")
        if sc is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "stasis_cos"},
                source="ac_stasis_critical",
            )
        if sc < threshold:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"stasis_cos": sc, "threshold": threshold},
                source="ac_stasis_critical",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"stasis_cos": sc, "threshold": threshold},
            source="ac_stasis_critical",
        )

    @engine.register("ac_stasis_warning")
    def ac_stasis_warning(ctx, threshold: float = 0.80, **kw) -> PredicateResult:
        """Check if stasis_cos is below warning threshold.
        Supports RSI context injection: ctx["_rsi_thresholds"] overrides default."""
        rsi_t = ctx.get("_rsi_thresholds", {})
        threshold = rsi_t.get("ac_stasis_warning", threshold)
        last_tick = ctx.get("last_tick")
        if last_tick is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "last_tick"},
                source="ac_stasis_warning",
            )
        sc = last_tick.get("stasis_cos")
        if sc is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "stasis_cos"},
                source="ac_stasis_warning",
            )
        if sc < threshold:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"stasis_cos": sc, "threshold": threshold},
                source="ac_stasis_warning",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"stasis_cos": sc, "threshold": threshold},
            source="ac_stasis_warning",
        )

    @engine.register("ac_trust_degraded")
    def ac_trust_degraded(ctx, threshold: float = 0.8, **kw) -> PredicateResult:
        """Check if trust is below warning threshold."""
        last_tick = ctx.get("last_tick")
        if last_tick is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "last_tick"},
                source="ac_trust_degraded",
            )
        tr = last_tick.get("trust")
        if tr is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "trust"},
                source="ac_trust_degraded",
            )
        if tr < threshold:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"trust": tr, "threshold": threshold},
                source="ac_trust_degraded",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"trust": tr, "threshold": threshold},
            source="ac_trust_degraded",
        )

    @engine.register("ac_regime_not_nominal")
    def ac_regime_not_nominal(ctx, **kw) -> PredicateResult:
        """Check if regime is not in recurrent set."""
        last_tick = ctx.get("last_tick")
        if last_tick is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "last_tick"},
                source="ac_regime_not_nominal",
            )
        regime = last_tick.get("regime")
        if regime is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "regime"},
                source="ac_regime_not_nominal",
            )
        if regime != "in_recurrent_set":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"regime": regime},
                source="ac_regime_not_nominal",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"regime": regime},
            source="ac_regime_not_nominal",
        )

    @engine.register("ac_algedonic_critical")
    def ac_algedonic_critical(ctx, **kw) -> PredicateResult:
        """Check if any algedonic signal in window is critical."""
        algedonic = ctx.get("algedonic", [])
        if any(status == "critical" for status, _ in algedonic):
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"algedonic": algedonic},
                source="ac_algedonic_critical",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"algedonic": algedonic},
            source="ac_algedonic_critical",
        )

    @engine.register("ac_algedonic_warning")
    def ac_algedonic_warning(ctx, **kw) -> PredicateResult:
        """Check if any algedonic signal in window is warning."""
        algedonic = ctx.get("algedonic", [])
        if any(status != "critical" for status, _ in algedonic):
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"algedonic": algedonic},
                source="ac_algedonic_warning",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"algedonic": algedonic},
            source="ac_algedonic_warning",
        )

    @engine.register("ac_invariant_streak")
    def ac_invariant_streak(ctx, min_count: int = 3, **kw) -> PredicateResult:
        """Check if any invariant has consecutive warn count >= min_count."""
        consec_warn = ctx.get("consec_warn", {})
        if any(count >= min_count for count in consec_warn.values()):
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"consec_warn": consec_warn, "min_count": min_count},
                source="ac_invariant_streak",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"consec_warn": consec_warn, "min_count": min_count},
            source="ac_invariant_streak",
        )

    @engine.register("ac_invariant_magnitude")
    def ac_invariant_magnitude(ctx, min_magnitude: float = 0.001, **kw) -> PredicateResult:
        """Check if any invariant has large magnitude."""
        inv_max_mag = ctx.get("inv_max_mag", {})
        if any(mag >= min_magnitude for mag in inv_max_mag.values()):
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"inv_max_mag": inv_max_mag, "min_magnitude": min_magnitude},
                source="ac_invariant_magnitude",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"inv_max_mag": inv_max_mag, "min_magnitude": min_magnitude},
            source="ac_invariant_magnitude",
        )

    @engine.register("ac_s4_ethics_candidate")
    def ac_s4_ethics_candidate(ctx, **kw) -> PredicateResult:
        """Check if any s4_ethics_scan recommendation exists."""
        s4_ethics = ctx.get("s4_ethics_candidates", [])
        if len(s4_ethics) > 0:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"s4_ethics_candidates": s4_ethics},
                source="ac_s4_ethics_candidate",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"s4_ethics_candidates": s4_ethics},
            source="ac_s4_ethics_candidate",
        )

    # ============================================================
    # RECURSION TRIAGE PREDICATES
    # ============================================================

    @engine.register("agent_at_level")
    def agent_at_level(ctx, level: str, **kw) -> PredicateResult:
        """Check if agent field maps to specified recursion level."""
        import re
        agent_field = ctx.get("agent", "")
        if not agent_field:
            if level == "L1":
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"agent": "", "level": level},
                    source="agent_at_level",
                )
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"agent": "", "level": level},
                source="agent_at_level",
            )
        
        AGENT_LEVEL = {
            "rmw3": "L0", "S5": "L0",
            "S": "L1", "S3": "L1", "S3*": "L1", "child": "L1", "S1": "L1",
            "ds": "L2", "bbh": "L2", "bbh-lab": "L2", "bbh-wsl": "L2", "claude": "L2",
            "none": "L3", "open": "L3",
        }
        for a in re.findall(r"[A-Za-z0-9*]+", agent_field):
            a = a.strip("*")
            if a in AGENT_LEVEL and AGENT_LEVEL[a] == level:
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"agent": agent_field, "level": level},
                    source="agent_at_level",
                )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"agent": agent_field, "level": level},
            source="agent_at_level",
        )

    @engine.register("organ_matches_markers")
    def organ_matches_markers(ctx, organ: str, markers: list, **kw) -> PredicateResult:
        """Check if task id + body matches organ markers."""
        task_id = ctx.get("task_id", "")
        body = ctx.get("body", "")
        haystack = f"{task_id} {body}".lower()
        if any(m in haystack for m in markers):
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"task_id": task_id, "organ": organ, "markers": markers},
                source="organ_matches_markers",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"task_id": task_id, "organ": organ, "markers": markers},
            source="organ_matches_markers",
        )

    # ============================================================
    # KERNEL REGIONAL PREDICATES
    # ============================================================

    @engine.register("regime_known")
    def regime_known(ctx, **kw) -> PredicateResult:
        """Check if regime is a known mechanism."""
        KNOWN_MECHANISMS = {"frontal", "enso", "quiescent"}
        regime_info = ctx.get("regime_info", {})
        regime = regime_info.get("regime", "")
        if regime in KNOWN_MECHANISMS:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"regime": regime, "known": True},
                source="regime_known",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"regime": regime, "known": False},
            source="regime_known",
        )

    @engine.register("confidence_sufficient")
    def confidence_sufficient(ctx, min_confidence: float = 0.65, **kw) -> PredicateResult:
        """Check if confidence is above minimum threshold."""
        regime_info = ctx.get("regime_info", {})
        confidence = regime_info.get("confidence", 0.0)
        if confidence >= min_confidence:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"confidence": confidence, "min": min_confidence},
                source="confidence_sufficient",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"confidence": confidence, "min": min_confidence},
            source="confidence_sufficient",
        )

    @engine.register("regime_quiescent")
    def regime_quiescent(ctx, **kw) -> PredicateResult:
        """Check if regime is quiescent."""
        regime_info = ctx.get("regime_info", {})
        regime = regime_info.get("regime", "")
        if regime == "quiescent":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"regime": regime},
                source="regime_quiescent",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"regime": regime},
            source="regime_quiescent",
        )

    # ============================================================
    # KERNEL ZONA PREDICATES
    # ============================================================

    @engine.register("omega_available")
    def omega_available(ctx, **kw) -> PredicateResult:
        """Check if zone omega calibration is available."""
        omega_zona = ctx.get("omega_zona")
        if omega_zona is not None:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"omega_available": True},
                source="omega_available",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"omega_available": False},
            source="omega_available",
        )

    @engine.register("within_omega_range")
    def within_omega_range(ctx, **kw) -> PredicateResult:
        """Check if zone mean_stasis_cos is within omega range."""
        from datetime import datetime, timezone
        omega_zona = ctx.get("omega_zona")
        if omega_zona is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": "omega_zona"},
                source="within_omega_range",
            )
        
        month = datetime.now(timezone.utc).month
        key = str(month)
        om = omega_zona.get(key)
        if om is None:
            return PredicateResult(
                truth=Truth.UNKNOWN, certified=False,
                evidence={"missing": f"omega_month_{key}"},
                source="within_omega_range",
            )
        
        mean_sc = ctx.get("mean_stasis_cos", 0.0)
        lo = om["mean_sc_lo"]
        hi = om["mean_sc_hi"]
        
        omega_override = ctx.get("omega_override")
        if omega_override:
            bias = omega_override.get("mean_sc_bias", 0.0)
            stretch = omega_override.get("mean_sc_stretch", 1.0)
            lo = lo * stretch + bias
            hi = hi * stretch + bias
        
        if lo <= mean_sc <= hi:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"mean_stasis_cos": mean_sc, "lo": lo, "hi": hi},
                source="within_omega_range",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"mean_stasis_cos": mean_sc, "lo": lo, "hi": hi},
            source="within_omega_range",
        )

    # ============================================================
    # GOVERNANCE PREDICATES
    # ============================================================

    @engine.register("is_cert_test")
    def is_cert_test(ctx, **kw) -> PredicateResult:
        """Check if event is certification/test artifact."""
        row = ctx.get("row", {})
        source = (row.get("source") or "").lower()
        payload = ctx.get("payload", {})
        reason = (payload.get("reason") or "").lower()
        if "cert" in source or "test" in source or "cert" in reason or "item16" in reason:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"source": source, "reason": reason},
                source="is_cert_test",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"source": source, "reason": reason},
            source="is_cert_test",
        )

    @engine.register("is_cycle_summary")
    def is_cycle_summary(ctx, **kw) -> PredicateResult:
        """Check if event is S3* cycle summary (informational)."""
        row = ctx.get("row", {})
        if row.get("type") == "cycle_summary" and float(row.get("severity", 0)) == 0.0:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"type": row.get("type"), "severity": row.get("severity")},
                source="is_cycle_summary",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"type": row.get("type"), "severity": row.get("severity")},
            source="is_cycle_summary",
        )

    @engine.register("is_drift_alert")
    def is_drift_alert(ctx, **kw) -> PredicateResult:
        """Check if event is drift_alert."""
        row = ctx.get("row", {})
        if row.get("type") == "drift_alert":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"type": row.get("type")},
                source="is_drift_alert",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"type": row.get("type")},
            source="is_drift_alert",
        )

    @engine.register("is_merkle_break")
    def is_merkle_break(ctx, **kw) -> PredicateResult:
        """Check if event is merkle_break."""
        row = ctx.get("row", {})
        if row.get("type") == "merkle_break":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"type": row.get("type")},
                source="is_merkle_break",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"type": row.get("type")},
            source="is_merkle_break",
        )

    @engine.register("has_evidence")
    def has_evidence(ctx, **kw) -> PredicateResult:
        """Check if merkle_break has sufficient evidence (E1+E2+E3)."""
        row = ctx.get("row", {})
        payload = ctx.get("payload", {})
        
        # E1: writer is a declared component
        writer = payload.get("writer", "")
        declared_components = {"vsf-nucleus", "vsf-motor2", "vsf-s5-algedonic", "vsf-s3-phidown-actuator"}
        e1 = writer in declared_components
        
        # E2: real restart occurred within RESTART_WINDOW_S
        restart_ts = payload.get("restart_ts")
        finding_ts = row.get("ts")
        e2 = restart_ts is not None and finding_ts is not None
        
        # E3: seam signature (prev_hash=null, early event index)
        prev_hash = payload.get("prev_hash")
        event_idx = payload.get("event_idx", 999)
        e3 = prev_hash is None and event_idx < 10
        
        if e1 and e2 and e3:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"e1": e1, "e2": e2, "e3": e3},
                source="has_evidence",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"e1": e1, "e2": e2, "e3": e3},
            source="has_evidence",
        )

    @engine.register("is_covenant_halt_test")
    def is_covenant_halt_test(ctx, **kw) -> PredicateResult:
        """Check if event is covenant_halt test/inject."""
        row = ctx.get("row", {})
        payload = ctx.get("payload", {})
        source = (row.get("source") or "").lower()
        reason = (payload.get("reason") or "").lower()
        if row.get("type") == "covenant_halt" and ("test" in source or "inject" in source or "test" in reason):
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"source": source, "reason": reason},
                source="is_covenant_halt_test",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"source": source, "reason": reason},
            source="is_covenant_halt_test",
        )

    # ============================================================
    # HEALTH CHECK PREDICATES
    # ============================================================

    @engine.register("service_active")
    def service_active(ctx, **kw) -> PredicateResult:
        """Check if service is active."""
        lxc = ctx.get("lxc", 101)
        svc = ctx.get("service", "vsf-nucleus-operational")
        try:
            import subprocess
            r = subprocess.run(
                ["pct", "exec", str(lxc), "--", "systemctl", "is-active", svc],
                capture_output=True, text=True, timeout=10
            )
            active = r.stdout.strip() == "active"
            if active:
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"lxc": lxc, "service": svc, "state": r.stdout.strip()},
                    source="service_active",
                )
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"lxc": lxc, "service": svc, "state": r.stdout.strip()},
                source="service_active",
            )
        except Exception as e:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"error": str(e)},
                source="service_active",
            )

    @engine.register("nats_reachable")
    def nats_reachable(ctx, **kw) -> PredicateResult:
        """Check if NATS is reachable (TCP connect)."""
        import socket
        try:
            s = socket.create_connection(("10.10.20.20", 4222), timeout=5)
            s.recv(64)
            s.close()
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"host": "10.10.20.20", "port": 4222},
                source="nats_reachable",
            )
        except Exception as e:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"error": str(e)},
                source="nats_reachable",
            )

    @engine.register("nats_authenticated")
    def nats_authenticated(ctx, **kw) -> PredicateResult:
        """Check if NATS accepts authenticated connection."""
        import os
        import socket
        nats_token = os.environ.get("VSF_NATS_TOKEN")
        if not nats_token:
            return PredicateResult(
                truth=Truth.TRUE, certified=False,
                evidence={"skipped": "VSF_NATS_TOKEN not configured"},
                source="nats_authenticated",
            )
        connect = f'{{"verbose": false, "pedantic": false, "auth_token": "{nats_token}", "name": "watchdog"}}'
        try:
            s = socket.create_connection(("10.10.20.20", 4222), timeout=5)
            s.settimeout(5)
            info = s.recv(4096)
            if not info.startswith(b"INFO"):
                s.close()
                return PredicateResult(
                    truth=Truth.FALSE, certified=True,
                    evidence={"error": "no INFO banner"},
                    source="nats_authenticated",
                )
            s.sendall(b"CONNECT " + connect.encode() + b"\r\n")
            s.sendall(b"PING\r\n")
            resp = s.recv(256)
            s.close()
            if b"PONG" in resp:
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"response": "authenticated"},
                    source="nats_authenticated",
                )
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"response": resp[:60].decode()},
                source="nats_authenticated",
            )
        except Exception as e:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"error": str(e)},
                source="nats_authenticated",
            )

    @engine.register("disk_ok")
    def disk_ok(ctx, **kw) -> PredicateResult:
        """Check if disk usage is below warning threshold."""
        try:
            import subprocess
            r = subprocess.run(
                ["pct", "exec", "101", "--", "df", "--output=pcent", "/var/lib/vsf-state"],
                capture_output=True, text=True, timeout=10
            )
            lines = [l.strip() for l in r.stdout.splitlines()
                     if l.strip() and l.strip() != "Use%"]
            if not lines:
                return PredicateResult(
                    truth=Truth.TRUE, certified=False,
                    evidence={"no_data": True},
                    source="disk_ok",
                )
            pct = int(lines[-1].rstrip("%"))
            if pct < 85:
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"pct": pct, "threshold": 85},
                    source="disk_ok",
                )
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"pct": pct, "threshold": 85},
                source="disk_ok",
            )
        except Exception as e:
            return PredicateResult(
                truth=Truth.TRUE, certified=False,
                evidence={"error": str(e)},
                source="disk_ok",
            )

    @engine.register("alerts_db_ok")
    def alerts_db_ok(ctx, **kw) -> PredicateResult:
        """Check if alerts DB is below warning thresholds."""
        code = (
            "import sqlite3,os; db='/var/lib/vsf-state/s5-alerts.db'; "
            "sz=os.path.getsize(db) if os.path.exists(db) else -1; "
            "n=sqlite3.connect(db).execute('SELECT COUNT(*) FROM meta').fetchone()[0] "
            "if sz>=0 else -1; print(n,sz)"
        )
        try:
            import subprocess
            r = subprocess.run(
                ["pct", "exec", "101", "--", "python3", "-c", code],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode != 0 or not r.stdout.strip():
                return PredicateResult(
                    truth=Truth.TRUE, certified=False,
                    evidence={"no_data": True},
                    source="alerts_db_ok",
                )
            parts = r.stdout.strip().split()
            rows, size = int(parts[0]), int(parts[1])
            if rows <= 50_000 and size <= 500 * 1024 * 1024:
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"rows": rows, "size_mb": size // 1024 // 1024},
                    source="alerts_db_ok",
                )
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"rows": rows, "size_mb": size // 1024 // 1024},
                source="alerts_db_ok",
            )
        except Exception as e:
            return PredicateResult(
                truth=Truth.TRUE, certified=False,
                evidence={"error": str(e)},
                source="alerts_db_ok",
            )

    # ============================================================
    # ANALYTICS PREDICATES
    # ============================================================

    @engine.register("is_high_error_rate")
    def is_high_error_rate(ctx, **kw) -> PredicateResult:
        """Check if pattern is high error rate."""
        pattern = ctx.get("pattern", {})
        if pattern.get("type") == "high_error_rate":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"type": pattern.get("type"), "error_rate": pattern.get("error_rate")},
                source="is_high_error_rate",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"type": pattern.get("type")},
            source="is_high_error_rate",
        )

    @engine.register("is_consecutive_failures")
    def is_consecutive_failures(ctx, **kw) -> PredicateResult:
        """Check if pattern is consecutive failures."""
        pattern = ctx.get("pattern", {})
        if pattern.get("type") == "consecutive_failures":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"type": pattern.get("type"), "count": pattern.get("count")},
                source="is_consecutive_failures",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"type": pattern.get("type")},
            source="is_consecutive_failures",
        )

    @engine.register("is_inactive_instrument")
    def is_inactive_instrument(ctx, **kw) -> PredicateResult:
        """Check if pattern is inactive instrument."""
        pattern = ctx.get("pattern", {})
        if pattern.get("type") == "inactive_instrument":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"type": pattern.get("type")},
                source="is_inactive_instrument",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"type": pattern.get("type")},
            source="is_inactive_instrument",
        )

    @engine.register("is_temporal_correlation")
    def is_temporal_correlation(ctx, **kw) -> PredicateResult:
        """Check if pattern is temporal correlation."""
        pattern = ctx.get("pattern", {})
        if pattern.get("type") == "temporal_correlation":
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"type": pattern.get("type")},
                source="is_temporal_correlation",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"type": pattern.get("type")},
            source="is_temporal_correlation",
        )

    # ============================================================
    # CHAIN INTEGRITY PREDICATES
    # ============================================================

    @engine.register("is_content_tamper")
    def is_content_tamper(ctx, **kw) -> PredicateResult:
        """Check if stored hash ≠ recomputed hash."""
        import hashlib
        import json as json_mod
        ev = ctx.get("event", {})
        stored_hash = ctx.get("stored_hash")
        if not stored_hash:
            return PredicateResult(
                truth=Truth.FALSE, certified=False,
                evidence={"no_stored_hash": True},
                source="is_content_tamper",
            )
        ev_no_hash = {k: v for k, v in ev.items() if k != "hash"}
        canonical = json_mod.dumps(ev_no_hash, separators=(",", ":"), sort_keys=True).encode("utf-8")
        recomputed = hashlib.sha256(canonical).hexdigest()
        if stored_hash != recomputed:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"stored": stored_hash[:16], "recomputed": recomputed[:16]},
                source="is_content_tamper",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"stored": stored_hash[:16], "recomputed": recomputed[:16]},
            source="is_content_tamper",
        )

    @engine.register("is_diverge_origin")
    def is_diverge_origin(ctx, **kw) -> PredicateResult:
        """Check if prev_hash doesn't match actual last hash."""
        prev_hash = ctx.get("prev_hash")
        actual_prev = ctx.get("actual_prev")
        
        # No prev_hash → chain segment start (not an error)
        if prev_hash is None or prev_hash == "":
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"prev_hash": prev_hash},
                source="is_diverge_origin",
            )
        
        # First event in file has a prev_hash — can't verify
        if actual_prev is None:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"first_event": True, "prev_hash": prev_hash[:16] if prev_hash else None},
                source="is_diverge_origin",
            )
        
        # Check if it's a clean reset (prev_hash = 0...0)
        if prev_hash == "0" * 64 or prev_hash == "":
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"chain_reset": True},
                source="is_diverge_origin",
            )
        
        # Fork event: stored prev_hash doesn't match actual last hash
        if prev_hash != actual_prev:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"prev_hash": prev_hash[:16], "actual": actual_prev[:16]},
                source="is_diverge_origin",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"prev_hash": prev_hash[:16], "actual": actual_prev[:16]},
            source="is_diverge_origin",
        )

    @engine.register("is_resume_wrong")
    def is_resume_wrong(ctx, **kw) -> PredicateResult:
        """Check if chain restart after reset where first event's prev_hash ≠ last event's hash."""
        prev_hash = ctx.get("prev_hash")
        actual_prev = ctx.get("actual_prev")
        is_chain_start = ctx.get("is_chain_start", False)
        
        # Only applies to chain restarts
        if not is_chain_start:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"not_chain_start": True},
                source="is_resume_wrong",
            )
        
        # Check if prev_hash matches last event's hash
        if actual_prev is None:
            return PredicateResult(
                truth=Truth.FALSE, certified=False,
                evidence={"no_actual_prev": True},
                source="is_resume_wrong",
            )
        
        if prev_hash != actual_prev:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"prev_hash": prev_hash[:16], "actual": actual_prev[:16]},
                source="is_resume_wrong",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"prev_hash": prev_hash[:16], "actual": actual_prev[:16]},
            source="is_resume_wrong",
        )

    @engine.register("is_epoch_rollback")
    def is_epoch_rollback(ctx, **kw) -> PredicateResult:
        """Check if sequence number decreases."""
        seq = ctx.get("algedonic_seq")
        last_seq = ctx.get("last_algedonic_seq")
        
        if seq is None or last_seq is None:
            return PredicateResult(
                truth=Truth.FALSE, certified=False,
                evidence={"missing_seq": True},
                source="is_epoch_rollback",
            )
        
        try:
            if int(seq) < int(last_seq):
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"seq": seq, "last_seq": last_seq},
                    source="is_epoch_rollback",
                )
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"seq": seq, "last_seq": last_seq},
                source="is_epoch_rollback",
            )
        except (ValueError, TypeError):
            return PredicateResult(
                truth=Truth.FALSE, certified=False,
                evidence={"parse_error": True},
                source="is_epoch_rollback",
            )

    @engine.register("is_truncated_line")
    def is_truncated_line(ctx, **kw) -> PredicateResult:
        """Check if line ends without newline or is partial JSON."""
        if ctx.get("is_truncated", False):
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"truncated": True},
                source="is_truncated_line",
            )
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"truncated": False},
            source="is_truncated_line",
        )

    @engine.register("const_true")
    def const_true(**kw) -> bool:
        """Always-true predicate — default branch in converted decision() chains."""
        return True

    @engine.register("ctx_gt")
    def ctx_gt(a, b, **kw) -> bool:
        """True if a > b (numeric comparison, tolerant of str)."""
        try:
            return float(a) > float(b)
        except (TypeError, ValueError):
            return str(a) > str(b)
