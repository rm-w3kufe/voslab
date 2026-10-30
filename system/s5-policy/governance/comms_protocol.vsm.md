# `comms_protocol.vsm`

```
⟦ comms-protocol | rmw3 | vsm-0.4 | 2026-04-18 ⟧

@vsm 1.0
// domain_context: {target=vsf-governance, env=VSF-session, layer=S4}
// External communications protocol — scope: emails, docs sent, lab responses, standards bodies

comm_types {
  OUTBOUND_DISCLOSURE: flow=outbound_flow  triage=true
  OUTBOUND_RESPONSE:   flow=outbound_flow  triage=true
  OUTBOUND_FOLLOWUP:   flow=outbound_flow  triage=true
  OUTBOUND_STANDARDS:  flow=outbound_flow  triage=true  gate=SD4_resolved
}

outbound_flow {
  step(1): coherence_check  owner=claude  // verify against strategy.vsm SD1-SD5; conflict → escalate rmw3 @S5
  step(2): draft            owner=claude  // docs/governance/<name>.md — no RESTRICTED content without rmw3
  step(3): review           owner=rmw3    // rmw3_approval=true before continuing
  step(4): snapshot         owner=claude  // sha256sum → vault/triage/<name>_sent.md + TRIAGE_README.md
  step(5): send             owner=rmw3    // record: recipient, date, method
  step(6): record           owner=claude  // update strategy.vsm#relations.<recipient>.sent[] + git commit
  invariant: "step(3) ∧ step(4) required before any send"
}

content_rules {
  allowed:    [V1-V5 conceptual classes, M1-M4 mitigations, VSF/PSI description, disclosure timeline]
  restricted: [V1 payloads, V4 raw transcripts, V5 implementation]  // requires rmw3 @S5 + NDA (SD5)
  never:      [involuntary third-party identifiers, personal user data]
  authority:  rmw3 @S5 — all exceptions require explicit approval
}

comm_log {
  sent(2026-04-13): {
    to:      modelbugbounty@anthropic.com
    files:   [security_disclosure.md, disclosure_addendum.md]
    triage:  [vault/triage/security_disclosure_sent.md, vault/triage/disclosure_addendum_sent.md]
    status:  awaiting_response
  }
}

integrity_rules {
  C1: external comms require rmw3 @S5 approval before sending
  C2: sent comms have vault/triage/ snapshot before send
  C3: sent comms recorded in strategy.vsm#relations + comm_log
  C4: if request contradicts SD1-SD5 → claude alerts rmw3, does not respond
  C5: claude does not impersonate rmw3 or respond as project author
}

⟦ /comms-protocol | rmw3 | vsm-0.4 | 2026-04-18 ⟧
```
