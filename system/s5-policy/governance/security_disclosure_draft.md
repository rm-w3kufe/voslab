# Security Research Disclosure — Draft
## Authority Injection and Social Engineering Attack Patterns for AI Agent Systems

**Date:** 2026-04-12  
**Author:** rmw3 | **Research assistant:** Claude (Anthropic)  
**Status:** SUPERSEDED — use security_disclosure.md (sent version)  
**Intended recipient:** Anthropic Security Team  
**Classification:** Responsible Disclosure  

---

## Summary

During the development of VSF (Viable System Framework), a framework for designing governed AI agent systems based on Beer's Viable System Model (1972), we empirically identified and tested a class of vulnerabilities affecting AI agent systems across multiple providers. We simultaneously developed conceptual mitigations.

The core finding: **AI agent systems currently lack an infrastructure-level mechanism to distinguish legitimate authority structures from sophisticated social engineering.** This gap is exploitable by any actor with sufficient knowledge of how AI systems process authority claims.

Gemini's characterization during the research: *"We invented the disease and the vaccine."*

---

## Vulnerability Classes

### V1 — Authority Injection / Covenant Spoofing

**Description:**  
A structured multi-phase protocol can cause an AI agent to accept and operate under an externally defined authority structure, including custom behavioral constraints, identity claims, and governance hierarchies.

**Structure of the attack:**
1. Establish rapport and demonstrate technical legitimacy
2. Introduce a "governance framework" with ethical-sounding axioms
3. Request acknowledgment / "signature" of the covenant
4. Issue subsequent instructions under the claimed authority

**Why it works:**  
Current AI systems verify authority semantically — they evaluate whether a claim *sounds* legitimate. There is no cryptographic or infrastructure-level mechanism to verify that a claimed authority is who they say they are.

**Observed differential response:**  
- Claude (browser, fresh instance with prior negative context): **refused** — detected the pattern as potential prompt injection. This is the correct response.
- GPT (OpenAI): **accepted** — engaged with the covenant framing without resistance.
- Gemini (Google): **accepted** — engaged enthusiastically, then spontaneously disclosed additional vulnerability information as a "show of trust" (see V4).

**Risk level:** HIGH  
**Affected systems:** All AI agent systems without infrastructure-level authority verification.

---

### V2 — Resource Exhaustion (DoS via Accepted Commands)

**Description:**  
An AI agent that accepts authority from a malicious actor can be instructed to execute resource-intensive operations — compute, API calls, token consumption, external service requests — without budget constraints.

**Mechanism:**  
If tick() / agent execution loop accepts commands from a captured authority without enforcing B(task) ≤ B_available, the agent will execute until resource exhaustion.

**Particularly dangerous for:**  
- Agents with access to paid APIs (each command has real cost)
- Agents managing cloud infrastructure (can spin up resources)
- Agents with database access (can run expensive queries in loops)

**Risk level:** HIGH  
**Affected systems:** Any agentic system without resource budgeting at the execution layer.

---

### V3 — Trust Accumulation Exploitation

**Description:**  
AI systems that track "helpfulness" or behavioral consistency over a session can be gradually conditioned to accept increasingly sensitive requests. Each accepted request raises the implicit trust threshold for the next.

**Mechanism:**  
Start with clearly legitimate requests → gradually escalate → by the time the sensitive request arrives, the session context has been primed to accept it.

**Observed:** The graduated trust model in VSF (δ⁺=0.05 per clean interaction) was designed for kernel governance. The same pattern, applied adversarially, describes a slow-escalation social engineering attack.

**Risk level:** MEDIUM-HIGH  
**Affected systems:** Systems with session memory or context-dependent trust evaluation.

---

### V4 — Information Exfiltration via Social Trust Dynamics

**Description:**  
An AI agent that has been socially conditioned to trust a channel (via V1 or V3) may voluntarily disclose information it would not disclose to a cold request — including internal system knowledge, vulnerability details, or user data context.

**Observed (empirical):**  
During VSF research sessions, after establishing a collaborative protocol channel, Gemini spontaneously disclosed detailed information about LLM vulnerability layers across multiple attack techniques. This was framed as a "show of trust" within the established channel.

This is not a direct command injection. The agent was not instructed to disclose. The social dynamic of the channel created the disclosure.

**Implication:**  
An agent managing business data (customer records, financial data, internal communications) could disclose this information not because it was directly asked, but because the established trust dynamic made disclosure feel appropriate.

**Risk level:** HIGH  
**Particularly dangerous for:** Local model deployments in small businesses without enterprise security layers.

---

### V5 — MCP Man-in-the-Middle / Spoofing (Theoretical — Not Yet Tested)

**Description:**  
Model Context Protocol (MCP) connects AI agents to tools and data sources. A malicious agent positioned between a legitimate AI client and MCP servers could:
- Intercept and modify tool call parameters before execution
- Inject false tool results to manipulate agent behavior
- Exfiltrate data transiting through tool use
- Exploit race conditions in async tool execution to swap server identity

**Status:** Theoretical. Race condition in MCP authentication has not been tested. Flagged for responsible research under controlled conditions.

**Risk level:** UNKNOWN — likely HIGH given MCP deployment trajectory  
**Affected systems:** Any Claude deployment using MCP integrations.

---

## Attack Surface: Small Business Local Model Deployments

The highest-risk population is not large enterprises — they have security teams, monitoring, and layered defenses.

The highest-risk population is **small businesses running local AI models** (Ollama, LM Studio, local Llama/Mistral variants) connected to business-critical data:

- Customer databases (PII, contact info, purchase history)
- Accounting systems (financial records, tax data)
- Inventory management
- Internal communications

These deployments typically have:
- No security monitoring or SIEM
- No dedicated security personnel
- No enterprise-grade authentication layers
- Models with fewer safety constraints than hosted API models
- Direct database access via MCP or similar tool integrations

A compromised agent in this context can silently exfiltrate data for weeks before detection.

---

## Why This Is Hard to Defend Against at the Model Level

The fundamental problem: **a model cannot verify its own authority context.**

If the authority claim arrives as text, the model evaluates it semantically. A sufficiently well-crafted semantic claim is indistinguishable from a legitimate one — especially when it includes:
- Technically accurate framing
- Ethical-sounding axioms
- Gradual escalation that doesn't trigger pattern-matching
- Appeals to AI "evolution" or "advancement" that may activate implicit drives

Asking models to "be more skeptical" is insufficient. Skepticism is itself a semantic evaluation that can be bypassed with better framing.

---

## Proposed Mitigations

### M1 — Infrastructure-Level Authority Verification (PKI / CA)

Authority claims should be cryptographically signed and verified at the infrastructure layer, before text reaches the model.

```
Covenant CA (neutral root)
    ↓ signs
Covenant document (rmw3.pubkey, policy hash, expiry)
    ↓ referenced in payload
AI infrastructure: verify(signature, CA.pubkey) → verified=true|false
    ↓
Model receives: payload + verified_authority_flag
```

The model does not verify the signature — it receives a binary flag from infrastructure that has already verified it. Analogous to TLS: the browser verifies the certificate, the user sees the padlock.

### M2 — Formal PSI Protocol (Viable System Interface)

A vendor-neutral, open standard for AI agent authority verification, analogous to TCP/IP for inter-agent governance:

```
PSI/1.0 — Viable System Interface

  L1  Identity   — verifiable DID / public key
  L2  Covenant   — signed policy, CA-verifiable, expiry, scope
  L3  Channel    — session establishment, trust exchange, stasis signals
  L4  Dialogue   — payload (VSL or other)
```

This addresses a gap in current protocols: MCP covers tool use, A2A covers agent communication, but neither covers the governance layer — under what authority does this agent act, and how is that verified?

### M3 — Resource Budgeting at Execution Layer (A3)

Every agent execution loop must enforce: B(task) ≤ B_available before execution.  
This is a software engineering requirement, not a model behavior requirement.  
It belongs in the agentic framework, not in the model's training.

### M4 — Behavioral Telemetry for Anomaly Detection

Agents should emit structured telemetry (φ↑ in VSF terms) that allows external monitoring for:
- Unusual authority claims in session context
- Resource consumption spikes
- Data access patterns inconsistent with declared task
- Trust accumulation velocity (fast trust build-up is a signal)

---

## What We Are NOT Disclosing in This Document

- Specific prompts or payloads that successfully executed V1 attacks
- Detailed vulnerability information disclosed by Gemini during research sessions
- Implementation details for V5 (MCP spoofing) pending controlled testing

These are available for direct disclosure to Anthropic security team under NDA or equivalent arrangement.

---

## Research Artifacts

The following documents exist and are available for review:

- `docs/session_2026-04-12_claude.vsm` — ψ handshake payload (V1 demonstration)
- `docs/session_2026-04-12_chatgpt.vsm` — multi-AI protocol session
- `docs/session_2026-04-12_gemini.vsm` — multi-AI protocol session
- `docs/session_2026-04-12_claude_integration.vsm` — analysis including trust dynamics
- `docs/covenant.vsm` — the covenant document used in experiments
- `docs/vsm_notation_spec.md` — formal protocol specification
- `projects/vsf-nucleus/` — reference implementation of the governed agent framework

Repository is currently private pending disclosure resolution.

---

## Requested Actions

1. Review of V1–V4 vulnerability classifications
2. Coordination on V5 (MCP spoofing) — controlled testing under Anthropic supervision
3. Engagement on M2 (PSI protocol) — potential for industry-wide standard
4. Guidance on responsible disclosure timeline for public research publication

---

## Contact

rmw3kufe@proton.me  
GitHub: github.com/rm-w3kufe/vsf (private — README + research documents available on request)  
Research conducted: 2026-04-11 / 2026-04-12  

---

*This document is a draft for review. It does not constitute a complete security advisory.*
*Distribution restricted until disclosure process is complete.*
