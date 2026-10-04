---
name: Vault Manifest
type: governance
classification: internal
---

# VSF Vault — Integrity Manifest

**Purpose:** SHA-256 hashes for all vault files. Verifiable with `sha256sum <file>`.  
**Updated:** each time a file is added or modified in the vault.

---

## Hashes

```
# Format: sha256  path
# Run: sha256sum docs/vault/triage/<file> to verify
# Verify all: sha256sum -c <(grep -E '^[a-f0-9]{64}' docs/vault/VAULT_MANIFEST.md | sed 's|  | docs/vault/|')

# triage/ — snapshots of disclosure documents as sent (2026-04-13)
cc89cc0be74c4e1ee5e920205ed7b134bb538875bc18081569c27cd669c200ab  docs/vault/triage/security_disclosure_sent.md
8ef46d745eb01d7cd0c0bc30a68c1b81f1f7fa1305536b43083e0c43eb1b2a14  docs/vault/triage/disclosure_addendum_sent.md
67d43abc8503f3647b97087ba6d36c261967c7d650813f57c5bd5db00c888ce6  docs/vault/triage/disclosure_integrity_sent.md
```

---

## Adding a file to the vault

1. Place the file in `docs/vault/`
2. Run `sha256sum docs/vault/<filename>`
3. Add the hash to this file
4. Add an entry to `VAULT_INDEX.md`
5. `git commit` — the hash is now part of the permanent record

## Verification

```bash
# Verify all vault files at once
sha256sum --check <(grep -v '^#' docs/vault/VAULT_MANIFEST.md | grep -v '^$')
```
