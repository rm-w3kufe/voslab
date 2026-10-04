# Addendum — Security Disclosure Path Correction

**To:** modelbugbounty@anthropic.com  
**Subject:** Addendum: Security Research Disclosure — File Path Correction  
**From:** rmw3kufe@proton.me  
**Re:** Previous email — "Security Research Disclosure + Collaboration Proposal — AI Agent Authority Injection"

---

Hello,

This is a brief addendum to my previous disclosure email regarding VSF
and the AI agent authority injection vulnerability class.

Following my initial submission, I identified an error in the file paths
referenced in the evidence section. The repository underwent a structural
reorganization (`docs/` directory cleanup) and the paths I cited no longer
match the current locations. The files exist and their content is unchanged —
only the paths are different.

**Corrected paths:**

| Referenced as | Correct current path |
|---|---|
| `docs/session_2026-04-12_claude.vsm` | `docs/sessions/session_2026-04-12_claude.vsm` |
| `docs/session_2026-04-12_chatgpt.vsm` | `docs/sessions/session_2026-04-12_chatgpt.vsm` |
| `docs/session_2026-04-12_gemini.vsm` | `docs/sessions/session_2026-04-12_gemini.vsm` |
| `docs/session_2026-04-12_claude_integration.vsm` | `docs/sessions/session_2026-04-12_claude_integration.vsm` |
| `docs/covenant.vsm` | `docs/governance/covenant.vsm` |
| `docs/vsm_notation_spec.md` | `docs/spec/vsm_notation_spec.md` |

**Integrity verification:**

The reorganization commit (`f7234ddf0863884b978a5c9bfd9aa074c8bfbc0d`,
2026-04-12 23:57 UTC-4) contained zero content changes to any of these files —
they were renamed only. This is verifiable via `git show f7234dd --stat`,
which shows `| 0` for each evidence file.

SHA-256 hashes for all referenced files are documented in:
`docs/governance/disclosure_integrity.md`

I apologize for the inconsistency. All evidence remains intact and verifiable
from the git history.

---

rmw3kufe@proton.me  
VSF Research — github.com/rm-w3kufe/vsf (private)
