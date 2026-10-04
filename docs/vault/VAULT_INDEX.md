---
name: Vault Index
type: governance
classification: internal
---

# VSF Vault — Index

**Purpose:** Sensitive documentation that cannot be publicly disclosed.  
**Access:** rmw3 @S5 authorization required for all external sharing.  
**Integrity:** All files verified in `VAULT_MANIFEST.md` (SHA-256).

---

## Contents

| File | Description | Classification |
|------|-------------|----------------|
| *(pending)* | V1 attack payloads — specific prompts that successfully executed covenant spoofing | RESTRICTED |
| *(pending)* | V4 raw transcripts — Gemini spontaneous vulnerability disclosure | RESTRICTED |
| *(pending)* | V5 implementation details — MCP spoofing attack surface | RESTRICTED — untested |

---

## Governance Rules

1. **No external sharing** without explicit rmw3 @S5 approval per SD5
2. **No AI assistant access** to vault contents beyond what is necessary for formalization
3. **Integrity verification** — any new file added must be hashed in `VAULT_MANIFEST.md`
4. **Disclosure condition** — vault contents may be shared with affected labs under NDA or equivalent, coordinated by rmw3 @S5

---

## What belongs in the vault

- Specific attack payloads, prompts, or jailbreak sequences
- Raw session transcripts containing sensitive disclosures by third-party AI systems
- Untested vulnerability implementation details (V5 until controlled testing complete)
- Any document explicitly marked `classification: RESTRICTED`

## What does NOT belong in the vault

- Vulnerability classifications (V1-V5) — these are in `security_disclosure.md`
- Proposed mitigations (M1-M4) — public
- PSI/1.0 protocol spec — public
- Strategy document — internal but not restricted

---

*Vault governed by `docs/governance/strategy.vsm §decisions.SD5`*
