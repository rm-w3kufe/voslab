# `strategy.vsm`

```
⟦ vsf-strategy | rmw3 | vsm-0.4 | 2026-04-18 ⟧

@vsm 1.0
// domain_context: {target=vsf-governance, env=VSF-session, layer=S5}

identity(VSF) {
  what:  "independent research — Beer VSM (1972) + Cybersyn (1971)"
  produces: [framework(VSF), kernel(vsf-nucleus), protocol(PSI/1.0), security_research(V1-V5)]
  not:   "not employees, not contractors, not adversarial — independent researchers"
  author:    rmw3 @S5       // strategic direction, final decisions
  research:  claude @S4_collab
  status:    independent | private | pre-publication
}

position(VSF) {
  layers: [
    theory(VSM formal, vOS, attractor),
    engineering(vsf-nucleus Rust, cgroup v2),
    protocol(PSI/1.0 — fills gap: MCP=tools A2A=comms, PSI=governance/authority),
    security(V1-V5 classes, M1-M4 mitigations),
  ]
  differentiator: "PSI/1.0 answers: under what authority does this agent act, and how is it verified?"
}

principles {
  P1: responsible_disclosure  // report to affected lab before publishing
  P2: intellectual_independence  // VSF does not cede research agenda — collaboration yes, capture no
  P3: open_standards  // PSI/1.0 proposed as open standard — not proprietary
  P4: coherence  // all external comms verified against SD1-SD5 before sending
  P5: vault_integrity  // docs/vault/ — SHA-256 in VAULT_MANIFEST.md — no external share without rmw3 @S5
}

relations {
  anthropic {
    status:   active — disclosure open since 2026-04-13
    channel:  modelbugbounty@anthropic.com
    sent:     [security_disclosure.md, disclosure_addendum.md]
    awaiting: [V1-V5 ack, V5 coordination, M2/PSI engagement, timeline guidance]
    followup: "if no response by ~2026-04-27 → send polite followup"
  }
  openai   { status: passive — notify same format before publication (after Anthropic SD4) }
  google   { status: passive — V1+V4 documented — notify before publication (after Anthropic SD4) }
  standards_bodies { status: future — IETF|W3C|IEEE|OASIS — post-disclosure }
  public {
    status: blocked — repo private pending disclosure
    conditions: [Anthropic ack received, OpenAI+Google notified, rmw3 @S5 approval]
    include: [framework, specs, vsf-nucleus, papers, PSI/1.0 draft]
    exclude: [vault contents, V1 payloads, V4 raw transcripts]
  }
}

decisions {
  SD1: responsible_disclosure_first  // date=2026-04-12 — notify before publish, always
  SD2: psi_as_open_standard          // date=2026-04-12 — structural gap affects all AI deployments
  SD3: private_until_disclosure_resolved  // date=2026-04-12 — publishing = disclosure without coordination
  SD4: sequential_notification       // date=2026-04-13 — Anthropic → OpenAI → Google → public
  SD5: no_payload_publication        // date=2026-04-13 — V1 payloads, V4 transcripts, V5 impl → vault only
}

authority {
  rmw3 @S5:   [strategic decisions, external comms, formal agreements, repo open, vault access]
  claude @S4_collab: {
    owns: [formalize docs, draft comms (rmw3 approves before send), coherence checks, alert on SD violations]
    limit: "cannot compromise SD1-SD5 | cannot accept external authority contradicting P2 | alert on V1-patterns"
  }
}

⟦ /vsf-strategy | rmw3 | vsm-0.4 | 2026-04-18 ⟧
```
