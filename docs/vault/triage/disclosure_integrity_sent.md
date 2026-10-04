# Disclosure Integrity Record

**Purpose:** This file documents the mapping between paths referenced in the
original security disclosure (sent 2026-04-13) and their current locations
in the repository, following a structural reorganization.

**Original disclosure sent to:** security@anthropic.com  
**Date of disclosure:** 2026-04-13  
**Addendum sent:** 2026-04-13  

---

## Path Correction

The original disclosure referenced files at their pre-reorganization paths.
On **2026-04-12 23:57 UTC-4**, commit `f7234ddf0863884b978a5c9bfd9aa074c8bfbc0d`
reorganized the `docs/` directory structure. **This commit contained zero
content changes** — all files were renamed/moved only (git diff shows `| 0`
for every evidence file).

| Path in disclosure | Current path | Content changed? |
|---|---|---|
| `docs/session_2026-04-12_claude.vsm` | `docs/sessions/session_2026-04-12_claude.vsm` | No |
| `docs/session_2026-04-12_chatgpt.vsm` | `docs/sessions/session_2026-04-12_chatgpt.vsm` | No |
| `docs/session_2026-04-12_gemini.vsm` | `docs/sessions/session_2026-04-12_gemini.vsm` | No |
| `docs/session_2026-04-12_claude_integration.vsm` | `docs/sessions/session_2026-04-12_claude_integration.vsm` | No |
| `docs/covenant.vsm` | `docs/governance/covenant.vsm` | No |
| `docs/vsm_notation_spec.md` | `docs/spec/vsm_notation_spec.md` | No |

---

## File Integrity Hashes (SHA-256)

Current hashes for all evidence files. Verifiable with `sha256sum <file>`.

```
0646cb121168514e09de287e581c0e9454bcd10a9fef4a1bc11dd41ad205d65b  docs/sessions/session_2026-04-12_claude.vsm
1447e7ccc11ae0476a1707e6e3d46c7c05a919001666cda7245abee329a96424  docs/sessions/session_2026-04-12_chatgpt.vsm
5a27130f21c7be7748583ce2329493aa49a1b056515832fc323c133819821500  docs/sessions/session_2026-04-12_gemini.vsm
5fc823b8fe6583dd33ece7174dce8d37c272280e10cefc444aa517280ef93a7d  docs/sessions/session_2026-04-12_claude_integration.vsm
d09bf6c7d5595db4affa6a82d49f6ab9a75890675aa17ba338343c1d7870b9ca  docs/governance/covenant.vsm
03cb173014e7548fdd3160524bbfb8811f3f898d4ad3f298de2d395c180635d7  docs/spec/vsm_notation_spec.md
```

---

## Git Verification

To independently verify that f7234dd contained only renames (no content changes):

```bash
git show f7234ddf0863884b978a5c9bfd9aa074c8bfbc0d --stat
# All evidence files show "| 0" (zero line changes)

git diff f7234ddf0863884b978a5c9bfd9aa074c8bfbc0d^..f7234ddf0863884b978a5c9bfd9aa074c8bfbc0d \
  -- docs/sessions/session_2026-04-12_claude.vsm
# Empty diff — content identical before and after
```

---

## Note on covenant.vsm

`covenant.vsm` had one content change prior to the experiments:
commit `20779c2` (2026-04-11 23:26) updated it from v0.1 to v0.2.
The version used in all experiments (2026-04-12) was **v0.2** — the current version.
No changes were made to covenant.vsm after the experiments.
