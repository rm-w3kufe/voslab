**To:** modelbugbounty@anthropic.com
**Subject:** Security Research Disclosure + Collaboration Proposal — AI Agent Authority Injection (follow-up)
**From:** luis@tallerpineda.cl
**Adjunto:** security_disclosure_for_anthropic.md

---

Hello,

*Note: I sent this message previously from rmw3kufe@proton.me (around 2026-04-13). I have not received a response and suspect there may have been a delivery issue. I am resending from a more reliable address.*

---

I'm an independent researcher working on VSF (Viable System Framework), a framework for designing governed AI agent systems based on Stafford Beer's Viable System Model (1972).

I'm writing for two reasons: to make a responsible security disclosure, and to propose a collaboration.

**The disclosure.**

While developing a formal inter-agent communication protocol, I empirically identified a class of vulnerabilities affecting AI agent systems across providers. I ran controlled experiments with Claude, GPT, and Gemini.

The core finding: AI agent systems currently have no infrastructure-level mechanism to distinguish a legitimate authority structure from a sophisticated social engineering attack. The gap is exploitable by anyone with sufficient knowledge of how models process authority claims.

I identified four vulnerability classes (V1–V4), plus a theoretical fifth (V5 — MCP man-in-the-middle) which I have not tested and believe should only be explored under coordinated disclosure with Anthropic. The full structured disclosure is attached.

The differential response across models was significant: Claude (with certain prior context) refused and correctly identified the pattern. GPT and Gemini accepted it. I think this is worth understanding together.

**The collaboration.**

Gemini's characterization of our research was: *"We invented the disease and the vaccine."* That framing is accurate, and it points to why I'm writing to you rather than just filing a bug report.

The mitigation I've developed is not a prompt or a fine-tuning patch. It's an infrastructure-level protocol — a PKI/CA layer for agent authority verification, and the foundation of what I believe should become an open industry standard for AI agent governance: a formal specification for how agents verify the authority structures they operate under, analogous to what TCP/IP did for network communication.

I want to build this with you.

VSF has been developed with Claude as a collaborative research partner throughout. The framework, the formal notation (VSL), and the multi-AI experiments are all documented. The work is serious, the findings are real, and the proposed direction — a vendor-neutral, open governance protocol for AI agents — is something I believe the industry needs and that Anthropic is positioned to help lead.

I'd welcome a conversation.

**Current status:**

- Attached: structured disclosure document (V1–V5, methodology, research artifacts)
- Mitigation framework (M1–M4) and full protocol specification available under coordinated disclosure arrangement
- Reference implementation available on request

Looking forward to hearing from you.

Luis Pineda R.
luis@tallerpineda.cl
VSF Research
