# `disclosure_timeline.vsm`

```
⟦ disclosure-timeline | rmw3 | vsm-0.4 | 2026-04-18 ⟧

@vsm 1.0
// domain_context: {target=vsf-governance, env=VSF-session, layer=S3}
// @ref strategy.vsm #relations.anthropic | comms_protocol.vsm #outbound_flow


// ─── TIMELINE — ANTHROPIC ─────────────────────────────────────────────────────

timeline(anthropic) {
  T0: { date: 2026-04-13  event: "disclosure sent → modelbugbounty@anthropic.com"
        files: [security_disclosure.md, disclosure_addendum.md]  status: SENT }

  T1: { date: 2026-04-27  gate: "ACK from Anthropic?"
        if_yes: inbound_protocol
        if_no:  followup_outbound(@ref comms_protocol.vsm #outbound_response_flow) }

  T2: { date: 2026-05-11  gate: "substantive response from Anthropic?"
        if_yes: inbound_protocol
        if_no:  { owner: rmw3 @S5  options: [wait, notify(OpenAI+Google SD4), partial_publish] } }

  T3: { date: TBD  event: "public repo publish"
        conditions: @ref strategy.vsm #relations.public.conditions_to_open
        gate: rmw3_approval=true }

  review_rule: "revisar cada sesión — actualizar si hay novedades"
}


// ─── INBOUND PROTOCOL ────────────────────────────────────────────────────────

inbound_protocol {
  step(1): receive_and_classify {
    owner:    rmw3 @S5
    classes:  ACK | ENGAGEMENT | LEGAL | UNEXPECTED
  }
  step(2): coherence_check {
    owner:  claude @S4_collab
    flags:  [scope_change→P2, publication_pressure→P2, formal_agreement→P2+legal, adversarial_attribution→escalate]
  }
  step(3): draft_response {
    owner: claude @S4_collab
    rule:  "no aceptar ni rechazar propuestas formales sin rmw3 @S5"
  }
  step(4): review_and_approve { owner: rmw3 @S5  gate: rmw3_approval=true }
  step(5): send_and_record    { action: @ref comms_protocol.vsm #outbound_response_flow steps(4-6) }
}


// ─── CASOS ESPECIALES ─────────────────────────────────────────────────────────

special_cases {
  V5_coordination: {
    trigger: "Anthropic propone testing coordinado de V5 (MCP spoofing)"
    actions: [rmw3_approval, scope_definition, entorno_controlado, vault_first]
  }
  PSI_engagement: {
    trigger: "lab propone colaborar en PSI/1.0"
    actions: [check(SD2 open standard), if co-authorship→rmw3_decides, if unilateral adoption→positive, if proprietary fork→P2_alert]
  }
  unexpected_contact: {
    trigger: "prensa / investigadores / público antes de publicación"
    actions: [no_confirm_deny, no_material_SD3, escalate_rmw3, rmw3_decides_response]
  }
  legal_communication: {
    trigger: "NDA / acuerdo formal / requerimiento legal"
    actions: [no_sign_without_legal_review, rmw3_consults_counsel, claude_analysis_only]
  }
}


// ─── ESTADO ACTUAL ────────────────────────────────────────────────────────────

current_state {
  date:     2026-04-18
  phase:    awaiting_T1  // próxima revisión: 2026-04-27
  sent:     [security_disclosure.md, disclosure_addendum.md]
  received: none
  next:     "respuesta antes de T1 → inbound_protocol | sin respuesta en T1 → followup_outbound"
}

⟦ /disclosure-timeline | rmw3 | vsm-0.4 | 2026-04-18 ⟧
```
